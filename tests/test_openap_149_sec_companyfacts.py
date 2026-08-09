from __future__ import annotations

from importlib import import_module

import pandas as pd
import pytest


def _module():
    return import_module("aurora.research.openap_181.sec_companyfacts_149")


def _facts() -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(
        tag: str,
        value: float,
        period_end: str,
        available_at: str,
        accession: str,
        *,
        form: str,
        period_start: str = "",
    ) -> None:
        rows.append(
            {
                "cik": 1,
                "entity_name": "Example Corp",
                "taxonomy": "us-gaap",
                "tag": tag,
                "unit": "USD",
                "value": value,
                "period_start": period_start,
                "period_end": period_end,
                "fy": int(period_end[:4]),
                "fp": "FY" if form == "10-K" else "Q2",
                "form": form,
                "filed": available_at[:10],
                "accession_number": accession,
                "frame": "",
                "available_at": available_at,
                "available_at_quality": "sec_acceptance_timestamp",
                "source": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
                "source_mode": "sec_official_api",
            }
        )

    add("Assets", 100.0, "2026-06-30", "2026-07-20T14:00:00Z", "q2", form="10-Q")
    add(
        "CashAndShortTermInvestments",
        25.0,
        "2026-06-30",
        "2026-07-20T14:00:00Z",
        "q2",
        form="10-Q",
    )
    for year, revenue, cogs, capex in (
        (2023, 100.0, 60.0, 10.0),
        (2024, 120.0, 72.0, 24.0),
        (2025, 200.0, 120.0, 60.0),
    ):
        scale = 1_000_000.0
        available = f"{year + 1}-02-15T15:00:00Z"
        accession = f"fy{year}"
        start = f"{year}-01-01"
        end = f"{year}-12-31"
        add("Assets", 100.0 * scale, end, available, accession, form="10-K")
        add(
            "Revenues",
            revenue * scale,
            end,
            available,
            accession,
            form="10-K",
            period_start=start,
        )
        add(
            "CostOfRevenue",
            cogs * scale,
            end,
            available,
            accession,
            form="10-K",
            period_start=start,
        )
        add(
            "PaymentsToAcquirePropertyPlantAndEquipment",
            capex * scale,
            end,
            available,
            accession,
            form="10-K",
            period_start=start,
        )
    return pd.DataFrame(rows)


def _submissions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cik": 1,
                "accession_number": accession,
                "accepted_at": accepted,
                "sic": 3571,
            }
            for accession, accepted in (
                ("q2", "2026-07-20T14:00:00Z"),
                ("fy2023", "2024-02-15T15:00:00Z"),
                ("fy2024", "2025-02-15T15:00:00Z"),
                ("fy2025", "2026-02-15T15:00:00Z"),
            )
        ]
    )


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


def test_companyfacts_batch_calculates_cash_gp_and_investment_causally() -> None:
    values = _module().calculate_companyfacts_149_current(
        _facts(),
        _submissions(),
        _status(),
        formation_at="2026-08-09",
        retrieved_at="2026-08-08T18:44:14Z",
    )

    assert values["signal"].tolist() == ["Cash", "GP", "Investment"]
    indexed = values.set_index("signal")
    assert indexed.loc["Cash", "value"] == 0.25
    assert indexed.loc["GP", "value"] == 0.8
    assert pd.notna(indexed.loc["Investment", "value"])
    assert values["source_id"].eq("sec_edgar").all()
    assert values["security_id"].eq("US-SEC-0000000001-AAA").all()
    assert values["ticker"].eq("AAA").all()
    assert values["fidelity_class"].eq("reconstructed").all()
    assert values["formula_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert pd.to_datetime(values["available_at"]).le(
        pd.to_datetime(values["formation_at"])
    ).all()


