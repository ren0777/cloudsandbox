"""Student Lambda console API (AWS-style: Functions, Create function, Code/Test/Configuration).
Invoking functions needs an engine that can execute code (capability `lambda:Invoke`); on other engines
the Test tab answers 409 not_in_simulator via the central capability check."""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import uuid
import zipfile
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import Action, Authz
from ..db import get_db
from ..errors import ApiError
from ..grader.iam_eval import parse_document
from ..models import LabSession, User
from .common import aws_call, console_session

router = APIRouter(prefix="/api/sessions/{session_id}/console/lambda", tags=["console"])
NAME = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
RUNTIMES = {"python3.12": ("lambda_function.py", "lambda_function.lambda_handler",
                           "import json\n\n\ndef lambda_handler(event, context):\n"
                           "    # TODO implement\n    return {\n        'statusCode': 200,\n"
                           "        'body': json.dumps('Hello from Lambda!')\n    }\n"),
            "nodejs20.x": ("index.mjs", "index.handler",
                           "export const handler = async (event) => {\n  // TODO implement\n"
                           "  return {\n    statusCode: 200,\n    body: JSON.stringify('Hello from Lambda!'),\n  };\n};\n")}
MAX_FILE = 64 * 1024
TRUST = {"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}


async def _call(sess: LabSession, fn: str, **kw: Any) -> dict:
    return await aws_call(sess, "lambda", fn, **kw)


class CreateFunctionIn(BaseModel):
    name: str = NAME
    runtime: Literal["python3.12", "nodejs20.x"] = "python3.12"
    architecture: Literal["x86_64", "arm64"] = "x86_64"
    role_mode: Literal["create", "existing"] = "create"
    role_arn: str | None = Field(None, max_length=2048)


class CodeIn(BaseModel):
    files: dict[str, str] = Field(min_length=1, max_length=20)


class ConfigIn(BaseModel):
    memory: int = Field(128, ge=128, le=10240)
    timeout: int = Field(3, ge=1, le=900)
    handler: str | None = Field(None, min_length=1, max_length=128)
    env: dict[str, str] = Field(default_factory=dict, max_length=50)


class InvokeIn(BaseModel):
    event: Any = Field(default_factory=dict)


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in sorted(files.items()):
            if name.startswith("/") or ".." in name.split("/"):
                raise ApiError("validation_error", f"invalid file name {name!r}", 400)
            z.writestr(name, content)
    return buf.getvalue()


def _config_out(c: dict[str, Any]) -> dict[str, Any]:
    return {"name": c["FunctionName"], "runtime": c.get("Runtime"), "handler": c.get("Handler"),
            "role": c.get("Role"), "memory": c.get("MemorySize"), "timeout": c.get("Timeout"),
            "architecture": (c.get("Architectures") or ["x86_64"])[0], "last_modified": c.get("LastModified"),
            "env": ((c.get("Environment") or {}).get("Variables") or {}), "code_size": c.get("CodeSize")}


async def _fetch_code(sess: LabSession, location: str) -> dict[str, str] | None:
    """Download the deployment package through the sandbox network (the engine may report its own
    host name in the URL) and return its small text files."""
    if not location:
        return None
    emu = urlsplit(sess.emulator_endpoint or "")
    loc = urlsplit(location)
    # keep the endpoint's own path (a runner gateway serves the emulator under /gw/<sandbox>/<token>/emulator)
    url = urlunsplit((emu.scheme, emu.netloc, emu.path.rstrip("/") + loc.path, loc.query, ""))
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url)
        r.raise_for_status()
        files: dict[str, str] = {}
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for info in z.infolist()[:20]:
                if info.is_dir() or info.file_size > MAX_FILE:
                    continue
                try:
                    files[info.filename] = z.read(info).decode("utf-8")
                except UnicodeDecodeError:
                    continue
        return files
    except Exception:
        return None


