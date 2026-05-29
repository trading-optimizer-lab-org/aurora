from __future__ import annotations

import json
from pathlib import Path

from aurora.cli.forge import build_parser
from aurora.research.agent_loop.estudios_bridge import LiteratureIdeaReport
from aurora.research.agent_loop.ideas import StrategyIdea
from aurora.research import sp500_route_tournament as tournament
from aurora.research import ml_search
from aurora.research.ml_search import MLSearchCandidate, MLSearchMetrics, MLSearchReport


def _candidate(candidate_id: str = "route-candidate") -> MLSearchCandidate:
    train = MLSearchMetrics(
        calmar=2.0,
        cagr=0.12,
        mdd=-0.06,
        trades=50,
        trades_per_year=25.0,
        long_fraction=0.55,
        final_nav=2.0,
    )
    valid = MLSearchMetrics(
        calmar=1.5,
        cagr=0.10,
        mdd=-0.07,
        trades=20,
        trades_per_year=20.0,
        long_fraction=0.50,
        final_nav=1.4,
    )
    return MLSearchCandidate(
        candidate_id=candidate_id,
        route="classic_ml",
        model="ridge",
        feature_set=("ret_lag_1", "pending_vix_level"),
        threshold=0.0,
        direction=1,
        train_metrics=train,
        validation_metrics=valid,
        rule="fake",
        robustness={
            "excess_pvalue": 0.01,
            "bootstrap_calmar_p05": 0.7,
            "bootstrap_excess_calmar_p05": 0.1,
            "random_baseline_pvalue": 0.01,
            "deflated_sharpe": 0.97,
            "pbo": 0.1,
            "feature_ablation_validation_calmar": 1.0,
            "regime_min_calmar": 0.2,
            "trade_concentration_top5": 0.2,
        },
    )


def _fake_report(config) -> MLSearchReport:
    cand = _candidate(config.run_id)
    return MLSearchReport(
        status="time_limit",
        locked_opened=False,
        objective_met=False,
        run_id=config.run_id,
        output_dir=str(Path(config.run_root) / config.run_id / "ml_search"),
        symbol=config.symbol,
        workers=config.workers,
        candidates_evaluated=10,
        batches_completed=1,
        train_period=("2010-01-01", "2013-10-18"),
        validation_period=("2013-10-21", "2019-12-31"),
        locked_period=("2020-01-01", "closed"),
        used_columns=("close", "pending_vix_level"),
        route_errors=tuple(),
        best_train=cand,
        best_validation=cand,
        objective_candidates=tuple(),
        top=(cand,),
    )


def test_sp500_route_tournament_all_routes_use_all_features(tmp_path, monkeypatch):
    seen = []

    def fake_run_ml_search(config):
        seen.append(config)
        return _fake_report(config)

    monkeypatch.setattr(
        tournament,
        "discover_literature_strategy_ideas",
        lambda **kwargs: LiteratureIdeaReport(
            queries=tuple(),
            studies_seen=0,
            ideas=tuple(),
            paper_artifacts=tuple(),
            errors=tuple(),
        ),
    )
    monkeypatch.setattr(tournament, "run_ml_search", fake_run_ml_search)

    report = tournament.run_sp500_route_tournament(
        tournament.SP500RouteTournamentConfig(
            run_id="route-test",
            run_root=str(tmp_path),
            workers=2,
            minutes_per_route=0.01,
            no_costs=True,
            no_locked=True,
        )
    )

    assert report.locked_opened is False
    assert [config.run_id for config in seen] == list(tournament.ROUTE_ORDER)
    assert all(config.include_pending_features for config in seen)
    assert all(config.pending_feature_version == "pending_features_v2_free_sources" for config in seen)
    assert all(config.no_locked for config in seen)
    assert all(0 < config.time_limit_seconds <= 0.6 for config in seen)


