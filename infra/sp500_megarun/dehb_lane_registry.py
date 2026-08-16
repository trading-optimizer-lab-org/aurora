"""Lazy train-only routing from F001-F240 to the audited feature engines."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd


LaneEvaluator = Callable[[str, Mapping[str, Any]], pd.DataFrame]
ContextBuilder = Callable[["TrainLaneEvaluator"], LaneEvaluator]

_TRAIN_PARTITION = "train_snapshot_1993_2010"
_TRAIN_END = pd.Timestamp("2010-12-31")
_AUTHORIZED_VALIDATION_PARTITION = "authorized_validation_snapshot_1993_2020"
_VALIDATION_END = pd.Timestamp("2020-12-31")
_ALL_LANES = tuple(f"F{number:03d}" for number in range(1, 241))
_ENGINE_MODULES = (
    "feature_input_normalizers",
    "feature_engine",
    "feature_smoke",
    "market_feature_engine",
    "market_feature_smoke",
    "macro_feature_engine",
    "macro_feature_smoke",
    "model_feature_engine",
    "model_feature_smoke",
    "advanced_feature_engine",
    "advanced_feature_smoke",
    "microstructure_feature_engine",
    "microstructure_feature_smoke",
    "positioning_feature_engine",
    "positioning_feature_smoke",
    "tail_macro_feature_engine",
    "tail_macro_feature_smoke",
    "fundamental_feature_engine",
    "fundamental_feature_smoke",
    "cross_section_feature_engine",
    "cross_section_feature_smoke",
    "technical_feature_engine",
    "technical_feature_smoke",
    "nonlinear_feature_engine",
    "nonlinear_feature_smoke",
    "predictive_feature_engine",
    "predictive_feature_smoke",
    "characteristic_feature_engine",
    "characteristic_feature_smoke",
    "global_factor_feature_engine",
    "global_factor_feature_smoke",
    "cross_asset_feature_engine",
    "cross_asset_feature_smoke",
    "rates_credit_feature_engine",
    "rates_credit_feature_smoke",
    "realtime_survey_feature_engine",
    "realtime_survey_feature_smoke",
    "financial_accounts_feature_engine",
    "financial_accounts_feature_smoke",
    "volatility_positioning_feature_engine",
    "volatility_positioning_feature_smoke",
    "policy_treasury_feature_engine",
    "policy_treasury_feature_smoke",
    "public_context_feature_engine",
    "public_context_feature_smoke",
)


class LaneRegistryError(ValueError):
    """Raised when a lane cannot be bound to the exact train snapshot."""


@dataclass(frozen=True)
class FamilyAdapter:
    start: int
    end: int
    builder: ContextBuilder

    def contains(self, lane_number: int) -> bool:
        return self.start <= lane_number <= self.end


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise LaneRegistryError(f"TRAIN_FILE_READ_FAILED:{path.name}") from exc
    return digest.hexdigest()


def _lane_number(lane_id: str) -> int:
    if len(lane_id) != 4 or not lane_id.startswith("F") or not lane_id[1:].isdigit():
        raise LaneRegistryError(f"UNKNOWN_LANE:{lane_id}")
    number = int(lane_id[1:])
    if lane_id != f"F{number:03d}" or not 1 <= number <= 240:
        raise LaneRegistryError(f"UNKNOWN_LANE:{lane_id}")
    return number


def supported_lane_ids() -> tuple[str, ...]:
    return _ALL_LANES


# Runtime dependencies are defined by the family builder, not by the
# individual lane declaration.  A family is initialized once and that
# initializer loads the complete panel it may use for every lane in the
# family.  Keeping this map here makes scheduling and runtime verification
# use the same source of truth as the evaluator.
_RUNTIME_DATASETS_BY_FAMILY: tuple[tuple[int, int, tuple[str, ...]], ...] = (
    (1, 20, ("D_SPY",)),
    (21, 31, ("D_CFTC", "D_RATES", "D_SPY", "D_VIX", "D_VXO")),
    (
        32,
        50,
        (
            "D_CALENDAR",
            "D_CFTC_LEGACY",
            "D_FOMC_PUBLIC",
            "D_FIN_COND",
            "D_FINRA_MARGIN",
            "D_FRENCH_FACTORS",
            "D_FRENCH_INDUSTRIES",
            "D_FX",
            "D_GOLD",
            "D_GOYAL",
            "D_MACRO_PIT",
            "D_PHILLY_RT",
            "D_RATES",
            "D_SHILLER",
            "D_SPY",
            "D_WTI",
            "D_Z1",
        ),
    ),
    (51, 60, ("D_CALENDAR", "D_SPY")),
    (61, 80, ("D_CALENDAR", "D_SPY")),
    (
        81,
        90,
        (
            "D_CALENDAR",
            "D_CFTC",
            "D_CFTC_LEGACY",
            "D_FINRA_MARGIN",
            "D_FRENCH_INDUSTRIES",
            "D_MARGIN",
            "D_SPY",
            "D_VIX",
            "D_VXO",
            "D_Z1",
        ),
    ),
    (
        91,
        100,
        (
            "D_CALENDAR",
            "D_CFTC",
            "D_FOMC_PUBLIC",
            "D_MACRO_PIT",
            "D_RATES",
            "D_SPY",
            "D_VIX",
            "D_VXO",
        ),
    ),
    (
        101,
        110,
        (
            "D_CALENDAR",
            "D_CBOE_VOL",
            "D_CFTC_LEGACY",
            "D_EPU",
            "D_FIN_COND",
            "D_GOLD",
            "D_GOYAL",
            "D_MACRO_PIT",
            "D_PHILLY_RT",
            "D_RATES",
            "D_SHILLER",
            "D_WTI",
            "D_Z1",
        ),
    ),
    (
        111,
        120,
        (
            "D_CBOE_VOL",
            "D_FIN_COND",
            "D_FRENCH_FACTORS",
            "D_FRENCH_INDUSTRIES",
            "D_FX",
            "D_GOYAL",
            "D_MACRO_PIT",
            "D_RATES",
            "D_SHILLER",
            "D_SPY",
        ),
    ),
    (121, 130, ("D_SPY",)),
    (131, 140, ("D_CALENDAR", "D_SPY")),
    (141, 150, ("D_CALENDAR", "D_SPY", "D_VIX", "D_VXO")),
    (151, 160, ("D_CALENDAR", "D_FRENCH_US", "D_SPY")),
    (161, 170, ("D_CALENDAR", "D_FRENCH_GLOBAL", "D_FRENCH_US", "D_SPY")),
    (
        171,
        180,
        ("D_CALENDAR", "D_FED_H15_H10", "D_SPY", "D_WORLD_BANK_COMMODITIES"),
    ),
    (
        181,
        190,
        (
            "D_CALENDAR",
            "D_CBOE_VOL",
            "D_FED_H15_H10",
            "D_FED_H3_H6_H8_G19_CP",
            "D_SPF",
            "D_SPY",
        ),
    ),
    (
        191,
        200,
        ("D_CALENDAR", "D_MACRO_PIT", "D_PHILLY_RT", "D_SLOOS", "D_SPF", "D_SPY"),
    ),
    (201, 210, ("D_CALENDAR", "D_SPY", "D_TIC", "D_Z1")),
    (
        211,
        220,
        ("D_CALENDAR", "D_CBOE_PCR", "D_CBOE_VOL", "D_CFTC_LEGACY", "D_SPY"),
    ),
    (
        221,
        230,
        (
            "D_CALENDAR",
            "D_FED_H15_H10",
            "D_FED_H3_H6_H8_G19_CP",
            "D_FOMC_PUBLIC",
            "D_SPY",
            "D_TIC",
            "D_TREASURY_AUCTIONS",
            "D_TREASURY_FISCAL",
        ),
    ),
    (
        231,
        240,
        (
            "D_CALENDAR",
            "D_FOMC_PUBLIC",
            "D_NOAA_NY",
            "D_PHILLY_RT",
            "D_SPY",
            "D_TIC",
            "D_TREASURY_AUCTIONS",
        ),
    ),
)


def runtime_dataset_ids_for_lane(lane_id: str) -> tuple[str, ...]:
    """Return every dataset loaded by the evaluator family for ``lane_id``."""

    number = _lane_number(lane_id)
    for start, end, dataset_ids in _RUNTIME_DATASETS_BY_FAMILY:
        if start <= number <= end:
            return dataset_ids
    raise LaneRegistryError(f"UNKNOWN_LANE:{lane_id}")


def default_lane_configurations(feature_contract: Any) -> dict[str, dict[str, Any]]:
    """Freeze the first audited choice of every F001-F240 parameter space."""

    rows: dict[str, dict[str, Any]] = {}
    for lane in feature_contract.lanes:
        configuration: dict[str, Any] = {}
        for name, choices in lane.parameter_space.items():
            if not choices:
                raise LaneRegistryError(
                    f"EMPTY_PARAMETER_CHOICES:{lane.lane_id}:{name}"
                )
            configuration[str(name)] = choices[0]
        rows[str(lane.lane_id)] = configuration
    if tuple(sorted(rows)) != _ALL_LANES:
        raise LaneRegistryError("DEFAULT_CONFIGURATIONS_LANE_MISMATCH")
    return rows


def _module(name: str) -> Any:
    return importlib.import_module(f"aurora.infra.sp500_megarun.{name}")


class TrainLaneEvaluator:
    """Load only one lane family at a time and cache its normalized train inputs."""

    def __init__(
        self,
        train_snapshot: Path,
        *,
        expected_manifest_sha256: str,
        expected_spy_sha256: str,
        default_configurations: Mapping[str, Mapping[str, Any]],
        baseline_feature_dirs: Mapping[str, Path] | None = None,
        adapters: Sequence[FamilyAdapter] | None = None,
        maximum_date: str | pd.Timestamp | None = None,
        _snapshot_name: str = _TRAIN_PARTITION,
        _manifest_partition: str = "train",
        _data_end: pd.Timestamp = _TRAIN_END,
        _validation_opened: bool = False,
        _mountable_by_first_cycle: bool = True,
        _engine_data_end_override: pd.Timestamp | None = None,
    ) -> None:
        self.snapshot = Path(train_snapshot).resolve()
        if self.snapshot.name != _snapshot_name:
            raise LaneRegistryError("TRAIN_SNAPSHOT_PARTITION_REQUIRED")
        manifest_path = self.snapshot / "snapshot_manifest.json"
        if _sha256_file(manifest_path) != expected_manifest_sha256:
            raise LaneRegistryError("TRAIN_MANIFEST_SHA256_MISMATCH")
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LaneRegistryError("TRAIN_MANIFEST_INVALID") from exc
        if (
            manifest.get("partition") != _manifest_partition
            or manifest.get("validation_opened") is not _validation_opened
            or manifest.get("locked_opened") is not False
            or manifest.get("mountable_by_first_cycle")
            is not _mountable_by_first_cycle
        ):
            raise LaneRegistryError("TRAIN_SNAPSHOT_BOUNDARY_OPEN")
        datasets = manifest.get("datasets")
        if not isinstance(datasets, Mapping):
            raise LaneRegistryError("TRAIN_DATASET_MANIFEST_MISSING")
        spy_row = datasets.get("D_SPY")
        if not isinstance(spy_row, Mapping) or spy_row.get("sha256") != expected_spy_sha256:
            raise LaneRegistryError("TRAIN_SPY_MANIFEST_SHA256_MISMATCH")
        self._datasets = datasets
        self._data_end = pd.Timestamp(_data_end).normalize()
        self._validation_opened = _validation_opened
        self._engine_data_end_override = _engine_data_end_override
        self._maximum_date = (
            pd.Timestamp(maximum_date).normalize()
            if maximum_date is not None
            else None
        )
        if self._maximum_date is not None and self._maximum_date > self._data_end:
            raise LaneRegistryError("PREFIX_DATE_AFTER_TRAIN_END")
        self._default_configurations = {
            str(lane): dict(configuration)
            for lane, configuration in default_configurations.items()
        }
        missing_defaults = sorted(set(_ALL_LANES) - set(self._default_configurations))
        if missing_defaults:
            raise LaneRegistryError(
                f"DEFAULT_CONFIGURATIONS_MISSING:{','.join(missing_defaults)}"
            )
        self._baseline_feature_dirs = {
            str(key): Path(value).resolve()
            for key, value in (baseline_feature_dirs or {}).items()
        }
        self._baseline_reports: dict[str, Mapping[str, Any]] = {}
        self._frames: dict[str, pd.DataFrame] = {}
        self._contexts: dict[tuple[int, int], LaneEvaluator] = {}
        self._adapters = tuple(adapters or _default_adapters())
        covered = {
            number
            for adapter in self._adapters
            for number in range(adapter.start, adapter.end + 1)
        }
        if covered != set(range(1, 241)):
            raise LaneRegistryError("LANE_ADAPTER_COVERAGE_MISMATCH")

    def _read(self, dataset_id: str) -> pd.DataFrame:
        cached = self._frames.get(dataset_id)
        if cached is not None:
            return cached
        target = self.snapshot / f"{dataset_id}.parquet"
        row = self._datasets.get(dataset_id)
        if not isinstance(row, Mapping) or not target.is_file():
            raise LaneRegistryError(f"TRAIN_DATASET_MISSING:{dataset_id}")
        if _sha256_file(target) != row.get("sha256"):
            raise LaneRegistryError(f"TRAIN_DATASET_SHA256_MISMATCH:{dataset_id}")
        frame = pd.read_parquet(target)
        if "date" not in frame or frame.empty:
            raise LaneRegistryError(f"EMPTY_TRAIN_DATASET:{dataset_id}")
        dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
        if dates.isna().any() or dates.gt(self._data_end).any():
            raise LaneRegistryError(f"NON_TRAIN_DATASET_ROW:{dataset_id}")
        if self._maximum_date is not None:
            frame = frame.loc[dates.le(self._maximum_date)].copy()
            if frame.empty:
                raise LaneRegistryError(f"EMPTY_TRAIN_DATASET_PREFIX:{dataset_id}")
        self._frames[dataset_id] = frame
        return frame

    def _read_many(self, dataset_ids: Sequence[str]) -> dict[str, pd.DataFrame]:
        return {dataset_id: self._read(dataset_id) for dataset_id in dataset_ids}

    def _sessions(self, dataset_id: str = "D_SPY") -> pd.DatetimeIndex:
        dates = pd.to_datetime(self._read(dataset_id)["date"], errors="raise")
        sessions = pd.DatetimeIndex(dates).normalize().unique().sort_values()
        return sessions[sessions <= self._data_end]

    def _default(self, lane_id: str) -> Mapping[str, Any]:
        return self._default_configurations[lane_id]

    def _baseline_features(self, lane_ids: Sequence[str]) -> dict[str, pd.DataFrame]:
        roots = self._baseline_feature_dirs
        if set(roots) != {"price", "market", "macro"}:
            raise LaneRegistryError("BASELINE_FEATURE_DIRS_REQUIRED")
        result: dict[str, pd.DataFrame] = {}
        report_names = {
            "price": "feature_smoke_report.json",
            "market": "market_feature_smoke_report.json",
            "macro": "macro_feature_smoke_report.json",
        }
        for lane_id in lane_ids:
            number = _lane_number(lane_id)
            family = "price" if number <= 20 else "market" if number <= 31 else "macro"
            report = self._baseline_reports.get(family)
            if report is None:
                report_path = roots[family] / report_names[family]
                try:
                    value = json.loads(report_path.read_text("utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise LaneRegistryError(
                        f"BASELINE_FEATURE_REPORT_INVALID:{family}"
                    ) from exc
                if not isinstance(value, Mapping):
                    raise LaneRegistryError(
                        f"BASELINE_FEATURE_REPORT_INVALID:{family}"
                    )
                if (
                    value.get("ready") is not True
                    or value.get("validation_opened") is not self._validation_opened
                    or value.get("locked_opened") is not False
                    or not isinstance(value.get("artifacts"), Mapping)
                ):
                    raise LaneRegistryError(
                        f"BASELINE_FEATURE_REPORT_NOT_READY:{family}"
                    )
                report = value
                self._baseline_reports[family] = report
            target = roots[family] / "features" / f"{lane_id}.parquet"
            if not target.is_file():
                raise LaneRegistryError(f"BASELINE_FEATURE_MISSING:{lane_id}")
            artifact = report["artifacts"].get(lane_id)
            if (
                not isinstance(artifact, Mapping)
                or artifact.get("path") != f"features/{lane_id}.parquet"
                or artifact.get("sha256") != _sha256_file(target)
            ):
                raise LaneRegistryError(f"BASELINE_FEATURE_SHA256_MISMATCH:{lane_id}")
            feature = pd.read_parquet(target)
            if self._maximum_date is not None:
                dates = pd.to_datetime(feature["date"], errors="raise").dt.normalize()
                feature = feature.loc[dates.le(self._maximum_date)].copy()
                if feature.empty:
                    raise LaneRegistryError(
                        f"EMPTY_BASELINE_FEATURE_PREFIX:{lane_id}"
                    )
            result[lane_id] = feature
        return result

    @contextmanager
    def _engine_boundary(self):
        boundary = self._engine_data_end_override
        if boundary is None:
            yield
            return
        modules = [_module(name) for name in _ENGINE_MODULES]
        if any(not hasattr(module, "_TRAIN_END") for module in modules):
            raise LaneRegistryError("ENGINE_BOUNDARY_HOOK_MISSING")
        original = [module._TRAIN_END for module in modules]
        try:
            for module in modules:
                module._TRAIN_END = boundary
            yield
        finally:
            for module, value in zip(modules, original, strict=True):
                module._TRAIN_END = value

    def __call__(self, lane_id: str, configuration: Mapping[str, Any]) -> pd.DataFrame:
        number = _lane_number(lane_id)
        adapter = next(
            (item for item in self._adapters if item.contains(number)),
            None,
        )
        if adapter is None:
            raise LaneRegistryError(f"UNKNOWN_LANE:{lane_id}")
        with self._engine_boundary():
            key = (adapter.start, adapter.end)
            evaluator = self._contexts.get(key)
            if evaluator is None:
                evaluator = adapter.builder(self)
                self._contexts[key] = evaluator
            return evaluator(lane_id, configuration)


class AuthorizedValidationLaneEvaluator(TrainLaneEvaluator):
    """Mount the explicitly authorized 1993-2020 warm-up snapshot."""

    def __init__(
        self,
        validation_snapshot: Path,
        *,
        expected_manifest_sha256: str,
        expected_spy_sha256: str,
        default_configurations: Mapping[str, Mapping[str, Any]],
        authorization: str,
        baseline_feature_dirs: Mapping[str, Path] | None = None,
        adapters: Sequence[FamilyAdapter] | None = None,
    ) -> None:
        from aurora.infra.sp500_megarun.selected_validation import VALIDATION_ACK

        if authorization != VALIDATION_ACK:
            raise LaneRegistryError("VALIDATION_AUTHORIZATION_INVALID")
        super().__init__(
            validation_snapshot,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_spy_sha256=expected_spy_sha256,
            default_configurations=default_configurations,
            baseline_feature_dirs=baseline_feature_dirs,
            adapters=adapters,
            _snapshot_name=_AUTHORIZED_VALIDATION_PARTITION,
            _manifest_partition="authorized_validation",
            _data_end=_VALIDATION_END,
            _validation_opened=True,
            _mountable_by_first_cycle=False,
            _engine_data_end_override=_VALIDATION_END,
        )


def _price(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("feature_smoke")
    raw = owner._read("D_SPY")
    sessions = owner._sessions()
    available = smoke.apply_available_at_policy(
        raw.iloc[:-1].copy(), policy="next_session", sessions=sessions
    )
    return lambda lane, config: smoke.evaluate_price_lane(lane, available, config)


def _market(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("market_feature_smoke")
    raw = owner._read_many(("D_SPY", "D_VIX", "D_VXO", "D_CFTC", "D_RATES"))
    sessions = owner._sessions()
    panels = {
        "spy": smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions),
        "cboe": smoke.normalize_cboe_vol_panel(raw["D_VIX"], raw["D_VXO"], sessions=sessions),
        "cftc": smoke.normalize_cftc_sp500_panel(raw["D_CFTC"], sessions=sessions),
        "rates": smoke.normalize_treasury_curve_panel(raw["D_RATES"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_market_lane(lane, panels, config)


def _macro(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("macro_feature_smoke")
    ids = (
        "D_RATES", "D_FIN_COND", "D_PHILLY_RT", "D_MACRO_PIT",
        "D_FOMC_PUBLIC", "D_CALENDAR", "D_GOYAL", "D_SHILLER", "D_SPY",
        "D_FX", "D_GOLD", "D_WTI", "D_FRENCH_FACTORS",
        "D_FRENCH_INDUSTRIES", "D_Z1", "D_FINRA_MARGIN", "D_CFTC_LEGACY",
    )
    raw = owner._read_many(ids)
    sessions = owner._sessions("D_CALENDAR")
    factors, industries = smoke.normalize_french_us_panels(
        raw["D_FRENCH_FACTORS"], raw["D_FRENCH_INDUSTRIES"], sessions=sessions
    )
    panels = {
        "credit": smoke.normalize_credit_spread_panel(raw["D_RATES"], sessions=sessions),
        "rates": smoke.normalize_treasury_curve_panel(raw["D_RATES"], sessions=sessions),
        "financial": smoke.normalize_financial_conditions_panel(raw["D_FIN_COND"], sessions=sessions),
        "realtime": smoke.normalize_philadelphia_realtime_growth_panel(raw["D_PHILLY_RT"], sessions=sessions),
        "macro": smoke.normalize_macro_release_panel(raw["D_MACRO_PIT"], sessions=sessions),
        "fomc": smoke.normalize_fomc_event_panel(raw["D_FOMC_PUBLIC"], sessions=sessions),
        "calendar": smoke.normalize_calendar_state_panel(sessions=sessions),
        "valuation": smoke.normalize_lagged_valuation_panel(raw["D_GOYAL"], raw["D_SHILLER"], sessions=sessions),
        "market": smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions),
        "fx": smoke.normalize_fx_cross_asset_panel(raw["D_FX"], sessions=sessions),
        "commodities": smoke.normalize_world_bank_cross_asset_panel(raw["D_GOLD"], raw["D_WTI"], sessions=sessions),
        "factors": factors,
        "industries": industries,
        "balance": smoke.normalize_revised_z1_equity_panel(raw["D_Z1"], sessions=sessions),
        "margin": smoke.normalize_finra_margin_panel(raw["D_FINRA_MARGIN"], sessions=sessions),
        "positioning": smoke.normalize_cftc_sp500_panel(raw["D_CFTC_LEGACY"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_macro_lane(lane, panels, config)


def _model(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("model_feature_smoke")
    sessions = owner._sessions("D_CALENDAR")
    market = smoke.normalize_spy_decision_panel(owner._read("D_SPY"), sessions=sessions)
    features = owner._baseline_features(tuple(f"F{i:03d}" for i in range(1, 51)))
    features["F051"] = smoke.evaluate_model_lane(
        "F051", market, features, owner._default("F051")
    )
    return lambda lane, config: smoke.evaluate_model_lane(lane, market, features, config)


def _spy_family(owner: TrainLaneEvaluator, module_name: str, function_name: str) -> LaneEvaluator:
    smoke = _module(module_name)
    sessions = owner._sessions("D_CALENDAR")
    spy = smoke.normalize_spy_decision_panel(owner._read("D_SPY"), sessions=sessions)
    function = getattr(smoke, function_name)
    return lambda lane, config: function(lane, spy, config)


def _advanced(owner: TrainLaneEvaluator) -> LaneEvaluator:
    return _spy_family(owner, "advanced_feature_smoke", "evaluate_advanced_lane")


def _microstructure(owner: TrainLaneEvaluator) -> LaneEvaluator:
    return _spy_family(owner, "microstructure_feature_smoke", "evaluate_microstructure_lane")


def _positioning(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("positioning_feature_smoke")
    raw = owner._read_many(smoke._REQUIRED_DATASETS)
    sessions = owner._sessions("D_CALENDAR")
    panels = {
        "spy": smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions),
        "balance": smoke.normalize_revised_z1_equity_panel(raw["D_Z1"], sessions=sessions),
        "finra_margin": smoke.normalize_finra_margin_panel(raw["D_FINRA_MARGIN"], sessions=sessions),
        "margin": smoke.normalize_finra_margin_panel(raw["D_MARGIN"], sessions=sessions),
        "legacy_cftc": smoke.normalize_cftc_sp500_panel(raw["D_CFTC_LEGACY"], sessions=sessions),
        "cftc": smoke.normalize_cftc_sp500_panel(raw["D_CFTC"], sessions=sessions),
        "vol": smoke.normalize_cboe_vol_panel(raw["D_VIX"], raw["D_VXO"], sessions=sessions),
        "industries": smoke.normalize_french_industry_panel(raw["D_FRENCH_INDUSTRIES"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_positioning_lane(lane, panels, config)


def _tail_macro(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("tail_macro_feature_smoke")
    raw = owner._read_many(smoke._REQUIRED_DATASETS)
    sessions = owner._sessions("D_CALENDAR")
    panels = {
        "spy": smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions),
        "vol": smoke.normalize_cboe_vol_panel(raw["D_VIX"], raw["D_VXO"], sessions=sessions),
        "cftc": smoke.normalize_cftc_sp500_panel(raw["D_CFTC"], sessions=sessions),
        "rates": smoke.normalize_treasury_curve_panel(raw["D_RATES"], sessions=sessions),
        "policy": smoke.normalize_policy_rate_panel(raw["D_RATES"], sessions=sessions),
        "calendar": smoke.normalize_calendar_state_panel(sessions=sessions),
        "liquidity": smoke.normalize_monetary_liquidity_panel(raw["D_MACRO_PIT"], sessions=sessions),
        "credit_money": smoke.normalize_credit_money_panel(raw["D_MACRO_PIT"], sessions=sessions),
        "macro": smoke.normalize_macro_release_panel(raw["D_MACRO_PIT"], sessions=sessions),
        "fomc": smoke.normalize_fomc_decision_panel(raw["D_FOMC_PUBLIC"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_tail_macro_lane(lane, panels, config)


def _fundamental(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("fundamental_feature_smoke")
    raw = owner._read_many(smoke._REQUIRED_DATASETS)
    sessions = owner._sessions("D_CALENDAR")
    panels = {
        "valuation": smoke.normalize_lagged_valuation_panel(raw["D_GOYAL"], raw["D_SHILLER"], sessions=sessions),
        "market_issuance": smoke.normalize_lagged_goyal_issuance_panel(raw["D_GOYAL"], sessions=sessions),
        "calendar": smoke.normalize_calendar_state_panel(sessions=sessions),
        "issuance": smoke.normalize_z1_corporate_issuance_panel(raw["D_Z1"], sessions=sessions),
        "credit_money": smoke.normalize_credit_money_panel(raw["D_MACRO_PIT"], sessions=sessions),
        "financial": smoke.normalize_financial_conditions_panel(raw["D_FIN_COND"], sessions=sessions),
        "credit": smoke.normalize_credit_spread_panel(raw["D_RATES"], sessions=sessions),
        "uncertainty": smoke.normalize_uncertainty_panel(raw["D_EPU"], sessions=sessions),
        "cycle": smoke.normalize_philadelphia_realtime_cycle_panel(raw["D_PHILLY_RT"], sessions=sessions),
        "rates": smoke.normalize_treasury_curve_panel(raw["D_RATES"], sessions=sessions),
        "macro": smoke.normalize_macro_release_panel(raw["D_MACRO_PIT"], sessions=sessions),
        "balance": smoke.normalize_revised_z1_equity_panel(raw["D_Z1"], sessions=sessions),
        "cftc": smoke.normalize_cftc_sp500_panel(raw["D_CFTC_LEGACY"], sessions=sessions),
        "vol": smoke.normalize_cboe_vol_bundle_panel(raw["D_CBOE_VOL"], sessions=sessions),
        "commodities": smoke.normalize_world_bank_cross_asset_panel(raw["D_GOLD"], raw["D_WTI"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_fundamental_lane(lane, panels, config)


def _cross_section(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("cross_section_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    sessions = owner._sessions()
    curve = smoke.normalize_treasury_curve_panel(raw["D_RATES"], sessions=sessions)
    panels = {
        "spy": smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions),
        "industries": smoke.normalize_french_industry_panel(raw["D_FRENCH_INDUSTRIES"], sessions=sessions),
        "factors": smoke.normalize_french_factor_panel(raw["D_FRENCH_FACTORS"], sessions=sessions),
        "rates": smoke._merge_rates(
            curve,
            smoke.normalize_credit_spread_panel(raw["D_RATES"], sessions=sessions),
            smoke.normalize_policy_rate_panel(raw["D_RATES"], sessions=sessions),
        ),
        "fx": smoke.normalize_fx_cross_asset_panel(raw["D_FX"], sessions=sessions),
        "valuation": smoke.normalize_lagged_valuation_panel(raw["D_GOYAL"], raw["D_SHILLER"], sessions=sessions),
        "financial": smoke.normalize_financial_conditions_panel(raw["D_FIN_COND"], sessions=sessions),
        "macro": smoke.normalize_macro_release_panel(raw["D_MACRO_PIT"], sessions=sessions),
        "vol": smoke.normalize_cboe_vol_bundle_panel(raw["D_CBOE_VOL"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_cross_section_lane(lane, panels, config)


def _technical(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("technical_feature_smoke")
    sessions = owner._sessions()
    spy = smoke.normalize_spy_decision_panel(owner._read("D_SPY"), sessions=sessions)
    return lambda lane, config: smoke.evaluate_technical_lane(lane, spy, config)


def _nonlinear(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("nonlinear_feature_smoke")
    owner._read("D_CALENDAR")
    sessions = owner._sessions()
    panels = {
        "spy": smoke.normalize_spy_decision_panel(owner._read("D_SPY"), sessions=sessions),
        "calendar": smoke.normalize_calendar_state_panel(sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_nonlinear_lane(lane, panels, config)


def _predictive(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("predictive_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    sessions = owner._sessions()
    panels = {
        "spy": smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions),
        "cboe": smoke.normalize_cboe_vol_panel(raw["D_VIX"], raw["D_VXO"], sessions=sessions),
    }
    features = owner._baseline_features(tuple(smoke._APPROVED_FEATURE_ROOTS))
    return lambda lane, config: smoke.evaluate_predictive_lane(lane, panels, features, config)


def _characteristic(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("characteristic_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    sessions = owner._sessions()
    market = smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = smoke.normalize_french_characteristic_panels(raw["D_FRENCH_US"], sessions=sessions)
    return lambda lane, config: smoke.evaluate_characteristic_lane(lane, market, panels, config)


def _global_factor(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("global_factor_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    sessions = owner._sessions()
    market = smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = {
        "industries": smoke.normalize_french_industry_panel(raw["D_FRENCH_US"], sessions=sessions),
        "us_factors": smoke.normalize_french_factor_panel(raw["D_FRENCH_US"], sessions=sessions),
    }
    panels.update(smoke.normalize_french_global_factor_panels(raw["D_FRENCH_GLOBAL"], sessions=sessions))
    return lambda lane, config: smoke.evaluate_global_factor_lane(lane, market, panels, config)


def _cross_asset(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("cross_asset_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    sessions = owner._sessions()
    market = smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    fed = raw["D_FED_H15_H10"]
    panels = {
        "fx": smoke.normalize_fx_cross_asset_panel(fed, sessions=sessions),
        "rates": smoke._merge_rate_panels(
            smoke.normalize_treasury_curve_panel(fed, sessions=sessions),
            smoke.normalize_usd_funding_panel(fed, sessions=sessions),
        ),
        "commodities": smoke.normalize_world_bank_commodity_panel(raw["D_WORLD_BANK_COMMODITIES"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_cross_asset_lane(lane, market, panels, config)


def _rates_credit(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("rates_credit_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    sessions = owner._sessions()
    market = smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    fed, macro = raw["D_FED_H15_H10"], raw["D_FED_H3_H6_H8_G19_CP"]
    panels = {
        "rates": smoke.normalize_treasury_curve_panel(fed, sessions=sessions),
        "credit": smoke.normalize_credit_spread_panel(fed, sessions=sessions),
        "spf_real_rate": smoke.normalize_spf_real_rate_panel(raw["D_SPF"], sessions=sessions),
        "cp": smoke.normalize_commercial_paper_panel(macro, sessions=sessions),
        "bank": smoke.normalize_bank_credit_panel(macro, sessions=sessions),
        "money": smoke.normalize_money_reserves_panel(macro, sessions=sessions),
        "consumer": smoke.normalize_consumer_credit_panel(macro, sessions=sessions),
        "vol": smoke.normalize_cboe_vol_bundle_panel(raw["D_CBOE_VOL"], sessions=sessions),
    }
    smoke._assert_no_fed_sentinel(panels)
    return lambda lane, config: smoke.evaluate_rates_credit_lane(lane, market, panels, config)


def _realtime(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("realtime_survey_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    sessions = owner._sessions()
    market = smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = {
        "realtime": smoke.normalize_realtime_macro_vintage_panel(raw["D_PHILLY_RT"], sessions=sessions),
        "macro_release": smoke.normalize_macro_release_panel(raw["D_MACRO_PIT"], sessions=sessions),
        "cycle": smoke.normalize_philadelphia_realtime_cycle_panel(raw["D_PHILLY_RT"], sessions=sessions),
        "spf_central": smoke.normalize_spf_central_panel(raw["D_SPF"], sessions=sessions),
        "spf_disagreement": smoke.normalize_spf_disagreement_panel(raw["D_SPF"], sessions=sessions),
        "spf_error": smoke.normalize_spf_output_error_panel(raw["D_SPF"], raw["D_MACRO_PIT"], sessions=sessions),
        "sloos": smoke.normalize_sloos_credit_panel(raw["D_SLOOS"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_realtime_survey_lane(lane, market, panels, config)


def _financial_accounts(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("financial_accounts_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    sessions = owner._sessions()
    market = smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = {
        "financial_accounts": smoke.normalize_revised_z1_financial_accounts_panel(raw["D_Z1"], sessions=sessions),
        "tic": smoke.normalize_tic_foreign_flow_panel(raw["D_TIC"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_financial_accounts_lane(lane, market, panels, config)


def _volatility_positioning(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("volatility_positioning_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    smoke._verify_pcr_fallback(raw["D_CBOE_PCR"])
    sessions = owner._sessions()
    market = smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = {
        "vol": smoke.normalize_cboe_vol_bundle_panel(raw["D_CBOE_VOL"], sessions=sessions),
        "fallback": smoke.normalize_cftc_cross_market_fallback_panel(raw["D_CBOE_PCR"], sessions=sessions),
        "cftc": smoke.normalize_cftc_sp500_panel(raw["D_CFTC_LEGACY"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_volatility_positioning_lane(lane, market, panels, config)


def _policy_treasury(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("policy_treasury_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    smoke._reject_unfrozen_fomc_derivatives(raw["D_FOMC_PUBLIC"])
    sessions = owner._sessions()
    market = smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    publications = smoke.normalize_fomc_publication_panels(raw["D_FOMC_PUBLIC"], sessions=sessions)
    panels = {
        "decisions": smoke.normalize_fomc_decision_panel(raw["D_FOMC_PUBLIC"], sessions=sessions),
        "policy_rate": smoke.normalize_policy_rate_panel(raw["D_FED_H15_H10"], sessions=sessions),
        "statements": publications["statements"],
        "minutes": publications["minutes"],
        "auctions": smoke.normalize_treasury_auction_results_panel(raw["D_TREASURY_AUCTIONS"], sessions=sessions),
        "debt": smoke.normalize_federal_debt_panel(raw["D_TREASURY_FISCAL"], sessions=sessions),
        "tic": smoke.normalize_tic_foreign_flow_panel(raw["D_TIC"], sessions=sessions),
        "monetary": smoke.normalize_monetary_liquidity_panel(raw["D_FED_H3_H6_H8_G19_CP"], sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_policy_treasury_lane(lane, market, panels, config)


def _public_context(owner: TrainLaneEvaluator) -> LaneEvaluator:
    smoke = _module("public_context_feature_smoke")
    raw = owner._read_many(smoke._DATASETS)
    smoke._reject_unfrozen_weather_fields(raw["D_NOAA_NY"])
    sessions = owner._sessions()
    market = smoke.normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = {
        "philly": smoke.normalize_philadelphia_publication_panel(raw["D_PHILLY_RT"], sessions=sessions),
        "announcements": smoke.normalize_treasury_auction_announcement_panel(raw["D_TREASURY_AUCTIONS"], sessions=sessions),
        "fomc_documents": smoke.normalize_fomc_document_mix_panel(raw["D_FOMC_PUBLIC"], sessions=sessions),
        "tic": smoke.normalize_tic_foreign_flow_panel(raw["D_TIC"], sessions=sessions),
        "weather": smoke.normalize_noaa_ny_weather_panel(raw["D_NOAA_NY"], sessions=sessions),
        "calendar": smoke.normalize_calendar_state_panel(sessions=sessions),
    }
    return lambda lane, config: smoke.evaluate_public_context_lane(lane, market, panels, config)


def _default_adapters() -> tuple[FamilyAdapter, ...]:
    builders = (
        (1, 20, _price), (21, 31, _market), (32, 50, _macro),
        (51, 60, _model), (61, 70, _advanced), (71, 80, _microstructure),
        (81, 90, _positioning), (91, 100, _tail_macro),
        (101, 110, _fundamental), (111, 120, _cross_section),
        (121, 130, _technical), (131, 140, _nonlinear),
        (141, 150, _predictive), (151, 160, _characteristic),
        (161, 170, _global_factor), (171, 180, _cross_asset),
        (181, 190, _rates_credit), (191, 200, _realtime),
        (201, 210, _financial_accounts), (211, 220, _volatility_positioning),
        (221, 230, _policy_treasury), (231, 240, _public_context),
    )
    return tuple(FamilyAdapter(start, end, builder) for start, end, builder in builders)


__all__ = [
    "FamilyAdapter",
    "AuthorizedValidationLaneEvaluator",
    "LaneEvaluator",
    "LaneRegistryError",
    "TrainLaneEvaluator",
    "default_lane_configurations",
    "supported_lane_ids",
]
