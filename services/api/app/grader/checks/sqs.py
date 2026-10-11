"""SQS checks. Evidence shape (collector 'sqs'), engine-independent (no URLs, ARNs or ids):
{"queues": {name: {"name", "fifo", "visibility_timeout", "retention_period", "delay_seconds",
                    "messages", "in_flight", "tags": {k: v}}},
 "peeks": {"<queue>|<max>": {"queue", "received", "bodies": [...]}},
 "deliveries": {"<queue>|<table>|<key>": {"queue", "table", "sent", "item": {attr: typed}|None, "error"?}}}

`sqs.message_present` declares a *probe*: during evidence capture the collector peeks up to 10 messages
with `VisibilityTimeout=0` (nothing is consumed), and grading reads only the stored bodies.
`sqs.delivers_item` declares an `sqs_deliver` probe: the collector sends a test message and records the
DynamoDB item the queue's consumer wrote (see `evidence._deliver`)."""

from typing import Any, Literal

from pydantic import Field

from ..registry import CheckOutcome, Params, check
from .dynamodb import TABLE, KeyValue, _expected, _key_text, plain

NAME = Field(min_length=1, max_length=80)
READS = ["sqs:ListQueues", "sqs:GetQueueAttributes", "sqs:ListQueueTags"]
PEEK_READS = READS + ["sqs:ReceiveMessage"]
ATTRS = ("visibility_timeout", "retention_period", "delay_seconds")
PEEK_MAX = 10


def _sqs(ev: dict) -> dict:
    return ev.get("sqs", {})


def _queue(ev: dict, name: str) -> dict | None:
    return _sqs(ev).get("queues", {}).get(name)


class QueueParams(Params):
    name: str = NAME
    fifo: bool | None = None


@check("sqs.queue_exists", QueueParams, "sqs", READS)
def queue_exists(p: QueueParams, ev: dict) -> CheckOutcome:
    want = p.name + (f" ({'FIFO' if p.fifo else 'standard'})" if p.fifo is not None else "")
    q = _queue(ev, p.name)
    if q is None:
        return CheckOutcome(False, want, "not found", f"No queue named {p.name}")
    actual = f"{q['name']} ({'FIFO' if q.get('fifo') else 'standard'})"
    ok = p.fifo is None or bool(q.get("fifo")) == p.fifo
    return CheckOutcome(ok, want, actual,
                        f"Queue {p.name} exists" if ok else f"Queue {p.name} is not {'FIFO' if p.fifo else 'standard'}")


class AttributeParams(Params):
    queue: str = NAME
    attribute: Literal["visibility_timeout", "retention_period", "delay_seconds"]
    value: int = Field(ge=0, le=1209600)


@check("sqs.queue_attribute", AttributeParams, "sqs", READS)
def queue_attribute(p: AttributeParams, ev: dict) -> CheckOutcome:
    want = f"{p.attribute} = {p.value}"
    q = _queue(ev, p.queue)
    if q is None:
        return CheckOutcome(False, want, "no queue", f"No queue named {p.queue}")
    raw = q.get(p.attribute)
    actual = f"{p.attribute} = {raw}"
    ok = str(raw) == str(p.value)
    return CheckOutcome(ok, want, actual,
                        f"{p.queue} has {want}" if ok else f"{p.queue} has {actual}, not {p.value}")


class TagParams(Params):
    queue: str = NAME
    key: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=256)


@check("sqs.queue_tag", TagParams, "sqs", READS)
def queue_tag(p: TagParams, ev: dict) -> CheckOutcome:
    q = _queue(ev, p.queue)
    if q is None:
        return CheckOutcome(False, f"{p.key}={p.value}", "no queue", f"No queue named {p.queue}")
    actual = q.get("tags", {}).get(p.key)
    ok = actual == p.value
    return CheckOutcome(ok, f"{p.key}={p.value}", f"{p.key}={actual}" if actual is not None else "tag missing",
                        f"{p.queue} is tagged {p.key}={p.value}" if ok
                        else f"{p.queue} should be tagged {p.key}={p.value}")


