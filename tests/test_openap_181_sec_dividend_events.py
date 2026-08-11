from __future__ import annotations

from pathlib import Path

import pandas as pd

from aurora.research.openap_181.sec_dividend_events import (
    DIVINIT_FORMULA_SHA256,
    DIVOMIT_FORMULA_SHA256,
    DIVSEASON_FORMULA_SHA256,
    calculate_sec_divinit_current,
    calculate_sec_divomit_current,
    calculate_sec_divseason_current,
)


FORMATION_AT = "2026-08-09T23:59:59Z"
RETRIEVED_AT = "2026-08-10T10:00:00Z"
ROOT = Path(__file__).resolve().parents[1]


def _status() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cik": 1,
                "symbol": "AAA",
                "surface": "companyfacts",
                "status": "ok",
            },
            {
                "cik": 1,
                "symbol": "AAA",
                "surface": "submissions",
                "status": "ok",
            },
        ]
    )


def _facts(
    *,
    tag: str = "CommonStockDividendsPerShareCashPaid",
    prior_positive: bool = False,
) -> pd.DataFrame:
    periods = pd.period_range("2024Q2", "2026Q2", freq="Q-DEC")
    rows: list[dict[str, object]] = []
    for index, period in enumerate(periods):
        start = period.start_time
        end = period.end_time.normalize()
        value = 0.0
        if index == len(periods) - 1:
            value = 0.25
        elif prior_positive and index == 3:
            value = 0.10
        filed = end + pd.Timedelta(days=25)
        rows.append(
            {
                "cik": 1,
                "taxonomy": "us-gaap",
                "tag": tag,
                "unit": "USD/shares",
                "value": value,
                "period_start": start.date().isoformat(),
                "period_end": end.date().isoformat(),
                "fy": end.year,
                "fp": "Q" if end.month != 12 else "FY",
                "form": "10-Q" if end.month != 12 else "10-K",
                "filed": filed.date().isoformat(),
                "accession_number": f"0000000001-{end.year % 100:02d}-{index:06d}",
                "available_at": filed.tz_localize("UTC").isoformat(),
            }
        )
    return pd.DataFrame(rows)


def _omission_facts() -> pd.DataFrame:
    facts = _facts().tail(7).reset_index(drop=True)
    facts["value"] = 0.25
    facts.loc[facts.index[-1], "value"] = 0.0
    return facts


def _season_facts() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, month in enumerate(
        pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"])
    ):
        start = month.replace(day=1)
        filed = month + pd.Timedelta(days=20)
        rows.append(
            {
                "cik": 1,
                "taxonomy": "us-gaap",
                "tag": "CommonStockDividendsPerShareCashPaid",
                "unit": "USD/shares",
                "value": 0.25,
                "period_start": start.date().isoformat(),
                "period_end": month.date().isoformat(),
                "fy": month.year,
                "fp": "Q",
                "form": "10-Q" if month.month != 12 else "10-K",
                "filed": filed.date().isoformat(),
                "accession_number": f"0000000001-{month.year % 100:02d}-{index:06d}",
                "available_at": filed.tz_localize("UTC").isoformat(),
            }
        )
    return pd.DataFrame(rows)


