"""SP500 all-feature route tournament.

Runs a fixed sequence of route adapters under the same train/validation
contract. Locked remains closed; each route delegates to the train-first
ML search with different search biases so the comparison is operationally
consistent.
"""
from __future__ import annotations

import json
import math
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aurora.core.runtime_paths import base_data_dir
from aurora.research.agent_loop.estudios_bridge import discover_literature_strategy_ideas
from aurora.research.ml_search import MLSearchCandidate, MLSearchConfig, MLSearchReport, run_ml_search


ROUTE_ORDER: tuple[str, ...] = (
    "genetic_programming_interpretable",
    "paper_literature_replicator",
    "auto_gen_combinatorial_triage",
    "adaptive_family_tournament",
    "rule_induction_trees",
    "symbolic_regression",
    "bayesian_rule_optimization",
    "strategy_combiner",
    "regime_adaptive",
)


@dataclass(frozen=True)
class RouteProfile:
    slug: str
    label: str
    models: tuple[str, ...]
    adaptive: bool
    quick_screen: int
    max_features: int
    seed_offset: int
    penalized_pools: tuple[str, ...] = tuple()
    penalty_factor: float = 0.25
    min_feature_distance: float = 0.45
    min_behavior_distance: float = 0.45


ROUTE_PROFILES: tuple[RouteProfile, ...] = (
    RouteProfile(
        "genetic_programming_interpretable",
        "Genetic Programming de reglas interpretables",
        ("forest", "xgboost", "lightgbm"),
        True,
        0,
        5,
        1000,
    ),
    RouteProfile(
        "paper_literature_replicator",
        "Paper replicator + literatura",
        ("ridge", "logistic", "lightgbm"),
        True,
        10000,
        6,
        4000,
    ),
    RouteProfile(
        "auto_gen_combinatorial_triage",
        "Auto-gen combinatorial + triage rapido",
        ("corr", "ridge", "logistic"),
        False,
        0,
        6,
        2000,
    ),
    RouteProfile(
        "adaptive_family_tournament",
        "Torneo adaptativo por familias",
        ("lightgbm", "xgboost"),
        True,
        30000,
        8,
        3000,
        penalized_pools=("technicals",),
        penalty_factor=0.15,
    ),
    RouteProfile(
        "rule_induction_trees",
        "Rule induction / arboles interpretables",
        ("forest",),
        True,
        0,
        6,
        5000,
    ),
    RouteProfile(
        "symbolic_regression",
        "Symbolic regression",
        ("corr", "ridge"),
        False,
        0,
        4,
        6000,
    ),
    RouteProfile(
        "bayesian_rule_optimization",
        "Bayesian optimization sobre reglas simples",
        ("lightgbm", "xgboost", "ridge"),
        True,
        15000,
        5,
        7000,
    ),
    RouteProfile(
        "strategy_combiner",
        "Strategy combiner",
        ("ridge", "logistic", "lightgbm", "xgboost"),
        True,
        5000,
        8,
        8000,
    ),
    RouteProfile(
        "regime_adaptive",
        "Regime adaptive",
        ("forest", "lightgbm", "xgboost"),
        True,
        10000,
        8,
        9000,
    ),
)


@dataclass(frozen=True)
class SP500RouteTournamentConfig:
    run_id: str
    symbol: str = "SPY"
    library: str = "prices_daily"
    workers: int = 6
    minutes_per_route: float = 60.0
    feature_mode: str = "all"
    pending_feature_library: str = "features_pending_daily"
    pending_feature_version: str = "pending_features_v2_free_sources"
    run_root: str | None = None
    no_costs: bool = True
    no_locked: bool = True
    max_candidates_per_route: int = 2_000_000
    batch_size: int = 1200
    seed: int = 42
    target_calmar: float = 1.25
    validation_target_calmar: float = 1.25
    train_end: str = "2013-10-18"
    validation_start: str = "2013-10-21"
    validation_end: str = "2019-12-31"
    locked_start: str = "2020-01-01"
    routes: tuple[str, ...] | None = None
    literature_max_queries: int = 4
    literature_per_query: int = 8
    literature_max_papers_to_enrich: int = 8
    literature_use_ai: bool = False
    literature_enabled: bool = True
    literature_extra_ideas_path: str | None = None


