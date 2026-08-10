"""Physical executability audit for every frozen lane parameter choice."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hashlib
from typing import Any

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.feature_contract import FrozenFeatureContract


ParameterRepair = Callable[[str, str, dict[str, Any]], dict[str, Any]]
LaneEvaluator = Callable[[str, Mapping[str, Any]], pd.DataFrame]


def output_signature(frame: pd.DataFrame) -> str:
    """Hash null locations and finite values independently of transport bytes."""

    values = pd.to_numeric(frame["value"], errors="coerce").to_numpy(dtype="<f8")
    valid = np.isfinite(values)
    canonical = np.nan_to_num(
        values,
        nan=9.87654321e307,
        posinf=8.7654321e307,
        neginf=-8.7654321e307,
    )
    return hashlib.sha256(valid.tobytes() + canonical.tobytes()).hexdigest()


def audit_frozen_parameter_choices(
    contract: FrozenFeatureContract,
    *,
    lane_ids: Sequence[str],
    evaluator: LaneEvaluator,
    expected_years: Sequence[int],
    repair: ParameterRepair | None = None,
) -> dict[str, Any]:
    """Execute one valid witness for every value in every frozen dimension."""

    lanes_by_id = {lane.lane_id: lane for lane in contract.lanes}
    years = tuple(sorted({int(year) for year in expected_years}))
    if not years:
        raise ValueError("PARAMETER_AUDIT_EXPECTED_YEARS_EMPTY")
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    coverage_limited: list[dict[str, Any]] = []
    signatures: dict[tuple[str, str], dict[str, list[Any]]] = {}
    maximum_output_date = pd.Timestamp.min

    for lane_id in lane_ids:
        lane = lanes_by_id[lane_id]
        baseline = {name: choices[0] for name, choices in lane.parameter_space.items()}
        for parameter, choices in lane.parameter_space.items():
            for choice in choices:
                configuration = {**baseline, parameter: choice}
                if repair is not None:
                    configuration = repair(lane_id, parameter, configuration)
                probe_id = f"{lane_id}:{parameter}:{choice!r}"
                try:
                    output = evaluator(lane_id, configuration)
                    output_dates = pd.to_datetime(output["date"], errors="raise")
                    available_at = pd.to_datetime(output["available_at"], errors="raise")
                    observed_at = pd.to_datetime(output["observed_at"], errors="raise")
                    values = pd.to_numeric(output["value"], errors="coerce")
                    valid = values.notna() & output_dates.dt.year.isin(years)
                    covered_years = tuple(sorted(set(output_dates.loc[valid].dt.year)))
                    if not covered_years:
                        raise ValueError("EMPTY_PARAMETER_CHOICE_OUTPUT")
                    missing_years = tuple(sorted(set(years) - set(covered_years)))
                    if output_dates.max() > pd.Timestamp("2010-12-31"):
                        raise ValueError("NON_TRAIN_PARAMETER_CHOICE_OUTPUT")
                    if not available_at.loc[valid].le(output_dates.loc[valid]).all():
                        raise ValueError("AVAILABLE_AFTER_DECISION")
                    if not observed_at.loc[valid].le(available_at.loc[valid]).all():
                        raise ValueError("OBSERVED_AFTER_AVAILABILITY")
                    signature = output_signature(output.loc[output_dates.dt.year.isin(years)])
                    signatures.setdefault((lane_id, parameter), {}).setdefault(
                        signature, []
                    ).append(choice)
                    maximum_output_date = max(maximum_output_date, output_dates.max())
                    records.append(
                        {
                            "probe_id": probe_id,
                            "lane_id": lane_id,
                            "parameter": parameter,
                            "choice": choice,
                            "configuration": configuration,
                            "non_null_expected_year_rows": int(valid.sum()),
                            "covered_years": list(covered_years),
                            "missing_expected_years": list(missing_years),
                            "output_sha256": signature,
                        }
                    )
                    if missing_years:
                        coverage_limited.append(
                            {
                                "probe_id": probe_id,
                                "covered_years": list(covered_years),
                                "missing_expected_years": list(missing_years),
                            }
                        )
                except (KeyError, TypeError, ValueError) as exc:
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
        for lane_id in lane_ids
        for choices in lanes_by_id[lane_id].parameter_space.values()
    )
    return {
        "schema_version": 1,
        "ready": not failures and not inactive_groups and len(records) == expected,
        "feature_contract_sha256": contract.sha256,
        "lane_ids": list(lane_ids),
        "lane_count": len(lane_ids),
        "expected_years": list(years),
        "expected_choice_probe_count": expected,
        "choice_probe_count": len(records),
        "failed_probes": failures,
        "coverage_limited_probes": coverage_limited,
        "inactive_choice_groups": inactive_groups,
        "maximum_output_date": maximum_output_date.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "records": records,
    }


__all__ = ["audit_frozen_parameter_choices", "output_signature"]
