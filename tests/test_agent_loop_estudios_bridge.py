from __future__ import annotations

import json
from pathlib import Path

from aurora.research.agent_loop.actions import AgentActionType
from aurora.research.agent_loop.estudios_bridge import (
    DEFAULT_ESTUDIOS_QUERIES,
    ESTUDIOS_ROOT_ENV,
    EXTENDED_ESTUDIOS_QUERIES,
    LiteratureIdeaReport,
    discover_literature_strategy_ideas,
    estudios_availability,
)
from aurora.research.agent_loop.executor import AgentActionExecutor
from aurora.research.agent_loop.ideas import StrategyIdea
from aurora.research.agent_loop.loop import run_agent_loop
from aurora.research.agent_loop.state import new_agent_state


def test_estudios_bridge_converts_search_results_to_safe_strategy_ideas(tmp_path: Path):
    payload = {
        "studies": [
            {
                "id": "W123",
                "title": "Equity market timing with volatility and credit spreads",
                "abstract": "VIX, momentum, trend, and credit stress signals.",
                "year": 2024,
            }
        ]
    }

    report = discover_literature_strategy_ideas(
        queries=("market timing",),
        runner=lambda cmd, cwd, timeout: json.dumps(payload),
    )

    assert report.studies_seen == 1
    assert len(report.ideas) == 1
    idea = report.ideas[0]
    assert idea.source == "estudios:W123"
    assert "locked" in " ".join(idea.forbidden)
    assert "future" not in " ".join(idea.features).lower()
    assert idea.rule_family == "drawdown_volatility"
    assert "VIX regime" in idea.features
    assert "credit stress" in idea.features


def test_estudios_bridge_skips_irrelevant_non_market_studies():
    payload = {
        "studies": [
            {
                "id": "WAGRI",
                "title": "Impact of pesticides use in agriculture",
                "abstract": "Benefits and hazards for crops.",
                "year": 2020,
            },
            {
                "id": "WMKT",
                "title": "Equity market timing with volatility",
                "abstract": "Volatility and momentum predict stock market regimes.",
                "year": 2020,
            },
        ]
    }

    report = discover_literature_strategy_ideas(
        queries=("market timing",),
        runner=lambda cmd, cwd, timeout: json.dumps(payload),
    )

    assert report.studies_seen == 2
    assert [idea.source for idea in report.ideas] == ["estudios:WMKT"]


def test_estudios_bridge_handles_unavailable_estudios_without_crashing():
    report = discover_literature_strategy_ideas(
        queries=("market timing",),
        runner=lambda cmd, cwd, timeout: (_ for _ in ()).throw(
            RuntimeError("ESTUDIOS unavailable")
        ),
    )

    assert report.ideas == ()
    assert report.studies_seen == 0
    assert "ESTUDIOS unavailable" in report.errors[0]


def test_estudios_bridge_reports_missing_estudios_root_without_runner(
    tmp_path: Path,
    monkeypatch,
):
    missing = tmp_path / "missing-estudios"
    monkeypatch.setenv(ESTUDIOS_ROOT_ENV, str(missing))

    availability = estudios_availability()
    report = discover_literature_strategy_ideas(queries=("market timing",))

    assert availability.available is False
    assert availability.reason == "root_not_found"
    assert report.ideas == ()
    assert report.estudios_available is False
    assert report.availability_reason == "root_not_found"
    assert str(missing) in report.estudios_root


def test_estudios_bridge_verifies_estudios_python_module(tmp_path: Path, monkeypatch):
    root = tmp_path / "estudios"
    root.mkdir()
    monkeypatch.setenv(ESTUDIOS_ROOT_ENV, str(root))

    availability = estudios_availability(python_bin=Path("definitely-not-python"))

    assert availability.available is False
    assert availability.reason == "python_not_found"


