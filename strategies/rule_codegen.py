"""Code preview from rule IR (R123).

Render an :class:`research.auto_gen.GeneratedRule` (or any rule with
the same shape) as Python source the operator can read before
promotion. Pure pretty-printer.

Future: per-platform renderers (PineScript, MQL5, EasyLanguage,
NinjaScript) plug into the same interface; today only the Python
renderer ships.
"""
from __future__ import annotations

from typing import Any, Mapping


def _format_params(params: Mapping[str, Any]) -> str:
    return ", ".join(
        f"{k}={v!r}"
        for k, v in sorted(params.items())
    )


def render_python(rule_dict: Mapping[str, Any]) -> str:
    """Render a rule dict (from ``GeneratedRule.to_dict``) as Python.

    Output is a self-contained snippet a developer can paste into a
    Strategy subclass.
    """
    block_a = rule_dict["block_a"]
    block_b = rule_dict["block_b"]
    comp = rule_dict["comparator"]
    allow_short = rule_dict.get("allow_short", False)
    a_call = f"{block_a['name']}(prices, {_format_params(block_a['params'])})"
    b_call = f"{block_b['name']}(prices, {_format_params(block_b['params'])})"
    comp_op = {
        "gt": ">",
        "lt": "<",
        "crosses_above": "crosses_above",
        "crosses_below": "crosses_below",
    }.get(comp, comp)
    if comp in ("gt", "lt"):
        cond = f"a {comp_op} b"
    else:
        cond = f"{comp_op}(a, b)"
    short_branch = ""
    if allow_short:
        short_branch = (
            "    # allow_short=True -> mirror condition for the short side\n"
            "    weights = np.where(cond, 1.0, np.where(~cond, -1.0, 0.0))\n"
        )
    else:
        short_branch = "    weights = cond.astype(float)\n"
    src = (
        "import numpy as np\n"
        "\n"
        "def signals(prices):\n"
        f"    a = {a_call}\n"
        f"    b = {b_call}\n"
        f"    cond = {cond}\n"
        f"{short_branch}"
        "    return weights\n"
    )
    return src


__all__ = ["render_python"]
