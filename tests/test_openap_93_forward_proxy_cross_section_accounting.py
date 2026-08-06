from __future__ import annotations

import pandas as pd
import pytest

from aurora.research.openap_93.accounting_pipeline import (
    calculate_delnetfin_from_components,
    resolve_delnetfin_components,
)
from aurora.research.openap_93.market_pipeline import calculate_indretbig_cross_section


def test_indretbig_uses_strict_top_30_percent_and_arithmetic_mean() -> None:
    cross_section = pd.DataFrame(
        {
            "symbol": list("ABCDE"),
            "industry_group": ["FF48-35"] * 5,
            "raw_close": [10.0, 20.0, 30.0, 40.0, 50.0],
            "pit_shares": [10.0] * 5,
            "month_return": [0.01, 0.02, 0.03, 0.04, 0.06],
        }
    )

    result = calculate_indretbig_cross_section(cross_section).set_index("symbol")

    assert result.loc["A", "industry_rank"] == pytest.approx(0.2)
    assert result.loc["C", "industry_rank"] == pytest.approx(0.6)
    assert not bool(result.loc["C", "is_big_firm"])
    assert bool(result.loc["D", "is_big_firm"])
    assert bool(result.loc["E", "is_big_firm"])
    assert result.loc[["A", "B", "C"], "indretbig"].tolist() == pytest.approx(
        [0.05, 0.05, 0.05]
    )
    assert result.loc[["D", "E"], "indretbig"].isna().all()


@pytest.mark.parametrize(
    ("forbidden_column", "replacement"),
    [("raw_close", "adj_close"), ("pit_shares", "current_shares")],
)
def test_indretbig_rejects_non_point_in_time_market_equity_inputs(
    forbidden_column: str,
    replacement: str,
) -> None:
    cross_section = pd.DataFrame(
        {
            "symbol": ["A", "B"],
            "industry_group": ["FF48-35", "FF48-35"],
            "raw_close": [10.0, 20.0],
            "pit_shares": [10.0, 10.0],
            "month_return": [0.01, 0.02],
        }
    ).rename(columns={forbidden_column: replacement})

    with pytest.raises(ValueError, match=forbidden_column):
        calculate_indretbig_cross_section(cross_section)


def _delnetfin_facts(*, omit: str | None = None) -> pd.DataFrame:
    aliases = {
        "ivst": "ShortTermInvestments",
        "ivao": "LongTermInvestments",
        "dltt": "LongTermDebtNoncurrent",
        "dlc": "LongTermDebtCurrent",
        "pstk": "PreferredStockValue",
        "at": "Assets",
    }
    values = {
        pd.Timestamp("2023-12-31"): {
            "ivst": 10.0,
            "ivao": 20.0,
            "dltt": 40.0,
            "dlc": 5.0,
            "pstk": 2.0,
            "at": 100.0,
        },
        pd.Timestamp("2024-12-31"): {
            "ivst": 15.0,
            "ivao": 25.0,
            "dltt": 42.0,
            "dlc": 6.0,
            "pstk": 3.0,
            "at": 120.0,
        },
    }
    rows: list[dict[str, object]] = []
    for period_end, components in values.items():
        for component, value in components.items():
            if component == omit:
                continue
            rows.append(
                {
                    "tag": aliases[component],
                    "value": value,
                    "unit": "USD",
                    "period_end": period_end,
                    "available_at": period_end + pd.Timedelta(days=60),
                    "form": "10-K",
                }
            )
    # Lower-priority alias must not override the preferred tag.
    if omit != "ivao":
        rows.append(
            {
                "tag": "OtherInvestments",
                "value": 999.0,
                "unit": "USD",
                "period_end": pd.Timestamp("2024-12-31"),
                "available_at": pd.Timestamp("2025-02-28"),
                "form": "10-K",
            }
        )
    return pd.DataFrame(rows)


def test_delnetfin_resolves_aliases_and_uses_exact_12_month_average_assets() -> None:
    facts = _delnetfin_facts()
    current = resolve_delnetfin_components(
        facts,
        period_end="2024-12-31",
        as_of="2025-03-31",
    )
    prior = resolve_delnetfin_components(
        facts,
        period_end="2023-12-31",
        as_of="2025-03-31",
    )

    current_by_component = current.set_index("component")
    assert current_by_component.loc["ivao", "resolved_tag"] == "LongTermInvestments"
    # net_fin changes from -17 to -11; average assets = 110.
    assert calculate_delnetfin_from_components(current, prior) == pytest.approx(6.0 / 110.0)


def test_delnetfin_allows_only_preferred_stock_zero_fallback() -> None:
    facts = _delnetfin_facts(omit="pstk")
    current = resolve_delnetfin_components(
        facts,
        period_end="2024-12-31",
        as_of="2025-03-31",
    )
    prior = resolve_delnetfin_components(
        facts,
        period_end="2023-12-31",
        as_of="2025-03-31",
    )

    preferred = current.set_index("component").loc["pstk"]
    assert preferred["value"] == 0.0
    assert preferred["resolved_tag"] == "__zero_fallback__"
    assert preferred["missing_reason"] == ""
    assert calculate_delnetfin_from_components(current, prior) is not None


@pytest.mark.parametrize("missing_component", ["ivst", "ivao", "dltt", "dlc", "at"])
def test_delnetfin_fails_closed_when_required_component_is_missing(
    missing_component: str,
) -> None:
    facts = _delnetfin_facts(omit=missing_component)
    current = resolve_delnetfin_components(
        facts,
        period_end="2024-12-31",
        as_of="2025-03-31",
    )
    prior = resolve_delnetfin_components(
        facts,
        period_end="2023-12-31",
        as_of="2025-03-31",
    )

    missing = current.set_index("component").loc[missing_component]
    assert pd.isna(missing["value"])
    assert missing["missing_reason"] == "required_component_missing"
    assert calculate_delnetfin_from_components(current, prior) is None


def test_delnetfin_rejects_non_12_month_comparison() -> None:
    facts = _delnetfin_facts()
    current = resolve_delnetfin_components(
        facts,
        period_end="2024-12-31",
        as_of="2025-03-31",
    )
    prior = resolve_delnetfin_components(
        facts.assign(
            period_end=lambda frame: frame["period_end"].where(
                frame["period_end"].ne(pd.Timestamp("2023-12-31")),
                pd.Timestamp("2023-11-30"),
            )
        ),
        period_end="2023-11-30",
        as_of="2025-03-31",
    )

    assert calculate_delnetfin_from_components(current, prior) is None
