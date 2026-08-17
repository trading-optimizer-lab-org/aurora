"""Fail-closed one-shot validation support for the frozen SP500 selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.dehb_objective import (
    ObjectiveContractError,
    score_realized_returns,
)


VALIDATION_ACK = "OPEN_SP500_MEGARUN_VALIDATION_2011_2020_SELECTED_12_ONCE"
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")


class SelectedValidationError(ValueError):
    """Raised when selected-strategy validation cannot remain fail-closed."""


@dataclass(frozen=True)
class ValidationSnapshotReceipt:
    snapshot_dir: Path
    manifest_sha256: str
    spy_sha256: str
    dataset_count: int
    maximum_date: str
    validation_opened: bool = True
    locked_opened: bool = False


@dataclass(frozen=True)
class SelectedStrategy:
    selection_order: int
    name: str
    source_kind: str
    source_id: str
    components: tuple[Mapping[str, Any], ...]
    composition: Mapping[str, Any]
    train_metrics: Mapping[str, float]
    recipe_sha256: str
    validation_informed: bool = False
    independent_validation: bool = True


@dataclass(frozen=True)
class SelectionManifest:
    selection_id: str
    source_train_run_id: int
    validation_opened: bool
    locked_opened: bool
    strategies: tuple[SelectedStrategy, ...]
    sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SelectedValidationError(f"SNAPSHOT_FILE_READ_FAILED:{path.name}") from exc
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _recipe_sha256(
    components: Sequence[Mapping[str, Any]],
    composition: Mapping[str, Any],
) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            {
                "components": [dict(component) for component in components],
                "composition": dict(composition),
            }
        )
    ).hexdigest()


def validate_selection_manifest(
    payload: Mapping[str, Any],
) -> tuple[SelectedStrategy, ...]:
    """Validate the exact pre-validation selection without opening data."""

    if (
        payload.get("schema_version") != 1
        or payload.get("selection_id") != "sp500-selected-12-before-validation-v1"
        or payload.get("source_train_run_id") != 31932275712
        or payload.get("validation_start") != "2011-01-01"
        or payload.get("validation_end") != "2020-12-31"
        or payload.get("locked_start") != "2021-01-01"
        or payload.get("validation_opened") is not False
        or payload.get("locked_opened") is not False
    ):
        raise SelectedValidationError("SELECTION_CONTRACT_INVALID")
    raw_strategies = payload.get("strategies")
    if not isinstance(raw_strategies, list) or len(raw_strategies) != 12:
        raise SelectedValidationError("SELECTION_STRATEGY_COUNT_INVALID")
    selected: list[SelectedStrategy] = []
    recipe_hashes: set[str] = set()
    source_ids: set[str] = set()
    allowed_compositions = {"identity", "and", "gate", "override", "vote", "weighted_score"}
    for expected_order, raw in enumerate(raw_strategies, start=1):
        if not isinstance(raw, Mapping) or raw.get("selection_order") != expected_order:
            raise SelectedValidationError("SELECTION_ORDER_INVALID")
        name = str(raw.get("name", "")).strip()
        source_kind = str(raw.get("source_kind", ""))
        source_id = str(raw.get("source_id", ""))
        train_metrics = raw.get("train_metrics")
        components = raw.get("components")
        composition = raw.get("composition")
        if (
            not name
            or source_kind not in {"catalog", "dehb"}
            or not source_id
            or source_id in source_ids
            or not isinstance(train_metrics, Mapping)
            or not isinstance(components, list)
            or not components
            or len(components) > 5
            or not isinstance(composition, Mapping)
        ):
            raise SelectedValidationError("SELECTION_STRATEGY_INVALID")
        normalized_components = []
        for component in components:
            if not isinstance(component, Mapping):
                raise SelectedValidationError("SELECTION_COMPONENT_INVALID")
            lane_id = str(component.get("lane_id", ""))
            configuration = component.get("configuration")
            if not re.fullmatch(r"F(?:00[1-9]|0[1-9][0-9]|1[0-9]{2}|2[0-3][0-9]|240)", lane_id):
                raise SelectedValidationError("SELECTION_LANE_INVALID")
            if not isinstance(configuration, Mapping):
                raise SelectedValidationError("SELECTION_CONFIGURATION_INVALID")
            _canonical_bytes(configuration)
            normalized_components.append(
                {"lane_id": lane_id, "configuration": dict(configuration)}
            )
        kind = str(composition.get("kind", ""))
        if kind not in allowed_compositions:
            raise SelectedValidationError("SELECTION_COMPOSITION_INVALID")
        if (kind == "identity") != (len(normalized_components) == 1):
            raise SelectedValidationError("SELECTION_COMPOSITION_ARITY_INVALID")
        required_metrics = {
            "annualized_strategy_return",
            "annualized_alpha",
            "weekly_winning_or_positive_rate",
        }
        if set(train_metrics) != required_metrics:
            raise SelectedValidationError("SELECTION_TRAIN_METRICS_INVALID")
        normalized_metrics = {key: float(train_metrics[key]) for key in required_metrics}
        if not all(math.isfinite(value) for value in normalized_metrics.values()):
            raise SelectedValidationError("SELECTION_TRAIN_METRICS_INVALID")
        recipe_hash = _recipe_sha256(normalized_components, composition)
        if recipe_hash in recipe_hashes:
            raise SelectedValidationError("SELECTION_STRATEGY_DUPLICATE")
        recipe_hashes.add(recipe_hash)
        source_ids.add(source_id)
        selected.append(
            SelectedStrategy(
                selection_order=expected_order,
                name=name,
                source_kind=source_kind,
                source_id=source_id,
                components=tuple(normalized_components),
                composition=dict(composition),
                train_metrics=normalized_metrics,
                recipe_sha256=recipe_hash,
            )
        )
    return tuple(selected)


def load_selection_manifest(path: Path) -> SelectionManifest:
    target = Path(path)
    try:
        payload = json.loads(target.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectedValidationError("SELECTION_MANIFEST_INVALID") from exc
    if not isinstance(payload, Mapping):
        raise SelectedValidationError("SELECTION_MANIFEST_INVALID")
    strategies = validate_selection_manifest(payload)
    return SelectionManifest(
        selection_id=str(payload["selection_id"]),
        source_train_run_id=int(payload["source_train_run_id"]),
        validation_opened=bool(payload["validation_opened"]),
        locked_opened=bool(payload["locked_opened"]),
        strategies=strategies,
        sha256=_sha256_file(target),
    )


def build_f024_inverse_diagnostic(
    selection: SelectionManifest,
) -> SelectedStrategy:
    """Build the exact validation-informed inverse of the selected F024 recipe."""

    expected = {
        "direction": "continuation",
        "normalization": "none",
        "statistic": "divergence",
        "window": 63,
    }
    matches = [
        strategy
        for strategy in selection.strategies
        if strategy.composition == {"kind": "identity"}
        and len(strategy.components) == 1
        and strategy.components[0].get("lane_id") == "F024"
        and strategy.components[0].get("configuration") == expected
    ]
    if len(matches) != 1:
        raise SelectedValidationError("F024_INVERSE_SOURCE_NOT_UNIQUE")
    configuration = dict(expected)
    configuration["direction"] = "reversal"
    components = ({"lane_id": "F024", "configuration": configuration},)
    composition = {"kind": "identity"}
    recipe_sha256 = _recipe_sha256(components, composition)
    return SelectedStrategy(
        selection_order=1,
        name="F024 divergencia VXO/VIX invertida",
        source_kind="validation_informed_diagnostic",
        source_id=f"diagnostic-f024-inverse-{recipe_sha256}",
        components=components,
        composition=composition,
        train_metrics={},
        recipe_sha256=recipe_sha256,
        validation_informed=True,
        independent_validation=False,
    )


def _compounded_return(values: pd.Series) -> float:
    return math.expm1(float(np.log1p(values.to_numpy(dtype=float)).sum()))


def score_validation_returns(
    strategy_returns: pd.Series,
    spy_returns: pd.Series,
) -> Mapping[str, Any]:
    """Score one unchanged recipe exclusively on validation years."""

    if strategy_returns.empty or not strategy_returns.index.equals(spy_returns.index):
        raise SelectedValidationError("VALIDATION_RETURN_INDEX_INVALID")
    dates = pd.DatetimeIndex(pd.to_datetime(strategy_returns.index)).normalize()
    if dates.has_duplicates or not dates.is_monotonic_increasing:
        raise SelectedValidationError("VALIDATION_RETURN_INDEX_INVALID")
    if dates.max() >= LOCKED_START:
        raise SelectedValidationError("VALIDATION_LOCKED_DATE_FORBIDDEN")
    if dates.min() < VALIDATION_START or dates.max() > VALIDATION_END:
        raise SelectedValidationError("VALIDATION_DATE_OUTSIDE_WINDOW")
    try:
        score = score_realized_returns(
            strategy_returns,
            spy_returns,
            target_years=tuple(range(2011, 2021)),
        )
    except ObjectiveContractError as exc:
        raise SelectedValidationError(f"VALIDATION_SCORE_INVALID:{exc}") from exc
    weekly = pd.DataFrame({"strategy": strategy_returns, "spy": spy_returns})
    weekly["week"] = dates.to_period("W-FRI")
    compounded = weekly.groupby("week", sort=True)[["strategy", "spy"]].agg(
        _compounded_return
    )
    positive_weeks = compounded["strategy"] > 0.0
    beating_weeks = compounded["strategy"] > compounded["spy"]
    union_weeks = positive_weeks | beating_weeks
    annual = {str(year): asdict(row) for year, row in score.annual_returns.items()}
    down_returns = [
        row.strategy_return
        for row in score.annual_returns.values()
        if row.spy_return < 0.0
    ]
    return {
        "annualized_strategy_return": score.annualized_strategy_return,
        "annualized_spy_return": score.annualized_spy_return,
        "annualized_alpha": score.annualized_alpha,
        "week_count": len(compounded),
        "positive_weeks": int(positive_weeks.sum()),
        "weeks_beating_spy": int(beating_weeks.sum()),
        "winning_or_positive_weeks": int(union_weeks.sum()),
        "weekly_positive_rate": float(positive_weeks.mean()),
        "weekly_spy_beat_rate": float(beating_weeks.mean()),
        "weekly_winning_or_positive_rate": float(union_weeks.mean()),
        "positive_years": sum(row.strategy_return > 0.0 for row in score.annual_returns.values()),
        "years_beating_spy": sum(row.active_return > 0.0 for row in score.annual_returns.values()),
        "years_passing_both": sum(row.passed for row in score.annual_returns.values()),
        "total_years": 10,
        "worst_annual_return": min(row.strategy_return for row in score.annual_returns.values()),
        "worst_annual_alpha": min(row.active_return for row in score.annual_returns.values()),
        "average_return_when_spy_falls": (
            float(sum(down_returns) / len(down_returns)) if down_returns else None
        ),
        "annual_returns": annual,
        "validation_start": VALIDATION_START.date().isoformat(),
        "validation_end": VALIDATION_END.date().isoformat(),
        "validation_opened": True,
        "locked_opened": False,
    }


def compose_selected_signals(
    signals: Sequence[pd.Series],
    composition: Mapping[str, Any],
) -> pd.Series:
    """Apply the frozen catalog composition semantics to selected signals."""

    if not signals:
        raise SelectedValidationError("VALIDATION_COMPOSITION_EMPTY")
    index = signals[0].index
    if any(not signal.index.equals(index) for signal in signals):
        raise SelectedValidationError("VALIDATION_COMPONENT_INDEX_MISMATCH")
    values = np.column_stack(
        [signal.fillna(0.0).to_numpy(dtype=float) for signal in signals]
    )
    kind = str(composition.get("kind"))
    if kind == "identity":
        out = values[:, 0]
    elif kind == "and":
        out = np.where(
            np.all(values == 1.0, axis=1),
            1.0,
            np.where(np.all(values == -1.0, axis=1), -1.0, 0.0),
        )
    elif kind == "gate":
        base = values[:, int(composition.get("base_component_index", 0))]
        out = np.where(
            (base != 0.0) & np.all(values == base[:, None], axis=1),
            base,
            0.0,
        )
    elif kind == "override":
        base = values[:, int(composition.get("base_component_index", 0))]
        priority = values[:, int(composition["priority_component_index"])]
        out = np.where(priority != 0.0, priority, base)
    elif kind == "vote":
        positive = np.sum(values == 1.0, axis=1)
        negative = np.sum(values == -1.0, axis=1)
        needed = (
            values.shape[1]
            if composition.get("mode") == "unanimity"
            else values.shape[1] // 2 + 1
        )
        out = np.where(
            positive >= needed,
            1.0,
            np.where(negative >= needed, -1.0, 0.0),
        )
    elif kind == "weighted_score":
        weights = np.asarray(composition["weights"], dtype=float)
        if (
            weights.shape != (values.shape[1],)
            or not np.isfinite(weights).all()
            or float(np.abs(weights).sum()) == 0.0
        ):
            raise SelectedValidationError("VALIDATION_WEIGHT_MISMATCH")
        out = np.sign(values @ weights / np.abs(weights).sum())
    else:
        raise SelectedValidationError(f"VALIDATION_COMPOSITION_UNKNOWN:{kind}")
    result = pd.Series(out, index=index, dtype=float, name="decision")
    return result.mask(result == 0.0)


def write_validation_baselines(
    evaluator: Callable[[str, Mapping[str, Any]], pd.DataFrame],
    default_configurations: Mapping[str, Mapping[str, Any]],
    output_dir: Path,
) -> Mapping[str, Path]:
    """Materialize F001-F050 on the authorized warm-up snapshot."""

    output = Path(output_dir).resolve()
    if output.exists():
        raise SelectedValidationError("VALIDATION_BASELINE_OUTPUT_ALREADY_EXISTS")
    roots = {family: output / f"baseline_{family}" for family in ("price", "market", "macro")}
    artifacts: dict[str, dict[str, Mapping[str, Any]]] = {
        family: {} for family in roots
    }
    for lane_number in range(1, 51):
        lane_id = f"F{lane_number:03d}"
        configuration = default_configurations.get(lane_id)
        if not isinstance(configuration, Mapping):
            raise SelectedValidationError(f"VALIDATION_BASELINE_CONFIG_MISSING:{lane_id}")
        feature = evaluator(lane_id, configuration)
        if not isinstance(feature, pd.DataFrame) or not {
            "date",
            "available_at",
            "value",
        }.issubset(feature.columns):
            raise SelectedValidationError(f"VALIDATION_BASELINE_INVALID:{lane_id}")
        dates = pd.to_datetime(feature["date"], errors="raise").dt.normalize()
        available = pd.to_datetime(
            feature["available_at"], errors="raise"
        ).dt.normalize()
        if (
            feature.empty
            or dates.duplicated().any()
            or not dates.is_monotonic_increasing
            or dates.max() > VALIDATION_END
            or available.max() > VALIDATION_END
        ):
            raise SelectedValidationError(f"VALIDATION_BASELINE_BOUNDARY:{lane_id}")
        family = "price" if lane_number <= 20 else "market" if lane_number <= 31 else "macro"
        root = roots[family]
        (root / "features").mkdir(parents=True, exist_ok=True)
        target = root / "features" / f"{lane_id}.parquet"
        feature.to_parquet(target, index=False)
        artifacts[family][lane_id] = {
            "path": f"features/{lane_id}.parquet",
            "sha256": _sha256_file(target),
        }
    report_names = {
        "price": "feature_smoke_report.json",
        "market": "market_feature_smoke_report.json",
        "macro": "macro_feature_smoke_report.json",
    }
    for family, root in roots.items():
        report = {
            "schema_version": 1,
            "ready": True,
            "validation_start": VALIDATION_START.date().isoformat(),
            "validation_end": VALIDATION_END.date().isoformat(),
            "validation_opened": True,
            "locked_opened": False,
            "artifacts": artifacts[family],
        }
        (root / report_names[family]).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return roots


def _load_manifest(path: Path, *, expected_partition: str) -> Mapping[str, Any]:
    target = path / "snapshot_manifest.json"
    try:
        manifest = json.loads(target.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectedValidationError(f"SNAPSHOT_MANIFEST_INVALID:{expected_partition}") from exc
    if manifest.get("partition") != expected_partition:
        raise SelectedValidationError(f"SNAPSHOT_PARTITION_INVALID:{expected_partition}")
    if manifest.get("locked_opened") is not False:
        raise SelectedValidationError("SNAPSHOT_LOCKED_ALREADY_OPEN")
    if manifest.get("validation_opened") is not False:
        raise SelectedValidationError("SNAPSHOT_VALIDATION_ALREADY_OPEN")
    datasets = manifest.get("datasets")
    if not isinstance(datasets, Mapping) or not datasets:
        raise SelectedValidationError("SNAPSHOT_DATASETS_INVALID")
    return manifest


def _verified_frame(root: Path, dataset_id: str, row: Mapping[str, Any]) -> pd.DataFrame:
    target = root / f"{dataset_id}.parquet"
    if not target.is_file() or _sha256_file(target) != row.get("sha256"):
        raise SelectedValidationError(f"SNAPSHOT_DATASET_HASH_MISMATCH:{dataset_id}")
    frame = pd.read_parquet(target)
    if "date" not in frame or frame.empty:
        raise SelectedValidationError(f"SNAPSHOT_DATASET_EMPTY:{dataset_id}")
    dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise SelectedValidationError(f"SNAPSHOT_DATASET_DATE_INVALID:{dataset_id}")
    result = frame.copy()
    result["date"] = dates
    return result


def build_authorized_validation_snapshot(
    train_dir: Path,
    validation_dir: Path,
    output_dir: Path,
    *,
    authorization: str,
) -> ValidationSnapshotReceipt:
    """Verify and combine train plus validation solely for signal warm-up."""

    if authorization != VALIDATION_ACK:
        raise SelectedValidationError("VALIDATION_AUTHORIZATION_INVALID")
    train_root = Path(train_dir).resolve()
    validation_root = Path(validation_dir).resolve()
    output_root = Path(output_dir).resolve()
    if train_root.name != "train_snapshot_1993_2010":
        raise SelectedValidationError("TRAIN_SNAPSHOT_NAME_INVALID")
    if validation_root.name != "validation_snapshot_2011_2020":
        raise SelectedValidationError("VALIDATION_SNAPSHOT_NAME_INVALID")
    if output_root.name != "authorized_validation_snapshot_1993_2020":
        raise SelectedValidationError("AUTHORIZED_SNAPSHOT_NAME_INVALID")
    if output_root.exists():
        raise SelectedValidationError("AUTHORIZED_SNAPSHOT_ALREADY_EXISTS")

    train_manifest = _load_manifest(train_root, expected_partition="train")
    validation_manifest = _load_manifest(
        validation_root,
        expected_partition="validation",
    )
    if train_manifest.get("contract_sha256") != validation_manifest.get(
        "contract_sha256"
    ):
        raise SelectedValidationError("SNAPSHOT_CONTRACT_MISMATCH")
    train_rows = train_manifest["datasets"]
    validation_rows = validation_manifest["datasets"]
    if set(train_rows) != set(validation_rows):
        raise SelectedValidationError("SNAPSHOT_DATASET_SET_MISMATCH")

    combined_frames: dict[str, pd.DataFrame] = {}
    for dataset_id in sorted(train_rows):
        train = _verified_frame(train_root, dataset_id, train_rows[dataset_id])
        validation = _verified_frame(
            validation_root,
            dataset_id,
            validation_rows[dataset_id],
        )
        train_dates = pd.DatetimeIndex(train["date"])
        validation_dates = pd.DatetimeIndex(validation["date"])
        if train_dates.max() > TRAIN_END:
            raise SelectedValidationError(f"TRAIN_BOUNDARY_VIOLATION:{dataset_id}")
        if validation_dates.min() < VALIDATION_START:
            raise SelectedValidationError(
                f"VALIDATION_START_BOUNDARY_VIOLATION:{dataset_id}"
            )
        if validation_dates.max() >= LOCKED_START:
            raise SelectedValidationError(f"LOCKED_BOUNDARY_VIOLATION:{dataset_id}")
        combined_frames[dataset_id] = pd.concat(
            [train, validation],
            ignore_index=True,
        ).sort_values("date", kind="mergesort", ignore_index=True)

    output_root.mkdir(parents=True)
    output_rows: dict[str, Mapping[str, Any]] = {}
    for dataset_id, frame in combined_frames.items():
        target = output_root / f"{dataset_id}.parquet"
        frame.to_parquet(target, index=False)
        dates = pd.DatetimeIndex(frame["date"])
        output_rows[dataset_id] = {
            **dict(train_rows[dataset_id]),
            "sha256": _sha256_file(target),
            "row_count": len(frame),
            "minimum_date": dates.min().date().isoformat(),
            "maximum_date": dates.max().date().isoformat(),
        }
    manifest = {
        "schema_version": 1,
        "contract_sha256": train_manifest["contract_sha256"],
        "partition": "authorized_validation",
        "mountable_by_first_cycle": False,
        "validation_start": VALIDATION_START.date().isoformat(),
        "validation_end": VALIDATION_END.date().isoformat(),
        "locked_start": LOCKED_START.date().isoformat(),
        "validation_opened": True,
        "locked_opened": False,
        "datasets": output_rows,
    }
    manifest_path = output_root / "snapshot_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ValidationSnapshotReceipt(
        snapshot_dir=output_root,
        manifest_sha256=_sha256_file(manifest_path),
        spy_sha256=str(output_rows["D_SPY"]["sha256"]),
        dataset_count=len(output_rows),
        maximum_date=VALIDATION_END.date().isoformat(),
    )


__all__ = [
    "LOCKED_START",
    "TRAIN_END",
    "VALIDATION_ACK",
    "VALIDATION_END",
    "VALIDATION_START",
    "SelectedValidationError",
    "SelectedStrategy",
    "SelectionManifest",
    "ValidationSnapshotReceipt",
    "build_authorized_validation_snapshot",
    "compose_selected_signals",
    "load_selection_manifest",
    "score_validation_returns",
    "validate_selection_manifest",
    "write_validation_baselines",
]
