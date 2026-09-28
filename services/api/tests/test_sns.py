"""SNS: capability parity, the real-runtime contract on every engine (marker docker) and the lab packs
(`sns-basics`, `sns-breakfix`) through `app.labtest`.

Publish is tested by delivering into an SQS subscription inside the sandbox (the only safe, hermetic
delivery target - no egress) and reading the message from the queue; see docs/M44-SERVICES-EVALUATION.md
for the evaluation and docs/LAB-AUTHORING.md for the checks and break actions.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from app.config import get_settings
from app.runtime import emulators


def must(cond, msg: str = "") -> None:
    if not cond:
        raise AssertionError(msg or "assertion failed")


TOPIC = "m44-contract"
QUEUE = "m44-contract-sns"

# Ops run in declaration order; `st` carries the topic/subscription ARNs and the SQS target queue.
SNS_CONTRACT = {
    "CreateTopic": lambda c, st: st.update(topic=c.create_topic(Name=TOPIC)["TopicArn"]),
    "ListTopics": lambda c, st: must(any(t2["TopicArn"] == st["topic"] for t2 in c.list_topics()["Topics"]),
                                     "topic not listed"),
    "GetTopicAttributes": lambda c, st: must(c.get_topic_attributes(TopicArn=st["topic"])["Attributes"].get("TopicArn")
                                             == st["topic"], "TopicArn did not round-trip"),
    "SetTopicAttributes": lambda c, st: must(
        (c.set_topic_attributes(TopicArn=st["topic"], AttributeName="DisplayName", AttributeValue="M44 Contract") or
         c.get_topic_attributes(TopicArn=st["topic"])["Attributes"].get("DisplayName") == "M44 Contract"),
        "DisplayName did not take effect"),
    "Subscribe": lambda c, st: st.update(sub=c.subscribe(TopicArn=st["topic"], Protocol="sqs",
                                                         Endpoint=st["qarn"], ReturnSubscriptionArn=True)["SubscriptionArn"]),
    "ListSubscriptionsByTopic": lambda c, st: must(
        any(s["SubscriptionArn"] == st["sub"] for s in c.list_subscriptions_by_topic(TopicArn=st["topic"])["Subscriptions"]),
        "subscription not listed"),
    "GetSubscriptionAttributes": lambda c, st: must(
        "SubscriptionArn" in c.get_subscription_attributes(SubscriptionArn=st["sub"])["Attributes"],
        "subscription attributes missing"),
    "SetSubscriptionAttributes": lambda c, st: must(
        (c.set_subscription_attributes(SubscriptionArn=st["sub"], AttributeName="RawMessageDelivery",
                                       AttributeValue="true") or
         c.get_subscription_attributes(SubscriptionArn=st["sub"])["Attributes"].get("RawMessageDelivery") == "true"),
        "RawMessageDelivery did not take effect"),
    "Publish": lambda c, st: publish_one(c, st),
    "PublishBatch": lambda c, st: publish_batch(c, st),
    "Unsubscribe": lambda c, st: must(
        (c.unsubscribe(SubscriptionArn=st["sub"]) or not any(
            s["SubscriptionArn"] == st["sub"] for s in c.list_subscriptions_by_topic(TopicArn=st["topic"])["Subscriptions"])),
        "subscription still listed after Unsubscribe"),
    "DeleteTopic": lambda c, st: delete_topic(c, st),
}


def poll_messages(st, want: int, timeout: float = 10.0) -> list[dict]:
    """Receive up to `want` raw messages from the target queue (RawMessageDelivery is on)."""
    import time

    got: list[dict] = []
    deadline = time.monotonic() + timeout
    while len(got) < want and time.monotonic() < deadline:
        r = st["sqs"].receive_message(QueueUrl=st["qurl"], MaxNumberOfMessages=min(want - len(got), 10),
                                      WaitTimeSeconds=1)
        got += r.get("Messages", [])
    return got


def publish_one(c, st) -> None:
    c.publish(TopicArn=st["topic"], Subject="m44", Message="contract-payload")
    msgs = poll_messages(st, 1)
    must(msgs, "published message was not delivered to the SQS subscription")
    must(msgs[0]["Body"] == "contract-payload", "raw delivery body changed")
    st["sqs"].delete_message(QueueUrl=st["qurl"], ReceiptHandle=msgs[0]["ReceiptHandle"])


def publish_batch(c, st) -> None:
    r = c.publish_batch(TopicArn=st["topic"], PublishBatchRequestEntries=[
        {"Id": "p1", "Message": "batch-1"}, {"Id": "p2", "Message": "batch-2"}])
    must(len(r["Successful"]) == 2, "batch publish did not accept both entries")
    msgs = poll_messages(st, 2)
    must(len(msgs) == 2, "batch messages were not delivered")
    must(sorted(m["Body"] for m in msgs) == ["batch-1", "batch-2"], "batch delivery bodies changed")
    for m in msgs:
        st["sqs"].delete_message(QueueUrl=st["qurl"], ReceiptHandle=m["ReceiptHandle"])


def delete_topic(c, st) -> None:
    c.delete_topic(TopicArn=st["topic"])
    try:
        c.get_topic_attributes(TopicArn=st["topic"])
        raise AssertionError("deleted topic still readable")
    except ClientError:
        pass


def test_sns_declaration_is_identical_on_every_engine():
    declared = {e: frozenset(op for op, o in emulators.get(e).capabilities.services["sns"].items()
                             if o.level == "supported") for e in emulators.ALL_ENGINES}
    assert len(set(declared.values())) == 1, declared
    assert set(declared["moto"]) == set(SNS_CONTRACT), set(declared["moto"]) ^ set(SNS_CONTRACT)


@pytest.mark.docker
@pytest.mark.parametrize("contract_engine", emulators.ALL_ENGINES)
async def test_sns_contract_for_every_declared_supported_operation(real_runner, contract_engine):
    caps = emulators.get(contract_engine).capabilities
    declared = {op for op, o in caps.services["sns"].items() if o.level == "supported"}
    assert declared == set(SNS_CONTRACT), declared ^ set(SNS_CONTRACT)
    sid = str(uuid.uuid4())
    info = await real_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env, "engine": contract_engine,
                                             "terminal_credential": "contract:abcdefgh1234"})
    try:
        adapter = emulators.get(contract_engine)
        c = adapter.client("sns", info["emulator_endpoint"])

        def setup() -> dict:
            sqs = adapter.client("sqs", info["emulator_endpoint"])
            qurl = sqs.create_queue(QueueName=QUEUE)["QueueUrl"]
            qarn = sqs.get_queue_attributes(QueueUrl=qurl, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
            return {"sqs": sqs, "qurl": qurl, "qarn": qarn}

        st = await asyncio.to_thread(setup)
        for op, fn in SNS_CONTRACT.items():
            await asyncio.to_thread(fn, c, st)
    finally:
        await real_runner.destroy_sandbox(sid)


# ------------------------------------------------------------------------------- lab packs
LABS_DIR = Path(get_settings().labs_dir)


@pytest.mark.docker
@pytest.mark.parametrize("pack,expected", [
    ("sns-basics", [("empty", "0.00"), ("partial", "45.00"), ("solution", "100.00")]),
    ("sns-breakfix", [("empty", "20.00"), ("partial", "70.00"), ("solution", "100.00"), ("reset", "20.00")]),
])
@pytest.mark.parametrize("lab_engine", emulators.ENGINES)
async def test_sns_labtest_on_every_engine(real_runner, lab_engine, pack, expected):
    from app.labtest import check_pack
    results = await check_pack(LABS_DIR / pack, real_runner, engine=lab_engine)
    assert [(r.name, str(r.actual)) for r in results] == [(f"{lab_engine}/{name}", score) for name, score in expected], \
        [(r.name, r.actual, r.detail) for r in results]
