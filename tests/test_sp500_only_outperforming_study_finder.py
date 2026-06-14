from __future__ import annotations

import csv
from pathlib import Path

import yaml

from scripts.find_sp500_only_outperforming_studies import _classify, _dedupe


def test_classify_accepts_sp500_only_outperform_claim() -> None:
    candidate = _classify(
        source="test",
        study_id="W1",
        title="A market timing rule for the S&P 500",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="market_timing",
        rule_or_abstract="Hold SPY when above its 10-month moving average; otherwise cash. The rule outperforms buy-and-hold S&P 500.",
        tradable_assets="SPY",
        benchmark="S&P 500 buy-and-hold",
        text="The SPY timing strategy outperforms buy-and-hold S&P 500.",
    )

    assert candidate.reject_reasons == ""
    assert candidate.evidence_strength in {"strong", "medium"}


def test_classify_rejects_other_traded_assets() -> None:
    candidate = _classify(
        source="test",
        study_id="W2",
        title="Global tactical allocation",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="taa",
        rule_or_abstract="Rotate between SPY, TLT and GLD and beat the S&P 500.",
        tradable_assets="SPY, TLT, GLD",
        benchmark="S&P 500",
        text="The strategy beats the S&P 500.",
    )

    assert "mentions_other_traded_assets" in candidate.reject_reasons


def test_dedupe_prefers_unique_doi_or_id() -> None:
    one = _classify(
        source="test",
        study_id="W1",
        title="S&P 500 timing",
        year="2020",
        doi="10.1/test",
        url="",
        query="",
        strategy_family="market_timing",
        rule_or_abstract="SPY rule outperforms S&P 500.",
        tradable_assets="SPY",
        benchmark="S&P 500",
        text="SPY rule outperforms S&P 500.",
    )
    two = _classify(
        source="test",
        study_id="W2",
        title="S&P 500 timing duplicate",
        year="2020",
        doi="10.1/test",
        url="",
        query="",
        strategy_family="market_timing",
        rule_or_abstract="SPY rule beats S&P 500.",
        tradable_assets="SPY",
        benchmark="S&P 500",
        text="SPY rule beats S&P 500.",
    )

    assert len(_dedupe([one, two])) == 1


def test_workflow_shape() -> None:
    path = Path(".github/workflows/sp500-only-outperforming-study-finder.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "SP500 Only Outperforming Study Finder"
    assert "workflow_dispatch" in data[True]
    assert "find_studies" in data["jobs"]
    assert "scripts/find_sp500_only_outperforming_studies.py" in text
    assert "--local-only" in text
