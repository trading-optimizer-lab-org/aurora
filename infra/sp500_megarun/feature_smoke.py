"""Train-only technical smoke for the executable SP500 price families."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_contract import (
    FeatureLaneSpec,
    apply_available_at_policy,
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.feature_engine import (
    FeatureEngineError,
    evaluate_price_family_batch,
    evaluate_price_lane,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame


_PRICE_LANE_IDS = tuple(f"F{number:03d}" for number in range(1, 21))
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_price_feature_smoke(
    spy_frame: pd.DataFrame,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Build and audit F001-F020 using only the supplied 1993-2010 SPY rows."""

    if "date" not in spy_frame:
        raise FeatureEngineError("MISSING_SPY_COLUMNS:date")
    dates = pd.to_datetime(spy_frame["date"], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise FeatureEngineError("INVALID_SPY_TIMESTAMPS")
    if dates.gt(_TRAIN_END).any():
        raise FeatureEngineError("NON_TRAIN_PRICE_ROW")
    if len(spy_frame) < 2:
        raise FeatureEngineError("INSUFFICIENT_SPY_SESSIONS")

    sessions = pd.DatetimeIndex(dates).unique().sort_values()
    available_spy = apply_available_at_policy(
        spy_frame.iloc[:-1].copy(),
        policy="next_session",
        sessions=sessions,
    )
    outputs = evaluate_price_family_batch(available_spy)
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_PRICE_LANE_IDS,
        search_start=_SEARCH_START,
        search_end=_TRAIN_END,
    )

    root = Path(output_dir)
    feature_dir = root / "features"
    feature_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, Any]] = {}
    for lane_id in _PRICE_LANE_IDS:
        target = feature_dir / f"{lane_id}.parquet"
        parquet_safe_frame(outputs[lane_id]).to_parquet(target, index=False)
        artifacts[lane_id] = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _sha256(target),
            "rows": int(len(outputs[lane_id])),
            "non_null_values": int(outputs[lane_id]["value"].notna().sum()),
        }

    maximum_feature_date = max(
        pd.to_datetime(frame["date"], errors="raise").max()
        for frame in outputs.values()
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": bool(audit.ready and len(outputs) == len(_PRICE_LANE_IDS)),
        "scope": "technical_feature_smoke_train_only",
        "executable_lanes": list(_PRICE_LANE_IDS),
        "executable_lane_count": len(_PRICE_LANE_IDS),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum_feature_date.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "availability_policy": "next_session",
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
    }
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "feature_smoke_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _compatible_price_parameters(
    lane: FeatureLaneSpec,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    if lane.lane_id == "F002" and int(parameters["fast"]) >= int(parameters["slow"]):
        parameters["slow"] = next(
            value
            for value in lane.parameter_space["slow"]
            if int(value) > int(parameters["fast"])
        )
    return parameters


def _output_signature(frame: pd.DataFrame) -> str:
    values = pd.to_numeric(frame["value"], errors="coerce").to_numpy(dtype="<f8")
    valid = np.isfinite(values)
    canonical = np.nan_to_num(
        values,
        nan=9.87654321e307,
        posinf=8.7654321e307,
        neginf=-8.7654321e307,
    )
    return hashlib.sha256(valid.tobytes() + canonical.tobytes()).hexdigest()


def build_price_parameter_choice_audit(
    spy_frame: pd.DataFrame,
    *,
    data_contract_path: Path,
    feature_contract_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Execute every frozen F001-F020 categorical choice on train-only rows."""

    data_contract = load_and_validate_contract(data_contract_path)
    feature_contract = load_and_validate_feature_contract(
        feature_contract_path,
        data_contract,
    )
    dates = pd.to_datetime(spy_frame["date"], errors="coerce").dt.normalize()
    if dates.isna().any() or dates.gt(_TRAIN_END).any() or len(dates) < 2:
        raise FeatureEngineError("INVALID_TRAIN_PRICE_PARAMETER_AUDIT_INPUT")
    sessions = pd.DatetimeIndex(dates).unique().sort_values()
    available_spy = apply_available_at_policy(
        spy_frame.iloc[:-1].copy(),
        policy="next_session",
        sessions=sessions,
    )

    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    signatures: dict[tuple[str, str], dict[str, list[Any]]] = {}
    maximum_output_date = pd.Timestamp.min
    lanes = feature_contract.lanes[:20]
    for lane in lanes:
        baseline = {
            name: choices[0] for name, choices in lane.parameter_space.items()
        }
        for parameter, choices in lane.parameter_space.items():
            for choice in choices:
                configuration = _compatible_price_parameters(
                    lane,
                    {**baseline, parameter: choice},
                )
                probe_id = f"{lane.lane_id}:{parameter}:{choice!r}"
                try:
                    output = evaluate_price_lane(
                        lane.lane_id,
                        available_spy,
                        configuration,
                    )
                    output_dates = pd.to_datetime(output["date"], errors="raise")
                    values = pd.to_numeric(output["value"], errors="coerce")
                    valid = values.notna() & output_dates.ge(_SEARCH_START)
                    covered_years = tuple(sorted(set(output_dates.loc[valid].dt.year)))
                    if covered_years != tuple(range(1998, 2011)):
                        raise FeatureEngineError(
                            f"INCOMPLETE_PARAMETER_CHOICE_COVERAGE:{covered_years}"
                        )
                    if output_dates.max() > _TRAIN_END:
                        raise FeatureEngineError("NON_TRAIN_PARAMETER_CHOICE_OUTPUT")
                    if not pd.to_datetime(output["available_at"]).le(output_dates).all():
                        raise FeatureEngineError("NON_CAUSAL_PARAMETER_CHOICE_OUTPUT")
                    signature = _output_signature(output)
                    signatures.setdefault((lane.lane_id, parameter), {}).setdefault(
                        signature, []
                    ).append(choice)
                    maximum_output_date = max(maximum_output_date, output_dates.max())
                    records.append(
                        {
                            "probe_id": probe_id,
                            "lane_id": lane.lane_id,
                            "parameter": parameter,
                            "choice": choice,
                            "configuration": configuration,
                            "non_null_search_rows": int(valid.sum()),
                            "covered_years": list(covered_years),
                            "output_sha256": signature,
                        }
                    )
                except (FeatureEngineError, KeyError, TypeError, ValueError) as exc:
                    failures.append(
                        {
                            "probe_id": probe_id,
                            "error": f"{type(exc).__name__}:{exc}",
                        }
                    )
    inactive_groups = [
        {
            "lane_id": lane_id,
            "parameter": parameter,
            "choices": choices,
            "output_sha256": signature,
        }
        for (lane_id, parameter), groups in sorted(signatures.items())
        for signature, choices in groups.items()
        if len(choices) > 1
    ]
    expected = sum(
        len(choices)
        for lane in lanes
        for choices in lane.parameter_space.values()
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": not failures and len(records) == expected,
        "scope": "F001_F020_every_frozen_parameter_choice_train_only",
        "data_contract_sha256": data_contract.sha256,
        "feature_contract_sha256": feature_contract.sha256,
        "lane_count": len(lanes),
        "expected_choice_probe_count": expected,
        "choice_probe_count": len(records),
        "failed_probes": failures,
        "inactive_choice_groups": inactive_groups,
        "maximum_output_date": maximum_output_date.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "records": records,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "FeatureEngineError",
    "build_price_feature_smoke",
    "build_price_parameter_choice_audit",
]
