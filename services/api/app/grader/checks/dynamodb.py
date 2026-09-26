"""DynamoDB checks. Evidence shape (collector 'dynamodb'), engine-independent and free of timestamps:
{"tables": {name: {"partition_key": {"name", "type"}, "sort_key": {...}|None,
                   "billing_mode": "PAY_PER_REQUEST"|"PROVISIONED",
                   "read_capacity": int|None, "write_capacity": int|None,
                   "items": {canonical_key: {attr: {"S"|"N"|"BOOL"|...: value}}},
                   "item_count": int, "items_truncated": bool}}}
"""

from typing import Any, Literal

from pydantic import Field

from ..registry import CheckOutcome, Params, check

TABLE = Field(min_length=3, max_length=255, pattern=r"^[A-Za-z0-9_.-]+$")
KeyValue = str | int | float | bool


def _tables(ev: dict) -> dict:
    return ev.get("dynamodb", {}).get("tables", {})


def plain(typed: dict[str, Any]) -> Any:
    """{"S": "x"} -> "x", {"N": "2"} -> "2" (numbers compared as canonical strings)."""
    (t, v), = typed.items()
    if t == "N":
        return canonical_number(v)
    if t == "BOOL":
        return bool(v)
    if t == "NULL":
        return None
    return v


def canonical_number(v: Any) -> str:
    from decimal import Decimal
    d = Decimal(str(v)).normalize()
    return format(d, "f") if d == d.to_integral() else str(d)


def _expected(v: KeyValue) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return canonical_number(v)
    return v


def _find(table: dict, key: dict[str, KeyValue]) -> dict | None:
    for item in table.get("items", {}).values():
        if all(k in item and plain(item[k]) == _expected(v) for k, v in key.items()):
            return item
    return None


def _key_text(key: dict[str, KeyValue]) -> str:
    return ", ".join(f"{k}={v}" for k, v in key.items())


class TableParams(Params):
    table: str = TABLE


@check("dynamodb.table_exists", TableParams, "dynamodb", ["dynamodb:ListTables", "dynamodb:DescribeTable"])
def table_exists(p: TableParams, ev: dict) -> CheckOutcome:
    ok = p.table in _tables(ev)
    return CheckOutcome(ok, "exists", "exists" if ok else "missing",
                        f"Table {p.table} exists" if ok else f"Table {p.table} was not found")


class KeySchemaParams(Params):
    table: str = TABLE
    partition_key: str = Field(min_length=1, max_length=255)
    partition_type: Literal["S", "N", "B"] = "S"
    sort_key: str | None = None
    sort_type: Literal["S", "N", "B"] = "S"


@check("dynamodb.key_schema", KeySchemaParams, "dynamodb", ["dynamodb:ListTables", "dynamodb:DescribeTable"])
def key_schema(p: KeySchemaParams, ev: dict) -> CheckOutcome:
    t = _tables(ev).get(p.table)
    exp = f"{p.partition_key} ({p.partition_type})" + (f", sort {p.sort_key} ({p.sort_type})" if p.sort_key else "")
    if t is None:
        return CheckOutcome(False, exp, "table missing", f"Table {p.table} was not found")
    pk, sk = t["partition_key"], t.get("sort_key")
    act = f"{pk['name']} ({pk['type']})" + (f", sort {sk['name']} ({sk['type']})" if sk else "")
    ok = pk == {"name": p.partition_key, "type": p.partition_type} and (
        (sk is None and p.sort_key is None) or (sk is not None and sk == {"name": p.sort_key, "type": p.sort_type}))
    return CheckOutcome(ok, exp, act, f"Primary key is {act}" if ok
                        else f"Primary key of {p.table} is {act}; expected {exp}")


class BillingParams(Params):
    table: str = TABLE
    mode: Literal["PAY_PER_REQUEST", "PROVISIONED"]


