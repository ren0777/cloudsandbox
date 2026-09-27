"""Simulated cost meter (phase 6): an EDUCATIONAL estimate of what the student's resources would cost on AWS,
computed purely from collector evidence and a versioned price table (`pricing/<version>.yaml`). It is never
live AWS billing, and every response says so. Price tables are immutable: a new version is a new file, so a
stored estimate can always be reproduced from (evidence, pricing version)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_VERSION = "edu-2026.1"
DISCLAIMER = ("Simulated, educational estimate using the Stackora price table {version} (simplified us-east-1 list "
              "prices, no free tier). This is not AWS billing: no real charges exist in Stackora.")
GB = Decimal(1024 ** 3)
Q4, Q2 = Decimal("0.0001"), Decimal("0.01")


@lru_cache
def pricing(version: str = DEFAULT_VERSION) -> dict[str, Any]:
    path = Path(__file__).parent / "pricing" / f"{version}.yaml"
    if not path.is_file():
        raise KeyError(f"unknown price table {version!r}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data.get("version") != version:
        raise ValueError(f"price table {path.name} declares version {data.get('version')!r}")
    return data


def _d(v: Any) -> Decimal:
    return Decimal(str(v))


def _qty(q: Decimal) -> str:
    """Plain decimal, no exponent: 1 → "1", 2.5e-7 GB → "0.000001" (6 places max)."""
    if q == q.to_integral_value():
        return str(int(q))
    s = format(q.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f").rstrip("0").rstrip(".")
    return s if s not in ("", "0") else "<0.000001"


def estimate(collectors: dict[str, Any], version: str = DEFAULT_VERSION) -> dict[str, Any]:
    p = pricing(version)
    hpm = _d(p["hours_per_month"])
    lines: list[dict[str, Any]] = []

    def line(resource: str, service: str, label: str, unit: str, quantity: Decimal, rate: Decimal, *,
             monthly_rate: bool = False, note: str | None = None) -> None:
        if monthly_rate:
            monthly = quantity * rate
            hourly = monthly / hpm
        else:
            hourly = quantity * rate
            monthly = hourly * hpm
        lines.append({"resource": resource, "service": service, "label": label, "unit": unit,
                      "quantity": _qty(quantity), "rate": str(rate),
                      "hourly": hourly, "monthly": monthly, "note": note})

    # EC2: compute for running instances, root volume for every non-terminated one
    ec2p = p["ec2"]
    for i in (collectors.get("ec2") or {}).get("instances", []):
        state = i.get("state")
        if state == "terminated":
            continue
        rid, name = f"ec2:instance:{i['id']}", i.get("name") or i["id"]
        if state in ("running", "pending"):
            known = i.get("type") in ec2p["instance_hourly"]
            rate = _d(ec2p["instance_hourly"].get(i.get("type"), ec2p["unknown_type_hourly"]))
            line(rid, "ec2", f"{name} ({i.get('type')}) compute", "instance-hour", Decimal(1), rate,
                 note=None if known else "instance type not in the price table; estimated")
        line(rid, "ec2", f"{name} root volume", "GB-month", _d(ec2p["root_volume_gb"]), _d(ec2p["ebs_gb_month"]),
             monthly_rate=True, note="still charged while the instance is stopped" if state == "stopped" else None)

    # S3: storage by object size
    for name, b in sorted((collectors.get("s3") or {}).get("buckets", {}).items()):
        size = sum(_d(o.get("size", 0)) for o in b.get("objects", {}).values())
        line(f"s3:{name}", "s3", f"{name} storage", "GB-month", size / GB, _d(p["s3"]["storage_gb_month"]),
             monthly_rate=True, note="partial object list" if b.get("objects_truncated") else None)

    # DynamoDB: provisioned capacity bills every hour; on-demand only per request (idle = storage only)
    dp = p["dynamodb"]
    for name, t in sorted((collectors.get("dynamodb") or {}).get("tables", {}).items()):
        rid = f"dynamodb:{name}"
        if t.get("billing_mode") == "PROVISIONED":
            line(rid, "dynamodb", f"{name} read capacity", "RCU-hour", _d(t.get("read_capacity") or 0),
                 _d(dp["provisioned_rcu_hourly"]), note="provisioned capacity is charged even when idle")
            line(rid, "dynamodb", f"{name} write capacity", "WCU-hour", _d(t.get("write_capacity") or 0),
                 _d(dp["provisioned_wcu_hourly"]))
        else:
            line(rid, "dynamodb", f"{name} on-demand", "requests", Decimal(0), Decimal(0),
                 note="on-demand: charged per request, nothing while idle")

    # Lambda: nothing while idle
    for name in sorted((collectors.get("lambda") or {}).get("functions", {})):
        line(f"lambda:{name}", "lambda", f"{name}", "invocations", Decimal(0), Decimal(0), note=p["lambda"]["note"])

    hourly = sum((x["hourly"] for x in lines), Decimal(0))
    monthly = sum((x["monthly"] for x in lines), Decimal(0))
    for x in lines:
        x["hourly"] = str(x["hourly"].quantize(Q4, rounding=ROUND_HALF_UP))
        x["monthly"] = str(x["monthly"].quantize(Q2, rounding=ROUND_HALF_UP))
    return {"simulated": True, "pricing_version": p["version"], "pricing_effective": p["effective"],
            "currency": p["currency"], "hourly": str(hourly.quantize(Q4, rounding=ROUND_HALF_UP)),
            "monthly": str(monthly.quantize(Q2, rounding=ROUND_HALF_UP)),
            "disclaimer": DISCLAIMER.format(version=p["version"]), "lines": lines}