def test_estudios_bridge_rotates_default_query_bank():
    seen: list[str] = []

    def runner(cmd, cwd, timeout):
        seen.append(cmd[4])
        return json.dumps({"studies": []})

    discover_literature_strategy_ideas(
        queries=DEFAULT_ESTUDIOS_QUERIES,
        query_offset=5,
        max_queries=3,
        runner=runner,
    )

    assert seen == list(EXTENDED_ESTUDIOS_QUERIES[5:8])


def test_estudios_bridge_enriches_papers_with_save_pdf_and_summary(tmp_path: Path):
    payload = {
        "studies": [
            {
                "openalex_id": "W123",
                "title": "Machine learning market timing with volatility and liquidity",
                "abstract": "Nonlinear volatility, liquidity, and credit spread signals.",
                "year": 2020,
                "doi": "10.1/test",
                "is_oa": True,
                "citations_count": 100,
            }
        ]
    }
    commands: list[list[str]] = []

    def runner(cmd, cwd, timeout):
        commands.append(cmd)
        if "search" in cmd:
            return json.dumps(payload)
        if "summarize" in cmd:
            out_path = Path(cmd[cmd.index("--file") + 1])
            out_path.write_text(
                "Critical prompt mentioning term spread, business cycle, and liquidity.",
                encoding="utf-8",
            )
            return "summary written"
        if "pdf" in cmd:
            return "PDF saved: C:/tmp/W123.pdf"
        if "save" in cmd:
            return "saved"
        return ""

    report = discover_literature_strategy_ideas(
        queries=("market timing",),
        runner=runner,
        output_dir=tmp_path,
        enrich_papers=True,
        max_papers_to_enrich=1,
    )

    assert len(report.paper_artifacts) == 1
    artifact = report.paper_artifacts[0]
    assert artifact.study_id == "W123"
    assert artifact.saved is True
    assert artifact.pdf_attempted is True
    assert artifact.pdf_available is True
    assert artifact.summary_prompt_path is not None
    assert Path(artifact.summary_prompt_path).exists()
    assert any("save" in cmd for cmd in commands)
    assert any("pdf" in cmd for cmd in commands)
    assert any("summarize" in cmd for cmd in commands)
    assert "liquidity pressure" in report.ideas[0].features


def test_estudios_bridge_keeps_ideas_when_pdf_is_unavailable(tmp_path: Path):
    payload = {
        "studies": [
            {
                "openalex_id": "WPDFLESS",
                "title": "Credit spread market timing",
                "abstract": "Credit spread and volatility signals.",
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
            out_path.write_text("Credit spread summary", encoding="utf-8")
            return "summary written"
        return "ok"

    report = discover_literature_strategy_ideas(
        queries=("credit timing",),
        runner=runner,
        output_dir=tmp_path,
        enrich_papers=True,
        max_papers_to_enrich=1,
    )

    assert len(report.ideas) == 1
    assert len(report.paper_artifacts) == 1
    assert report.paper_artifacts[0].pdf_available is False
    assert "no legal pdf" in report.errors[0]


def test_estudios_bridge_uses_ai_extractor_for_structured_paper_ideas(tmp_path: Path):
    payload = {
        "studies": [
            {
                "openalex_id": "WAI",
                "title": "Timing equity markets with liquidity and term spreads",
                "abstract": "Market liquidity and term spread interactions.",
                "is_oa": True,
            }
        ]
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payload)
        if "summarize" in cmd:
            out_path = Path(cmd[cmd.index("--file") + 1])
            out_path.write_text(
                "Paper says liquidity pressure and term spread interact nonlinearly.",
                encoding="utf-8",
            )
        return "ok"

    def ai_extractor(prompt, timeout):
        assert "Timing equity markets" in prompt
        return json.dumps({
            "ideas": [
                {
                    "idea_id": "liquidity_term_spread_ai",
                    "features": ["liquidity pressure", "term spread", "SPY momentum"],
                    "rule_family": "yield_curve_macro",
                    "hypothesis": "Use liquidity and term spread interaction to time SPY.",
                }
            ],
            "claims": ["Liquidity and term spread interact."],
            "warnings": ["Validate out of sample."],
        })

    report = discover_literature_strategy_ideas(
        queries=("liquidity timing",),
        runner=runner,
        output_dir=tmp_path,
        enrich_papers=True,
        download_pdfs=False,
        summarize_papers=True,
        use_ai=True,
        ai_extractor=ai_extractor,
        max_papers_to_enrich=1,
    )

    assert any(idea.idea_id == "liquidity_term_spread_ai" for idea in report.ideas)
    ai_idea = next(idea for idea in report.ideas if idea.idea_id == "liquidity_term_spread_ai")
    assert ai_idea.rule_family == "yield_curve_macro"
    assert "term spread" in ai_idea.features
    assert report.paper_artifacts[0].ai_used is True
    assert report.paper_artifacts[0].ai_insight_path is not None
    assert Path(report.paper_artifacts[0].ai_insight_path).exists()


def test_paper_ai_uses_openai_provider(monkeypatch):
    from aurora.research.agent_loop import estudios_bridge

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": "{\"ideas\": []}",
                            }
                        ]
                    }
                ]
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("AURORA_PAPER_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AURORA_PAPER_AI_MODEL", "test-model")
    monkeypatch.setattr(estudios_bridge.urllib.request, "urlopen", fake_urlopen)

    raw = estudios_bridge._run_paper_ai("lee este paper", 12)

    assert raw == "{\"ideas\": []}"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["payload"]["model"] == "test-model"
    assert captured["payload"]["input"] == "lee este paper"
    assert captured["timeout"] == 12


