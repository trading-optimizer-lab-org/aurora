from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from aurora.research.sp500_literature_build import (
    SP500_LITERATURE_QUERIES,
    SP500LiteratureBuildConfig,
    run_sp500_literature_build,
)


def test_literature_build_searches_multiple_queries(tmp_path: Path):
    seen: list[str] = []

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            seen.append(cmd[4])
            return json.dumps({"studies": []})
        return "ok"

    run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-test",
            run_root=str(tmp_path),
            max_studies=3,
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=lambda prompt, timeout: json.dumps({"usable_for_strategy": False}),
    )

    assert seen == list(SP500_LITERATURE_QUERIES)


def test_literature_build_report_records_estudios_availability(tmp_path: Path):
    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-availability",
            run_root=str(tmp_path),
            max_studies=1,
            no_locked=True,
        ),
        runner=lambda cmd, cwd, timeout: json.dumps({"studies": []}) if "search" in cmd else "ok",
        ai_extractor=lambda prompt, timeout: json.dumps({"usable_for_strategy": False}),
    )

    status = json.loads(Path(report.status_path).read_text(encoding="utf-8"))
    markdown = Path(report.markdown_report_path).read_text(encoding="utf-8")

    assert isinstance(report.estudios_available, bool)
    assert "estudios_available" in status
    assert "estudios_root" in status
    assert "ESTUDIOS disponible:" in markdown


def test_literature_build_requires_estudios_when_no_runner(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AURORA_ESTUDIOS_ROOT", str(tmp_path / "missing-estudios"))

    try:
        run_sp500_literature_build(
            SP500LiteratureBuildConfig(
                run_id="lit-missing-estudios",
                run_root=str(tmp_path),
                max_studies=1,
                no_locked=True,
            )
        )
    except RuntimeError as exc:
        assert "ESTUDIOS unavailable" in str(exc)
        assert "AURORA_ESTUDIOS_ROOT" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when ESTUDIOS is unavailable")


def test_literature_build_deduplicates_by_openalex_doi_title(tmp_path: Path):
    payload = {
        "studies": [
            {"id": "W1", "title": "SP500 timing", "doi": "10/a", "year": 2020},
            {"openalex_id": "W1", "title": "SP500 timing duplicate", "doi": "10/b", "year": 2020},
            {"title": "Same DOI", "doi": "10/a", "year": 2021},
            {"title": "Title Only", "year": 2022},
            {"title": "title only", "year": 2022},
        ]
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payload)
        if "summarize" in cmd:
            out_path = Path(cmd[cmd.index("--file") + 1])
            out_path.write_text("SP500 volatility timing", encoding="utf-8")
        return "ok"

    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-dedupe",
            run_root=str(tmp_path),
            max_studies=10,
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=lambda prompt, timeout: json.dumps({"usable_for_strategy": False}),
    )

    with sqlite3.connect(report.sqlite_path) as con:
        count = con.execute("select count(*) from studies").fetchone()[0]

    assert count == 2


def test_literature_build_limits_to_200_selected_studies(tmp_path: Path):
    payload = {
        "studies": [
            {
                "id": f"W{i}",
                "title": f"SP500 market timing volatility {i}",
                "abstract": "VIX credit spread momentum stock returns",
                "year": 2020,
                "citations_count": i,
            }
            for i in range(260)
        ]
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payload)
        if "summarize" in cmd:
            out_path = Path(cmd[cmd.index("--file") + 1])
            out_path.write_text("SP500 volatility timing", encoding="utf-8")
        return "ok"

    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-limit",
            run_root=str(tmp_path),
            max_studies=200,
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=lambda prompt, timeout: json.dumps({"usable_for_strategy": False}),
    )

    with sqlite3.connect(report.sqlite_path) as con:
        selected = con.execute("select count(*) from studies where selected=1").fetchone()[0]

    assert selected == 200


def test_literature_build_never_opens_locked(tmp_path: Path):
    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-lock",
            run_root=str(tmp_path),
            max_studies=1,
            no_locked=True,
        ),
        runner=lambda cmd, cwd, timeout: json.dumps({"studies": []}) if "search" in cmd else "ok",
        ai_extractor=lambda prompt, timeout: json.dumps({"usable_for_strategy": False}),
    )

    assert report.locked_opened is False
    assert json.loads(Path(report.status_path).read_text(encoding="utf-8"))["locked_opened"] is False


def test_literature_build_writes_sqlite_ledger(tmp_path: Path):
    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-sqlite",
            run_root=str(tmp_path),
            max_studies=1,
            no_locked=True,
        ),
        runner=lambda cmd, cwd, timeout: json.dumps({"studies": []}) if "search" in cmd else "ok",
        ai_extractor=lambda prompt, timeout: json.dumps({"usable_for_strategy": False}),
    )

    with sqlite3.connect(report.sqlite_path) as con:
        tables = {
            row[0]
            for row in con.execute("select name from sqlite_master where type='table'")
        }

    assert {
        "studies",
        "search_results",
        "paper_texts",
        "ai_extractions",
        "strategy_ideas",
        "idea_sources",
        "feature_mappings",
        "failures",
    }.issubset(tables)