@dataclass(frozen=True)
class RouteTournamentResult:
    route: str
    label: str
    status: str
    output_dir: str
    candidates_evaluated: int
    batches_completed: int
    locked_opened: bool
    best_candidate: dict[str, Any] | None
    robust_score: float
    robustness_passes: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SP500RouteTournamentReport:
    run_id: str
    status: str
    locked_opened: bool
    output_dir: str
    route_results: tuple[RouteTournamentResult, ...]
    global_leaderboard: tuple[RouteTournamentResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "locked_opened": self.locked_opened,
            "output_dir": self.output_dir,
            "route_results": [result.to_dict() for result in self.route_results],
            "global_leaderboard": [result.to_dict() for result in self.global_leaderboard],
        }


def run_sp500_route_tournament(config: SP500RouteTournamentConfig) -> SP500RouteTournamentReport:
    if not config.no_costs:
        raise ValueError("sp500-route-tournament v1 only supports --no-costs")
    if not config.no_locked:
        raise ValueError("sp500-route-tournament v1 requires --no-locked")
    if config.feature_mode != "all":
        raise ValueError("sp500-route-tournament v1 requires --feature-mode all")
    if config.workers < 1:
        raise ValueError("workers must be >= 1")
    if config.minutes_per_route <= 0:
        raise ValueError("minutes_per_route must be > 0")

    selected_profiles = _selected_route_profiles(config.routes)
    output_dir = _output_dir(config)
    routes_dir = output_dir / "routes"
    output_dir.mkdir(parents=True, exist_ok=True)
    routes_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "tournament_status.json"
    progress_path = output_dir / "tournament_progress.jsonl"

    results: list[RouteTournamentResult] = []
    _write_json(status_path, _status_payload(config, output_dir, "running", results))

    for index, profile in enumerate(selected_profiles, start=1):
        route_started = time.perf_counter()
        _append_jsonl(
            progress_path,
            {
                "event": "route_started",
                "route": profile.slug,
                "label": profile.label,
                "index": index,
                "total_routes": len(selected_profiles),
                "locked_opened": False,
                "created_at_utc": _now(),
            },
        )
        route_dir = routes_dir / profile.slug
        route_dir.mkdir(parents=True, exist_ok=True)
        try:
            literature_ideas: tuple[dict[str, Any], ...] = tuple()
            if profile.slug == "paper_literature_replicator":
                literature_ideas = _prepare_literature_route(
                    config,
                    route_dir,
                    progress_path,
                )
            remaining_seconds = max(
                0.01,
                float(config.minutes_per_route) * 60.0 - (time.perf_counter() - route_started),
            )
            route_config = _ml_config_for_route(
                config,
                profile,
                routes_dir,
                literature_ideas=literature_ideas,
                time_limit_seconds=remaining_seconds,
            )
            report = run_ml_search(route_config)
            result = _route_result(profile, report)
        except Exception as exc:  # keep tournament moving route by route
            (route_dir / "stderr.log").write_text(traceback.format_exc(), encoding="utf-8")
            result = RouteTournamentResult(
                route=profile.slug,
                label=profile.label,
                status="error",
                output_dir=str(route_dir),
                candidates_evaluated=0,
                batches_completed=0,
                locked_opened=False,
                best_candidate=None,
                robust_score=-math.inf,
                robustness_passes=0,
                error=str(exc),
            )
        results.append(result)
        _write_json(route_dir / "status.json", result.to_dict())
        _append_jsonl(
            progress_path,
            {
                "event": "route_completed",
                "route": profile.slug,
                "status": result.status,
                "candidates_evaluated": result.candidates_evaluated,
                "batches_completed": result.batches_completed,
                "robust_score": result.robust_score,
                "locked_opened": result.locked_opened,
                "created_at_utc": _now(),
            },
        )
        _write_json(status_path, _status_payload(config, output_dir, "running", results))

    leaderboard = tuple(sorted(results, key=lambda item: item.robust_score, reverse=True))
    _write_json(output_dir / "route_leaderboard.json", [result.to_dict() for result in results])
    _write_json(output_dir / "global_leaderboard.json", [result.to_dict() for result in leaderboard])
    (output_dir / "global_leaderboard.md").write_text(
        _leaderboard_markdown(config, leaderboard),
        encoding="utf-8",
    )
    report = SP500RouteTournamentReport(
        run_id=config.run_id,
        status="completed",
        locked_opened=False,
        output_dir=str(output_dir),
        route_results=tuple(results),
        global_leaderboard=leaderboard,
    )
    _write_json(status_path, report.to_dict())
    return report


def _selected_route_profiles(routes: tuple[str, ...] | None) -> tuple[RouteProfile, ...]:
    if not routes:
        return ROUTE_PROFILES
    profiles_by_slug = {profile.slug: profile for profile in ROUTE_PROFILES}
    unknown = tuple(route for route in routes if route not in profiles_by_slug)
    if unknown:
        raise ValueError(f"Unknown route(s): {', '.join(unknown)}")
    return tuple(profiles_by_slug[route] for route in routes)


