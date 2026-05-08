"""Rule IR <-> YAML round-trip (R78)."""
from __future__ import annotations

from typing import Any, Dict

import yaml

from .ir import (
    Action,
    ActionKind,
    BoolExpr,
    Comparator,
    ComparisonOp,
    Indicator,
    Logical,
    LogicalOp,
    PriceRef,
    Rule,
    ValueExpr,
)


def _value_to_dict(v: ValueExpr) -> Any:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, PriceRef):
        return {"price": v.field}
    if isinstance(v, Indicator):
        return {"indicator": v.name, "args": list(v.args)}
    raise TypeError(f"unsupported value expr: {v!r}")


def _value_from_dict(obj: Any) -> ValueExpr:
    if isinstance(obj, (int, float)):
        return float(obj)
    if "price" in obj:
        return PriceRef(field=str(obj["price"]))
    if "indicator" in obj:
        return Indicator(name=str(obj["indicator"]),
                         args=tuple(float(a) for a in obj.get("args", [])))
    raise ValueError(f"cannot decode value: {obj!r}")


def _bool_to_dict(b: BoolExpr) -> Dict[str, Any]:
    if isinstance(b, Comparator):
        return {
            "compare": {
                "left": _value_to_dict(b.left),
                "op": b.op.value,
                "right": _value_to_dict(b.right),
            }
        }
    if isinstance(b, Logical):
        return {
            "logical": {
                "op": b.op.value,
                "operands": [_bool_to_dict(o) for o in b.operands],
            }
        }
    raise TypeError(f"unsupported bool expr: {b!r}")


def _bool_from_dict(obj: Dict[str, Any]) -> BoolExpr:
    if "compare" in obj:
        c = obj["compare"]
        return Comparator(
            left=_value_from_dict(c["left"]),
            op=ComparisonOp(c["op"]),
            right=_value_from_dict(c["right"]),
        )
    if "logical" in obj:
        l = obj["logical"]
        return Logical(
            op=LogicalOp(l["op"]),
            operands=tuple(_bool_from_dict(o) for o in l["operands"]),
        )
    raise ValueError(f"cannot decode bool expr: {obj!r}")


def rule_to_yaml(rule: Rule) -> str:
    """Serialise a Rule to YAML."""
    payload = {
        "name": rule.name,
        "condition": _bool_to_dict(rule.condition),
        "action": rule.action.kind.value,
    }
    return yaml.safe_dump(payload, sort_keys=False)


def rule_from_yaml(text: str) -> Rule:
    """Parse a Rule from YAML."""
    payload = yaml.safe_load(text)
    return Rule(
        name=str(payload["name"]),
        condition=_bool_from_dict(payload["condition"]),
        action=Action(kind=ActionKind(payload["action"])),
    )


__all__ = ["rule_to_yaml", "rule_from_yaml"]
