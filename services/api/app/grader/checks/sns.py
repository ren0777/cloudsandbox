"""SNS checks. Evidence shape (collector 'sns'), engine-independent (no ARNs, policies or timestamps):
{"topics": {name: {"name", "display_name", "subscriptions": [{"protocol", "queue", "raw_delivery"}]}}}

Delivery is graded through the SQS collector: a lab that publishes to a topic and checks
`sqs.message_present` proves real in-sandbox fan-out without any egress."""

from typing import Literal

from pydantic import Field

from ..registry import CheckOutcome, Params, check

NAME = Field(min_length=1, max_length=256)
TOPIC_READS = ["sns:ListTopics", "sns:GetTopicAttributes"]
SUB_READS = ["sns:ListTopics", "sns:ListSubscriptionsByTopic", "sns:GetSubscriptionAttributes"]


def _sns(ev: dict) -> dict:
    return ev.get("sns", {})


def _topic(ev: dict, name: str) -> dict | None:
    return _sns(ev).get("topics", {}).get(name)


class TopicParams(Params):
    name: str = NAME
    display_name: str | None = Field(None, max_length=100)


@check("sns.topic_exists", TopicParams, "sns", TOPIC_READS)
def topic_exists(p: TopicParams, ev: dict) -> CheckOutcome:
    want = p.name + (f" (display name {p.display_name!r})" if p.display_name is not None else "")
    t = _topic(ev, p.name)
    if t is None:
        return CheckOutcome(False, want, "not found", f"No topic named {p.name}")
    actual = f"{t['name']}" + (f" (display name {t.get('display_name')!r})" if t.get("display_name") else "")
    ok = p.display_name is None or t.get("display_name") == p.display_name
    return CheckOutcome(ok, want, actual,
                        f"Topic {p.name} exists" if ok
                        else f"Topic {p.name} has display name {t.get('display_name')!r}, not {p.display_name!r}")


class SubscriptionParams(Params):
    topic: str = NAME
    queue: str = NAME
    expect: Literal["present", "absent"] = "present"


@check("sns.subscription", SubscriptionParams, "sns", SUB_READS)
def subscription(p: SubscriptionParams, ev: dict) -> CheckOutcome:
    want = f"{p.queue} subscribed to {p.topic} ({p.expect})"
    t = _topic(ev, p.topic)
    if t is None:
        return CheckOutcome(False, want, "no topic", f"No topic named {p.topic}")
    subs = [s for s in t.get("subscriptions", []) if s.get("protocol") == "sqs" and s.get("queue") == p.queue]
    hit = bool(subs)
    others = ", ".join(f"{s.get('protocol')}:{s.get('queue')}" for s in t.get("subscriptions", [])) or "none"
    if p.expect == "absent":
        return CheckOutcome(not hit, want, others,
                            f"{p.queue} is not subscribed to {p.topic}" if not hit
                            else f"{p.queue} is still subscribed to {p.topic}")
    return CheckOutcome(hit, want, others,
                        f"{p.queue} receives messages from {p.topic}" if hit
                        else f"{p.queue} is not subscribed to {p.topic} (subscriptions: {others})")