@check("dynamodb.billing_mode", BillingParams, "dynamodb", ["dynamodb:ListTables", "dynamodb:DescribeTable"])
def billing_mode(p: BillingParams, ev: dict) -> CheckOutcome:
    t = _tables(ev).get(p.table)
    if t is None:
        return CheckOutcome(False, p.mode, "table missing", f"Table {p.table} was not found")
    label = {"PAY_PER_REQUEST": "on-demand", "PROVISIONED": "provisioned"}
    ok = t["billing_mode"] == p.mode
    return CheckOutcome(ok, p.mode, t["billing_mode"],
                        f"{p.table} uses {label[p.mode]} capacity" if ok
                        else f"{p.table} uses {label[t['billing_mode']]} capacity; expected {label[p.mode]}")


class ItemParams(Params):
    table: str = TABLE
    key: dict[str, KeyValue] = Field(min_length=1, max_length=2)
    attributes: dict[str, KeyValue] = Field(default_factory=dict)


@check("dynamodb.item", ItemParams, "dynamodb", ["dynamodb:ListTables", "dynamodb:DescribeTable", "dynamodb:Scan"])
def item(p: ItemParams, ev: dict) -> CheckOutcome:
    t = _tables(ev).get(p.table)
    want = {**p.key, **p.attributes}
    exp = ", ".join(f"{k}={v}" for k, v in want.items())
    if t is None:
        return CheckOutcome(False, exp, "table missing", f"Table {p.table} was not found")
    found = _find(t, p.key)
    if found is None:
        return CheckOutcome(False, exp, "item missing", f"No item with {_key_text(p.key)} in {p.table}")
    wrong = [k for k, v in p.attributes.items() if k not in found or plain(found[k]) != _expected(v)]
    actual = ", ".join(f"{k}={plain(found[k]) if k in found else '(missing)'}" for k in want)
    if wrong:
        return CheckOutcome(False, exp, actual, f"Item {_key_text(p.key)} has the wrong {', '.join(wrong)}")
    return CheckOutcome(True, exp, actual, f"Item {_key_text(p.key)} is correct")


class AttrTypeParams(Params):
    table: str = TABLE
    key: dict[str, KeyValue] = Field(min_length=1, max_length=2)
    attribute: str = Field(min_length=1, max_length=255)
    attribute_type: Literal["S", "N", "BOOL", "B", "L", "M", "SS", "NS", "NULL"]
    value: KeyValue | None = None


@check("dynamodb.attribute_type", AttrTypeParams, "dynamodb",
       ["dynamodb:ListTables", "dynamodb:DescribeTable", "dynamodb:Scan"])
def attribute_type(p: AttrTypeParams, ev: dict) -> CheckOutcome:
    t = _tables(ev).get(p.table)
    exp = f"{p.attribute}: {p.attribute_type}" + (f" = {p.value}" if p.value is not None else "")
    found = _find(t, p.key) if t else None
    if found is None or p.attribute not in found:
        return CheckOutcome(False, exp, "attribute missing", f"Item {_key_text(p.key)} has no {p.attribute}")
    (typ, _), = found[p.attribute].items()
    val_ok = p.value is None or plain(found[p.attribute]) == _expected(p.value)
    act = f"{p.attribute}: {typ} = {plain(found[p.attribute])}"
    ok = typ == p.attribute_type and val_ok
    return CheckOutcome(ok, exp, act, f"{p.attribute} is stored correctly" if ok
                        else f"{p.attribute} should be stored as {p.attribute_type}")


class CountParams(Params):
    table: str = TABLE
    min: int = Field(ge=0, le=1000)


@check("dynamodb.item_count", CountParams, "dynamodb", ["dynamodb:ListTables", "dynamodb:DescribeTable", "dynamodb:Scan"])
def item_count(p: CountParams, ev: dict) -> CheckOutcome:
    t = _tables(ev).get(p.table)
    if t is None:
        return CheckOutcome(False, f">= {p.min} items", "table missing", f"Table {p.table} was not found")
    n = t["item_count"]
    ok = n >= p.min
    return CheckOutcome(ok, f">= {p.min} items", f"{n} items", f"{p.table} holds {n} items" if ok
                        else f"{p.table} holds {n} items; it needs at least {p.min}")