def test_estudios_bridge_falls_back_when_ai_output_is_bad(tmp_path: Path):
    payload = {
        "studies": [
            {
                "openalex_id": "WBADAI",
                "title": "Volatility timing",
                "abstract": "VIX and volatility timing.",
            }
        ]
    }

    def runner(cmd, cwd, timeout):
        if "search" in cmd:
            return json.dumps(payload)
        if "summarize" in cmd:
            out_path = Path(cmd[cmd.index("--file") + 1])
            out_path.write_text("Volatility timing", encoding="utf-8")
        return "ok"

    report = discover_literature_strategy_ideas(
        queries=("bad ai",),
        runner=runner,
        output_dir=tmp_path,
        enrich_papers=True,
        download_pdfs=False,
        summarize_papers=True,
        use_ai=True,
        ai_extractor=lambda prompt, timeout: "not-json",
        max_papers_to_enrich=1,
    )

    assert len(report.ideas) == 1
    assert report.ideas[0].source == "estudios:WBADAI"
    assert report.paper_artifacts[0].ai_used is False
    assert "AI extraction failed" in (report.paper_artifacts[0].ai_error or "")


def test_executor_discovers_literature_ideas_and_queues_feature_generation(
    tmp_path: Path,
    monkeypatch,
):
    from aurora.research.agent_loop import executor as executor_mod

    idea = StrategyIdea(
        idea_id="study_market_timing_v1",
        features=("SPY momentum", "credit stress"),
        rule_family="trend_stress_combo",
        hypothesis="Literature inspired market timing hypothesis using causal signals.",
        allowed_data=("train only",),
        forbidden=("locked", "future data"),
        source="estudios:W1",
    )
    monkeypatch.setattr(
        executor_mod,
        "discover_literature_strategy_ideas",
        lambda **kwargs: LiteratureIdeaReport(
            queries=("q",),
            studies_seen=1,
            ideas=(idea,),
            paper_artifacts=(),
            errors=(),
        ),
    )
    state = new_agent_state(tmp_path / "run", goal_id="g", run_id="r")

    result = AgentActionExecutor().execute(
        action={"action": AgentActionType.DISCOVER_STRATEGY_IDEAS.value},
        goal=None,  # type: ignore[arg-type]
        state=state,
    )

    assert result["ok"] is True
    assert result["next_action"]["action"] == AgentActionType.GENERATE_FEATURE_SET.value
    assert "study_market_timing_v1" in (
        state.run_dir / "idea_queue.jsonl"
    ).read_text(encoding="utf-8")
    assert "study_market_timing_v1" in (
        state.run_dir / "literature_ideas.jsonl"
    ).read_text(encoding="utf-8")


