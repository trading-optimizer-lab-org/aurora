"""Frozen formula and availability contract for the 240-lane SP500 campaign."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    import pandas as pd

from aurora.infra.sp500_megarun.data_contract import FreeDataContract


class FeatureContractError(ValueError):
    """Raised when a formula or availability contract is not scientifically frozen."""


_REGISTERED_OPERATORS = frozenset(
    {
        "adaptive_average",
        "analog_neighbors",
        "ar_forecast",
        "band_state",
        "bar_geometry",
        "calendar_state",
        "change_point",
        "cross_asset_state",
        "cross_section_breadth",
        "cross_section_dispersion",
        "cross_section_leadership",
        "cross_section_momentum",
        "cross_section_spread",
        "curve_state",
        "dynamic_factor",
        "event_density",
        "event_state",
        "extreme_state",
        "factor_state",
        "filtered_volatility",
        "financial_state",
        "forecast_combination",
        "fractal_state",
        "garch_forecast",
        "gap_state",
        "historical_control",
        "hurst_state",
        "liquidity_state",
        "macro_vintage_state",
        "markov_state",
        "model_forecast",
        "momentum",
        "moving_average_cross",
        "moving_average_distance",
        "multihorizon_momentum",
        "nonlinear_path_state",
        "ordinal_state",
        "oscillator_state",
        "path_decomposition",
        "positioning_state",
        "price_level_state",
        "range_breakout",
        "range_state",
        "ratio_state",
        "realized_volatility",
        "recurrence_state",
        "regime_gate",
        "regression_trend",
        "release_state",
        "reversal",
        "seasonal_state",
        "spectral_state",
        "spread_state",
        "state_space_trend",
        "streak_state",
        "stress_state",
        "survey_state",
        "symbolic_rule",
        "tail_state",
        "threshold_regime",
        "trend_curvature",
        "variance_decomposition",
        "volume_state",
        "voting_ensemble",
        "wavelet_state",
        "weather_state",
        "zscore_state",
    }
)

_REGISTERED_AVAILABLE_AT_POLICIES = frozenset(
    {
        "same_session",
        "next_session",
        "friday_after_tuesday",
        "h10_following_week_release_plus_session",
        "two_calendar_days",
        "next_month_third_session",
        "quarter_end_next_session",
        "quarter_end_plus_60_days_next_session",
        "second_month_tenth_session",
        "thirteen_month_revision_guard",
        "frequency_aware",
        "max_input_available_at",
    }
)

_DATASET_AVAILABLE_AT_POLICIES: Mapping[str, str] = {
    "D_SPY": "next_session",
    "D_VIX": "next_session",
    "D_VXO": "next_session",
    "D_CFTC": "friday_after_tuesday",
    "D_RATES": "next_session",
    "D_FIN_COND": "next_session",
    "D_MACRO_PIT": "frequency_aware",
    "D_PHILLY_RT": "next_session",
    "D_MARGIN": "second_month_tenth_session",
    "D_EPU": "max_input_available_at",
    "D_FRENCH_FACTORS": "next_session",
    "D_FRENCH_INDUSTRIES": "next_session",
    "D_GOYAL": "thirteen_month_revision_guard",
    "D_SHILLER": "thirteen_month_revision_guard",
    "D_WTI": "next_month_third_session",
    "D_GOLD": "next_month_third_session",
    "D_FX": "h10_following_week_release_plus_session",
    "D_CALENDAR": "same_session",
    "D_CBOE_VOL": "next_session",
    "D_CBOE_PCR": "friday_after_tuesday",
    "D_CFTC_LEGACY": "friday_after_tuesday",
    "D_FED_H15_H10": "frequency_aware",
    "D_FED_H3_H6_H8_G19_CP": "frequency_aware",
    "D_SPF": "quarter_end_next_session",
    "D_SLOOS": "quarter_end_plus_60_days_next_session",
    "D_Z1": "thirteen_month_revision_guard",
    "D_FINRA_MARGIN": "second_month_tenth_session",
    "D_FRENCH_US": "frequency_aware",
    "D_FRENCH_GLOBAL": "next_session",
    "D_WORLD_BANK_COMMODITIES": "next_month_third_session",
    "D_TREASURY_AUCTIONS": "next_session",
    "D_TREASURY_FISCAL": "next_session",
    "D_TIC": "second_month_tenth_session",
    "D_FOMC_PUBLIC": "same_session",
    "D_NOAA_NY": "two_calendar_days",
    "D_DERIVED_CAUSAL": "max_input_available_at",
}


def registered_operator_names() -> frozenset[str]:
    """Return the closed operator vocabulary understood by the campaign."""

    return _REGISTERED_OPERATORS


def registered_available_at_policies() -> frozenset[str]:
    """Return the closed set of row-level availability projections."""

    return _REGISTERED_AVAILABLE_AT_POLICIES


def dataset_available_at_policies() -> Mapping[str, str]:
    """Return the frozen availability policy for every contracted dataset."""

    return dict(_DATASET_AVAILABLE_AT_POLICIES)


@dataclass(frozen=True)
class FeatureLaneSpec:
    lane_id: str
    operator: str
    formula: str
    inputs: tuple[str, ...]
    required_datasets: tuple[str, ...]
    parameter_space: Mapping[str, tuple[Any, ...]]
    minimum_history: int
    available_at_mode: str
    position_values: tuple[int, int]
    allowed_crosses: tuple[str, ...]
    implementation_status: str
    canonical_sha256: str


@dataclass(frozen=True)
class CrossRule:
    rule_id: str
    left_lanes: tuple[str, ...]
    right_lanes: tuple[str, ...]
    compositions: tuple[str, ...]
    max_features: int
    economic_rationale: str


@dataclass(frozen=True)
class FrozenFeatureContract:
    path: Path
    sha256: str
    search_end: date
    validation_opened: bool
    locked_opened: bool
    lanes: tuple[FeatureLaneSpec, ...]
    cross_rules: tuple[CrossRule, ...]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _parse_parameter_space(
    raw: object,
    *,
    lane_id: str,
) -> Mapping[str, tuple[Any, ...]]:
    if not isinstance(raw, Mapping) or not raw:
        raise FeatureContractError(f"MISSING_PARAMETER_SPACE:{lane_id}")
    parsed: dict[str, tuple[Any, ...]] = {}
    for name, values in raw.items():
        if not isinstance(values, list) or not values:
            raise FeatureContractError(f"EMPTY_PARAMETER_DIMENSION:{lane_id}:{name}")
        parsed[str(name)] = tuple(values)
    return parsed


def _expand_lane_selectors(raw: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise FeatureContractError(f"MISSING_CROSS_SELECTOR:{label}")
    expanded: list[str] = []
    for selector in raw:
        text = str(selector)
        if "-" not in text:
            expanded.append(text)
            continue
        start_text, end_text = text.split("-", maxsplit=1)
        if not (start_text.startswith("F") and end_text.startswith("F")):
            raise FeatureContractError(f"INVALID_CROSS_SELECTOR:{label}:{text}")
        start = int(start_text[1:])
        end = int(end_text[1:])
        if start > end:
            raise FeatureContractError(f"INVALID_CROSS_SELECTOR:{label}:{text}")
        expanded.extend(f"F{index:03d}" for index in range(start, end + 1))
    return tuple(dict.fromkeys(expanded))


def _parse_cross_rules(payload: Mapping[str, Any]) -> tuple[CrossRule, ...]:
    raw_rules = payload.get("cross_rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise FeatureContractError("MISSING_CROSS_RULES")
    valid_lanes = {f"F{index:03d}" for index in range(1, 241)}
    valid_compositions = {"and", "or", "gate", "override", "vote", "weighted_score"}
    parsed: list[CrossRule] = []
    seen_ids: set[str] = set()
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, Mapping):
            raise FeatureContractError("INVALID_CROSS_RULE")
        rule_id = str(raw_rule.get("rule_id", ""))
        if not rule_id or rule_id in seen_ids:
            raise FeatureContractError(f"INVALID_CROSS_RULE_ID:{rule_id}")
        seen_ids.add(rule_id)
        left = _expand_lane_selectors(raw_rule.get("left"), label=f"{rule_id}.left")
        right = _expand_lane_selectors(raw_rule.get("right"), label=f"{rule_id}.right")
        unknown = sorted((set(left) | set(right)) - valid_lanes)
        if unknown:
            raise FeatureContractError(f"UNKNOWN_CROSS_LANE:{rule_id}:{','.join(unknown)}")
        compositions = tuple(str(value) for value in raw_rule.get("compositions", ()))
        if not compositions or not set(compositions) <= valid_compositions:
            raise FeatureContractError(f"INVALID_CROSS_COMPOSITION:{rule_id}")
        max_features = int(raw_rule.get("max_features", 0))
        if not 2 <= max_features <= 5:
            raise FeatureContractError(f"INVALID_CROSS_MAX_FEATURES:{rule_id}")
        rationale = str(raw_rule.get("economic_rationale", "")).strip()
        if not rationale:
            raise FeatureContractError(f"MISSING_CROSS_RATIONALE:{rule_id}")
        parsed.append(
            CrossRule(
                rule_id=rule_id,
                left_lanes=left,
                right_lanes=right,
                compositions=compositions,
                max_features=max_features,
                economic_rationale=rationale,
            )
        )
    return tuple(parsed)


def load_and_validate_feature_contract(
    path: Path,
    data_contract: FreeDataContract,
) -> FrozenFeatureContract:
    """Load all 240 formula blueprints and reject any unfrozen scientific choice."""

    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FeatureContractError(f"FEATURE_CONTRACT_NOT_FOUND:{path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeatureContractError(f"INVALID_FEATURE_CONTRACT_JSON:{path}") from exc
    if not isinstance(payload, Mapping):
        raise FeatureContractError("FEATURE_CONTRACT_ROOT_NOT_OBJECT")

    boundaries = payload.get("boundaries")
    if not isinstance(boundaries, Mapping):
        raise FeatureContractError("MISSING_FEATURE_BOUNDARIES")
    if bool(boundaries.get("validation_opened")):
        raise FeatureContractError("VALIDATION_MUST_REMAIN_CLOSED")
    if bool(boundaries.get("locked_opened")):
        raise FeatureContractError("LOCKED_MUST_REMAIN_CLOSED")
    search_end = date.fromisoformat(str(boundaries.get("search_end")))
    if search_end != data_contract.boundaries.search_end:
        raise FeatureContractError("SEARCH_END_MISMATCH")

    operator_spaces = payload.get("operator_spaces")
    if not isinstance(operator_spaces, Mapping):
        raise FeatureContractError("MISSING_OPERATOR_SPACES")
    raw_lanes = payload.get("lanes")
    if not isinstance(raw_lanes, list):
        raise FeatureContractError("MISSING_FEATURE_LANES")
    expected_ids = [f"F{index:03d}" for index in range(1, 241)]
    if [str(row.get("lane_id")) for row in raw_lanes if isinstance(row, Mapping)] != expected_ids:
        raise FeatureContractError("FEATURE_LANES_NOT_CONTIGUOUS_F001_F240")
    implemented_lanes = set(
        _expand_lane_selectors(payload.get("implemented_lanes"), label="implemented_lanes")
    )

    lanes: list[FeatureLaneSpec] = []
    canonical_seen: dict[str, str] = {}
    for index, row in enumerate(raw_lanes):
        if not isinstance(row, Mapping):
            raise FeatureContractError(f"INVALID_FEATURE_LANE:{index}")
        lane_id = expected_ids[index]
        operator = str(row.get("operator", "")).strip()
        if operator not in _REGISTERED_OPERATORS:
            raise FeatureContractError(f"UNKNOWN_OPERATOR:{lane_id}:{operator}")
        formula = str(row.get("formula", "")).strip()
        if not formula or any(token in formula.casefold() for token in ("todo", "placeholder", "tbd")):
            raise FeatureContractError(f"UNFROZEN_FORMULA:{lane_id}")

        contracted_datasets = tuple(data_contract.lanes[index].required_datasets)
        required_datasets = tuple(row.get("required_datasets", contracted_datasets))
        if set(required_datasets) != set(contracted_datasets):
            raise FeatureContractError(f"DATASET_CONTRACT_MISMATCH:{lane_id}")
        inputs = tuple(str(value) for value in row.get("inputs", required_datasets))
        if not inputs:
            raise FeatureContractError(f"MISSING_INPUTS:{lane_id}")
        raw_space = row.get(
            "parameter_space",
            operator_spaces.get(operator, operator_spaces.get("*")),
        )
        parameter_space = _parse_parameter_space(raw_space, lane_id=lane_id)
        minimum_history = int(row.get("minimum_history", 504))
        if minimum_history < 1:
            raise FeatureContractError(f"INVALID_MINIMUM_HISTORY:{lane_id}")
        available_at_mode = str(
            row.get("available_at_mode", payload.get("available_at_mode", ""))
        )
        if available_at_mode != "max_input_available_at":
            raise FeatureContractError(f"INVALID_AVAILABLE_AT_MODE:{lane_id}")
        position_values = tuple(row.get("position_values", payload.get("position_values", ())))
        if position_values != (-1, 1):
            raise FeatureContractError(f"INVALID_POSITION_VALUES:{lane_id}")
        allowed_crosses = tuple(str(value) for value in row.get("allowed_crosses", ()))
        if len(allowed_crosses) > 4:
            raise FeatureContractError(f"TOO_MANY_ALLOWED_CROSSES:{lane_id}")
        implementation_status = (
            "executable" if lane_id in implemented_lanes else "blueprint_only"
        )

        canonical_payload = {
            "operator": operator,
            "formula": formula,
            "inputs": inputs,
            "required_datasets": required_datasets,
            "parameter_space": parameter_space,
            "minimum_history": minimum_history,
            "available_at_mode": available_at_mode,
            "position_values": position_values,
            "allowed_crosses": allowed_crosses,
            "implementation_status": implementation_status,
        }
        canonical_sha256 = hashlib.sha256(_canonical_json(canonical_payload)).hexdigest()
        if canonical_sha256 in canonical_seen:
            raise FeatureContractError(
                "DUPLICATE_CANONICAL_FORMULA:"
                f"{canonical_seen[canonical_sha256]}:{lane_id}"
            )
        canonical_seen[canonical_sha256] = lane_id
        lanes.append(
            FeatureLaneSpec(
                lane_id=lane_id,
                operator=operator,
                formula=formula,
                inputs=inputs,
                required_datasets=required_datasets,
                parameter_space=parameter_space,
                minimum_history=minimum_history,
                available_at_mode=available_at_mode,
                position_values=(-1, 1),
                allowed_crosses=allowed_crosses,
                implementation_status=implementation_status,
                canonical_sha256=canonical_sha256,
            )
        )

    cross_rules = _parse_cross_rules(payload)
    return FrozenFeatureContract(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        search_end=search_end,
        validation_opened=False,
        locked_opened=False,
        lanes=tuple(lanes),
        cross_rules=cross_rules,
    )


def is_cross_allowed(
    contract: FrozenFeatureContract,
    left_lane: str,
    right_lane: str,
) -> bool:
    """Return whether the frozen economic matrix admits a two-family cross."""

    if left_lane == right_lane:
        return False
    return any(
        (
            left_lane in rule.left_lanes
            and right_lane in rule.right_lanes
        )
        or (
            right_lane in rule.left_lanes
            and left_lane in rule.right_lanes
        )
        for rule in contract.cross_rules
    )


def _session_on_or_after(
    targets: pd.Series,
    sessions: pd.DatetimeIndex,
    *,
    strictly_after: bool,
) -> pd.Series:
    import pandas as pd

    normalized_sessions = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().unique().sort_values()
    target_values = pd.to_datetime(targets, errors="coerce").dt.normalize()
    positions = normalized_sessions.searchsorted(
        target_values.to_numpy(),
        side="right" if strictly_after else "left",
    )
    output = pd.Series(pd.NaT, index=targets.index, dtype="datetime64[ns]")
    valid = positions < len(normalized_sessions)
    if valid.any():
        output.loc[valid] = normalized_sessions.take(positions[valid]).to_numpy()
    return output


def apply_available_at_policy(
    frame: pd.DataFrame,
    *,
    policy: str,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Add observed_at and available_at without filling from a future observation."""

    import pandas as pd

    if "date" not in frame:
        raise FeatureContractError("DATE_COLUMN_REQUIRED_FOR_AVAILABILITY")
    result = frame.copy()
    result["observed_at"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    if result["observed_at"].isna().any():
        raise FeatureContractError("INVALID_OBSERVED_AT")
    if policy == "same_session":
        available = _session_on_or_after(result["observed_at"], sessions, strictly_after=False)
    elif policy == "next_session":
        available = _session_on_or_after(result["observed_at"], sessions, strictly_after=True)
    elif policy == "two_calendar_days":
        targets = result["observed_at"] + pd.Timedelta(days=2)
        available = _session_on_or_after(targets, sessions, strictly_after=False)
    elif policy == "friday_after_tuesday":
        targets = result["observed_at"] + pd.Timedelta(days=3)
        available = _session_on_or_after(targets, sessions, strictly_after=False)
    elif policy == "h10_following_week_release_plus_session":
        days_to_following_monday = 7 - result["observed_at"].dt.weekday
        release_targets = result["observed_at"] + pd.to_timedelta(
            days_to_following_monday, unit="D"
        )
        release_sessions = _session_on_or_after(
            release_targets, sessions, strictly_after=False
        )
        available = _session_on_or_after(
            release_sessions, sessions, strictly_after=True
        )
    elif policy == "next_month_third_session":
        available = _nth_session_of_offset_month(
            result["observed_at"], sessions, month_offset=1, session_number=3
        )
    elif policy == "second_month_tenth_session":
        available = _nth_session_of_offset_month(
            result["observed_at"], sessions, month_offset=2, session_number=10
        )
    elif policy == "thirteen_month_revision_guard":
        targets = result["observed_at"] + pd.offsets.MonthBegin(13) + pd.Timedelta(days=14)
        available = _session_on_or_after(targets, sessions, strictly_after=False)
    elif policy == "quarter_end_next_session":
        quarter_end = result["observed_at"] + pd.offsets.QuarterEnd(0)
        available = _session_on_or_after(quarter_end, sessions, strictly_after=True)
    elif policy == "quarter_end_plus_60_days_next_session":
        quarter_end = result["observed_at"] + pd.offsets.QuarterEnd(0)
        targets = quarter_end + pd.Timedelta(days=60)
        available = _session_on_or_after(targets, sessions, strictly_after=False)
    else:
        raise FeatureContractError(f"UNKNOWN_AVAILABLE_AT_POLICY:{policy}")
    if available.isna().any():
        raise FeatureContractError("AVAILABLE_AT_OUTSIDE_SESSION_CALENDAR")
    if available.lt(result["observed_at"]).any():
        raise FeatureContractError("AVAILABLE_AT_PRECEDES_OBSERVATION")
    result["available_at"] = available
    return result


def _nth_session_of_offset_month(
    observed_at: pd.Series,
    sessions: pd.DatetimeIndex,
    *,
    month_offset: int,
    session_number: int,
) -> pd.Series:
    import pandas as pd

    normalized_sessions = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().unique().sort_values()
    output = pd.Series(pd.NaT, index=observed_at.index, dtype="datetime64[ns]")
    for index, observed in observed_at.items():
        target_month = pd.Timestamp(observed) + pd.offsets.MonthBegin(month_offset)
        month_sessions = normalized_sessions[
            (normalized_sessions.year == target_month.year)
            & (normalized_sessions.month == target_month.month)
        ]
        if len(month_sessions) >= session_number:
            output.loc[index] = month_sessions[session_number - 1]
    return output


def maximum_input_available_at(
    frame: pd.DataFrame,
    columns: Sequence[str],
) -> pd.Series:
    """A feature becomes usable only when its slowest required input is usable."""

    import pandas as pd

    if not columns:
        raise FeatureContractError("NO_AVAILABLE_AT_INPUTS")
    missing = [column for column in columns if column not in frame]
    if missing:
        raise FeatureContractError(f"MISSING_AVAILABLE_AT_COLUMNS:{','.join(missing)}")
    values = frame[list(columns)].apply(pd.to_datetime, errors="coerce")
    if values.isna().any().any():
        raise FeatureContractError("NULL_INPUT_AVAILABLE_AT")
    return values.max(axis=1)
