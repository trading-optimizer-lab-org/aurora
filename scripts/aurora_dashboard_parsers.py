"""Format-safe result extraction for the Aurora runs dashboard.

This module only interprets explicit values in a source artifact. It never
guesses a metric unit, research phase, baseline, or validation state.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable


PARSER_VERSION = "1.0.0"
_TEXT_EXTENSIONS = {".csv", ".json", ".jsonl", ".md", ".markdown", ".txt", ".html", ".htm"}
_METRIC_KEYS = {
    "calmar",
    "cagr",
    "cagr_pct",
    "sharpe",
    "sortino",
    "max_drawdown",
    "max_drawdown_pct",
    "mdd",
    "win_rate",
    "accuracy",
    "n_trades",
    "trades",
    "overall_passed",
    "passed",
    "p_value",
    "pvalue",
    "correlation",
    "coverage",
}
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_. -]{0,80}$")


@dataclass(frozen=True)
class ParserContext:
    run_id: int
    artifact_id: int
    workflow_name: str
    artifact_name: str
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class NormalizedMetric:
    result_id: str
    run_id: int
    artifact_id: int
    result_kind: str
    parser_key: str
    parser_version: str
    status: str
    metric_key: str
    metric_value: float | None
    value_text: str | None
    unit: str | None
    phase: str | None
    period_start: str | None
    period_end: str | None
    baseline: str | None
    cost_model: str | None
    candidate_id: str | None
    passed: bool | None
    source_path: str | None
    evidence: dict[str, Any]
    captured_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "result_kind": self.result_kind,
            "parser_key": self.parser_key,
            "parser_version": self.parser_version,
            "status": self.status,
            "metric_key": self.metric_key,
            "metric_value": self.metric_value,
            "value_text": self.value_text,
            "unit": self.unit,
            "phase": self.phase,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "baseline": self.baseline,
            "cost_model": self.cost_model,
            "candidate_id": self.candidate_id,
            "passed": self.passed,
            "source_path": self.source_path,
            "evidence": self.evidence,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True)
class ParseReport:
    parser_key: str
    parser_version: str
    status: str
    result_kind: str
    metrics: tuple[NormalizedMetric, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    readable: bool = False


Parser = Callable[[bytes, ParserContext, str, str], ParseReport]
_PARSERS: list[tuple[str, Callable[[str, str], bool], Parser]] = []


def register_parser(key: str, matcher: Callable[[str, str], bool], parser: Parser) -> None:
    """Register a parser in deterministic order, replacing an existing key."""
    global _PARSERS
    _PARSERS = [entry for entry in _PARSERS if entry[0] != key]
    _PARSERS.append((key, matcher, parser))


def _extension(name: str) -> str:
    name = name.lower().split("?", 1)[0]
    dot = name.rsplit(".", 1)
    return f".{dot[-1]}" if len(dot) == 2 else ""


def _parser_key(workflow_name: str, artifact_name: str) -> str:
    value = f"{workflow_name} {artifact_name}".lower()
    for key in ("atlas", "swr", "spy", "btc", "paper", "literature", "openap"):
        if key in value:
            return key
    return "generic"


def _result_kind(parser_key: str) -> str:
    if parser_key in {"atlas", "swr", "spy", "btc", "paper"}:
        return "backtest"
    if parser_key == "literature":
        return "literature"
    if parser_key == "openap":
        return "data_quality"
    return "unclassified"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "passed", "pass"}:
            return True
        if lowered in {"false", "no", "failed", "fail"}:
            return False
    return None


def _key_name(key: Any) -> str | None:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return None
    normalized = key.strip().lower().replace(" ", "_").replace("-", "_")
    return normalized if normalized in _METRIC_KEYS else None


def _context_value(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def _records(payload: Any) -> Iterable[tuple[str, Any, dict[str, Any], str]]:
    """Yield metric key/value/context/source path from nested structured data."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            metric_key = _key_name(key)
            if metric_key:
                yield metric_key, value, payload, str(key)
            if isinstance(value, (dict, list)):
                yield from _records(value)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            if isinstance(item, (dict, list)):
                for record in _records(item):
                    yield record[0], record[1], record[2], f"[{index}].{record[3]}"