def test_executor_falls_back_to_codex_when_estudios_has_no_new_ideas(
    tmp_path: Path,
    monkeypatch,
):
    from aurora.research.agent_loop import executor as executor_mod

    monkeypatch.setattr(
        executor_mod,
        "discover_literature_strategy_ideas",
        lambda **kwargs: LiteratureIdeaReport(
            queries=("q",),
            studies_seen=0,
            ideas=(),
            paper_artifacts=(),
            errors=("offline",),
        ),
    )
    state = new_agent_state(tmp_path / "run", goal_id="g", run_id="r")

    result = AgentActionExecutor().execute(
        action={"action": AgentActionType.DISCOVER_STRATEGY_IDEAS.value},
        goal=None,  # type: ignore[arg-type]
        state=state,
    )

    assert result["ok"] is False
    assert result["next_action"]["action"] == AgentActionType.ASK_CODEX_FOR_IDEAS.value
    assert "DISCOVER_STRATEGY_IDEAS" in (
        state.run_dir / "blocked_routes.jsonl"
    ).read_text(encoding="utf-8")


def test_loop_uses_estudios_ideas_after_repeated_no_improvement(
    tmp_path: Path,
    monkeypatch,
):
    from aurora.research.agent_loop import executor as executor_mod

    class Best:
        passed = False

    class Report:
        best = Best()

        def to_dict(self):
            return {
                "locked_opened": False,
                "best": {
                    "passed": False,
                    "robust_train_score": 0.2,
                    "rule": {"feature": "spy_ret_5"},
                },
            }

    goal = tmp_path / "goal.yaml"
    goal.write_text(
        """
goal_id: sp500_long_short_calmar_1
instrument: SPY
target_metric: calmar
target_value: 1.0
constraints:
  only_long_or_short: true
  always_fully_invested: true
  leverage_allowed: false
  cash_allowed: false
  traded_assets: [SPY]
  external_signals_allowed: true
protocol:
  optimise_on: train
  validation_role: exam_only
  locked_role: final_only
  open_locked: false
  robustness_required: true
  trial_logging_required: true
loop:
  stop_when_objective_met: true
  continue_on_failure: true
  pause_only_when_all_routes_blocked: false
  no_improvement_round_limit: 10
""".strip(),
        encoding="utf-8",
    )
    idea = StrategyIdea(
        idea_id="study_loop_v1",
        features=("SPY momentum", "credit stress"),
        rule_family="trend_stress_combo",
        hypothesis="Literature inspired market timing hypothesis using causal signals.",
        allowed_data=("train only",),
        forbidden=("locked", "future data"),
        source="estudios:W2",
    )
    monkeypatch.setattr(executor_mod, "run_sp500_autosearch", lambda config: Report())
    monkeypatch.setattr(executor_mod, "discover_sources", lambda config: None)
    monkeypatch.setattr(
        executor_mod,
        "discover_literature_strategy_ideas",
        lambda **kwargs: LiteratureIdeaReport(
            queries=("q",),
            studies_seen=1,
            ideas=(idea,),
            paper_artifacts=(),
            errors=(),
        ),
    )

    result = run_agent_loop(
        goal_path=goal,
        run_root=tmp_path / "runs",
        max_agent_steps=6,
        dry_run_codex=True,
        dry_run_worktree=True,
    )

    assert any(
        step["action"] == AgentActionType.DISCOVER_STRATEGY_IDEAS.value
        for step in result.steps
    )
    assert result.state.locked_opened is False
    assert "study_loop_v1" in (
        result.state.run_dir / "idea_queue.jsonl"
    ).read_text(encoding="utf-8")