def _ml_config_for_route(
    config: SP500RouteTournamentConfig,
    profile: RouteProfile,
    routes_dir: Path,
    *,
    literature_ideas: tuple[dict[str, Any], ...] = tuple(),
    time_limit_seconds: float | None = None,
) -> MLSearchConfig:
    return MLSearchConfig(
        run_id=profile.slug,
        symbol=config.symbol,
        library=config.library,
        target_calmar=config.target_calmar,
        validation_target_calmar=config.validation_target_calmar,
        train_end=config.train_end,
        validation_start=config.validation_start,
        validation_end=config.validation_end,
        locked_start=config.locked_start,
        workers=config.workers,
        max_candidates=config.max_candidates_per_route,
        batch_size=config.batch_size,
        seed=config.seed + profile.seed_offset,
        run_root=str(routes_dir),
        no_costs=True,
        no_locked=True,
        include_pending_features=True,
        pending_feature_library=config.pending_feature_library,
        pending_feature_version=config.pending_feature_version,
        models=profile.models,
        top_n=20,
        target_objective_count=1,
        min_feature_jaccard_distance=profile.min_feature_distance,
        min_behavior_distance=profile.min_behavior_distance,
        train_subperiod_count=6,
        validation_subperiod_count=6,
        min_train_subperiod_calmar=0.75,
        min_validation_subperiod_calmar=0.75,
        min_train_cagr=0.06,
        min_validation_cagr=0.06,
        max_train_mdd=0.30,
        max_validation_mdd=0.30,
        min_train_annual_return=0.0,
        min_validation_annual_return=0.0,
        min_train_annual_calmar=0.0,
        min_validation_annual_calmar=0.0,
        max_train_validation_calmar_ratio=3.0,
        min_validation_excess_pvalue=0.05,
        min_validation_bootstrap_calmar_p05=0.50,
        min_validation_bootstrap_excess_calmar_p05=0.0,
        max_validation_random_baseline_pvalue=0.05,
        min_validation_deflated_sharpe=0.95,
        max_validation_pbo=0.20,
        min_feature_ablation_validation_calmar=0.75,
        min_validation_regime_calmar=0.0,
        max_validation_trade_concentration=0.40,
        statistical_bootstrap_paths=300,
        statistical_bootstrap_block=21,
        statistical_random_shuffles=300,
        statistical_pbo_splits=8,
        min_trades_per_year=12.0,
        max_trades_per_year=80.0,
        min_long_fraction=0.25,
        max_long_fraction=0.75,
        max_features_per_candidate=profile.max_features,
        reject_same_feature_family=True,
        adaptive_family_search=profile.adaptive,
        adaptive_quick_screen_candidates=profile.quick_screen,
        adaptive_family_min_weight=0.60,
        adaptive_family_reward=6.0,
        penalized_feature_pools=profile.penalized_pools,
        penalized_feature_pool_factor=profile.penalty_factor,
        defer_robustness_until_basic_pass=False,
        effective_dsr_trials=50_000,
        time_limit_seconds=(
            float(config.minutes_per_route) * 60.0
            if time_limit_seconds is None
            else float(time_limit_seconds)
        ),
        literature_ideas=literature_ideas,
    )