@router.get("/functions")
async def list_functions(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
                         db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    fns = (await _call(sess, "list_functions")).get("Functions", [])
    return {"functions": sorted((_config_out(f) for f in fns), key=lambda f: f["name"])}


@router.get("/execution-roles")
async def execution_roles(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
                          db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    roles = (await aws_call(sess, "iam", "list_roles")).get("Roles", [])
    out = []
    for r in roles:
        trust = parse_document(r.get("AssumeRolePolicyDocument", {}))
        if "lambda.amazonaws.com" in json.dumps(trust):
            out.append({"name": r["RoleName"], "arn": r["Arn"]})
    return {"roles": out}


@router.post("/functions", status_code=201)
async def create_function(session_id: uuid.UUID, body: CreateFunctionIn, user: User = Depends(Authz(Action.session_use)),
                          db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    if body.architecture != "x86_64":
        raise ApiError("not_in_simulator", "Only the x86_64 architecture is available in the CloudLabs simulator.", 409)
    if body.role_mode == "existing":
        if not body.role_arn:
            raise ApiError("validation_error", "choose an existing execution role", 400)
        role_arn = body.role_arn
    else:  # AWS console: "Create a new role with basic Lambda permissions"
        role_name = f"{body.name}-role-{secrets.token_hex(4)}"
        role_arn = (await aws_call(sess, "iam", "create_role", RoleName=role_name,
                                   AssumeRolePolicyDocument=json.dumps(TRUST)))["Role"]["Arn"]
    filename, handler, code = RUNTIMES[body.runtime]
    await _call(sess, "create_function", FunctionName=body.name, Runtime=body.runtime, Role=role_arn, Handler=handler,
                Code={"ZipFile": _zip({filename: code})}, Architectures=["x86_64"])
    return {"name": body.name, "role": role_arn}


@router.get("/functions/{name}")
async def get_function(session_id: uuid.UUID, name: str, user: User = Depends(Authz(Action.session_use)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    out = await _call(sess, "get_function", FunctionName=name)
    files = await _fetch_code(sess, (out.get("Code") or {}).get("Location", ""))
    return {**_config_out(out["Configuration"]), "files": files, "code_available": files is not None}


@router.put("/functions/{name}/code")
async def deploy_code(session_id: uuid.UUID, name: str, body: CodeIn, user: User = Depends(Authz(Action.session_use)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "update_function_code", FunctionName=name, ZipFile=_zip(body.files))
    return {"deployed": True}


@router.put("/functions/{name}/configuration")
async def update_configuration(session_id: uuid.UUID, name: str, body: ConfigIn,
                               user: User = Depends(Authz(Action.session_use)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    kw: dict[str, Any] = {"FunctionName": name, "MemorySize": body.memory, "Timeout": body.timeout,
                          "Environment": {"Variables": body.env}}
    if body.handler:
        kw["Handler"] = body.handler
    await _call(sess, "update_function_configuration", **kw)
    return {"updated": True}


@router.post("/functions/{name}/invoke")
async def invoke(session_id: uuid.UUID, name: str, body: InvokeIn, user: User = Depends(Authz(Action.session_use)),
                 db: AsyncSession = Depends(get_db)):
    """The console's Test button."""
    sess = await console_session(session_id, user, db)
    t0 = asyncio.get_running_loop().time()
    r = await _call(sess, "invoke", FunctionName=name, Payload=json.dumps(body.event).encode())
    raw = await asyncio.to_thread(r["Payload"].read)
    text = raw.decode("utf-8", "replace")
    try:
        payload: Any = json.loads(text) if text else None
    except ValueError:
        payload = text[:5000]
    return {"status_code": r.get("StatusCode"), "function_error": r.get("FunctionError"), "response": payload,
            "duration_ms": int((asyncio.get_running_loop().time() - t0) * 1000)}


@router.delete("/functions/{name}", status_code=204)
async def delete_function(session_id: uuid.UUID, name: str, user: User = Depends(Authz(Action.session_use)),
                          db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_function", FunctionName=name)
