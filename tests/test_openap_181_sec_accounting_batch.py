from __future__ import annotations

import runpy
import sys
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest

from aurora.core.execution_policy import LocalRunBlocked

def _module():
    return import_module("aurora.research.openap_181.sec_accounting_batch")


def _identity(*ciks: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "security_id": [f"FIGI-{cik}" for cik in ciks],
            "cik": list(ciks),
            "valid_from": pd.Timestamp("2000-01-01"),
            "valid_to": pd.NaT,
            "is_primary": True,
            "security_type": "common_stock",
            "mapping_source": "audited_fixture",
        }
    )


def _fsd_tables(
    submissions: list[dict[str, object]],
    facts: list[dict[str, object]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sub = pd.DataFrame(submissions)
    tags = sorted({str(record["tag"]) for record in facts})
    tag = pd.DataFrame(
        {
            "tag": tags,
            "version": "us-gaap/2024",
            "custom": 0,
            "abstract": 0,
            "datatype": "monetary",
        }
    )
    num = pd.DataFrame(
        [
            {
                "adsh": record["adsh"],
                "tag": record["tag"],
                "version": "us-gaap/2024",
                "coreg": "",
                "ddate": record["ddate"],
                "qtrs": record["qtrs"],
                "uom": "USD",
                "value": record["value"],
            }
            for record in facts
        ]
    )
    pre = pd.DataFrame(
        [
            {
                "adsh": record["adsh"],
                "report": 1,
                "line": index + 1,
                "stmt": record["stmt"],
                "inpth": 0,
                "rfile": "H",
                "tag": record["tag"],
                "version": "us-gaap/2024",
                "plabel": record["tag"],
                "negating": 0,
            }
            for index, record in enumerate(facts)
        ]
    )
    return sub, tag, num, pre


def _submission(
    adsh: str,
    cik: int,
    *,
    form: str,
    period: int,
    filed: int,
    accepted: int,
    sic: int,
) -> dict[str, object]:
    return {
        "adsh": adsh,
        "cik": cik,
        "name": f"Issuer {cik}",
        "sic": sic,
        "form": form,
        "period": period,
        "filed": filed,
        "accepted": accepted,
        "fy": int(str(period)[:4]),
        "fp": "FY" if form.startswith("10-K") else "Q1",
    }


def _fact(
    adsh: str,
    tag: str,
    value: float,
    *,
    ddate: int,
    qtrs: int,
    stmt: str,
) -> dict[str, object]:
    return {
        "adsh": adsh,
        "tag": tag,
        "value": value,
        "ddate": ddate,
        "qtrs": qtrs,
        "stmt": stmt,
    }


def test_cash_uses_as_filed_components_and_never_backfills_an_amendment():
    module = _module()
    submissions = [
        _submission(
            "orig",
            1,
            form="10-Q",
            period=20240331,
            filed=20240501,
            accepted=20240501120000,
            sic=3571,
        ),
        _submission(
            "amend",
            1,
            form="10-Q/A",
            period=20240331,
            filed=20240615,
            accepted=20240615120000,
            sic=3571,
        ),
    ]
    facts = []
    for adsh, cash in (("orig", 40.0), ("amend", 50.0)):
        facts.extend(
            [
                _fact(adsh, "Assets", 200.0, ddate=20240331, qtrs=0, stmt="BS"),
                _fact(
                    adsh,
                    "CashAndCashEquivalentsAtCarryingValue",
                    cash,
                    ddate=20240331,
                    qtrs=0,
                    stmt="BS",
                ),
                _fact(
                    adsh,
                    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                    999.0,
                    ddate=20240331,
                    qtrs=0,
                    stmt="BS",
                ),
                _fact(
                    adsh,
                    "ShortTermInvestments",
                    10.0,
                    ddate=20240331,
                    qtrs=0,
                    stmt="BS",
                ),
            ]
        )
    normalized = module.normalize_sec_fsd_tables(*_fsd_tables(submissions, facts))

    result = module.calculate_sec_accounting_batch(
        normalized,
        _identity(1),
        [pd.Timestamp("2024-05-31"), pd.Timestamp("2024-06-30")],
    )
    cash = result.loc[result["signal"].eq("Cash")].sort_values("formation_at")

    assert cash["value"].tolist() == pytest.approx([0.25, 0.30])
    assert cash["accession_number"].tolist() == ["orig", "amend"]
    assert cash["available_at"].tolist() == [
        pd.Timestamp("2024-05-01 12:00:00"),
        pd.Timestamp("2024-06-15 12:00:00"),
    ]
    assert cash["formula_id"].eq("openap_cash_cheq_atq_sec_fsd").all()


def test_gp_matches_openap_formula_and_excludes_financial_or_invalid_assets():
    module = _module()
    submissions = [
        _submission(
            f"annual-{cik}",
            cik,
            form="10-K",
            period=20241231,
            filed=20250301,
            accepted=20250301120000,
            sic=sic,
        )
        for cik, sic in ((1, 3571), (2, 6021), (3, 3571))
    ]
    facts = []
    for cik, assets in ((1, 200.0), (2, 200.0), (3, 0.0)):
        adsh = f"annual-{cik}"
        facts.extend(
            [
                _fact(adsh, "Revenues", 300.0, ddate=20241231, qtrs=4, stmt="IS"),
                _fact(adsh, "CostOfRevenue", 180.0, ddate=20241231, qtrs=4, stmt="IS"),
                _fact(adsh, "Assets", assets, ddate=20241231, qtrs=0, stmt="BS"),
            ]
        )
    normalized = module.normalize_sec_fsd_tables(*_fsd_tables(submissions, facts))

    result = module.calculate_sec_accounting_batch(
        normalized,
        _identity(1, 2, 3),
        [pd.Timestamp("2025-03-31")],
    )
    gp = result.loc[result["signal"].eq("GP")].set_index("cik")

    assert gp.loc[1, "value"] == pytest.approx(0.6)
    assert pd.isna(gp.loc[2, "value"])
    assert gp.loc[2, "reason_if_missing"] == "financial_sic_excluded"
    assert pd.isna(gp.loc[3, "value"])
    assert gp.loc[3, "reason_if_missing"] == "nonpositive_assets"


def test_investment_uses_36_month_window_minimum_24_and_revenue_floor():
    module = _module()
    submissions = [
        _submission(
            "fy2021",
            1,
            form="10-K",
            period=20211231,
            filed=20220301,
            accepted=20220301120000,
            sic=3571,
        ),
        _submission(
            "fy2022",
            1,
            form="10-K",
            period=20221231,
            filed=20230301,
            accepted=20230301120000,
            sic=3571,
        ),
        _submission(
            "fy2023-low-revenue",
            1,
            form="10-K",
            period=20231231,
            filed=20240301,
            accepted=20240301120000,
            sic=3571,
        ),
    ]
    facts = []
    for adsh, ddate, capex, revenue in (
        ("fy2021", 20211231, 10_000_000.0, 100_000_000.0),
        ("fy2022", 20221231, 40_000_000.0, 200_000_000.0),
        ("fy2023-low-revenue", 20231231, 1_000_000.0, 5_000_000.0),
    ):
        facts.extend(
            [
                _fact(
                    adsh,
                    "PaymentsToAcquirePropertyPlantAndEquipment",
                    capex,
                    ddate=ddate,
                    qtrs=4,
                    stmt="CF",
                ),
                _fact(adsh, "Revenues", revenue, ddate=ddate, qtrs=4, stmt="IS"),
            ]
        )
    normalized = module.normalize_sec_fsd_tables(*_fsd_tables(submissions, facts))

    result = module.calculate_sec_accounting_batch(
        normalized,
        _identity(1),
        [pd.Timestamp("2024-02-29"), pd.Timestamp("2024-03-31")],
    )
    investment = result.loc[result["signal"].eq("Investment")].set_index(
        "formation_at"
    )

    assert investment.loc[pd.Timestamp("2024-02-29"), "value"] == pytest.approx(
        4.0 / 3.0
    )
    assert investment.loc[pd.Timestamp("2024-02-29"), "observation_count"] == 24
    assert pd.isna(investment.loc[pd.Timestamp("2024-03-31"), "value"])
    assert (
        investment.loc[pd.Timestamp("2024-03-31"), "reason_if_missing"]
        == "revenue_below_10m_usd"
    )


def test_sec_batch_evidence_marks_formula_and_pipeline_only_but_stays_blocked():
    module = _module()
    evidence = module.build_sec_accounting_batch_evidence(
        evidence_run_url="https://github.com/example/aurora/actions/runs/1",
        evidence_artifact="openap-181-sec-accounting-batch",
        implementation_commit="a" * 40,
    )

    assert evidence["signal"].tolist() == ["Cash", "GP", "Investment"]
    assert evidence["formula_implemented"].all()
    assert evidence["data_pipeline_implemented"].all()
    assert not evidence["point_in_time_verified"].any()
    assert not evidence["identity_verified"].any()
    assert not evidence["coverage_measured"].any()
    assert not evidence["fidelity_measured"].any()
    assert evidence["strict_gate_result"].eq("blocked").all()
    assert evidence["blocking_reason"].eq(
        "point_in_time_identity_coverage_fidelity_not_measured"
    ).all()


def test_sec_batch_writer_persists_observations_evidence_and_summary(tmp_path):
    module = _module()
    submissions = [
        _submission(
            "cash",
            1,
            form="10-Q",
            period=20240331,
            filed=20240501,
            accepted=20240501120000,
            sic=3571,
        )
    ]
    facts = [
        _fact("cash", "Assets", 200.0, ddate=20240331, qtrs=0, stmt="BS"),
        _fact(
            "cash",
            "CashAndCashEquivalentsAtCarryingValue",
            40.0,
            ddate=20240331,
            qtrs=0,
            stmt="BS",
        ),
        _fact(
            "cash",
            "ShortTermInvestments",
            10.0,
            ddate=20240331,
            qtrs=0,
            stmt="BS",
        ),
    ]
    sub, tag, num, pre = _fsd_tables(submissions, facts)

    summary = module.write_sec_accounting_batch_outputs(
        sub,
        tag,
        num,
        pre,
        _identity(1),
        [pd.Timestamp("2024-05-31")],
        tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/1",
        evidence_artifact="openap-181-sec-accounting-batch",
        implementation_commit="a" * 40,
    )

    observations = pd.read_csv(tmp_path / "sec_accounting_batch_observations.csv")
    evidence = pd.read_csv(tmp_path / "sec_accounting_batch_evidence.csv")
    assert summary == {
        "normalized_facts": 3,
        "observations": 3,
        "finite_values": 1,
        "signals": 3,
        "strict_approved": 0,
    }
    assert set(observations["signal"]) == {"Cash", "GP", "Investment"}
    assert evidence["strict_gate_result"].eq("blocked").all()
    for name in {
        "sec_accounting_batch_normalized_facts.csv",
        "sec_accounting_batch_observations.csv",
        "sec_accounting_batch_evidence.csv",
        "sec_accounting_batch_summary.json",
    }:
        assert (tmp_path / name).stat().st_size > 0


def test_sec_batch_cli_fails_closed_outside_github(tmp_path, monkeypatch):
    script = Path(__file__).parents[1] / "scripts" / "run_openap_181_sec_accounting_batch.py"
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(script), "--output-dir", str(tmp_path)])

    with pytest.raises(LocalRunBlocked, match="OpenAP 181 SEC accounting batch"):
        runpy.run_path(str(script), run_name="__main__")


