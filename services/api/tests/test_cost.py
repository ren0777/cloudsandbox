"""Phase 6 — simulated cost meter: versioned educational price table, pure estimate from evidence."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.cost import DEFAULT_VERSION, estimate, pricing
from app.insights import insights


def inst(i, state="running", itype="t3.micro"):
    return {"id": i, "name": i, "state": state, "type": itype, "key_name": None, "security_groups": []}


def test_ec2_running_stopped_terminated_and_unknown_types():
    e = estimate({"ec2": {"instances": [inst("a"), inst("b", "stopped"), inst("c", "terminated"),
                                        inst("d", itype="p5.48xlarge")], "security_groups": {}, "key_pairs": []}})
    by = {(x["resource"], x["unit"]): x for x in e["lines"]}
    assert by[("ec2:instance:a", "instance-hour")]["hourly"] == "0.0104"
    assert by[("ec2:instance:a", "instance-hour")]["monthly"] == "7.59"      # 0.0104 × 730
    assert by[("ec2:instance:a", "GB-month")]["monthly"] == "0.64"           # 8 GiB × 0.08
    assert ("ec2:instance:b", "instance-hour") not in by                     # stopped: no compute...
    assert by[("ec2:instance:b", "GB-month")]["note"] == "still charged while the instance is stopped"  # ...but storage
    assert not any(r == "ec2:instance:c" for r, _ in by)                     # terminated: nothing
    assert by[("ec2:instance:d", "instance-hour")]["note"].startswith("instance type not in the price table")
    # totals: a (0.0104 + 0.64/730) + b (0.64/730) + d (0.10 + 0.64/730)
    assert Decimal(e["hourly"]) == (Decimal("0.0104") + Decimal("0.10") + 3 * Decimal("0.64") / 730).quantize(Decimal("0.0001"))
    assert e["simulated"] is True and e["pricing_version"] == DEFAULT_VERSION and e["currency"] == "USD"
    assert "not AWS billing" in e["disclaimer"] and DEFAULT_VERSION in e["disclaimer"]


def test_storage_and_capacity_modes():
    gib = 1024 ** 3
    e = estimate({
        "s3": {"buckets": {"big": {"objects": {"a": {"size": gib}}, "objects_truncated": False},
                           "tiny": {"objects": {"i": {"size": 120}}, "objects_truncated": False}}},
        "dynamodb": {"tables": {"prov": {"billing_mode": "PROVISIONED", "read_capacity": 5, "write_capacity": 5},
                                "od": {"billing_mode": "PAY_PER_REQUEST"}}},
        "lambda": {"functions": {"fn": {}}},
    })
    by = {x["label"]: x for x in e["lines"]}
    assert by["big storage"]["monthly"] == "0.02" and by["big storage"]["quantity"] == "1"
    assert by["tiny storage"]["quantity"] == "<0.000001" and by["tiny storage"]["monthly"] == "0.00"
    assert by["prov read capacity"]["hourly"] == "0.0007" and by["prov write capacity"]["hourly"] == "0.0033"
    assert by["prov read capacity"]["note"] == "provisioned capacity is charged even when idle"
    assert by["od on-demand"]["monthly"] == "0.00" and "nothing while idle" in by["od on-demand"]["note"]
    assert by["fn"]["monthly"] == "0.00"
    assert e["monthly"] == "2.87"  # 0.023 + 5×0.00013×730 + 5×0.00065×730 = 0.023 + 0.4745 + 2.3725
    assert estimate({})["lines"] == [] and estimate({})["hourly"] == "0.0000"


def test_price_tables_are_versioned_and_immutable_by_name():
    assert pricing(DEFAULT_VERSION)["version"] == DEFAULT_VERSION
    with pytest.raises(KeyError):
        pricing("aws-live")
    assert estimate({}, DEFAULT_VERSION)["pricing_effective"] == "2026-01-01"


def test_insights_combine_graph_and_cost_from_the_same_evidence():
    out = insights({"collectors": {"ec2": {"instances": [inst("web")], "security_groups": {}, "key_pairs": []}}})
    assert [n["id"] for n in out["graph"]["nodes"]] == ["ec2:instance:web"]
    assert {x["resource"] for x in out["cost"]["lines"]} == {"ec2:instance:web"}
