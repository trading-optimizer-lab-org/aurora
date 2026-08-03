"""Versioned contracts for the canonical GTBI V7 successor outputs."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from .canonical import canonical_bytes, domain_digest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPOSITORY_ROOT / "config" / "gtbi" / "schemas" / "v7" / "results"
RESULT_FILES = (
    "summary.json",
    "leaderboard.csv",
    "filtered_leaderboard.csv",
    "yearly_trade_performance.csv",
    "top_indicator_rules.jsonl",
)


class SuccessorContractError(ValueError):
    """Raised when successor evidence violates its frozen contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SuccessorContractError(f"JSON object expected: {path}")
    return dict(value)


def _schema(name: str) -> dict[str, Any]:
    return _load_object(SCHEMA_ROOT / name)


def _data_row_count(path: Path) -> int:
    if not path.is_file() or path.stat().st_size == 0:
        return 0
    with path.open("rb") as handle:
        newline_count = sum(
            chunk.count(b"\n") for chunk in iter(lambda: handle.read(1024 * 1024), b"")
        )
    return max(newline_count - 1, 0)


def _jsonl_row_count(path: Path) -> int:
    if not path.is_file() or path.stat().st_size == 0:
        return 0
    with path.open("rb") as handle:
        return sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1024 * 1024), b""))


def _coerce_csv_row(row: dict[str, str], schema: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    properties = schema.get("properties", {})
    for key, contract in properties.items():
        if key not in result:
            continue
        value = result[key]
        expected = contract.get("type")
        if expected == "integer" and value != "":
            result[key] = int(float(value))
        elif expected == "number" and value != "":
            result[key] = float(value)
    return result


def _validate_csv_sample(path: Path, schema_name: str, *, limit: int = 100) -> None:
    schema = _schema(schema_name)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SuccessorContractError(f"CSV header missing: {path.name}")
        missing = set(schema.get("required", ())) - set(reader.fieldnames)
        if missing:
            raise SuccessorContractError(f"{path.name} missing columns: {sorted(missing)}")
        for index, row in enumerate(reader):
            if index >= limit:
                break
            jsonschema.validate(_coerce_csv_row(dict(row), schema), schema)


def _candidate_ids(path: Path) -> set[str]:
    values: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "candidate_id" not in reader.fieldnames:
            raise SuccessorContractError("leaderboard.csv lacks candidate_id")
        for row in reader:
            candidate_id = str(row.get("candidate_id") or "")
            if candidate_id:
                values.add(candidate_id)
    return values


def _maximum_year(path: Path) -> int | None:
    maximum: int | None = None
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "year" not in reader.fieldnames:
            raise SuccessorContractError("yearly_trade_performance.csv lacks year")
        for row in reader:
            if not row.get("year"):
                continue
            value = int(float(str(row["year"])))
            maximum = value if maximum is None else max(maximum, value)
    return maximum


def validate_v7_result_artifact(root: Path) -> dict[str, Any]:
    """Validate frozen schemas, row equations and scientific boundaries."""
    root = Path(root)
    missing = [name for name in RESULT_FILES if not (root / name).is_file()]
    if missing:
        raise SuccessorContractError(f"result files missing: {missing}")

    summary = _load_object(root / "summary.json")
    jsonschema.validate(summary, _schema("summary.schema.json"))
    leaderboard_rows = _data_row_count(root / "leaderboard.csv")
    filtered_rows = _data_row_count(root / "filtered_leaderboard.csv")
    yearly_rows = _data_row_count(root / "yearly_trade_performance.csv")
    top_rule_rows = _jsonl_row_count(root / "top_indicator_rules.jsonl")
    early_rows = _data_row_count(root / "early_rejected_strategies.csv")

    if int(summary["total_strategies_evaluated"]) != leaderboard_rows:
        raise SuccessorContractError("evaluated count does not equal leaderboard rows")
    if int(summary["total_strategies_early_rejected"]) != early_rows:
        raise SuccessorContractError("early-rejected count does not equal early-rejected rows")
    if int(summary["leaderboard_rows"]) != leaderboard_rows:
        raise SuccessorContractError("summary leaderboard_rows mismatch")
    if int(summary["total_terminal_identities"]) != int(summary["total_strategies_loaded"]):
        raise SuccessorContractError("terminal identities do not equal loaded strategies")

    _validate_csv_sample(root / "leaderboard.csv", "leaderboard-row.schema.json")
    if yearly_rows:
        _validate_csv_sample(
            root / "yearly_trade_performance.csv",
            "yearly-trade-performance-row.schema.json",
        )
    with (root / "top_indicator_rules.jsonl").open("r", encoding="utf-8") as handle:
        rule_schema = _schema("top-indicator-rule.schema.json")
        for index, line in enumerate(handle):
            if index >= 100:
                break
            if line.strip():
                jsonschema.validate(json.loads(line), rule_schema)

    best = summary.get("best_candidate_id")
    candidates = _candidate_ids(root / "leaderboard.csv")
    if best is not None and str(best) not in candidates:
        raise SuccessorContractError("best_candidate_id is absent from leaderboard")
    if not candidates and best is not None:
        raise SuccessorContractError("empty leaderboard cannot name a best candidate")
    maximum_year = _maximum_year(root / "yearly_trade_performance.csv") if yearly_rows else None
    if maximum_year is not None and maximum_year > 2020:
        raise SuccessorContractError("result contains a year after 2020")

    files = []
    for path in sorted((root / name for name in RESULT_FILES), key=lambda item: item.name):
        files.append(
            {"path": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_successor_result_contract_receipt_v1",
        "campaign_id": "gtbi_v7_new_reference_v1",
        "valid": True,
        "leaderboard_rows": leaderboard_rows,
        "filtered_leaderboard_rows": filtered_rows,
        "yearly_trade_performance_rows": yearly_rows,
        "top_indicator_rule_rows": top_rule_rows,
        "early_rejected_rows": early_rows,
        "best_candidate_id": best,
        "maximum_result_year": maximum_year,
        "locked_start": "2021-01-01",
        "locked_authorized": False,
        "locked_data_accessed": False,
        "github_only_run": True,
        "requires_local_machine": False,
        "files": files,
    }
    receipt["receipt_digest"] = domain_digest("GTBI_V7_SUCCESSOR_RESULT_CONTRACT_V1", receipt)
    return receipt


def write_canonical_json(path: Path, payload: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(canonical_bytes(payload) + b"\n")


def schema_inventory() -> list[dict[str, Any]]:
    return [
        {"path": path.relative_to(REPOSITORY_ROOT).as_posix(), "sha256": sha256_file(path)}
        for path in sorted(SCHEMA_ROOT.glob("*.schema.json"))
    ]


def iter_result_consumers(paths: Iterable[Path]) -> Iterable[tuple[Path, list[str]]]:
    """Yield source files that name one or more canonical result files."""
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        consumed = [name for name in RESULT_FILES if name in text]
        if consumed:
            yield path, consumed
