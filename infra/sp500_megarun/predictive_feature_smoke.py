"""Train-only GitHub smoke for executable SP500 lanes F141-F150."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_cboe_vol_panel,
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.predictive_feature_engine import (
    evaluate_predictive_family_batch,
)


class PredictiveFeatureSmokeError(ValueError):
    """Raised when the predictive smoke is not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(141, 151))
_DATASETS = ("D_SPY", "D_CALENDAR", "D_VIX", "D_VXO")
_APPROVED_FEATURE_ROOTS = {
    "F003": "price",
    "F015": "price",
    "F021": "market",
    "F032": "macro",
    "F039": "macro",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_features(
    *,
    price_feature_dir: Path,
    market_feature_dir: Path,
    macro_feature_dir: Path,
) -> dict[str, pd.DataFrame]:
    roots = {
        "price": price_feature_dir,
        "market": market_feature_dir,
        "macro": macro_feature_dir,
    }
    features: dict[str, pd.DataFrame] = {}
    for lane, root_name in _APPROVED_FEATURE_ROOTS.items():
        target = roots[root_name] / "features" / f"{lane}.parquet"
        if not target.is_file():
            raise PredictiveFeatureSmokeError(f"CAUSAL_FEATURE_MISSING:{lane}")
        features[lane] = pd.read_parquet(target)
    return features


def build_predictive_feature_smoke(
    train_snapshot: str | Path,
    *,
    price_feature_dir: str | Path,
    market_feature_dir: str | Path,
    macro_feature_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute F141-F150 without mounting validation or locked partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise PredictiveFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    raw: dict[str, pd.DataFrame] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise PredictiveFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset}")
        raw[dataset] = pd.read_parquet(target)
    if "date" not in raw["D_CALENDAR"] or raw["D_CALENDAR"].empty:
        raise PredictiveFeatureSmokeError("EMPTY_PHYSICAL_CALENDAR")
    feature_panels = _load_features(
        price_feature_dir=Path(price_feature_dir),
        market_feature_dir=Path(market_feature_dir),
        macro_feature_dir=Path(macro_feature_dir),
    )
    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    panels = {
        "spy": normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions),
        "cboe": normalize_cboe_vol_panel(
            raw["D_VIX"], raw["D_VXO"], sessions=sessions
        ),
    }
    outputs = dict(evaluate_predictive_family_batch(panels, feature_panels))
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_LANES,
        search_start=_SEARCH_START,
        search_end=_TRAIN_END,
    )
    root = Path(output_dir)
    artifacts: dict[str, dict[str, object]] = {}
    maximum = pd.Timestamp.min
    for lane, output in outputs.items():
        target = root / "features" / f"{lane}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        parquet_safe_frame(output).to_parquet(target, index=False)
        maximum = max(maximum, pd.to_datetime(output["date"]).max())
        artifacts[lane] = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _sha256(target),
            "rows": len(output),
            "non_null_values": int(output["value"].notna().sum()),
        }
    report = {
        "schema_version": 1,
        "ready": bool(audit.ready and len(outputs) == 10),
        "scope": "predictive_model_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": 10,
        "approved_causal_inputs": list(_APPROVED_FEATURE_ROOTS),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "target_definition": "next_session_spy_log_return_known_at_next_decision",
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [
            list(group) for group in audit.exact_duplicate_groups
        ],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "predictive_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


__all__ = ["PredictiveFeatureSmokeError", "build_predictive_feature_smoke"]
