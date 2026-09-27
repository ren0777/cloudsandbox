"""Student DynamoDB console API (AWS-style: Tables, Create table, capacity, Explore items, Create item).
Acts on the student's own emulator through the EmulatorAdapter, exactly like the CLI.

Adapted from Floci UI (MIT, https://github.com/floci-io/floci-ui, AwsDynamoDbAdapter.ts; see
THIRD_PARTY_NOTICES.md): table-name rule, key-schema construction from partition/sort key inputs,
batched describes and the 100-item explore cap."""

from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from boto3.dynamodb.types import TypeDeserializer
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import Action, AuthzAny
from ..db import get_db
from ..errors import ApiError
from ..grader.checks.dynamodb import canonical_number
from ..models import LabSession, User
from .common import aws_call, console_session

router = APIRouter(prefix="/api/sessions/{session_id}/console/dynamodb", tags=["console"])
TABLE_RE = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")  # Floci UI / AWS rule
EXPLORE_LIMIT = 100
_deser = TypeDeserializer()


async def _call(sess: LabSession, fn: str, **kw: Any) -> dict:
    return await aws_call(sess, "dynamodb", fn, **kw)


class KeyAttr(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: Literal["S", "N", "B"] = "S"


class TagIn(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: str = Field("", max_length=256)


class CreateTableIn(BaseModel):
    name: str
    partition_key: KeyAttr
    sort_key: KeyAttr | None = None
    billing_mode: Literal["PAY_PER_REQUEST", "PROVISIONED"] = "PROVISIONED"
    read_capacity: int | None = Field(5, ge=1, le=1000)
    write_capacity: int | None = Field(5, ge=1, le=1000)
    tags: list[TagIn] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _check(self) -> "CreateTableIn":
        if not TABLE_RE.match(self.name):
            raise ValueError("Use a valid table name: 3-255 letters, numbers, underscores, dots or hyphens.")
        if self.sort_key and self.sort_key.name == self.partition_key.name:
            raise ValueError("The sort key must differ from the partition key.")
        return self


class CapacityIn(BaseModel):
    billing_mode: Literal["PAY_PER_REQUEST", "PROVISIONED"]
    read_capacity: int | None = Field(None, ge=1, le=1000)
    write_capacity: int | None = Field(None, ge=1, le=1000)


class AttrIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: Literal["S", "N", "BOOL"]
    value: str | bool | int | float


class PutItemIn(BaseModel):
    attributes: list[AttrIn] = Field(min_length=1, max_length=100)


class TypedValue(BaseModel):
    type: Literal["S", "N", "B", "BOOL"]
    value: Any


class DeleteItemIn(BaseModel):
    key: dict[str, TypedValue] = Field(min_length=1, max_length=2)


def _typed(a: AttrIn) -> dict[str, Any]:
    if a.type == "S":
        return {"S": str(a.value)}
    if a.type == "BOOL":
        return {"BOOL": a.value if isinstance(a.value, bool) else str(a.value).lower() == "true"}
    try:
        return {"N": canonical_number(Decimal(str(a.value).strip()))}
    except (InvalidOperation, ValueError):
        raise ApiError("validation_error", f"{a.name}: '{a.value}' is not a number", 400) from None


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return canonical_number(v)
    if isinstance(v, (set, frozenset)):
        return sorted(_plain(x) for x in v)
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, bytes):
        return v.hex()
    return v


def _item_out(raw: dict[str, Any], key_names: list[str]) -> list[dict[str, Any]]:
    order = sorted(raw, key=lambda k: (key_names.index(k) if k in key_names else len(key_names), k))
    return [{"name": k, "type": next(iter(raw[k])), "value": _plain(_deser.deserialize(raw[k]))} for k in order]


def _summary(d: dict[str, Any]) -> dict[str, Any]:
    types = {a["AttributeName"]: a["AttributeType"] for a in d.get("AttributeDefinitions", [])}
    ks = {k["KeyType"]: k["AttributeName"] for k in d.get("KeySchema", [])}
    mode = (d.get("BillingModeSummary") or {}).get("BillingMode") or "PROVISIONED"
    pt = d.get("ProvisionedThroughput") or {}
    return {
        "name": d["TableName"], "status": d.get("TableStatus", "ACTIVE"),
        "partition_key": {"name": ks["HASH"], "type": types.get(ks["HASH"], "S")},
        "sort_key": {"name": ks["RANGE"], "type": types.get(ks["RANGE"], "S")} if "RANGE" in ks else None,
        "billing_mode": mode, "item_count": d.get("ItemCount", 0),
        "read_capacity": pt.get("ReadCapacityUnits") if mode == "PROVISIONED" else None,
        "write_capacity": pt.get("WriteCapacityUnits") if mode == "PROVISIONED" else None,
        "arn": d.get("TableArn"), "created_at": d.get("CreationDateTime"),
    }


@router.get("/tables")
async def list_tables(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    names = (await _call(sess, "list_tables", Limit=100)).get("TableNames", [])
    out = []
    for n in names:
        s = _summary((await _call(sess, "describe_table", TableName=n))["Table"])
        out.append({k: s[k] for k in ("name", "status", "partition_key", "sort_key", "billing_mode", "item_count")})
    return {"tables": out}


@router.post("/tables", status_code=201)
async def create_table(session_id: uuid.UUID, body: CreateTableIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    attrs = [{"AttributeName": body.partition_key.name, "AttributeType": body.partition_key.type}]
    keys = [{"AttributeName": body.partition_key.name, "KeyType": "HASH"}]
    if body.sort_key:
        attrs.append({"AttributeName": body.sort_key.name, "AttributeType": body.sort_key.type})
        keys.append({"AttributeName": body.sort_key.name, "KeyType": "RANGE"})
    kw: dict[str, Any] = {"TableName": body.name, "AttributeDefinitions": attrs, "KeySchema": keys,
                          "BillingMode": body.billing_mode}
    if body.billing_mode == "PROVISIONED":
        kw["ProvisionedThroughput"] = {"ReadCapacityUnits": body.read_capacity or 5,
                                       "WriteCapacityUnits": body.write_capacity or 5}
    desc = (await _call(sess, "create_table", **kw))["TableDescription"]
    tags = [t for t in body.tags if t.key.strip()]
    if tags and desc.get("TableArn"):
        await _call(sess, "tag_resource", ResourceArn=desc["TableArn"],
                    Tags=[{"Key": t.key, "Value": t.value} for t in tags])
    return {"name": body.name}


@router.get("/tables/{table}")
async def table_details(session_id: uuid.UUID, table: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    s = _summary((await _call(sess, "describe_table", TableName=table))["Table"])
    tags: dict[str, str] = {}
    if s["arn"]:
        tags = {t["Key"]: t["Value"] for t in (await _call(sess, "list_tags_of_resource", ResourceArn=s["arn"]))
                .get("Tags", [])}
    s["item_count"] = (await _call(sess, "scan", TableName=table, Select="COUNT")).get("Count", s["item_count"])
    return {**s, "tags": tags}


@router.delete("/tables/{table}", status_code=204)
async def delete_table(session_id: uuid.UUID, table: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _call(sess, "delete_table", TableName=table)


@router.put("/tables/{table}/capacity")
async def update_capacity(session_id: uuid.UUID, table: str, body: CapacityIn,
                          user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    kw: dict[str, Any] = {"TableName": table, "BillingMode": body.billing_mode}
    if body.billing_mode == "PROVISIONED":
        kw["ProvisionedThroughput"] = {"ReadCapacityUnits": body.read_capacity or 5,
                                       "WriteCapacityUnits": body.write_capacity or 5}
    await _call(sess, "update_table", **kw)
    return {"billing_mode": body.billing_mode}


@router.get("/tables/{table}/items")
async def explore_items(session_id: uuid.UUID, table: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    s = _summary((await _call(sess, "describe_table", TableName=table))["Table"])
    key_names = [s["partition_key"]["name"]] + ([s["sort_key"]["name"]] if s["sort_key"] else [])
    items: list[dict[str, Any]] = []
    kw: dict[str, Any] = {"TableName": table, "Limit": EXPLORE_LIMIT}
    truncated = False
    while True:
        page = await _call(sess, "scan", **kw)
        items += page.get("Items", [])
        if len(items) >= EXPLORE_LIMIT or not page.get("LastEvaluatedKey"):
            truncated = bool(page.get("LastEvaluatedKey")) or len(items) > EXPLORE_LIMIT
            break
        kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    items = items[:EXPLORE_LIMIT]
    items.sort(key=lambda it: json.dumps([it.get(k) for k in key_names], sort_keys=True, default=str))
    return {"items": [_item_out(it, key_names) for it in items], "key_names": key_names,
            "count": len(items), "truncated": truncated}


@router.post("/tables/{table}/items", status_code=201)
async def put_item(session_id: uuid.UUID, table: str, body: PutItemIn,
                   user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    names = [a.name for a in body.attributes]
    if len(names) != len(set(names)):
        raise ApiError("validation_error", "attribute names must be unique", 400)
    await _call(sess, "put_item", TableName=table, Item={a.name: _typed(a) for a in body.attributes})
    return {"saved": True}


@router.post("/tables/{table}/items/delete", status_code=204)
async def delete_item(session_id: uuid.UUID, table: str, body: DeleteItemIn,
                      user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    key = {k: ({"N": canonical_number(v.value)} if v.type == "N" else {v.type: v.value}) for k, v in body.key.items()}
    await _call(sess, "delete_item", TableName=table, Key=key)
