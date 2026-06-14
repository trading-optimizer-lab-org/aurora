from __future__ import annotations

import csv
import urllib.error
from pathlib import Path

import yaml

import scripts.find_sp500_only_outperforming_studies as finder
from scripts.find_sp500_only_outperforming_studies import _candidate_from_semantic_scholar_paper, _classify, _dedupe


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


def test_classify_rejects_stock_recommendation_context() -> None:
    candidate = _classify(
        source="test",
        study_id="W6",
        title="A practical machine learning approach for dynamic stock recommendation",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="ml",
        rule_or_abstract="The model ranks individual stocks and reports outperformance versus the S&P 500 benchmark.",
        tradable_assets="",
        benchmark="S&P 500",
        text="A stock recommendation strategy outperforms the S&P 500 benchmark.",
    )

    assert "non_sp500_only_strategy_context" in candidate.reject_reasons


def test_classify_rejects_esg_portfolio_against_sp500() -> None:
    candidate = _classify(
        source="test",
        study_id="W7",
        title="ESG corporate practices and stock performance",
        year="2025",
        doi="",
        url="",
        query="",
        strategy_family="portfolio",
        rule_or_abstract="A portfolio of top 30 listed companies outperforms the S&P 500 index.",
        tradable_assets="",
        benchmark="S&P 500",
        text="The ESG portfolio outperforms the S&P 500 benchmark.",
    )

    assert "non_sp500_only_strategy_context" in candidate.reject_reasons


def test_classify_rejects_factor_strategy_within_sp500() -> None:
    candidate = _classify(
        source="test",
        study_id="W15",
        title="Can Simple Strategies Beat S&P 500?",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="factor",
        rule_or_abstract="Size and/or value strategies applied within the S&P 500 index outperform the S&P 500.",
        tradable_assets="",
        benchmark="S&P 500",
        text="Size, value and smart beta strategies within the index outperform the S&P 500.",
    )

    assert "non_sp500_only_strategy_context" in candidate.reject_reasons


def test_classify_rejects_sp500_constituent_stock_strategy() -> None:
    candidate = _classify(
        source="test",
        study_id="W8",
        title="Directional movements of S&P 500 constituent stocks",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="stock_selection",
        rule_or_abstract="Buy the top S&P 500 constituents and sell short the bottom constituents.",
        tradable_assets="",
        benchmark="S&P 500",
        text="The constituent stock strategy outperforms the market.",
    )

    assert "non_sp500_only_strategy_context" in candidate.reject_reasons


def test_classify_rejects_aapl_or_multi_market_context() -> None:
    candidate = _classify(
        source="test",
        study_id="W9",
        title="Adaptive reinforcement learning for S&P 500 and AAPL",
        year="2024",
        doi="",
        url="",
        query="",
        strategy_family="ml",
        rule_or_abstract="Uses historical data from the S&P 500 Index and AAPL stock.",
        tradable_assets="",
        benchmark="S&P 500",
        text="The S&P 500 and AAPL stock strategy outperforms buy-and-hold.",
    )

    assert "non_sp500_only_strategy_context" in candidate.reject_reasons


def test_classify_rejects_leveraged_inverse_etf_pairs() -> None:
    candidate = _classify(
        source="test",
        study_id="W10",
        title="Leveraged and inverse ETF pairs",
        year="2024",
        doi="",
        url="",
        query="",
        strategy_family="etf_pairs",
        rule_or_abstract="Leveraged and inverse ETFs mimic the S&P 500 and outperform the index.",
        tradable_assets="leveraged and inverse ETFs",
        benchmark="S&P 500",
        text="Leveraged and inverse ETFs outperform the S&P 500 on a risk-adjusted basis.",
    )

    assert "non_sp500_only_strategy_context" in candidate.reject_reasons


def test_classify_rejects_prediction_only_without_trading_backtest() -> None:
    candidate = _classify(
        source="test",
        study_id="W11",
        title="S&P 500 price forecasting with N-BEATS",
        year="2024",
        doi="",
        url="",
        query="",
        strategy_family="forecasting",
        rule_or_abstract="Predicts S&P 500 price and reports superior RMSE and predictive accuracy.",
        tradable_assets="SPY",
        benchmark="S&P 500",
        text="The model uses S&P 500 data and surpasses other models in RMSE, MAE and predictive accuracy.",
    )

    assert "prediction_only_no_trading_backtest" in candidate.reject_reasons