def test_sp500_route_tournament_writes_global_leaderboard(tmp_path, monkeypatch):
    monkeypatch.setattr(
        tournament,
        "discover_literature_strategy_ideas",
        lambda **kwargs: LiteratureIdeaReport(
            queries=tuple(),
            studies_seen=0,
            ideas=tuple(),
            paper_artifacts=tuple(),
            errors=tuple(),
        ),
    )
    monkeypatch.setattr(tournament, "run_ml_search", _fake_report)

    report = tournament.run_sp500_route_tournament(
        tournament.SP500RouteTournamentConfig(
            run_id="leaderboard-test",
            run_root=str(tmp_path),
            minutes_per_route=0.01,
            no_costs=True,
            no_locked=True,
        )
    )

    out = Path(report.output_dir)
    assert (out / "tournament_status.json").exists()
    assert (out / "tournament_progress.jsonl").exists()
    assert (out / "route_leaderboard.json").exists()
    assert (out / "global_leaderboard.json").exists()
    assert (out / "global_leaderboard.md").exists()
    assert len(json.loads((out / "global_leaderboard.json").read_text(encoding="utf-8"))) == 9


def test_sp500_route_tournament_continues_after_route_failure(tmp_path, monkeypatch):
    calls = {"count": 0}

    def flaky(config):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return _fake_report(config)

    monkeypatch.setattr(
        tournament,
        "discover_literature_strategy_ideas",
        lambda **kwargs: LiteratureIdeaReport(
            queries=tuple(),
            studies_seen=0,
            ideas=tuple(),
            paper_artifacts=tuple(),
            errors=tuple(),
        ),
    )
    monkeypatch.setattr(tournament, "run_ml_search", flaky)

    report = tournament.run_sp500_route_tournament(
        tournament.SP500RouteTournamentConfig(
            run_id="failure-test",
            run_root=str(tmp_path),
            minutes_per_route=0.01,
            no_costs=True,
            no_locked=True,
        )
    )

    assert calls["count"] == 9
    assert report.route_results[0].status == "error"
    assert report.route_results[1].status == "time_limit"


def test_sp500_paper_route_discovers_estudios_before_ml_search(tmp_path, monkeypatch):
    seen = {}

    idea = StrategyIdea(
        idea_id="credit_vix_paper",
        features=("VIX regime", "credit stress", "SPY momentum"),
        rule_family="trend_stress_combo",
        hypothesis="Paper-derived market timing idea.",
        allowed_data=("train only",),
        forbidden=("locked", "future data"),
        source="estudios:W1",
    )

    def fake_discover(**kwargs):
        seen["discover_kwargs"] = kwargs
        return LiteratureIdeaReport(
            queries=("market timing",),
            studies_seen=1,
            ideas=(idea,),
            paper_artifacts=tuple(),
            errors=tuple(),
        )

    def fake_run_ml_search(config):
        seen["ml_config"] = config
        return _fake_report(config)

    monkeypatch.setattr(tournament, "discover_literature_strategy_ideas", fake_discover)
    monkeypatch.setattr(tournament, "run_ml_search", fake_run_ml_search)

    report = tournament.run_sp500_route_tournament(
        tournament.SP500RouteTournamentConfig(
            run_id="paper-route",
            run_root=str(tmp_path),
            minutes_per_route=0.01,
            no_costs=True,
            no_locked=True,
            routes=("paper_literature_replicator",),
        )
    )

    route_dir = Path(report.output_dir) / "routes" / "paper_literature_replicator"
    literature_dir = route_dir / "estudios_literature"
    assert seen["discover_kwargs"]["output_dir"] == literature_dir
    assert seen["discover_kwargs"]["enrich_papers"] is True
    assert seen["discover_kwargs"]["summarize_papers"] is True
    assert seen["ml_config"].literature_ideas[0]["idea_id"] == "credit_vix_paper"
    assert (literature_dir / "literature_report.json").exists()
    assert (literature_dir / "literature_ideas.jsonl").exists()
    assert report.route_results[0].status == "time_limit"