def test_literature_build_records_pdf_available_false(tmp_path: Path):
    payload = {
        "studies": [
            {
                "id": "WNO",
                "title": "SP500 credit spread timing",
                "abstract": "credit spread timing stock returns",
                "is_oa": False,
            }
        ]
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payload)
        if "pdf" in cmd:
            raise RuntimeError("no legal pdf")
        if "summarize" in cmd:
            out_path = Path(cmd[cmd.index("--file") + 1])
            out_path.write_text("credit spread timing", encoding="utf-8")
        return "ok"

    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-nopdf",
            run_root=str(tmp_path),
            max_studies=1,
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=lambda prompt, timeout: json.dumps({"usable_for_strategy": False}),
    )

    with sqlite3.connect(report.sqlite_path) as con:
        pdf_available = con.execute(
            "select pdf_available from paper_texts where study_id='WNO'"
        ).fetchone()[0]

    assert pdf_available == 0


def test_literature_ai_extraction_has_required_fields(tmp_path: Path):
    payload = {
        "studies": [
            {
                "id": "WAI",
                "title": "VIX and SP500 market timing",
                "abstract": "VIX predicts equity market regimes",
            }
        ]
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payload)
        if "summarize" in cmd:
            out_path = Path(cmd[cmd.index("--file") + 1])
            out_path.write_text("VIX market timing strategy", encoding="utf-8")
        return "ok"

    def ai(prompt, timeout):
        return json.dumps(
            {
                "usable_for_strategy": True,
                "confidence": 0.84,
                "strategy_family": "volatility_vix",
                "hypothesis": "Use VIX stress to reduce SP500 exposure.",
                "required_features": ["vix", "spy_momentum"],
                "signal_logic_plain": "Long when trend is healthy and VIX stress is falling.",
                "expected_holding_period": "daily_to_monthly",
                "overfitting_risks": ["threshold mining"],
                "test_priority": "high",
            }
        )

    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-ai",
            run_root=str(tmp_path),
            max_studies=1,
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=ai,
    )

    with sqlite3.connect(report.sqlite_path) as con:
        row = con.execute(
            "select usable_for_strategy, confidence, strategy_family, test_priority "
            "from ai_extractions where study_id='WAI'"
        ).fetchone()

    assert row == (1, 0.84, "volatility_vix", "high")


def test_literature_ideas_link_back_to_source_papers(tmp_path: Path):
    payload = {
        "studies": [
            {
                "id": "WSRC",
                "title": "Credit spreads and SP500 returns",
                "abstract": "Credit spread predicts stock returns.",
            }
        ]
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payload)
        if "summarize" in cmd:
            out_path = Path(cmd[cmd.index("--file") + 1])
            out_path.write_text("credit spread timing", encoding="utf-8")
        return "ok"

    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-source",
            run_root=str(tmp_path),
            max_studies=1,
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=lambda prompt, timeout: json.dumps(
            {
                "usable_for_strategy": True,
                "confidence": 0.7,
                "strategy_family": "credit",
                "hypothesis": "Credit stress gates SP500.",
                "required_features": ["credit_spread"],
                "signal_logic_plain": "Risk off when spreads widen.",
                "expected_holding_period": "weekly",
                "overfitting_risks": [],
                "test_priority": "high",
            }
        ),
    )

    with sqlite3.connect(report.sqlite_path) as con:
        source = con.execute("select study_id from idea_sources").fetchone()[0]

    assert source == "WSRC"


def test_literature_feature_mapping_uses_known_aurora_features(tmp_path: Path):
    payload = {
        "studies": [
            {
                "id": "WMAP",
                "title": "VIX credit spreads and yield curve timing",
                "abstract": "VIX credit spread yield curve SP500",
            }
        ]
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payload)
        if "summarize" in cmd:
            out_path = Path(cmd[cmd.index("--file") + 1])
            out_path.write_text("VIX credit spread yield curve", encoding="utf-8")
        return "ok"

    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-map",
            run_root=str(tmp_path),
            max_studies=1,
            no_locked=True,
        ),
        runner=runner,
        ai_extractor=lambda prompt, timeout: json.dumps(
            {
                "usable_for_strategy": True,
                "confidence": 0.8,
                "strategy_family": "macro_credit_vol",
                "hypothesis": "Combine VIX, credit and curve.",
                "required_features": ["vix", "credit_spread", "yield_curve"],
                "signal_logic_plain": "Risk off when all stress signals rise.",
                "expected_holding_period": "weekly",
                "overfitting_risks": [],
                "test_priority": "high",
            }
        ),
    )

    with sqlite3.connect(report.sqlite_path) as con:
        mapped = {row[0] for row in con.execute("select aurora_feature from feature_mappings")}

    assert {"pending_yf_vix_level", "cs_spread", "yc_10y_2y"}.issubset(mapped)


def test_literature_report_is_written(tmp_path: Path):
    report = run_sp500_literature_build(
        SP500LiteratureBuildConfig(
            run_id="lit-report",
            run_root=str(tmp_path),
            max_studies=1,
            no_locked=True,
        ),
        runner=lambda cmd, cwd, timeout: json.dumps({"studies": []}) if "search" in cmd else "ok",
        ai_extractor=lambda prompt, timeout: json.dumps({"usable_for_strategy": False}),
    )

    text = Path(report.markdown_report_path).read_text(encoding="utf-8")

    assert "SP500 Literature Corpus" in text
    assert "Locked abierto: false" in text


def test_literature_build_cli_parses_command():
    from aurora.cli.forge import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "research",
            "sp500-literature-build",
            "--run-id",
            "sp500-literature-smoke",
            "--max-studies",
            "10",
            "--pdf-mode",
            "full-if-available",
            "--output",
            "sqlite",
            "--no-locked",
        ]
    )

    assert args.func.__name__ == "cmd_research_sp500_literature_build"
    assert args.run_id == "sp500-literature-smoke"
    assert args.max_studies == 10
    assert args.no_locked is True