def test_classify_rejects_cost_adjusted_momentum_loss() -> None:
    candidate = _classify(
        source="test",
        study_id="W12",
        title="Application of Momentum Strategy to S&P 500",
        year="2024",
        doi="",
        url="",
        query="",
        strategy_family="momentum",
        rule_or_abstract="Some S&P 500 momentum strategies beat the benchmark under ideal conditions.",
        tradable_assets="SPY",
        benchmark="S&P 500",
        text="There are some strategies that beat the benchmark under ideal conditions, but all of them loss when transaction fees are taken into account.",
    )

    assert "negative_or_non_outperform_result" in candidate.reject_reasons


def test_classify_rejects_outperforming_non_benchmark_method() -> None:
    candidate = _classify(
        source="test",
        study_id="W13",
        title="S&P 500 option-implied prediction device",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="prediction",
        rule_or_abstract="Market timing strategies based on recovered moments outperform those based on risk-neutral moments.",
        tradable_assets="SPY",
        benchmark="S&P 500",
        text="Using options on the S&P 500, market timing strategies based on recovered moments outperform those based on risk-neutral moments.",
    )

    assert "no_outperform_vs_sp500_or_buyhold_claim_found" in candidate.reject_reasons


def test_classify_accepts_outperform_the_market_phrase() -> None:
    candidate = _classify(
        source="test",
        study_id="W14",
        title="S&P 500 timing strategy",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="market_timing",
        rule_or_abstract="A SPY timing strategy can outperform the market.",
        tradable_assets="SPY",
        benchmark="S&P 500",
        text="The SPY market timing strategy can outperform the market.",
    )

    assert candidate.reject_reasons == ""


def test_classify_rejects_cannot_beat_market_language() -> None:
    candidate = _classify(
        source="test",
        study_id="W3",
        title="The ups and downs of the S&P 500",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="market_timing",
        rule_or_abstract=(
            "A filter trading rule on the S&P 500 may look profitable, but once costs are deducted "
            "profits vanish and investors cannot beat the market."
        ),
        tradable_assets="SPY",
        benchmark="S&P 500 buy-and-hold",
        text=(
            "The S&P 500 filter strategy can appear to beat buy-and-hold before costs, "
            "but once costs are deducted profits vanish. You cannot beat the market."
        ),
    )

    assert "negative_or_non_outperform_result" in candidate.reject_reasons


def test_classify_rejects_neither_ai_can_beat_buy_hold() -> None:
    candidate = _classify(
        source="test",
        study_id="W16",
        title="Why neither traditional ML nor agentic AI can beat buy-and-hold",
        year="2026",
        doi="",
        url="",
        query="",
        strategy_family="ml",
        rule_or_abstract="The S&P 500 strategy shows neither ML nor AI can beat buy-and-hold.",
        tradable_assets="SPY",
        benchmark="S&P 500",
        text="The study finds neither traditional ML nor agentic AI can beat buy-and-hold.",
    )

    assert "negative_or_non_outperform_result" in candidate.reject_reasons


def test_classify_rejects_random_walk_non_rejection_language() -> None:
    candidate = _classify(
        source="test",
        study_id="W17",
        title="Random walks, Hurst exponent, and market efficiency",
        year="2010",
        doi="",
        url="",
        query="",
        strategy_family="market_efficiency",
        rule_or_abstract=(
            "The S&P 500 analysis is not evidence against the random walk hypothesis "
            "and is not a documented trading strategy outperforming buy-and-hold."
        ),
        tradable_assets="SPY",
        benchmark="S&P 500",
        text=(
            "The S&P 500 results are not evidence against random walk behaviour and "
            "are not incompatible with random walk market efficiency."
        ),
    )

    assert "negative_or_non_outperform_result" in candidate.reject_reasons


