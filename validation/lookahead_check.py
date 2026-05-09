"""Anti-lookahead static + runtime checks.

Static: AST scan strategy signal function for forward-slicing patterns.
Runtime: re-run strategy with shuffled future bars; if metrics change -> leak.
"""
from __future__ import annotations
import ast
import inspect
import textwrap
from dataclasses import dataclass, field
from typing import Callable
import numpy as np
import pandas as pd

from aurora.core import seed as _seed
from aurora.core.seed import child_rng


@dataclass
class LookaheadReport:
    static_warnings: list[str]
    runtime_violation: bool
    runtime_metric_delta: float
    passed: bool
    static_v2: "StaticLookaheadReport | None" = None


@dataclass
class StaticLookaheadReport:
    warnings: list[str] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    severity_counts: dict = field(default_factory=lambda: {"high": 0, "medium": 0, "low": 0})


def _is_negative_constant(node: ast.AST) -> int | None:
    """Return positive shift magnitude N if node is a negative integer constant.

    Handles `-1` parsed as `UnaryOp(USub, Constant(1))` and `Constant(-1)` (rare).
    Returns None when not a clear negative integer.
    """
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand = node.operand
        if isinstance(operand, ast.Constant) and isinstance(operand.value, int) and operand.value > 0:
            return operand.value
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and node.value < 0:
        return -node.value
    return None


def _is_positive_constant_offset(node: ast.AST) -> int | None:
    """If node is a BinOp `name + positive_int` or `name - negative_int`, return offset."""
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            # name + N or N + name
            if isinstance(node.right, ast.Constant) and isinstance(node.right.value, int) and node.right.value > 0:
                return node.right.value
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, int) and node.left.value > 0:
                return node.left.value
            # name + (-(-N)) — fall through; rare
        if isinstance(node.op, ast.Sub):
            # name - (-N) -> forward
            neg = _is_negative_constant(node.right)
            if neg is not None:
                return neg
    return None


def _slice_uses_forward_offset(slice_node: ast.AST) -> bool:
    """True if a Subscript slice contains an additive forward offset like i+1, t+N."""
    if isinstance(slice_node, ast.Slice):
        for part in (slice_node.lower, slice_node.upper, slice_node.step):
            if part is not None and _is_positive_constant_offset(part) is not None:
                return True
            # nested check inside parts (rare)
            if part is not None and isinstance(part, ast.BinOp):
                if _is_positive_constant_offset(part) is not None:
                    return True
        return False
    if isinstance(slice_node, ast.Tuple):
        return any(_slice_uses_forward_offset(e) for e in slice_node.elts)
    if _is_positive_constant_offset(slice_node) is not None:
        return True
    return False


class _ForwardSliceVisitor(ast.NodeVisitor):
    """Backward-compatible text-pattern visitor (severity: low)."""

    def __init__(self):
        self.warnings: list[str] = []
        self.findings: list[dict] = []

    def visit_Subscript(self, node):
        try:
            src = ast.unparse(node)
            for pat in ("[i+", "[t+", "[idx+"):
                if pat in src.replace(" ", ""):
                    msg = f"forward index suspect: {src}"
                    self.warnings.append(msg)
                    self.findings.append({
                        "pattern": "text_forward_index",
                        "line": getattr(node, "lineno", -1),
                        "col": getattr(node, "col_offset", -1),
                        "src": src,
                        "severity": "low",
                    })
                    break
        except Exception:
            pass
        self.generic_visit(node)