def _make_metric(
    context: ParserContext,
    parser_key: str,
    result_kind: str,
    metric_key: str,
    value: Any,
    metadata: dict[str, Any],
    source_path: str,
    index: int,
) -> NormalizedMetric:
    numeric = _number(value)
    value_text = None if numeric is not None else (str(value) if value is not None else None)
    passed = _bool(value) if metric_key in {"passed", "overall_passed"} else _bool(metadata.get("passed"))
    result_id = f"{context.run_id}:{context.artifact_id}:{metric_key}:{index}"
    return NormalizedMetric(
        result_id=result_id,
        run_id=context.run_id,
        artifact_id=context.artifact_id,
        result_kind=result_kind,
        parser_key=parser_key,
        parser_version=PARSER_VERSION,
        status="parsed" if numeric is not None or value_text is not None else "partial",
        metric_key=metric_key,
        metric_value=numeric,
        value_text=value_text,
        # Only explicit metadata is allowed to populate these fields.
        unit=_context_value(metadata, "unit", "units"),
        phase=_context_value(metadata, "phase", "tier"),
        period_start=_context_value(metadata, "period_start", "start", "from"),
        period_end=_context_value(metadata, "period_end", "end", "to"),
        baseline=_context_value(metadata, "baseline", "benchmark"),
        cost_model=_context_value(metadata, "cost_model", "costs"),
        candidate_id=_context_value(metadata, "candidate_id", "candidate"),
        passed=passed,
        source_path=source_path,
        evidence={"artifact_name": context.artifact_name, "workflow_name": context.workflow_name},
        captured_at=context.captured_at,
    )


def _parse_structured(payload: Any, context: ParserContext, parser_key: str) -> tuple[NormalizedMetric, ...]:
    result_kind = _result_kind(parser_key)
    metrics: list[NormalizedMetric] = []
    for index, (key, value, metadata, path) in enumerate(_records(payload)):
        metrics.append(_make_metric(context, parser_key, result_kind, key, value, metadata, path, index))
    return tuple(metrics)


def _parse_csv(text: str, context: ParserContext, parser_key: str) -> tuple[NormalizedMetric, ...]:
    reader = csv.DictReader(io.StringIO(text))
    metrics: list[NormalizedMetric] = []
    for row_index, row in enumerate(reader):
        for key, value in row.items():
            metric_key = _key_name(key)
            if metric_key and value not in (None, ""):
                metrics.append(_make_metric(context, parser_key, _result_kind(parser_key), metric_key, value, row, f"row[{row_index}].{key}", len(metrics)))
    return tuple(metrics)


def _parse_text(text: str, context: ParserContext, parser_key: str) -> tuple[NormalizedMetric, ...]:
    metrics: list[NormalizedMetric] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if ":" not in line and "=" not in line:
            continue
        separator = ":" if ":" in line else "="
        raw_key, raw_value = line.split(separator, 1)
        metric_key = _key_name(raw_key.strip().strip("|`*"))
        if metric_key:
            metrics.append(_make_metric(context, parser_key, _result_kind(parser_key), metric_key, raw_value.strip().strip("|`*"), {}, f"line[{line_number}]", len(metrics)))
    return tuple(metrics)


def parse_artifact(name: str, payload: bytes, context: ParserContext | None = None) -> ParseReport:
    """Parse explicit metrics without guessing semantics."""
    context = context or ParserContext(run_id=0, artifact_id=0, workflow_name="", artifact_name=name)
    parser_key = _parser_key(context.workflow_name, name)
    extension = _extension(name)
    if extension not in _TEXT_EXTENSIONS:
        return ParseReport(parser_key=parser_key, parser_version=PARSER_VERSION, status="unclassified", result_kind=_result_kind(parser_key), warnings=("unsupported extension",), readable=False)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ParseReport(parser_key=parser_key, parser_version=PARSER_VERSION, status="error", result_kind=_result_kind(parser_key), errors=("payload is not UTF-8 text",), readable=False)

    try:
        if extension == ".csv":
            metrics = _parse_csv(text, context, parser_key)
        elif extension in {".json", ".jsonl"}:
            if extension == ".jsonl":
                payloads = [json.loads(line) for line in text.splitlines() if line.strip()]
                metrics = _parse_structured(payloads, context, parser_key)
            else:
                metrics = _parse_structured(json.loads(text), context, parser_key)
        else:
            metrics = _parse_text(text, context, parser_key)
    except (json.JSONDecodeError, csv.Error, ValueError) as exc:
        return ParseReport(parser_key=parser_key, parser_version=PARSER_VERSION, status="error", result_kind=_result_kind(parser_key), errors=(str(exc),), readable=True)

    status = "parsed" if metrics else "partial"
    warnings = () if metrics else ("readable artifact contains no recognized metric keys",)
    return ParseReport(parser_key=parser_key, parser_version=PARSER_VERSION, status=status, result_kind=_result_kind(parser_key), metrics=metrics, warnings=warnings, readable=True)


def parser_catalog() -> tuple[str, ...]:
    return ("generic", "atlas", "swr", "spy", "btc", "paper", "literature", "openap")
