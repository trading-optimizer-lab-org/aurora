from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from aurora.research.literature_corpus_build import (
    LiteratureCorpusBuildConfig,
    run_literature_corpus_build,
)


def test_literature_corpus_paginates_sorts_and_records_empty_queries(tmp_path: Path, monkeypatch):
    import aurora.research.literature_corpus_build as corpus

    monkeypatch.setattr(corpus, "LITERATURE_QUERY_BANK", {"market_timing": ("equity timing",)})
    seen: list[tuple[str, str, str]] = []

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            seen.append((cmd[cmd.index("--sort") + 1], cmd[cmd.index("--page") + 1], cmd[cmd.index("--per-page") + 1]))
            return json.dumps({"studies": [], "total": 0})
        return "ok"

    report = run_literature_corpus_build(
        LiteratureCorpusBuildConfig(
            run_id="corpus-pages",
            run_root=str(tmp_path),
            pages_per_query=2,
            per_page=200,
            sorts=("relevance", "citations"),
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=lambda prompt, timeout: json.dumps({"usable_for_strategy": False}),
    )

    assert seen == [
        ("relevance", "1", "200"),
        ("relevance", "2", "200"),
        ("citations", "1", "200"),
        ("citations", "2", "200"),
    ]
    with sqlite3.connect(report.sqlite_path) as con:
        assert con.execute("select count(*) from search_queries").fetchone()[0] == 4
        assert con.execute("select sum(returned_count) from search_queries").fetchone()[0] == 0


def test_literature_corpus_deduplicates_but_keeps_all_sources(tmp_path: Path, monkeypatch):
    import aurora.research.literature_corpus_build as corpus

    monkeypatch.setattr(corpus, "LITERATURE_QUERY_BANK", {"vix": ("vix returns", "volatility timing")})
    payloads = {
        "vix returns": {
            "studies": [
                {"id": "W1", "doi": "10/example", "title": "VIX Predicts Returns", "year": 2020, "abstract": "VIX volatility timing"},
            ],
            "total": 1,
        },
        "volatility timing": {
            "studies": [
                {"openalex_id": "W1", "doi": "https://doi.org/10/example", "title": "VIX predicts returns", "year": 2020, "abstract": "VIX volatility timing"},
            ],
            "total": 1,
        },
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payloads[cmd[4]])
        if "summarize" in cmd:
            Path(cmd[cmd.index("--file") + 1]).write_text("VIX timing rule", encoding="utf-8")
        return "ok"

    report = run_literature_corpus_build(
        LiteratureCorpusBuildConfig(
            run_id="corpus-dedupe",
            run_root=str(tmp_path),
            pages_per_query=1,
            sorts=("relevance",),
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=lambda prompt, timeout: json.dumps(
            {
                "usable_for_strategy": True,
                "confidence": 0.8,
                "strategy_family": "volatility_timing",
                "hypothesis": "VIX regimes forecast risk appetite",
                "signal_logic_plain": "Use VIX to change exposure",
                "tradable_assets": ["SPY"],
                "required_features": ["vix"],
                "expected_holding_period": "weekly",
                "overfitting_risks": ["publication bias"],
                "reason_to_test": "direct market timing evidence",
            }
        ),
    )

    with sqlite3.connect(report.sqlite_path) as con:
        assert con.execute("select count(*) from studies").fetchone()[0] == 1
        assert con.execute("select count(*) from study_sources").fetchone()[0] == 2
        assert con.execute("select count(*) from raw_search_results").fetchone()[0] == 2


def test_literature_corpus_exports_ready_and_pending_ideas(tmp_path: Path, monkeypatch):
    import aurora.research.literature_corpus_build as corpus

    monkeypatch.setattr(corpus, "LITERATURE_QUERY_BANK", {"mixed": ("mixed strategy",)})
    payload = {
        "studies": [
            {
                "id": "WREADY",
                "title": "Credit Spread Timing",
                "year": 2021,
                "abstract": "credit spread predicts equity returns",
                "citations_count": 10,
            },
            {
                "id": "WPENDING",
                "title": "Satellite Data And Earnings",
                "year": 2022,
                "abstract": "satellite parking lot imagery predicts earnings",
                "citations_count": 20,
            },
        ],
        "total": 2,
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payload)
        if "summarize" in cmd:
            Path(cmd[cmd.index("--file") + 1]).write_text("summary", encoding="utf-8")
        return "ok"

    def ai(prompt, timeout):
        if "Satellite" in prompt:
            return json.dumps(
                {
                    "usable_for_strategy": True,
                    "confidence": 0.7,
                    "strategy_family": "alternative_data",
                    "hypothesis": "Satellite data may forecast earnings",
                    "signal_logic_plain": "Use satellite signal",
                    "tradable_assets": ["SPY"],
                    "required_features": ["satellite_parking_lot_traffic"],
                    "expected_holding_period": "monthly",
                    "overfitting_risks": [],
                    "reason_to_test": "novel data",
                }
            )
        return json.dumps(
            {
                "usable_for_strategy": True,
                "confidence": 0.8,
                "strategy_family": "credit_spreads",
                "hypothesis": "Credit spread predicts risk",
                "signal_logic_plain": "Use credit spread",
                "tradable_assets": ["SPY"],
                "required_features": ["credit_spread"],
                "expected_holding_period": "weekly",
                "overfitting_risks": [],
                "reason_to_test": "supported public data",
            }
        )

    report = run_literature_corpus_build(
        LiteratureCorpusBuildConfig(
            run_id="corpus-artifacts",
            run_root=str(tmp_path),
            pages_per_query=1,
            sorts=("relevance",),
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=ai,
    )

    out = Path(report.output_dir)
    assert (out / "literature_corpus.sqlite").exists()
    assert (out / "studies_all.csv").exists()
    assert (out / "ideas_ready_to_test.csv").read_text(encoding="utf-8").count("\n") == 2
    assert (out / "ideas_pending_data.csv").read_text(encoding="utf-8").count("\n") == 2
    coverage = json.loads((out / "coverage_report.json").read_text(encoding="utf-8"))
    assert coverage["locked_opened"] is False
    assert coverage["backtest_enabled"] is False
    assert report.ideas_ready_to_test == 1
    assert report.ideas_pending_data == 1


def test_literature_corpus_never_allows_locked_or_backtests(tmp_path: Path):
    try:
        run_literature_corpus_build(
            LiteratureCorpusBuildConfig(
                run_id="bad-lock",
                run_root=str(tmp_path),
                no_locked=False,
            ),
            runner=lambda cmd, cwd, timeout: "{}",
        )
    except ValueError as exc:
        assert "--no-locked" in str(exc)
    else:
        raise AssertionError("expected --no-locked failure")

    try:
        run_literature_corpus_build(
            LiteratureCorpusBuildConfig(
                run_id="bad-backtest",
                run_root=str(tmp_path),
                backtest_enabled=True,
            ),
            runner=lambda cmd, cwd, timeout: "{}",
        )
    except ValueError as exc:
        assert "does not run backtests" in str(exc)
    else:
        raise AssertionError("expected backtest failure")


def test_literature_corpus_cli_parses_command():
    from aurora.cli.forge import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "research",
            "literature-corpus-build",
            "--run-id",
            "lit-corpus-smoke",
            "--pages-per-query",
            "2",
            "--sorts",
            "relevance,date",
            "--no-locked",
        ]
    )

    assert args.func.__name__ == "cmd_research_literature_corpus_build"
    assert args.run_id == "lit-corpus-smoke"
    assert args.pages_per_query == 2
    assert args.no_locked is True


def test_literature_discovery_workflow_is_headless_and_locked_closed():
    workflow = Path(".github/workflows/literature-strategy-idea-discovery-9h.yml").read_text(
        encoding="utf-8"
    )

    assert "timeout-minutes: 540" in workflow
    assert "literature-corpus-build" in workflow
    assert "--no-locked" in workflow
    assert "--pages-per-query" in workflow
    assert 'PAGES_PER_QUERY_SAFE="${PAGES_PER_QUERY_INPUT:-5}"' in workflow
    assert 'MAX_STUDIES_TO_ENRICH_SAFE="${MAX_STUDIES_TO_ENRICH_INPUT:-0}"' in workflow
    assert 'RUN_ID_SAFE="${RUN_ID_INPUT:-literature-idea-discovery}-${GITHUB_RUN_ID}"' in workflow
    assert "ESTUDIOS_REPO_URL" in workflow
    assert "backtest" not in workflow.lower()