class _ExtendedLookaheadVisitor(ast.NodeVisitor):
    """Extended AST visitor catching: shift(-N), iloc/loc forward, lambda forward,
    reverse-cumsum, groupby bfill, df.index > X heuristic, for-loop forward access.
    """

    _ACCUMULATOR_METHODS = {"cumsum", "cumprod", "cummax", "cummin", "expanding"}

    def __init__(self):
        self.warnings: list[str] = []
        self.findings: list[dict] = []
        self._loop_var_stack: list[set[str]] = []

    def _add(self, pattern: str, severity: str, node: ast.AST, msg: str):
        try:
            src = ast.unparse(node)
        except Exception:
            src = "<unrenderable>"
        self.warnings.append(msg)
        self.findings.append({
            "pattern": pattern,
            "line": getattr(node, "lineno", -1),
            "col": getattr(node, "col_offset", -1),
            "src": src,
            "severity": severity,
        })

    # 1. shift(-N)
    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            # series.shift(-N)
            if attr == "shift" and node.args:
                neg = _is_negative_constant(node.args[0])
                if neg is None and node.keywords:
                    for kw in node.keywords:
                        if kw.arg in ("periods", "n"):
                            neg = _is_negative_constant(kw.value)
                            if neg is not None:
                                break
                if neg is not None:
                    var = ast.unparse(node.func.value) if hasattr(ast, "unparse") else "?"
                    self._add(
                        "shift_negative",
                        "high",
                        node,
                        f"`{var}.shift(-{neg})` -- negative shift = future lookup",
                    )

            # 7. groupby(...).bfill() or fillna(method='bfill')
            if attr == "bfill":
                # call chain: <expr>.bfill(...) where <expr> includes groupby(
                chain_src = ast.unparse(node.func.value) if hasattr(ast, "unparse") else ""
                if "groupby(" in chain_src:
                    self._add(
                        "groupby_bfill",
                        "high",
                        node,
                        f"`{chain_src}.bfill()` -- backward fill on groups uses future values",
                    )
            if attr == "fillna":
                method_val = None
                for kw in node.keywords:
                    if kw.arg == "method" and isinstance(kw.value, ast.Constant):
                        method_val = kw.value.value
                if method_val is None and node.args:
                    a0 = node.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        method_val = a0.value
                if method_val == "bfill":
                    chain_src = ast.unparse(node.func.value) if hasattr(ast, "unparse") else ""
                    if "groupby(" in chain_src:
                        self._add(
                            "groupby_fillna_bfill",
                            "high",
                            node,
                            f"`{chain_src}.fillna(method='bfill')` -- backward fill on groups uses future values",
                        )

            # 6. reverse-cumsum: <something>[::-1].cumsum() — handled via Subscript->Call chain
            if attr in self._ACCUMULATOR_METHODS:
                inner = node.func.value
                if isinstance(inner, ast.Subscript):
                    sl = inner.slice
                    if isinstance(sl, ast.Slice) and sl.step is not None:
                        # detect step == -1
                        step = sl.step
                        if (
                            isinstance(step, ast.UnaryOp)
                            and isinstance(step.op, ast.USub)
                            and isinstance(step.operand, ast.Constant)
                            and step.operand.value == 1
                        ) or (
                            isinstance(step, ast.Constant) and step.value == -1
                        ):
                            self._add(
                                "reverse_cumulative",
                                "high",
                                node,
                                f"`{ast.unparse(node)}` -- cumulative on reversed sequence sees future in original time",
                            )

        self.generic_visit(node)

    # 2/3. Subscript forward + index>X heuristic
    def visit_Subscript(self, node: ast.Subscript):
        # iloc[i+N:] / loc[i+N:] / arr[t+1:]
        try:
            container_src = ast.unparse(node.value) if hasattr(ast, "unparse") else ""
        except Exception:
            container_src = ""

        if _slice_uses_forward_offset(node.slice):
            severity = "high"
            pattern = "subscript_forward_offset"
            if container_src.endswith(".iloc") or container_src.endswith(".loc") or ".iloc" in container_src or ".loc" in container_src:
                pattern = "iloc_loc_forward"
            self._add(
                pattern,
                severity,
                node,
                f"forward subscript: `{ast.unparse(node)}`",
            )

        # 3. df[df.index > X] heuristic
        sl = node.slice
        if isinstance(sl, ast.Compare) and len(sl.ops) == 1 and isinstance(sl.ops[0], (ast.Gt, ast.GtE)):
            left = sl.left
            if isinstance(left, ast.Attribute) and left.attr == "index":
                # right side variable -> heuristic suspicious
                comparator = sl.comparators[0]
                if not isinstance(comparator, ast.Constant):
                    self._add(
                        "index_gt_future",
                        "medium",
                        node,
                        f"`{ast.unparse(node)}` -- df[df.index > X] uses runtime variable; possible future filter",
                    )

        self.generic_visit(node)

    # 4. for i in range(...): use prices[i+N]
    def visit_For(self, node: ast.For):
        loop_vars: set[str] = set()
        if isinstance(node.target, ast.Name):
            loop_vars.add(node.target.id)
        elif isinstance(node.target, ast.Tuple):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    loop_vars.add(elt.id)
        self._loop_var_stack.append(loop_vars)
        # scan the body for forward subscripts that use the loop var
        for child in ast.walk(node):
            if isinstance(child, ast.Subscript):
                hit = self._forward_offset_uses_var(child.slice, loop_vars)
                if hit is not None:
                    name_id, offset = hit
                    self._add(
                        "for_loop_forward_access",
                        "high",
                        child,
                        f"loop forward access: `{ast.unparse(child)}` (loop var `{name_id}` + {offset})",
                    )
        self.generic_visit(node)
        self._loop_var_stack.pop()

    @staticmethod
    def _forward_offset_uses_var(slice_node: ast.AST, allowed: set[str]):
        """Return (var_name, offset) if a forward offset references one of `allowed`."""
        def _check_binop(b: ast.BinOp):
            if not isinstance(b.op, ast.Add):
                return None
            if isinstance(b.left, ast.Name) and isinstance(b.right, ast.Constant):
                if isinstance(b.right.value, int) and b.right.value > 0 and b.left.id in allowed:
                    return (b.left.id, b.right.value)
            if isinstance(b.right, ast.Name) and isinstance(b.left, ast.Constant):
                if isinstance(b.left.value, int) and b.left.value > 0 and b.right.id in allowed:
                    return (b.right.id, b.left.value)
            return None

        if isinstance(slice_node, ast.BinOp):
            return _check_binop(slice_node)
        if isinstance(slice_node, ast.Slice):
            for part in (slice_node.lower, slice_node.upper, slice_node.step):
                if isinstance(part, ast.BinOp):
                    h = _check_binop(part)
                    if h is not None:
                        return h
            return None
        if isinstance(slice_node, ast.Tuple):
            for e in slice_node.elts:
                h = _ExtendedLookaheadVisitor._forward_offset_uses_var(e, allowed)
                if h is not None:
                    return h
        return None

    # 5. lambda i: df.iloc[i+N]
    def visit_Lambda(self, node: ast.Lambda):
        arg_names = {a.arg for a in node.args.args}
        for child in ast.walk(node.body):
            if isinstance(child, ast.Subscript):
                hit = self._forward_offset_uses_var(child.slice, arg_names)
                if hit is not None:
                    name_id, offset = hit
                    self._add(
                        "lambda_forward_access",
                        "medium",
                        child,
                        f"lambda forward access: `{ast.unparse(child)}` (param `{name_id}` + {offset})",
                    )
        self.generic_visit(node)


