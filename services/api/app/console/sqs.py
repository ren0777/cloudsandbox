"""Student SQS console API (AWS-style: Queues, Send message, Messages, Attributes, Tags).

Queues are emulator state; there is no background worker. Resources are addressed by queue name, and every
call is capability-filtered against `sqs:*` for the session's engine (PLAN emulator strategy §6)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import Action, AuthzAny
from ..db import get_db
from ..errors import ApiError
from ..models import LabSession, User
from .common import aws_call, console_session

router = APIRouter(prefix="/api/sessions/{session_id}/console/sqs", tags=["console"])
QUEUE_NAME = r"^[A-Za-z0-9_-]{1,80}(\.fifo)?$"


async def _call(sess: LabSession, fn: str, **kw: Any) -> dict:
    return await aws_call(sess, "sqs", fn, **kw)


class QueueIn(BaseModel):
    name: str = Field(pattern=QUEUE_NAME)
    fifo: bool = False
    visibility_timeout: int = Field(30, ge=0, le=43200)
    retention_period: int = Field(345600, ge=60, le=1209600)
    delay_seconds: int = Field(0, ge=0, le=900)


class AttributesIn(BaseModel):
    visibility_timeout: int = Field(30, ge=0, le=43200)
    retention_period: int = Field(345600, ge=60, le=1209600)
    delay_seconds: int = Field(0, ge=0, le=900)
    receive_wait_time: int = Field(1, ge=0, le=20)


class TagIn(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: str = Field("", max_length=256)


class TagsIn(BaseModel):
    tags: list[TagIn] = Field(default_factory=list, max_length=50)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=262144)


class PollIn(BaseModel):
    max: int = Field(10, ge=1, le=10)
    wait_seconds: int = Field(1, ge=0, le=20)


class ReceiptIn(BaseModel):
    receipt_handle: str = Field(min_length=1, max_length=4096)


def _attr_int(attrs: dict[str, str], name: str, default: str = "0") -> int:
    try:
        return int(attrs.get(name, default))
    except (TypeError, ValueError):
        return 0


async def _url(sess: LabSession, name: str) -> str:
    try:
        return (await _call(sess, "get_queue_url", QueueName=name))["QueueUrl"]
    except ApiError:
        raise ApiError("queue_not_found", f"Queue {name} does not exist", 404) from None


def _queue_out(name: str, attrs: dict[str, str]) -> dict[str, Any]:
    return {"name": name, "fifo": attrs.get("FifoQueue") == "true",
            "visibility_timeout": attrs.get("VisibilityTimeout", "30"),
            "retention_period": attrs.get("MessageRetentionPeriod", "345600"),
            "delay_seconds": attrs.get("DelaySeconds", "0"),
            "messages": attrs.get("ApproximateNumberOfMessages", "0"),
            "in_flight": attrs.get("ApproximateNumberOfMessagesNotVisible", "0")}


@router.get("/queues")
async def list_queues(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    names = sorted(u.rsplit("/", 1)[-1] for u in (await _call(sess, "list_queues")).get("QueueUrls", []))
    queues = []
    for name in names:
        attrs = (await _call(sess, "get_queue_attributes", QueueUrl=await _url(sess, name),
                             AttributeNames=["All"]))["Attributes"]
        queues.append(_queue_out(name, attrs))
    return {"queues": queues}


@router.post("/queues", status_code=201)
async def create_queue(session_id: uuid.UUID, body: QueueIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    if body.fifo and not body.name.endswith(".fifo"):
        raise ApiError("invalid_queue_name", "A FIFO queue name must end in .fifo", 422)
    attrs = {"VisibilityTimeout": str(body.visibility_timeout),
             "MessageRetentionPeriod": str(body.retention_period),
             "DelaySeconds": str(body.delay_seconds)}
    if body.fifo:
        attrs["FifoQueue"] = "true"
    url = (await _call(sess, "create_queue", QueueName=body.name, Attributes=attrs))["QueueUrl"]
    return {"name": body.name, "url": url}


@router.get("/queues/{name}")
async def queue_detail(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    if not await _exists(sess, name):
        raise ApiError("queue_not_found", f"Queue {name} does not exist", 404)
    url = await _url(sess, name)
    attrs = (await _call(sess, "get_queue_attributes", QueueUrl=url, AttributeNames=["All"]))["Attributes"]
    tags = (await _call(sess, "list_queue_tags", QueueUrl=url)).get("Tags", {})
    return {**_queue_out(name, attrs), "url": url, "arn": attrs.get("QueueArn", ""),
            "attributes": {k: v for k, v in sorted(attrs.items())}, "tags": tags}


async def _exists(sess: LabSession, name: str) -> bool:
    try:
        await _url(sess, name)
        return True
    except ApiError:
        return False


@router.put("/queues/{name}/attributes")
async def set_attributes(session_id: uuid.UUID, name: str, body: AttributesIn,
                         user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                         db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    url = await _url(sess, name)
    await _call(sess, "set_queue_attributes", QueueUrl=url, Attributes={
        "VisibilityTimeout": str(body.visibility_timeout),
        "MessageRetentionPeriod": str(body.retention_period),
        "DelaySeconds": str(body.delay_seconds),
        "ReceiveMessageWaitTimeSeconds": str(body.receive_wait_time)})
    return {"name": name}


@router.put("/queues/{name}/tags")
async def set_tags(session_id: uuid.UUID, name: str, body: TagsIn,
                   user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                   db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    url = await _url(sess, name)
    current = (await _call(sess, "list_queue_tags", QueueUrl=url)).get("Tags", {})
    wanted = {t.key: t.value for t in body.tags if t.key.strip()}
    removed = sorted(set(current) - set(wanted))
    if removed:
        await _call(sess, "untag_queue", QueueUrl=url, TagKeys=removed)
    if wanted:
        await _call(sess, "tag_queue", QueueUrl=url, Tags=wanted)
    return {"tags": wanted}


@router.post("/queues/{name}/messages", status_code=201)
async def send_message(session_id: uuid.UUID, name: str, body: MessageIn,
                       user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    url = await _url(sess, name)
    attrs = (await _call(sess, "get_queue_attributes", QueueUrl=url,
                         AttributeNames=["FifoQueue"])).get("Attributes", {})
    kw: dict[str, Any] = {"QueueUrl": url, "MessageBody": body.body}
    if attrs.get("FifoQueue") == "true":
        kw["MessageGroupId"] = "console"  # FIFO queues require a group; the console uses one demo group
    out = await _call(sess, "send_message", **kw)
    return {"message_id": out.get("MessageId"), "md5_of_body": out.get("MD5OfBody")}


@router.post("/queues/{name}/poll")
async def poll_messages(session_id: uuid.UUID, name: str, body: PollIn,
                        user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    """Show up to 10 messages without consuming them: `VisibilityTimeout=0` keeps them visible, so
    polling never hides a message from other consumers (or from grading). Deleting removes it."""
    sess = await console_session(session_id, user, db)
    url = await _url(sess, name)
    out = await _call(sess, "receive_message", QueueUrl=url, MaxNumberOfMessages=body.max,
                      WaitTimeSeconds=body.wait_seconds, VisibilityTimeout=0,
                      AttributeNames=["All"], MessageAttributeNames=["All"])
    messages = [{"id": m["MessageId"], "body": m["Body"], "receipt_handle": m["ReceiptHandle"],
                 "attributes": m.get("Attributes", {}), "message_attributes": m.get("MessageAttributes", {}),
                 "receive_count": m.get("Attributes", {}).get("ApproximateReceiveCount", "1")}
                for m in out.get("Messages", [])]
    return {"messages": messages}


@router.post("/queues/{name}/messages/delete", status_code=204)
async def delete_message(session_id: uuid.UUID, name: str, body: ReceiptIn,
                         user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                         db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    url = await _url(sess, name)
    await _call(sess, "delete_message", QueueUrl=url, ReceiptHandle=body.receipt_handle)


@router.post("/queues/{name}/purge", status_code=204)
async def purge_queue(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    url = await _url(sess, name)
    await _call(sess, "purge_queue", QueueUrl=url)


@router.delete("/queues/{name}", status_code=204)
async def delete_queue(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    url = await _url(sess, name)
    await _call(sess, "delete_queue", QueueUrl=url)