def _prepare_literature_route(
    config: SP500RouteTournamentConfig,
    route_dir: Path,
    progress_path: Path,
) -> tuple[dict[str, Any], ...]:
    literature_dir = route_dir / "estudios_literature"
    literature_dir.mkdir(parents=True, exist_ok=True)
    _append_jsonl(
        progress_path,
        {
            "event": "estudios_discovery_started",
            "route": "paper_literature_replicator",
            "output_dir": str(literature_dir),
            "use_ai": config.literature_use_ai,
            "literature_enabled": config.literature_enabled,
            "literature_role": "train_feature_prior",
            "validation_role": "report_only",
            "locked_opened": False,
            "created_at_utc": _now(),
        },
    )
    if not config.literature_enabled:
        summary = {
            "studies_seen": 0,
            "ideas_count": 0,
            "extra_ai_ideas_count": 0,
            "paper_artifacts_count": 0,
            "errors": [],
            "literature_enabled": False,
            "literature_role": "disabled",
            "validation_role": "report_only",
            "locked_opened": False,
        }
        _write_json(literature_dir / "literature_summary.json", summary)
        _write_json(literature_dir / "literature_report.json", summary | {"ideas": []})
        _append_jsonl(
            progress_path,
            {
                "event": "estudios_discovery_skipped",
                "route": "paper_literature_replicator",
                **summary,
                "created_at_utc": _now(),
            },
        )
        return tuple()
    try:
        report = discover_literature_strategy_ideas(
            max_queries=config.literature_max_queries,
            per_query=config.literature_per_query,
            output_dir=literature_dir,
            enrich_papers=True,
            download_pdfs=True,
            summarize_papers=True,
            max_papers_to_enrich=config.literature_max_papers_to_enrich,
            use_ai=config.literature_use_ai,
        )
    except Exception as exc:
        error_payload = {
            "queries": [],
            "studies_seen": 0,
            "ideas": [],
            "paper_artifacts": [],
            "errors": [str(exc)],
            "literature_enabled": True,
            "literature_role": "train_feature_prior",
            "validation_role": "report_only",
            "locked_opened": False,
        }
        _write_json(literature_dir / "literature_report.json", error_payload)
        _append_jsonl(
            progress_path,
            {
                "event": "estudios_discovery_failed",
                "route": "paper_literature_replicator",
                "error": str(exc),
                "locked_opened": False,
                "created_at_utc": _now(),
            },
        )
        return tuple()

    payload = report.to_dict()
    extra_ideas = _load_extra_literature_ideas(config.literature_extra_ideas_path)
    if extra_ideas:
        payload["ideas"] = [*payload.get("ideas", []), *extra_ideas]
    _write_json(literature_dir / "literature_report.json", payload)
    for idea in payload.get("ideas", []):
        if isinstance(idea, dict):
            _append_jsonl(literature_dir / "literature_ideas.jsonl", idea)
    for artifact in report.paper_artifacts:
        _append_jsonl(literature_dir / "literature_papers.jsonl", artifact.to_dict())
    summary = {
        "studies_seen": report.studies_seen,
        "ideas_count": len(payload.get("ideas", [])),
        "extra_ai_ideas_count": len(extra_ideas),
        "paper_artifacts_count": len(report.paper_artifacts),
        "errors": list(report.errors),
        "estudios_available": report.estudios_available,
        "estudios_root": report.estudios_root,
        "availability_reason": report.availability_reason,
        "literature_enabled": True,
        "literature_role": "train_feature_prior",
        "selection_role": "train_feature_prior_only",
        "validation_role": "report_only",
        "locked_opened": False,
    }
    _write_json(literature_dir / "literature_summary.json", summary)
    _append_jsonl(
        progress_path,
        {
            "event": "estudios_discovery_completed",
            "route": "paper_literature_replicator",
            **summary,
            "created_at_utc": _now(),
        },
    )
    return tuple(idea for idea in payload.get("ideas", []) if isinstance(idea, dict))


