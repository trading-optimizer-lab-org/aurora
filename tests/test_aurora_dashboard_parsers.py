from __future__ import annotations

import json

from scripts.aurora_dashboard_parsers import ParserContext, parse_artifact, parser_catalog


def _context(name: str = "summary.json") -> ParserContext:
    return ParserContext(
        run_id=123,
        artifact_id=456,
        workflow_name="SP500 Atlas Static Run",
        artifact_name=name,
        captured_at="2026-08-20T08:00:00+00:00",
    )


def test_json_metrics_keep_explicit_semantics_and_provenance() -> None:
    payload = json.dumps({
        "phase": "validation",
        "unit": "ratio",
        "baseline": "SPY",
        "calmar": 1.42,
        "sharpe": 1.18,
        "overall_passed": True,
    }).encode()

    report = parse_artifact("summary.json", payload, _context())

    assert report.status == "parsed"
    assert report.parser_key == "atlas"
    assert {metric.metric_key for metric in report.metrics} == {"calmar", "sharpe", "overall_passed"}
    calmar = next(metric for metric in report.metrics if metric.metric_key == "calmar")
    assert calmar.unit == "ratio"
    assert calmar.phase == "validation"
    assert calmar.baseline == "SPY"
    assert calmar.result_id.startswith("123:456:calmar:")


def test_result_ids_are_distinct_for_files_in_the_same_artifact() -> None:
    train = parse_artifact(
        "train.csv",
        b"sharpe\n1.0\n",
        ParserContext(3, 4, "Literature Strategy Backtest", "train.csv"),
    )
    validation = parse_artifact(
        "validation.csv",
        b"sharpe\n1.0\n",
        ParserContext(3, 4, "Literature Strategy Backtest", "validation.csv"),
    )

    assert train.metrics[0].result_id != validation.metrics[0].result_id


def test_csv_metrics_are_read_without_inventing_units() -> None:
    report = parse_artifact(
        "leaderboard.csv",
        b"candidate_id,calmar,sharpe\nabc,1.2,0.8\n",
        ParserContext(3, 4, "SWR CPPI corr95", "leaderboard.csv"),
    )

    assert report.parser_key == "swr"
    assert {metric.metric_key for metric in report.metrics} == {"calmar", "sharpe"}
    assert all(metric.unit is None for metric in report.metrics)


def test_prefixed_backtest_metrics_keep_the_full_explicit_column_name() -> None:
    report = parse_artifact(
        "validation_report.csv",
        b"candidate_id,train_1x_sharpe,validation_1x_calmar,validation_trades_per_month\nabc,1.2,0.8,3\n",
        ParserContext(3, 4, "Literature Strategy Backtest", "validation_report.csv"),
    )

    assert {metric.metric_key for metric in report.metrics} == {
        "train_1x_sharpe",
        "validation_1x_calmar",
        "validation_trades_per_month",
    }
    assert all(metric.unit is None for metric in report.metrics)


def test_text_and_unknown_files_remain_visible_without_fake_results() -> None:
    text_report = parse_artifact("report.md", b"calmar: 1.1\nstatus: done", _context("report.md"))
    binary_report = parse_artifact("matrix.parquet", b"PAR1\x00\x01", _context("matrix.parquet"))

    assert text_report.status == "parsed"
    assert binary_report.status == "unclassified"
    assert binary_report.metrics == ()


def test_malformed_json_is_an_explicit_error() -> None:
    report = parse_artifact("summary.json", b"{not-json", _context())
    assert report.status == "error"
    assert report.readable is True
    assert report.errors


def test_parser_catalog_covers_named_families() -> None:
    assert parser_catalog() == ("generic", "atlas", "swr", "spy", "btc", "paper", "literature", "openap")