def test_companyfacts_batch_ignores_facts_not_available_at_formation() -> None:
    facts = _facts()
    future = facts.iloc[[0]].copy()
    future.loc[:, "value"] = 999.0
    future.loc[:, "available_at"] = "2026-08-10T00:00:00Z"
    future.loc[:, "accession_number"] = "future"

    values = _module().calculate_companyfacts_149_current(
        pd.concat([facts, future], ignore_index=True),
        _submissions(),
        _status(),
        formation_at="2026-08-09",
        retrieved_at="2026-08-08T18:44:14Z",
    )

    assert values.set_index("signal").loc["Cash", "value"] == 0.25


def test_companyfacts_expanded_accounting_calculates_pure_sec_formulas() -> None:
    facts = _facts()
    extra: list[dict[str, object]] = []
    values_by_year = {
        2024: {
            "Liabilities": 40.0,
            "StockholdersEquity": 60.0,
            "CashAndCashEquivalentsAtCarryingValue": 10.0,
            "InventoryNet": 10.0,
            "AccountsReceivableNetCurrent": 20.0,
            "PropertyPlantAndEquipmentNet": 40.0,
            "SellingGeneralAndAdministrativeExpense": 10.0,
            "InterestExpenseNonOperating": 5.0,
        },
        2025: {
            "Liabilities": 40.0,
            "StockholdersEquity": 60.0,
            "CashAndCashEquivalentsAtCarryingValue": 10.0,
            "InventoryNet": 20.0,
            "AccountsReceivableNetCurrent": 20.0,
            "PropertyPlantAndEquipmentNet": 40.0,
            "SellingGeneralAndAdministrativeExpense": 10.0,
            "InterestExpenseNonOperating": 5.0,
        },
    }
    for year, concepts in values_by_year.items():
        template = facts.loc[
            facts["accession_number"].eq(f"fy{year}")
            & facts["tag"].eq("Assets")
        ].iloc[0]
        for tag, value in concepts.items():
            row = template.copy()
            row["tag"] = tag
            row["value"] = value * 1_000_000.0
            if tag in {
                "SellingGeneralAndAdministrativeExpense",
                "InterestExpenseNonOperating",
            }:
                row["period_start"] = f"{year}-01-01"
            extra.append(row.to_dict())

    targets = {
        "BookLeverage",
        "ChAssetTurnover",
        "InvGrowth",
        "OPLeverage",
        "OperProf",
        "tang",
    }
    values = _module().calculate_companyfacts_accounting_current(
        pd.concat([facts, pd.DataFrame(extra)], ignore_index=True),
        _status(),
        formation_at="2026-08-09",
        retrieved_at="2026-08-08T18:44:14Z",
        target_signals=targets,
    )

    assert set(values["signal"]) == targets
    indexed = values.set_index("signal")
    assert indexed.loc["BookLeverage", "value"] == 0.4
    assert indexed.loc["ChAssetTurnover", "value"] == pytest.approx(0.8)
    assert indexed.loc["InvGrowth", "value"] == pytest.approx(1.0)
    assert indexed.loc["OPLeverage", "value"] == pytest.approx(1.3)
    assert indexed.loc["OperProf", "value"] == pytest.approx(65.0 / 60.0)
    assert indexed.loc["tang", "value"] == pytest.approx(0.5664)
    assert values["source_id"].eq("sec_edgar").all()
    assert values["fidelity_class"].eq("unvalidated_proxy").all()
    assert pd.to_datetime(values["period_end"]).le(
        pd.to_datetime(values["available_at"])
    ).all()
    assert pd.to_datetime(values["available_at"]).le(
        pd.to_datetime(values["formation_at"])
    ).all()


def test_sec_submissions_calculate_firm_age_as_explicit_current_proxy() -> None:
    submissions = _submissions()
    future = submissions.iloc[[0]].copy()
    future.loc[:, "accession_number"] = "future"
    future.loc[:, "accepted_at"] = "2026-08-10T00:00:00Z"

    values = _module().calculate_sec_submission_current(
        pd.concat([submissions, future], ignore_index=True),
        _status(),
        formation_at="2026-08-09",
        retrieved_at="2026-08-08T18:44:14Z",
    )

    assert values["signal"].tolist() == ["FirmAge"]
    assert values.iloc[0]["value"] == 31.0
    assert values.iloc[0]["fidelity_class"] == "unvalidated_proxy"
    assert values.iloc[0]["formula_id"] == (
        "openap_firmage_sec_first_filing_months_proxy"
    )
    assert values.iloc[0]["source_id"] == "sec_edgar"
    assert pd.Timestamp(values.iloc[0]["available_at"]) == pd.Timestamp(
        "2024-02-15T15:00:00Z"
    )