def _load_extra_literature_ideas(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"literature extra ideas path not found: {source}")
    raw = source.read_text(encoding="utf-8-sig")
    ideas: list[dict[str, Any]] = []
    if source.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        payload = json.loads(raw)
        rows = payload.get("ideas", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("literature extra ideas must be a JSON list or JSONL file")
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = json.dumps(row, ensure_ascii=False).lower()
        if "locked" not in " ".join(str(item).lower() for item in row.get("forbidden", ())):
            raise ValueError("extra literature idea must explicitly forbid locked data")
        if any(token in text for token in ("future data as input", "lookahead", "live trading")):
            raise ValueError("extra literature idea contains unsafe text")
        ideas.append(row)
    return ideas


def _route_result(profile: RouteProfile, report: MLSearchReport) -> RouteTournamentResult:
    best = _best_report_candidate(report)
    score, passes = _robust_score(best)
    best_payload = None
    if best is not None:
        best_payload = best.to_dict()
        best_payload["tournament_route"] = profile.slug
        best_payload["tournament_label"] = profile.label
    return RouteTournamentResult(
        route=profile.slug,
        label=profile.label,
        status=report.status,
        output_dir=report.output_dir,
        candidates_evaluated=report.candidates_evaluated,
        batches_completed=report.batches_completed,
        locked_opened=report.locked_opened,
        best_candidate=best_payload,
        robust_score=score,
        robustness_passes=passes,
    )


def _best_report_candidate(report: MLSearchReport) -> MLSearchCandidate | None:
    candidates: list[MLSearchCandidate] = []
    if report.best_validation is not None:
        candidates.append(report.best_validation)
    if report.best_train is not None:
        candidates.append(report.best_train)
    candidates.extend(report.objective_candidates)
    candidates.extend(report.top)
    scored = [(candidate, _robust_score(candidate)[0]) for candidate in candidates]
    if not scored:
        return None
    return sorted(scored, key=lambda item: item[1], reverse=True)[0][0]


def _robust_score(candidate: MLSearchCandidate | None) -> tuple[float, int]:
    if candidate is None:
        return -math.inf, 0
    valid = candidate.validation_metrics
    train = candidate.train_metrics
    robustness = dict(candidate.robustness or {})
    checks = (
        ("validation_calmar", valid is not None and valid.calmar >= 1.25),
        ("validation_cagr", valid is not None and valid.cagr >= 0.06),
        ("validation_mdd", valid is not None and valid.mdd >= -0.30),
        ("trades", valid is not None and 12.0 <= valid.trades_per_year <= 80.0),
        ("long_fraction", valid is not None and 0.25 <= valid.long_fraction <= 0.75),
        ("excess_pvalue", robustness.get("excess_pvalue", 1.0) <= 0.05),
        ("bootstrap_calmar", robustness.get("bootstrap_calmar_p05", -math.inf) >= 0.50),
        ("bootstrap_excess", robustness.get("bootstrap_excess_calmar_p05", -math.inf) >= 0.0),
        ("random_baseline", robustness.get("random_baseline_pvalue", 1.0) <= 0.05),
        ("deflated_sharpe", robustness.get("deflated_sharpe", -math.inf) >= 0.95),
        ("pbo", robustness.get("pbo", 1.0) <= 0.20),
        ("ablation", robustness.get("feature_ablation_validation_calmar", -math.inf) >= 0.75),
        ("regime", robustness.get("regime_min_calmar", -math.inf) >= 0.0),
        ("trade_concentration", robustness.get("trade_concentration_top5", 1.0) <= 0.40),
    )
    passed = sum(1 for _, ok in checks if bool(ok))
    valid_calmar = valid.calmar if valid is not None else -10.0
    bootstrap = float(robustness.get("bootstrap_calmar_p05", 0.0))
    pbo = float(robustness.get("pbo", 1.0))
    concentration = float(robustness.get("trade_concentration_top5", 1.0))
    complexity = len(candidate.feature_set)
    score = (
        passed * 1000.0
        + valid_calmar * 100.0
        + bootstrap * 10.0
        - pbo * 10.0
        - concentration * 5.0
        - complexity
        + min(train.calmar, 10.0)
    )
    return float(score), passed


def _status_payload(
    config: SP500RouteTournamentConfig,
    output_dir: Path,
    status: str,
    results: list[RouteTournamentResult],
) -> dict[str, Any]:
    return {
        "status": status,
        "run_id": config.run_id,
        "symbol": config.symbol,
        "locked_opened": False,
        "feature_mode": config.feature_mode,
        "workers": config.workers,
        "minutes_per_route": config.minutes_per_route,
        "routes_total": len(config.routes or ROUTE_ORDER),
        "routes_completed": len(results),
        "route_order": list(config.routes or ROUTE_ORDER),
        "literature_enabled": config.literature_enabled,
        "literature_role": "train_feature_prior" if config.literature_enabled else "disabled",
        "validation_role": "report_only",
        "route_results": [result.to_dict() for result in results],
        "output_dir": str(output_dir),
        "updated_at_utc": _now(),
    }


def _leaderboard_markdown(
    config: SP500RouteTournamentConfig,
    leaderboard: tuple[RouteTournamentResult, ...],
) -> str:
    lines = [
        "# SP500 Route Tournament",
        "",
        f"Run ID: `{config.run_id}`",
        "Locked opened: `False`",
        "",
        "| Rank | Route | Status | Score | Robust passes | Candidate | Valid Calmar | Train Calmar |",
        "|---:|---|---|---:|---:|---|---:|---:|",
    ]
    for rank, result in enumerate(leaderboard, start=1):
        candidate = result.best_candidate or {}
        valid = candidate.get("validation_metrics") or {}
        train = candidate.get("train_metrics") or {}
        lines.append(
            f"| {rank} | {result.label} | {result.status} | {result.robust_score:.2f} | "
            f"{result.robustness_passes} | {candidate.get('candidate_id', '')} | "
            f"{_fmt(valid.get('calmar'))} | {_fmt(train.get('calmar'))} |"
        )
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.3f}"
    except Exception:
        return str(value)


def _output_dir(config: SP500RouteTournamentConfig) -> Path:
    root = Path(config.run_root) if config.run_root else base_data_dir() / "agent_loop"
    return root / config.run_id


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ROUTE_ORDER",
    "ROUTE_PROFILES",
    "RouteTournamentResult",
    "SP500RouteTournamentConfig",
    "SP500RouteTournamentReport",
    "run_sp500_route_tournament",
]
