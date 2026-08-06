from __future__ import annotations

import pandas as pd
import pytest

from aurora.research.openap_93.event_pipeline import (
    calculate_event_signals,
    dividend_season_value,
    infer_dividend_frequency,
)


@pytest.mark.parametrize(
    ("months", "expected"),
    [
        (["2025-01", "2025-04", "2025-07", "2025-10"], "quarterly"),
        (["2024-01", "2024-07", "2025-01", "2025-07"], "semiannual"),
        (["2023-01", "2024-01", "2025-01"], "annual"),
        (["2025-01", "2025-02", "2025-03", "2025-04"], "monthly"),
        (["2025-04"], "unknown"),
    ],
)
def test_dividend_frequency_is_inferred_only_from_completed_payments(
    months: list[str], expected: str
) -> None:
    assert infer_dividend_frequency(months) == expected


@pytest.mark.parametrize(
    ("months", "completed_month", "expected"),
    [
        (["2025-07", "2025-10", "2026-01", "2026-04"], "2026-06", 1.0),
        (["2025-06", "2025-12", "2026-06"], "2026-06", 0.0),
        (["2025-07", "2026-01"], "2026-06", 1.0),
        (["2025-06"], "2026-05", 1.0),
        (["2026-04"], "2026-06", 1.0),
        (["2026-05"], "2026-06", 0.0),
        (["2026-01", "2026-02", "2026-03", "2026-04"], "2026-06", None),
        ([], "2026-06", None),
    ],
)
def test_dividend_season_uses_openap_frequency_specific_lags(
    months: list[str], completed_month: str, expected: float | None
) -> None:
    assert dividend_season_value(months, completed_month) == expected


def test_event_pipeline_labels_divseason_variant_and_excludes_monthly_payer() -> None:
    dates = pd.to_datetime(
        [
            "2026-01-15",
            "2026-02-15",
            "2026-03-15",
            "2026-04-15",
            "2026-06-30",
        ]
    )
    prices = pd.DataFrame(
        {
            "symbol": ["MONTHLY"] * len(dates),
            "date": dates,
            "dividends": [0.1, 0.1, 0.1, 0.1, 0.0],
        }
    )
    master = pd.DataFrame(
        {"symbol": ["MONTHLY"], "first_clean_price_date": ["2020-01-01"]}
    )

    result = calculate_event_signals(master, prices, formation_at="2026-07-15")
    divseason = result.loc[result["signal"].eq("DivSeason")].iloc[0]

    assert divseason["value"] is None or pd.isna(divseason["value"])
    assert divseason["reason_if_missing"] == "not_applicable:monthly_dividend_payer"
    assert divseason["variant_id"] == "openap_dividend_seasonality_frequency_inferred"