def test_companyfacts_calculates_additional_non_93_sec_accounting_signals() -> None:
    facts = _facts()
    extra: list[dict[str, object]] = []
    for year, sga in ((2023, 5.0), (2024, 8.0), (2025, 10.0)):
        template = facts.loc[
            facts["accession_number"].eq(f"fy{year}")
            & facts["tag"].eq("Assets")
        ].iloc[0]
        sga_row = template.copy()
        sga_row["tag"] = "SellingGeneralAndAdministrativeExpense"
        sga_row["value"] = sga * 1_000_000.0
        sga_row["period_start"] = f"{year}-01-01"
        extra.append(sga_row.to_dict())

    latest = facts.loc[
        facts["accession_number"].eq("fy2025") & facts["tag"].eq("Assets")
    ].iloc[0]
    for tag, amount in (
        ("ResearchAndDevelopmentExpense", 5.0),
        ("PaymentsForRepurchaseOfCommonStock", 2.0),
    ):
        row = latest.copy()
        row["tag"] = tag
        row["value"] = amount * 1_000_000.0
        row["period_start"] = "2025-01-01"
        extra.append(row.to_dict())

    values = _module().calculate_companyfacts_accounting_current(
        pd.concat([facts, pd.DataFrame(extra)], ignore_index=True),
        _status(),
        formation_at="2026-08-09",
        retrieved_at="2026-08-08T18:44:14Z",
        target_signals={
            "GrSaleToGrOverhead",
            "OperProfRD",
            "ShareRepurchase",
        },
    )

    indexed = values.set_index("signal")
    assert set(indexed.index) == {
        "GrSaleToGrOverhead",
        "OperProfRD",
        "ShareRepurchase",
    }
    assert indexed.loc["GrSaleToGrOverhead", "value"] == pytest.approx(
        0.2797202797202797
    )
    assert indexed.loc["OperProfRD", "value"] == pytest.approx(0.75)
    assert indexed.loc["ShareRepurchase", "value"] == 1.0
    assert indexed.loc["OperProfRD", "fidelity_class"] == "unvalidated_proxy"
    assert indexed.loc["ShareRepurchase", "fidelity_class"] == "reconstructed"


def test_companyfacts_calculates_deferred_revenue_change_as_explicit_proxy() -> None:
    facts = _facts()
    extra: list[dict[str, object]] = []
    for year, deferred_revenue in ((2024, 20.0), (2025, 30.0)):
        template = facts.loc[
            facts["accession_number"].eq(f"fy{year}")
            & facts["tag"].eq("Assets")
        ].iloc[0]
        for tag, amount in (
            ("ContractWithCustomerLiabilityCurrent", deferred_revenue),
            ("StockholdersEquity", 60.0),
        ):
            row = template.copy()
            row["tag"] = tag
            row["value"] = amount * 1_000_000.0
            extra.append(row.to_dict())

    values = _module().calculate_companyfacts_accounting_current(
        pd.concat([facts, pd.DataFrame(extra)], ignore_index=True),
        _status(),
        formation_at="2026-08-09",
        retrieved_at="2026-08-08T18:44:14Z",
        target_signals={"DelDRC"},
    )

    assert values["signal"].tolist() == ["DelDRC"]
    assert values.iloc[0]["value"] == pytest.approx(0.1)
    assert values.iloc[0]["fidelity_class"] == "unvalidated_proxy"
    assert values.iloc[0]["source_id"] == "sec_edgar"
    assert pd.Timestamp(values.iloc[0]["available_at"]) <= pd.Timestamp(
        values.iloc[0]["formation_at"]
    )
