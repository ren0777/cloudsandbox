"""SQS checks. Evidence shape (collector 'sqs'), engine-independent (no URLs, ARNs or ids):
{"queues": {name: {"name", "fifo", "visibility_timeout", "retention_period", "delay_seconds",
                    "messages", "in_flight", "tags": {k: v}}},
 "peeks": {"<queue>|<max>": {"queue", "received", "bodies": [...]}}}

`sqs.message_present` declares a *probe*: during evidence capture the collector peeks up to 10 messages
with `VisibilityTimeout=0` (nothing is consumed), and grading reads only the stored bodies."""

from typing import Any, Literal

from pydantic import Field

from ..registry import CheckOutcome, Params, check

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