def _validation_frames(*, reverse_gp: bool = False):
    expected_rows = []
    observation_rows = []
    reference_rows = []
    for month_index, month in enumerate(pd.date_range("2020-01-31", periods=12, freq="ME")):
        for firm_index in range(10):
            security_id = f"PERMNO-{firm_index}"
            expected_rows.append(
                {
                    "security_id": security_id,
                    "formation_at": month,
                    "exchange": "NASDAQ" if firm_index % 2 else "NYSE",
                    "security_type": "common_stock",
                    "delisted": False,
                }
            )
            for signal_index, signal in enumerate(("Cash", "GP", "Investment")):
                value = float(firm_index + signal_index * 20 + month_index / 100)
                reference_value = -value if reverse_gp and signal == "GP" else value
                observation_rows.append(
                    {
                        "security_id": security_id,
                        "formation_at": month,
                        "signal": signal,
                        "value": value,
                    }
                )
                reference_rows.append(
                    {
                        "security_id": security_id,
                        "formation_at": month,
                        "signal": signal,
                        "reference_value": reference_value,
                    }
                )
    return (
        pd.DataFrame(observation_rows),
        pd.DataFrame(reference_rows),
        pd.DataFrame(expected_rows),
    )


def test_validation_approves_only_complete_evidence_above_frozen_thresholds():
    module = _module()
    observations, reference, expected = _validation_frames()

    evidence, coverage, fidelity = module.evaluate_sec_accounting_validation(
        observations,
        reference,
        expected,
        point_in_time_verified=True,
        identity_verified=True,
        evidence_run_url="https://github.com/example/aurora/actions/runs/2",
        evidence_artifact="openap-181-sec-accounting-validation",
        implementation_commit="b" * 40,
    )

    assert evidence["signal"].tolist() == ["Cash", "GP", "Investment"]
    assert evidence["coverage_result"].eq("pass").all()
    assert evidence["fidelity_result"].eq("pass").all()
    assert evidence["strict_gate_result"].eq("approved").all()
    assert evidence["blocking_reason"].eq("none").all()
    assert coverage["expected_rows"].eq(120).all()
    assert coverage["found_rows"].eq(120).all()
    assert coverage["coverage_ratio"].eq(1.0).all()
    assert fidelity["paired_rows"].eq(120).all()
    assert fidelity["paired_months"].eq(12).all()
    assert fidelity["spearman"].eq(1.0).all()
    assert fidelity["sign_agreement"].eq(1.0).all()
    assert fidelity["extreme_decile_agreement"].eq(1.0).all()
    assert fidelity["minimum_paired_rows"].eq(60).all()
    assert fidelity["minimum_paired_months"].eq(12).all()
    assert fidelity["minimum_spearman"].eq(0.95).all()
    assert fidelity["minimum_sign_agreement"].eq(0.95).all()
    assert fidelity["minimum_extreme_decile_agreement"].eq(0.80).all()


