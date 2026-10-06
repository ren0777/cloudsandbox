"""Student SNS console API (AWS-style: Topics, Subscriptions, Publish).

SNS has no egress in a sandbox, so the only delivery target is an SQS queue inside the same sandbox: the
console subscribes queues and publishes to show real fan-out. Every call is capability-filtered against
`sns:*` (and the queue lookup against `sqs:*`) for the session's engine."""

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

router = APIRouter(prefix="/api/sessions/{session_id}/console/sns", tags=["console"])
TOPIC_NAME = r"^[A-Za-z0-9_-]{1,256}$"


async def _call(sess: LabSession, fn: str, **kw: Any) -> dict:
    return await aws_call(sess, "sns", fn, **kw)


class TopicIn(BaseModel):
    name: str = Field(pattern=TOPIC_NAME)
    display_name: str = Field("", max_length=100)


class TopicAttributesIn(BaseModel):
    display_name: str = Field("", max_length=100)


class SubscribeIn(BaseModel):
    queue: str = Field(min_length=1, max_length=80)
    raw_delivery: bool = False


class SubscriptionIn(BaseModel):
    subscription_arn: str = Field(min_length=1, max_length=2048)


class PublishIn(BaseModel):
    message: str = Field(min_length=1, max_length=262144)
    subject: str = Field("", max_length=100)


async def _topic_arn(sess: LabSession, name: str) -> str:
    topics = (await _call(sess, "list_topics")).get("Topics", [])
    for t in topics:
        if t["TopicArn"].rsplit(":", 1)[-1] == name:
            return t["TopicArn"]
    raise ApiError("topic_not_found", f"Topic {name} does not exist", 404)


async def _queue_arn(sess: LabSession, name: str) -> str:
    try:
        url = await aws_call(sess, "sqs", "get_queue_url", QueueName=name)
        return (await aws_call(sess, "sqs", "get_queue_attributes", QueueUrl=url["QueueUrl"],
                               AttributeNames=["QueueArn"]))["Attributes"]["QueueArn"]
    except ApiError:
        raise ApiError("queue_not_found", f"Queue {name} does not exist", 404) from None


def _subscription_out(sub: dict[str, Any]) -> dict[str, Any]:
    endpoint = sub.get("Endpoint", "")
    return {"arn": sub.get("SubscriptionArn"), "protocol": sub.get("Protocol", ""), "endpoint": endpoint,
            "queue": endpoint.rsplit(":", 1)[-1] if sub.get("Protocol") == "sqs" else endpoint,
            "raw_delivery": False}


def _topic_out(name: str, arn: str, attrs: dict[str, str], subscriptions: list[dict]) -> dict[str, Any]:
    return {"name": name, "arn": arn, "display_name": attrs.get("DisplayName", ""),
            "subscriptions": len(subscriptions), "attributes": dict(sorted(attrs.items()))}


# ---------------------------------------------------------------------------------------- topics
@router.get("/topics")
async def list_topics(session_id: uuid.UUID, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    out = []
    for t in (await _call(sess, "list_topics")).get("Topics", []):
        arn = t["TopicArn"]
        name = arn.rsplit(":", 1)[-1]
        attrs = (await _call(sess, "get_topic_attributes", TopicArn=arn)).get("Attributes", {})
        subs = (await _call(sess, "list_subscriptions_by_topic", TopicArn=arn)).get("Subscriptions", [])
        out.append(_topic_out(name, arn, attrs, subs))
    out.sort(key=lambda t: t["name"])
    return {"topics": out}


@router.post("/topics", status_code=201)
async def create_topic(session_id: uuid.UUID, body: TopicIn, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    arn = (await _call(sess, "create_topic", Name=body.name))["TopicArn"]
    if body.display_name:
        await _call(sess, "set_topic_attributes", TopicArn=arn, AttributeName="DisplayName",
                    AttributeValue=body.display_name)
    return {"name": body.name, "arn": arn}


@router.get("/topics/{name}")
async def topic_detail(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    arn = await _topic_arn(sess, name)
    attrs = (await _call(sess, "get_topic_attributes", TopicArn=arn)).get("Attributes", {})
    subs = [_subscription_out(s) for s in
            (await _call(sess, "list_subscriptions_by_topic", TopicArn=arn)).get("Subscriptions", [])]
    for sub in subs:
        if sub["arn"] and sub["arn"] != "PendingConfirmation":
            a = (await _call(sess, "get_subscription_attributes",
                             SubscriptionArn=sub["arn"])).get("Attributes", {})
            sub["raw_delivery"] = a.get("RawMessageDelivery") == "true"
    subs.sort(key=lambda s: (s["protocol"], s["queue"]))
    return {**_topic_out(name, arn, attrs, subs), "subscriptions_list": subs}


@router.put("/topics/{name}/attributes")
async def set_topic_attributes(session_id: uuid.UUID, name: str, body: TopicAttributesIn,
                               user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                               db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    arn = await _topic_arn(sess, name)
    await _call(sess, "set_topic_attributes", TopicArn=arn, AttributeName="DisplayName",
                AttributeValue=body.display_name)
    return {"name": name, "display_name": body.display_name}


@router.delete("/topics/{name}", status_code=204)
async def delete_topic(session_id: uuid.UUID, name: str, user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    arn = await _topic_arn(sess, name)
    await _call(sess, "delete_topic", TopicArn=arn)


# --------------------------------------------------------------------------------- subscriptions
@router.post("/topics/{name}/subscriptions", status_code=201)
async def subscribe(session_id: uuid.UUID, name: str, body: SubscribeIn,
                    user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                    db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    arn = await _topic_arn(sess, name)
    queue_arn = await _queue_arn(sess, body.queue)
    sub_arn = (await _call(sess, "subscribe", TopicArn=arn, Protocol="sqs", Endpoint=queue_arn,
                           ReturnSubscriptionArn=True))["SubscriptionArn"]
    if body.raw_delivery and sub_arn and sub_arn != "PendingConfirmation":
        await _call(sess, "set_subscription_attributes", SubscriptionArn=sub_arn,
                    AttributeName="RawMessageDelivery", AttributeValue="true")
    return {"subscription_arn": sub_arn, "queue": body.queue}


@router.post("/topics/{name}/subscriptions/delete", status_code=204)
async def unsubscribe(session_id: uuid.UUID, name: str, body: SubscriptionIn,
                      user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    await _topic_arn(sess, name)  # ownership/validity
    await _call(sess, "unsubscribe", SubscriptionArn=body.subscription_arn)


# --------------------------------------------------------------------------------------- publish
@router.post("/topics/{name}/publish", status_code=201)
async def publish(session_id: uuid.UUID, name: str, body: PublishIn,
                  user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                  db: AsyncSession = Depends(get_db)):
    sess = await console_session(session_id, user, db)
    arn = await _topic_arn(sess, name)
    kw: dict[str, Any] = {"TopicArn": arn, "Message": body.message}
    if body.subject:
        kw["Subject"] = body.subject
    out = await _call(sess, "publish", **kw)
    return {"message_id": out.get("MessageId")}