def scan_lookahead(signal_fn: Callable) -> list[str]:
    """Static AST scan. Returns list of warnings (empty = clean).

    Backward-compatible API: includes both legacy text-pattern findings (low severity)
    and extended AST findings, flattened into a single warning list.
    """
    try:
        src = textwrap.dedent(inspect.getsource(signal_fn))
    except (OSError, TypeError):
        return ["could not read source"]
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"parse error: {e}"]
    legacy = _ForwardSliceVisitor()
    legacy.visit(tree)
    extended = _ExtendedLookaheadVisitor()
    extended.visit(tree)
    return legacy.warnings + extended.warnings


def scan_lookahead_v2(signal_fn: Callable) -> StaticLookaheadReport:
    """Extended scan covering shift(-N), iloc forward, lambda forward, reverse-cumsum,
    groupby bfill, forward index comparison, for-loop forward access, plus legacy text
    patterns. Returns a structured report.
    """
    report = StaticLookaheadReport()
    try:
        src = textwrap.dedent(inspect.getsource(signal_fn))
    except (OSError, TypeError):
        report.warnings.append("could not read source")
        return report
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        report.warnings.append(f"parse error: {e}")
        return report

    legacy = _ForwardSliceVisitor()
    legacy.visit(tree)
    extended = _ExtendedLookaheadVisitor()
    extended.visit(tree)

    report.warnings = list(legacy.warnings) + list(extended.warnings)
    report.findings = list(legacy.findings) + list(extended.findings)
    counts = {"high": 0, "medium": 0, "low": 0}
    for f in report.findings:
        sev = f.get("severity", "low")
        if sev not in counts:
            counts[sev] = 0
        counts[sev] += 1
    report.severity_counts = counts
    return report