def test_validation_rejects_low_fidelity_without_changing_frozen_thresholds():
    module = _module()
    observations, reference, expected = _validation_frames(reverse_gp=True)

    evidence, _, fidelity = module.evaluate_sec_accounting_validation(
        observations,
        reference,
        expected,
        point_in_time_verified=True,
        identity_verified=True,
        evidence_run_url="https://github.com/example/aurora/actions/runs/3",
        evidence_artifact="openap-181-sec-accounting-validation",
        implementation_commit="c" * 40,
    )
    indexed = evidence.set_index("signal")
    fidelity_indexed = fidelity.set_index("signal")

    assert indexed.loc["Cash", "strict_gate_result"] == "approved"
    assert indexed.loc["GP", "strict_gate_result"] == "blocked"
    assert indexed.loc["GP", "blocking_reason"] == "fidelity_below_frozen_threshold"
    assert fidelity_indexed.loc["GP", "spearman"] == pytest.approx(-1.0)
    assert fidelity_indexed.loc["GP", "minimum_spearman"] == 0.95


def test_validation_refuses_fidelity_when_historical_identity_is_not_verified():
    module = _module()
    observations, reference, expected = _validation_frames()

    evidence, coverage, fidelity = module.evaluate_sec_accounting_validation(
        observations,
        reference,
        expected,
        point_in_time_verified=True,
        identity_verified=False,
        evidence_run_url="https://github.com/example/aurora/actions/runs/4",
        evidence_artifact="openap-181-sec-accounting-validation",
        implementation_commit="d" * 40,
    )

    assert evidence["coverage_measured"].all()
    assert evidence["coverage_result"].eq("pass").all()
    assert not evidence["fidelity_measured"].any()
    assert evidence["fidelity_result"].eq("not_measured").all()
    assert evidence["strict_gate_result"].eq("blocked").all()
    assert evidence["blocking_reason"].eq("identity_not_verified").all()
    assert coverage["coverage_ratio"].eq(1.0).all()
    assert fidelity["measurement_status"].eq("blocked_identity_not_verified").all()