def test_classify_rejects_treasury_issue_operating_leg() -> None:
    candidate = _classify(
        source="test",
        study_id="W18",
        title="Super Bowl Stock Market Predictor",
        year="2024",
        doi="",
        url="",
        query="",
        strategy_family="seasonality",
        rule_or_abstract=(
            "Buy the S&P 500 in NFC years and invest in Treasury issues in AFC years; "
            "the switching strategy beats buy-and-hold."
        ),
        tradable_assets="S&P 500 and Treasury issues",
        benchmark="S&P 500 buy-and-hold",
        text=(
            "An investment policy of buying the S&P 500 in NFC years and investing in "
            "Treasury issues in AFC years beats a buy-and-hold strategy."
        ),
    )

    assert "mentions_other_traded_assets" in candidate.reject_reasons


def test_classify_rejects_theoretical_timing_threshold_without_found_strategy() -> None:
    candidate = _classify(
        source="test",
        study_id="W19",
        title="How Much Information Is Required to Time the Market?",
        year="2018",
        doi="",
        url="",
        query="",
        strategy_family="market_timing",
        rule_or_abstract=(
            "Derives the minimum required information coefficient for a timing strategy "
            "to outperform a buy-and-hold market benchmark."
        ),
        tradable_assets="S&P 500",
        benchmark="S&P 500 buy-and-hold",
        text=(
            "The authors derive formulas to estimate the minimum required information "
            "coefficient for a timing strategy to outperform a buy-and-hold market benchmark."
        ),
    )

    assert "theoretical_framework_no_found_strategy" in candidate.reject_reasons


def test_classify_accepts_improve_returns_versus_buy_hold_language() -> None:
    candidate = _classify(
        source="test",
        study_id="W4",
        title="Optimal probabilistic market timing using S&P 500 cycles",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="market_timing",
        rule_or_abstract=(
            "Uses historical bull and bear regime probabilities on the daily S&P 500 price index "
            "to time market exposure."
        ),
        tradable_assets="SPY",
        benchmark="S&P 500 buy-and-hold",
        text=(
            "The S&P 500 market-timing strategy is designed to improve long-run investment returns "
            "versus buy-and-hold."
        ),
    )

    assert candidate.reject_reasons == ""


def test_classify_accepts_whereas_sp500_metric_comparison() -> None:
    candidate = _classify(
        source="test",
        study_id="W5",
        title="Return predictability and market timing on the S&P 500",
        year="2020",
        doi="",
        url="",
        query="",
        strategy_family="market_timing",
        rule_or_abstract="Transforms forecasts into an investable SPY market timing trading strategy.",
        tradable_assets="SPY",
        benchmark="S&P 500 buy-and-hold",
        text=(
            "The strategy results in 16.6% annual returns with a 0.92 Sharpe ratio, "
            "whereas the S&P 500 has annual returns of 10% and a 0.46 Sharpe ratio."
        ),
    )

    assert candidate.reject_reasons == ""


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


def test_openalex_search_handles_http_error(monkeypatch) -> None:
    def raise_http_error(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.openalex.org/works", 400, "Bad Request", {}, None)

    monkeypatch.setattr(finder.urllib.request, "urlopen", raise_http_error)

    assert finder._openalex_search("bad query", page=1, per_page=1) == {}


def test_semantic_scholar_search_handles_http_error(monkeypatch) -> None:
    def raise_http_error(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.semanticscholar.org", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(finder.urllib.request, "urlopen", raise_http_error)

    assert finder._semantic_scholar_search("bad query", offset=0, limit=1) == {}


def test_semantic_scholar_candidate_classification() -> None:
    candidate = _candidate_from_semantic_scholar_paper(
        {
            "paperId": "abc",
            "title": "S&P 500 market timing strategy",
            "year": 2020,
            "abstract": "A SPY trading rule outperforms buy-and-hold S&P 500.",
            "externalIds": {"DOI": "10.1/test"},
            "openAccessPdf": {"url": "https://example.test/paper.pdf"},
        },
        query="test",
    )

    assert candidate.source == "semantic_scholar"
    assert candidate.reject_reasons == ""


def test_workflow_shape() -> None:
    path = Path(".github/workflows/sp500-only-outperforming-study-finder.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")

    assert data["name"] == "SP500 Only Outperforming Study Finder"
    assert "workflow_dispatch" in data[True]
    assert "find_studies" in data["jobs"]
    assert "scripts/find_sp500_only_outperforming_studies.py" in text
    assert "--local-only" in text