def runtime_lookahead_check_intraday(signal_fn: Callable,
                                     ohlcv_minute_df: pd.DataFrame,
                                     shuffle_from_idx: int | None = None,
                                     seed: int = 42,
                                     include_static_v2: bool = True,
                                     n_shuffles: int = 20) -> LookaheadReport:
    """Runtime lookahead check for intraday/minute-bar strategies.

    Same shuffle-and-compare logic as ``runtime_lookahead_check`` but operates
    on full OHLCV minute-bar DataFrames. After index ``k`` we permute ROWS of
    the OHLCV frame (preserving columns), recompute signals, and verify that
    signals BEFORE ``k`` are unchanged. Any divergence indicates the strategy
    pulls future bars.

    A single random permutation can give a false negative when the permutation
    happens to leave a key bar in place. To mitigate this we run ``n_shuffles``
    independent permutations and return the maximum absolute pre-k signal
    divergence across all of them.

    Args:
        signal_fn: callable(ohlcv_df) -> array of signals
        ohlcv_minute_df: DataFrame with at minimum OHLCV columns and a
                         monotonically-increasing index of minute timestamps.
        shuffle_from_idx: index after which rows are shuffled (default: middle)
        seed: RNG seed for the row permutation
        include_static_v2: when True (default) also attaches the StaticLookaheadReport.
        n_shuffles: number of independent shuffles to test (>= 1). Default 20.
            The reported delta is the max over shuffles; ``passed`` is False if
            any shuffle exceeds the leak threshold.

    Returns:
        LookaheadReport mirroring ``runtime_lookahead_check`` for daily prices.
    """
    if not isinstance(ohlcv_minute_df, pd.DataFrame):
        raise TypeError("ohlcv_minute_df must be a pd.DataFrame")
    if len(ohlcv_minute_df) < 4:
        raise ValueError("ohlcv_minute_df too short for runtime intraday check")
    if n_shuffles < 1:
        raise ValueError(f"n_shuffles must be >= 1 (got {n_shuffles})")

    static_warns = scan_lookahead(signal_fn)
    static_v2 = scan_lookahead_v2(signal_fn) if include_static_v2 else None

    df_orig = ohlcv_minute_df.copy()
    sig_orig = np.asarray(signal_fn(df_orig))

    n = len(ohlcv_minute_df)
    k = shuffle_from_idx if shuffle_from_idx is not None else (n // 2)

    # Use child_rng when a global seed is active so cross-process runs share
    # the same permutation; fall back to the explicit ``seed`` argument
    # otherwise (legacy behaviour, default seed=42).
    rng = child_rng("lookahead_runtime") if _seed.GLOBAL_SEED is not None else np.random.default_rng(seed)
    base_values = ohlcv_minute_df.values.copy()
    max_diff_overall = 0.0

    # We always run all ``n_shuffles`` permutations and report the max delta.
    # Short-circuiting on the first leaking shuffle defeats the purpose of
    # taking multiple draws to mitigate false negatives where a single random
    # permutation happens to leave a key bar in place.
    for _ in range(n_shuffles):
        # Shuffle row positions in [k, n) only; preserve full schema and original index.
        perm = rng.permutation(n - k)
        values = base_values.copy()
        tail = values[k:].copy()
        values[k:] = tail[perm]
        df_shuf = pd.DataFrame(
            values,
            index=ohlcv_minute_df.index,
            columns=ohlcv_minute_df.columns,
        )
        sig_shuf = np.asarray(signal_fn(df_shuf))

        if len(sig_orig) != len(sig_shuf):
            return LookaheadReport(static_warns, True, np.inf, False, static_v2)
        diff = np.abs(np.asarray(sig_orig[:k], dtype=float) - np.asarray(sig_shuf[:k], dtype=float))
        if len(diff) > 0:
            d = float(diff.max())
            if d > max_diff_overall:
                max_diff_overall = d

    leak = max_diff_overall > 1e-6
    return LookaheadReport(
        static_warnings=static_warns,
        runtime_violation=leak,
        runtime_metric_delta=max_diff_overall,
        passed=not leak,
        static_v2=static_v2,
    )


def runtime_lookahead_check(signal_fn: Callable, prices: pd.Series,
                            shuffle_from_idx: int | None = None,
                            seed: int = 42,
                            include_static_v2: bool = True,
                            n_shuffles: int = 20) -> LookaheadReport:
    """Runtime check: shuffle prices AFTER index k, recompute signals, compare to original.

    If signals[:k] differ between original and shuffled future -> lookahead leak.

    A single random permutation can give a false negative when the permutation
    happens to leave a key bar in place (e.g. a leaky strategy that only peeks
    at the very next bar may not flag if that bar is unchanged by the random
    draw). To mitigate this we run ``n_shuffles`` independent permutations and
    return the maximum absolute pre-k signal divergence across all of them.

    Args:
        signal_fn: Strategy.signals
        prices: original prices
        shuffle_from_idx: index from which to shuffle (default: middle)
        include_static_v2: when True (default) also attach StaticLookaheadReport.
        n_shuffles: number of independent shuffles to test (>= 1). Default 20.
            The reported delta is the max over shuffles; ``passed`` is False if
            any shuffle exceeds the leak threshold.
    """
    if n_shuffles < 1:
        raise ValueError(f"n_shuffles must be >= 1 (got {n_shuffles})")
    static_warns = scan_lookahead(signal_fn)
    static_v2 = scan_lookahead_v2(signal_fn) if include_static_v2 else None
    p_orig = prices.copy()
    sig_orig = np.asarray(signal_fn(p_orig))
    n = len(prices)
    k = shuffle_from_idx if shuffle_from_idx is not None else (n // 2)

    # Use child_rng when a global seed is active so cross-process runs share
    # the same permutation; fall back to the explicit ``seed`` argument
    # otherwise (legacy behaviour, default seed=42).
    rng = child_rng("lookahead_runtime") if _seed.GLOBAL_SEED is not None else np.random.default_rng(seed)
    base_values = prices.values.copy()
    max_diff_overall = 0.0

    # We always run all ``n_shuffles`` permutations and report the max delta.
    # Short-circuiting on the first leaking shuffle defeats the purpose of
    # taking multiple draws to mitigate false negatives where a single random
    # permutation happens to leave a key bar in place.
    for _ in range(n_shuffles):
        shuffled = base_values.copy()
        perm = rng.permutation(shuffled[k:])
        shuffled[k:] = perm
        p_shuf = pd.Series(shuffled, index=prices.index, name=prices.name)
        sig_shuf = np.asarray(signal_fn(p_shuf))

        if len(sig_orig) != len(sig_shuf):
            return LookaheadReport(static_warns, True, np.inf, False, static_v2)
        diff = np.abs(np.asarray(sig_orig[:k], dtype=float) - np.asarray(sig_shuf[:k], dtype=float))
        if len(diff) > 0:
            d = float(diff.max())
            if d > max_diff_overall:
                max_diff_overall = d

    leak = max_diff_overall > 1e-6
    # Pass only on runtime check; static warnings advisory (heuristic, false positives possible)
    return LookaheadReport(
        static_warnings=static_warns,
        runtime_violation=leak,
        runtime_metric_delta=max_diff_overall,
        passed=not leak,
        static_v2=static_v2,
    )
