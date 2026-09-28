"""SQS preparation (M44): capability parity and the real-runtime contract on every engine (marker docker).

No lab pack and no console page yet - see docs/M44-SERVICES-EVALUATION.md for the evaluation, the
proposed grader checks and the proposed FastAPI/console shape.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest

from app.config import get_settings
from app.runtime import emulators


def must(cond, msg: str = "") -> None:
    if not cond:
        raise AssertionError(msg or "assertion failed")


QNAME = "m44-contract"

# Ops run in declaration order; `st` carries the queue URL and receipt handles between them.
SQS_CONTRACT = {
    "CreateQueue": lambda c, st: st.update(qurl=c.create_queue(QueueName=QNAME, Attributes={
        "VisibilityTimeout": "30", "MessageRetentionPeriod": "3600",
        "ReceiveMessageWaitTimeSeconds": "1"})["QueueUrl"]),
    "GetQueueUrl": lambda c, st: must(c.get_queue_url(QueueName=QNAME)["QueueUrl"] == st["qurl"],
                                      "GetQueueUrl differs from CreateQueue"),
    "ListQueues": lambda c, st: must(any(u.endswith(QNAME) for u in
                                         c.list_queues(QueueNamePrefix=QNAME).get("QueueUrls", [])),
                                     "queue not listed"),
    "GetQueueAttributes": lambda c, st: must(
        c.get_queue_attributes(QueueUrl=st["qurl"], AttributeNames=["All"])["Attributes"].get("VisibilityTimeout") == "30"
        and (st.update(arn=c.get_queue_attributes(QueueUrl=st["qurl"],
                                                  AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]) or True),
        "queue attributes did not round-trip"),
    "SetQueueAttributes": lambda c, st: must(
        (c.set_queue_attributes(QueueUrl=st["qurl"], Attributes={"VisibilityTimeout": "45"}) or
         c.get_queue_attributes(QueueUrl=st["qurl"],
                                AttributeNames=["VisibilityTimeout"])["Attributes"]["VisibilityTimeout"] == "45"),
        "SetQueueAttributes did not take effect"),
    "TagQueue": lambda c, st: c.tag_queue(QueueUrl=st["qurl"], Tags={"project": "cloudcafe"}),
    "ListQueueTags": lambda c, st: must(c.list_queue_tags(QueueUrl=st["qurl"]).get("Tags", {}).get("project")
                                        == "cloudcafe", "queue tag missing"),
    "UntagQueue": lambda c, st: must((c.untag_queue(QueueUrl=st["qurl"], TagKeys=["project"]) or
                                      "project" not in c.list_queue_tags(QueueUrl=st["qurl"]).get("Tags", {})),
                                     "queue tag not removed"),
    "SendMessage": lambda c, st: c.send_message(QueueUrl=st["qurl"], MessageBody=json.dumps({"drink": "latte"}),
                                                MessageAttributes={
                                                    "project": {"DataType": "String", "StringValue": "cloudcafe"},
                                                    "attempts": {"DataType": "Number", "StringValue": "2"}}),
    "ReceiveMessage": lambda c, st: receive_one(c, st),
    "ChangeMessageVisibility": lambda c, st: c.change_message_visibility(
        QueueUrl=st["qurl"], ReceiptHandle=st["receipt"], VisibilityTimeout=0),
    "DeleteMessage": lambda c, st: c.delete_message(QueueUrl=st["qurl"], ReceiptHandle=st["receipt"]),
    "SendMessageBatch": lambda c, st: must(len(c.send_message_batch(QueueUrl=st["qurl"], Entries=[
        {"Id": "m1", "MessageBody": "batch-1"}, {"Id": "m2", "MessageBody": "batch-2"}])["Successful"]) == 2,
        "batch send did not accept both entries"),
    "DeleteMessageBatch": lambda c, st: delete_batch(c, st),
    "PurgeQueue": lambda c, st: c.purge_queue(QueueUrl=st["qurl"]),
    "DeleteQueue": lambda c, st: c.delete_queue(QueueUrl=st["qurl"]),
}


def receive_one(c, st) -> None:
    r = c.receive_message(QueueUrl=st["qurl"], MaxNumberOfMessages=1, WaitTimeSeconds=1,
                          AttributeNames=["All"], MessageAttributeNames=["All"])
    msgs = r.get("Messages", [])
    must(msgs, "no message received")
    m = msgs[0]
    st["receipt"] = m["ReceiptHandle"]
    must(json.loads(m["Body"]) == {"drink": "latte"}, "message body changed")
    must(m.get("MessageAttributes", {}).get("project", {}).get("StringValue") == "cloudcafe",
         "message attribute missing")


def delete_batch(c, st) -> None:
    handles = []
    for _ in range(2):
        r = c.receive_message(QueueUrl=st["qurl"], MaxNumberOfMessages=2, WaitTimeSeconds=1)
        handles += [{"Id": f"d{i}", "ReceiptHandle": m["ReceiptHandle"]}
                    for i, m in enumerate(r.get("Messages", []))]
    must(len(handles) >= 2, "batch messages not received")
    r = c.delete_message_batch(QueueUrl=st["qurl"], Entries=handles[:2])
    must(len(r.get("Successful", [])) == 2, "batch delete did not accept both entries")


def test_sqs_declaration_is_identical_on_every_engine():
    declared = {e: frozenset(op for op, o in emulators.get(e).capabilities.services["sqs"].items()
                             if o.level == "supported") for e in emulators.ALL_ENGINES}
    assert len(set(declared.values())) == 1, declared
    assert set(declared["moto"]) == set(SQS_CONTRACT), set(declared["moto"]) ^ set(SQS_CONTRACT)


@pytest.mark.docker
@pytest.mark.parametrize("contract_engine", emulators.ALL_ENGINES)
async def test_sqs_contract_for_every_declared_supported_operation(real_runner, contract_engine):
    caps = emulators.get(contract_engine).capabilities
    declared = {op for op, o in caps.services["sqs"].items() if o.level == "supported"}
    assert declared == set(SQS_CONTRACT), declared ^ set(SQS_CONTRACT)
    sid = str(uuid.uuid4())
    info = await real_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env, "engine": contract_engine,
                                             "terminal_credential": "contract:abcdefgh1234"})
    try:
        c = emulators.get(contract_engine).client("sqs", info["emulator_endpoint"])
        st: dict = {}
        for op, fn in SQS_CONTRACT.items():
            await asyncio.to_thread(fn, c, st)
    finally:
        await real_runner.destroy_sandbox(sid)


# ------------------------------------------------------------------------------- lab packs
LABS_DIR = Path(get_settings().labs_dir)


@pytest.mark.docker
@pytest.mark.parametrize("pack,expected", [
    ("sqs-basics", [("empty", "0.00"), ("partial", "35.00"), ("solution", "100.00")]),
    ("sqs-breakfix", [("empty", "20.00"), ("partial", "70.00"), ("solution", "100.00"), ("reset", "20.00")]),
])
@pytest.mark.parametrize("lab_engine", emulators.ENGINES)
async def test_sqs_labtest_on_every_engine(real_runner, lab_engine, pack, expected):
    from app.labtest import check_pack
    results = await check_pack(LABS_DIR / pack, real_runner, engine=lab_engine)
    assert [(r.name, str(r.actual)) for r in results] == [(f"{lab_engine}/{name}", score) for name, score in expected], \
        [(r.name, r.actual, r.detail) for r in results]