class MessageParams(Params):
    queue: str = NAME
    body_contains: str | None = Field(None, max_length=1000)


def _probe(p: MessageParams) -> dict[str, Any]:
    return {"kind": "sqs_peek", "queue": p.queue, "max": PEEK_MAX}


@check("sqs.message_present", MessageParams, "sqs", PEEK_READS, probe=_probe)
def message_present(p: MessageParams, ev: dict) -> CheckOutcome:
    want = f"a message in {p.queue}" + (f" containing {p.body_contains!r}" if p.body_contains else "")
    peek = _sqs(ev).get("peeks", {}).get(f"{p.queue}|{PEEK_MAX}")
    if peek is None:
        return CheckOutcome(False, want, "no evidence", f"No message evidence for {p.queue}")
    if peek.get("error"):
        return CheckOutcome(False, want, peek["error"], f"Could not read {p.queue}: {peek['error']}")
    bodies: list[str] = peek.get("bodies", [])
    if p.body_contains:
        hit = any(p.body_contains in body for body in bodies)
    else:
        hit = bool(bodies)
    shown = ", ".join(repr(b[:60]) for b in bodies[:3]) or "no messages"
    return CheckOutcome(hit, want, f"{len(bodies)} message(s): {shown}",
                        f"{p.queue} holds a matching message" if hit
                        else f"{p.queue} has no message matching {p.body_contains!r} (first messages: {shown})")


class DeliveryParams(Params):
    queue: str = NAME
    body: dict[str, Any] | str = Field(description="The test message sent to the queue (JSON object or text).")
    table: str = TABLE
    key: dict[str, str | int] = Field(min_length=1, max_length=2,
                                      description="The item the consumer must write; removed before the message is sent.")
    attributes: dict[str, KeyValue] = Field(default_factory=dict)
    wait: int = Field(20, ge=5, le=30, description="Seconds to wait for the item to appear.")


def _deliver_probe(p: DeliveryParams) -> dict[str, Any]:
    return {"kind": "sqs_deliver", "queue": p.queue, "body": p.body, "table": p.table, "key": p.key, "wait": p.wait}


@check("sqs.delivers_item", DeliveryParams, "sqs",
       PEEK_READS + ["sqs:GetQueueUrl", "sqs:SendMessage", "dynamodb:DeleteItem", "dynamodb:GetItem"],
       probe=_deliver_probe)
def delivers_item(p: DeliveryParams, ev: dict) -> CheckOutcome:
    """End to end: a message sent to the queue is consumed and produces the expected DynamoDB item."""
    from ..evidence import delivery_key
    want = {**p.key, **p.attributes}
    exp = f"message to {p.queue} → item {_key_text(p.key)} in {p.table}"
    d = _sqs(ev).get("deliveries", {}).get(delivery_key(_deliver_probe(p)))
    if d is None:
        return CheckOutcome(False, exp, "no evidence", f"No delivery evidence for {p.queue}")
    if d.get("error"):
        where, _, code = d["error"].partition(": ")
        name = p.table if where == "table" else p.queue
        return CheckOutcome(False, exp, d["error"], f"Could not use {name} for the test message ({code})")
    item = d.get("item")
    if item is None:
        return CheckOutcome(False, exp, "no item after waiting",
                            f"A test order sent to {p.queue} never reached {p.table}. Is a trigger connected, "
                            "and does the function save the order?")
    wrong = [k for k, v in p.attributes.items() if k not in item or plain(item[k]) != _expected(v)]
    actual = ", ".join(f"{k}={plain(item[k]) if k in item else '(missing)'}" for k in want)
    if wrong:
        return CheckOutcome(False, exp, actual, f"A test order sent to {p.queue} was saved with the wrong "
                                                f"{', '.join(wrong)}")
    return CheckOutcome(True, exp, actual, f"A test order sent to {p.queue} was processed and saved to {p.table}")