def test_sec_divinit_emits_positive_only_for_proven_24m_zero_transition() -> None:
    result = calculate_sec_divinit_current(
        _facts(),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert result["value"] == 1.0
    assert result["current_usable"]
    assert result["fidelity_class"] == "reconstructed"
    assert result["period_end"] == "2026-06-30"
    assert result["observation_count"] == 9
    assert result["formula_sha256"] == DIVINIT_FORMULA_SHA256


def test_sec_divinit_accepts_declared_dividend_fallback() -> None:
    result = calculate_sec_divinit_current(
        _facts(tag="CommonStockDividendsPerShareDeclared"),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert result["value"] == 1.0
    assert result["current_usable"]


def test_sec_divinit_does_not_treat_prior_dividend_as_zero() -> None:
    result = calculate_sec_divinit_current(
        _facts(prior_positive=True),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert pd.isna(result["value"])
    assert not result["current_usable"]
    assert result["reason_if_missing"].startswith("no_complete_zero_to_positive")


def test_sec_divinit_never_extends_past_guaranteed_six_month_window() -> None:
    result = calculate_sec_divinit_current(
        _facts(),
        _status(),
        formation_at="2026-10-01T00:00:00Z",
        retrieved_at="2026-10-01T00:00:00Z",
    ).iloc[0]

    assert pd.isna(result["value"])
    assert not result["current_usable"]


def test_sec_divomit_emits_positive_for_six_regular_quarters_then_zero() -> None:
    result = calculate_sec_divomit_current(
        _omission_facts(),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert result["value"] == 1.0
    assert result["current_usable"]
    assert result["fidelity_class"] == "reconstructed"
    assert result["period_end"] == "2026-06-30"
    assert result["observation_count"] == 7
    assert result["formula_sha256"] == DIVOMIT_FORMULA_SHA256


def test_sec_divomit_rejects_future_period_even_if_filed_before_formation() -> None:
    facts = _omission_facts().iloc[:-1].copy()
    future = _omission_facts().iloc[-1].copy()
    future["period_start"] = "2026-07-01"
    future["period_end"] = "2026-09-30"
    future["filed"] = "2026-08-06"
    future["available_at"] = "2026-08-06T21:18:06Z"
    future["value"] = 0.0
    facts = pd.concat([facts, pd.DataFrame([future])], ignore_index=True)

    result = calculate_sec_divomit_current(
        facts,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert pd.isna(result["value"])
    assert not result["current_usable"]
    assert result["reason_if_missing"].startswith("no_complete_6q_regular")


def test_sec_divomit_fails_closed_on_missing_regular_quarter() -> None:
    facts = _omission_facts().drop(index=2).reset_index(drop=True)
    result = calculate_sec_divomit_current(
        facts,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert pd.isna(result["value"])
    assert not result["current_usable"]
    assert result["reason_if_missing"].startswith("no_complete_6q_regular")


def test_sec_divomit_does_not_extend_delayed_detection_beyond_two_months() -> None:
    result = calculate_sec_divomit_current(
        _omission_facts(),
        _status(),
        formation_at="2026-09-01T00:00:00Z",
        retrieved_at="2026-09-01T00:00:00Z",
    ).iloc[0]

    assert pd.isna(result["value"])
    assert not result["current_usable"]


def test_sec_divseason_emits_positive_from_regular_direct_month_facts() -> None:
    result = calculate_sec_divseason_current(
        _season_facts(),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).iloc[0]

    assert result["value"] == 1.0
    assert result["current_usable"]
    assert result["fidelity_class"] == "reconstructed"
    assert result["observation_count"] == 4
    assert result["formula_sha256"] == DIVSEASON_FORMULA_SHA256


def test_sec_divseason_does_not_emit_zero_for_unpredicted_month() -> None:
    result = calculate_sec_divseason_current(
        _season_facts(),
        _status(),
        formation_at="2026-09-01T00:00:00Z",
        retrieved_at="2026-09-01T00:00:00Z",
    ).iloc[0]

    assert pd.isna(result["value"])
    assert not result["current_usable"]


def test_sec_divinit_is_connected_to_fresh_guarded_sec_batch() -> None:
    source_runner = (
        ROOT / "scripts" / "run_openap_yfinance_sec_current.py"
    ).read_text(encoding="utf-8")
    calc_runner = (
        ROOT / "scripts" / "run_openap_149_sec_companyfacts.py"
    ).read_text(encoding="utf-8")
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-sec-companyfacts.yml"
    ).read_text(encoding="utf-8")

    assert "DIVIDEND_EVENT_COMPANYFACT_TAGS" in source_runner
    assert "calculate_sec_divinit_current" in calc_runner
    assert "calculate_sec_divomit_current" in calc_runner
    assert "calculate_sec_divseason_current" in calc_runner
    assert "tests/test_openap_181_sec_dividend_events.py" in workflow
    assert "require_github_actions_or_explicit_local_permission" in calc_runner