def test_sp500_paper_route_merges_extra_ai_literature_ideas(tmp_path, monkeypatch):
    seen = {}
    extra_path = tmp_path / "extra_ai_ideas.jsonl"
    extra_path.write_text(
        "\ufeff"
        +
        json.dumps({
            "idea_id": "ai_global_financial_cycle",
            "features": ["VIX regime", "rates slope", "credit stress"],
            "rule_family": "trend_stress_combo",
            "hypothesis": "AI reading: global financial cycle tightens risk appetite.",
            "allowed_data": ["train only"],
            "forbidden": ["locked", "future data"],
            "source": "codex_ai:W1954685264",
        })
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        tournament,
        "discover_literature_strategy_ideas",
        lambda **kwargs: LiteratureIdeaReport(
            queries=("market timing",),
            studies_seen=1,
            ideas=tuple(),
            paper_artifacts=tuple(),
            errors=tuple(),
        ),
    )

    def fake_run_ml_search(config):
        seen["ml_config"] = config
        return _fake_report(config)

    monkeypatch.setattr(tournament, "run_ml_search", fake_run_ml_search)

    report = tournament.run_sp500_route_tournament(
        tournament.SP500RouteTournamentConfig(
            run_id="paper-route-extra",
            run_root=str(tmp_path),
            minutes_per_route=0.01,
            no_costs=True,
            no_locked=True,
            routes=("paper_literature_replicator",),
            literature_extra_ideas_path=str(extra_path),
        )
    )

    route_dir = Path(report.output_dir) / "routes" / "paper_literature_replicator"
    summary = json.loads(
        (route_dir / "estudios_literature" / "literature_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["extra_ai_ideas_count"] == 1
    assert summary["literature_role"] == "train_feature_prior"
    assert summary["selection_role"] == "train_feature_prior_only"
    assert summary["validation_role"] == "report_only"
    assert seen["ml_config"].literature_ideas[0]["idea_id"] == "ai_global_financial_cycle"


def test_sp500_paper_route_can_disable_literature_evidence(tmp_path, monkeypatch):
    called = {"discover": False}

    def fake_discover(**kwargs):
        called["discover"] = True
        raise AssertionError("literature discovery should be disabled")

    def fake_run_ml_search(config):
        assert config.literature_ideas == tuple()
        return _fake_report(config)

    monkeypatch.setattr(tournament, "discover_literature_strategy_ideas", fake_discover)
    monkeypatch.setattr(tournament, "run_ml_search", fake_run_ml_search)

    report = tournament.run_sp500_route_tournament(
        tournament.SP500RouteTournamentConfig(
            run_id="paper-route-disabled",
            run_root=str(tmp_path),
            minutes_per_route=0.01,
            no_costs=True,
            no_locked=True,
            routes=("paper_literature_replicator",),
            literature_enabled=False,
        )
    )

    route_dir = Path(report.output_dir) / "routes" / "paper_literature_replicator"
    summary = json.loads(
        (route_dir / "estudios_literature" / "literature_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert called["discover"] is False
    assert summary["literature_enabled"] is False
    assert summary["literature_role"] == "disabled"
    assert summary["validation_role"] == "report_only"


def test_ml_search_builds_literature_feature_groups_from_estudios_ideas():
    groups = ml_search._literature_feature_groups(
        [
            "pending_vix_close",
            "pending_hyg_lqd_ratio",
            "pending_xlu_xly_ratio",
            "roll_ret_21",
            "pa_gap",
        ],
        (
            {
                "idea_id": "credit_vix",
                "features": ("VIX regime", "credit stress"),
                "rule_family": "trend_stress_combo",
                "hypothesis": "Use volatility and credit spreads.",
            },
        ),
    )

    assert "literature_all" in groups
    assert "pending_vix_close" in groups["literature_all"]
    assert "pending_hyg_lqd_ratio" in groups["literature_all"]


def test_sp500_route_tournament_cli_parser_accepts_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "research",
            "sp500-route-tournament",
            "--run-id",
            "routes-cli",
            "--workers",
            "6",
            "--minutes-per-route",
            "60",
            "--feature-mode",
            "all",
            "--pending-feature-version",
            "pending_features_v2_free_sources",
            "--no-costs",
            "--no-locked",
        ]
    )

    assert args.func.__name__ == "cmd_research_sp500_route_tournament"
    assert args.workers == 6
    assert args.minutes_per_route == 60
    assert args.feature_mode == "all"
    assert args.no_locked is True


def test_sp500_route_tournament_cli_can_disable_literature_evidence():
    parser = build_parser()
    args = parser.parse_args(
        [
            "research",
            "sp500-route-tournament",
            "--run-id",
            "routes-cli",
            "--feature-mode",
            "all",
            "--no-costs",
            "--no-locked",
            "--no-literature-evidence",
        ]
    )

    assert args.no_literature_evidence is True
