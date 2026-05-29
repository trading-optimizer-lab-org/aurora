"""Action executor for Aurora autonomous research loops."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aurora.research.agent_loop.actions import AgentActionType, AgentStatus
from aurora.research.agent_loop.connector_builder import AgentConnectorBuilder
from aurora.research.agent_loop.estudios_bridge import discover_literature_strategy_ideas
from aurora.research.agent_loop.goal import AgentGoalSpec
from aurora.research.agent_loop.ideas import (
    blocked_features,
    build_unique_feature_pack,
    blocked_rule_signatures,
    ideas_from_action,
    ensure_fresh_round_feature_packs,
    next_unbuilt_idea,
    queue_ideas,
    record_feature_pack,
    repeated_best_features,
)
from aurora.research.agent_loop.state import AgentRunState, append_jsonl
from aurora.research.source_discovery import SourceDiscoveryConfig, discover_sources
from aurora.research.sp500_autosearch import AutosearchConfig, run_sp500_autosearch


class AgentActionExecutor:
    """Execute validated actions with existing Aurora tools."""

    def __init__(
        self,
        *,
        candidates_per_round: int = 50_000,
        max_search_hours: float = 2.0,
        rounds_per_batch: int = 3,
        cpu_workers: int = 3,
        round_workers: int = 1,
        connector_builder: AgentConnectorBuilder | None = None,
    ):
        self.candidates_per_round = int(candidates_per_round)
        self.max_search_hours = float(max_search_hours)
        self.rounds_per_batch = max(1, int(rounds_per_batch))
        self.cpu_workers = max(1, int(cpu_workers))
        self.round_workers = max(1, int(round_workers))
        self.connector_builder = connector_builder or AgentConnectorBuilder()

    def execute(
        self,
        *,
        action: dict[str, object],
        goal: AgentGoalSpec,
        state: AgentRunState,
    ) -> dict[str, Any]:
        action_type = str(action["action"])
        if action_type == AgentActionType.RUN_AUTOSEARCH.value:
            return self._run_autosearch(goal=goal, state=state)
        if action_type == AgentActionType.DISCOVER_SOURCES.value:
            return self._discover_sources(state=state)
        if action_type == AgentActionType.DISCOVER_STRATEGY_IDEAS.value:
            return self._discover_strategy_ideas(state=state)
        if action_type == AgentActionType.BUILD_SOURCE_CONNECTOR.value:
            return self._build_source_connector(action=action, state=state)
        if action_type == AgentActionType.GENERATE_FEATURE_SET.value:
            return self._generate_feature_set(state=state)
        if action_type == AgentActionType.RUN_KRONOS_SEARCH.value:
            return self._run_kronos_search(action=action, goal=goal, state=state)
        if action_type in {
            AgentActionType.ASK_CODEX_FOR_IDEAS.value,
            AgentActionType.ASK_CODEX_FOR_FAILURE_REVIEW.value,
            AgentActionType.ASK_CODEX_FOR_CONNECTOR_PLAN.value,
        }:
            return self._record_codex_guidance(action=action, state=state)
        return self._record_blocked(action=action, state=state, reason="not_implemented")

    def _run_autosearch(self, *, goal: AgentGoalSpec, state: AgentRunState) -> dict[str, Any]:
        state.status = AgentStatus.SEARCHING_STRATEGY.value
        generated_packs = ensure_fresh_round_feature_packs(
            state,
            count=self.rounds_per_batch,
        )
        if generated_packs:
            append_jsonl(state.run_dir / "decisions.jsonl", {
                "event": "fresh_features_for_round",
                "research_round": state.research_rounds + 1,
                "rounds_per_batch": self.rounds_per_batch,
                "feature_packs": [pack.to_dict() for pack in generated_packs],
            })
        new_blocks = repeated_best_features(state)
        if new_blocks:
            append_jsonl(state.run_dir / "decisions.jsonl", {
                "event": "repetition_gate",
                "blocked_features": new_blocks,
            })
        if self.round_workers > 1 and self.rounds_per_batch > 1:
            payload = self._run_parallel_autosearch_batch(goal=goal, state=state)
            passed = bool(_best_value(payload, "passed"))
        else:
            report = run_sp500_autosearch(AutosearchConfig(
                target_calmar=goal.target_value,
                symbol=goal.instrument,
                max_rounds=self.rounds_per_batch,
                max_candidates_per_round=self.candidates_per_round,
                max_hours=self.max_search_hours,
                cpu_workers=self.cpu_workers,
                open_locked_final=False,
                output_dir=str(state.run_dir / "autosearch"),
                round_offset=state.research_rounds,
                feature_packs_path=str(state.run_dir / "feature_packs.jsonl"),
                blocked_features=blocked_features(state.run_dir),
                blocked_rule_signatures=blocked_rule_signatures(state.run_dir),
            ))
            payload = report.to_dict()
            passed = bool(getattr(getattr(report, "best", None), "passed", False))
        if payload.get("locked_opened"):
            self._record_blocked(
                action={"action": AgentActionType.RUN_AUTOSEARCH.value},
                state=state,
                reason="autosearch_reported_locked_opened",
            )
            return {"ok": False, "result": payload}
        score = _extract_score(payload)
        rounds_completed = int(payload.get("rounds_completed", 1) or 1)
        rounds_done = max(1, rounds_completed)
        state.research_rounds += rounds_done
        if score is not None and (
            state.best_score is None or score > state.best_score
        ):
            state.best_score = score
            state.rounds_without_improvement = 0
        else:
            state.rounds_without_improvement += rounds_done
        append_jsonl(state.run_dir / "trials.jsonl", {
            "action": AgentActionType.RUN_AUTOSEARCH.value,
            "score": score,
            "best_score": state.best_score,
            "rounds_without_improvement": state.rounds_without_improvement,
            "rounds_in_batch": rounds_done,
            "cpu_workers": self.cpu_workers,
            "round_workers": self.round_workers,
            "result": payload,
        })
        if passed:
            state.objective_met = True
            state.status = AgentStatus.OBJECTIVE_MET.value
        else:
            state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
            state.blocked_routes.append("autosearch_no_candidate")
        return {"ok": True, "objective_met": passed, "result": payload}

    def _run_kronos_search(
        self,
        *,
        action: dict[str, object],
        goal: AgentGoalSpec,
        state: AgentRunState,
    ) -> dict[str, Any]:
        state.status = AgentStatus.SEARCHING_STRATEGY.value
        from aurora.research.kronos_tool import KronosToolConfig, run_kronos_search

        validation_target = action.get("validation_target_calmar")
        if validation_target is None:
            validation_target = goal.target_value
        report = run_kronos_search(
            KronosToolConfig(
                run_id=state.run_id,
                symbol=str(action.get("symbol", goal.instrument)),
                model=str(action.get("model", "Kronos-mini")),
                target_calmar=float(action.get("target_calmar", goal.target_value)),
                validation_target_calmar=float(validation_target),
                train_only=True,
                no_costs=True,
                run_root=str(state.run_dir.parent),
                allow_volume=bool(action.get("allow_volume", False)),
                forecast_step=int(action.get("forecast_step", 5)),
                max_windows=int(action.get("max_windows", 400)),
                lookback=int(action.get("lookback", 256)),
            )
        )
        payload = report.to_dict()
        if payload.get("locked_opened"):
            return self._record_blocked(
                action={"action": AgentActionType.RUN_KRONOS_SEARCH.value},
                state=state,
                reason="kronos_reported_locked_opened",
            )
        score = None
        if isinstance(payload.get("best"), dict):
            metrics = payload["best"].get("metrics")
            if isinstance(metrics, dict) and isinstance(metrics.get("calmar"), int | float):
                score = float(metrics["calmar"])
        state.research_rounds += 1
        if score is not None and (
            state.best_score is None or score > state.best_score
        ):
            state.best_score = score
            state.rounds_without_improvement = 0
        else:
            state.rounds_without_improvement += 1
        append_jsonl(state.run_dir / "trials.jsonl", {
            "action": AgentActionType.RUN_KRONOS_SEARCH.value,
            "score": score,
            "best_score": state.best_score,
            "rounds_without_improvement": state.rounds_without_improvement,
            "result": payload,
        })
        if report.objective_met:
            state.objective_met = True
            state.status = AgentStatus.OBJECTIVE_MET.value
        else:
            state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
            state.blocked_routes.append("kronos_no_candidate")
        return {"ok": True, "objective_met": report.objective_met, "result": payload}

    def _run_parallel_autosearch_batch(
        self,
        *,
        goal: AgentGoalSpec,
        state: AgentRunState,
    ) -> dict[str, Any]:
        """Run each feature-combination round as an independent child search."""

        batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        batch_dir = state.run_dir / "autosearch" / f"parallel_{batch_id}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        inner_cpu_workers = 1
        common = {
            "target_calmar": goal.target_value,
            "symbol": goal.instrument,
            "max_rounds": 1,
            "max_candidates_per_round": self.candidates_per_round,
            "max_hours": self.max_search_hours,
            "cpu_workers": inner_cpu_workers,
            "open_locked_final": False,
            "feature_packs_path": str(state.run_dir / "feature_packs.jsonl"),
            "blocked_features": tuple(blocked_features(state.run_dir)),
            "blocked_rule_signatures": tuple(blocked_rule_signatures(state.run_dir)),
        }
        configs: list[dict[str, Any]] = []
        for combo_index in range(self.rounds_per_batch):
            round_offset = state.research_rounds + combo_index
            configs.append({
                **common,
                "round_offset": round_offset,
                "output_dir": str(
                    batch_dir / f"combo_{combo_index + 1:02d}_round_{round_offset}"
                ),
                "parallel_combo_index": combo_index + 1,
            })

        append_jsonl(state.run_dir / "decisions.jsonl", {
            "event": "parallel_autosearch_batch_started",
            "batch_id": batch_id,
            "round_workers": min(self.round_workers, len(configs)),
            "combinations": len(configs),
            "inner_cpu_workers": inner_cpu_workers,
            "round_offsets": [config["round_offset"] for config in configs],
        })

        payloads: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        with ProcessPoolExecutor(max_workers=min(self.round_workers, len(configs))) as pool:
            futures = {
                pool.submit(_run_single_combo_autosearch_task, config): config
                for config in configs
            }
            for future in as_completed(list(futures)):
                config = futures[future]
                try:
                    payload = future.result()
                except Exception as exc:
                    error = {
                        "parallel_combo_index": config["parallel_combo_index"],
                        "round_offset": config["round_offset"],
                        "error": str(exc),
                    }
                    errors.append(error)
                    append_jsonl(batch_dir / "parallel_results.jsonl", error)
                    continue
                payload["parallel_combo_index"] = config["parallel_combo_index"]
                payload["round_offset"] = config["round_offset"]
                payloads.append(payload)
                append_jsonl(batch_dir / "parallel_results.jsonl", payload)

        if not payloads:
            raise RuntimeError(f"all parallel autosearch combinations failed: {errors}")

        best_payload = _best_payload(payloads)
        aggregated = dict(best_payload)
        aggregated["project_id"] = f"parallel_{batch_id}"
        aggregated["run_dir"] = str(batch_dir)
        aggregated["rounds_completed"] = sum(
            int(payload.get("rounds_completed", 1) or 1) for payload in payloads
        )
        aggregated["candidates_evaluated"] = sum(
            int(payload.get("candidates_evaluated", 0) or 0) for payload in payloads
        )
        aggregated["validation_examined"] = sum(
            int(payload.get("validation_examined", 0) or 0) for payload in payloads
        )
        aggregated["locked_opened"] = any(bool(payload.get("locked_opened")) for payload in payloads)
        aggregated["stopped_reason"] = (
            "target_passed_validation"
            if any(bool(_best_value(payload, "passed")) for payload in payloads)
            else "parallel_batch_exhausted"
        )
        aggregated["attempts_path"] = str(batch_dir / "parallel_results.jsonl")
        aggregated["ledger_path"] = str(batch_dir / "parallel_results.jsonl")
        aggregated["parallel_combinations"] = {
            "enabled": True,
            "round_workers": min(self.round_workers, len(configs)),
            "inner_cpu_workers": inner_cpu_workers,
            "requested_combinations": len(configs),
            "completed_combinations": len(payloads),
            "failed_combinations": errors,
            "round_offsets": [config["round_offset"] for config in configs],
            "children": [
                {
                    "parallel_combo_index": payload.get("parallel_combo_index"),
                    "round_offset": payload.get("round_offset"),
                    "score": _extract_score(payload),
                    "passed": bool(_best_value(payload, "passed")),
                    "candidates_evaluated": payload.get("candidates_evaluated"),
                    "run_dir": payload.get("run_dir"),
                }
                for payload in sorted(
                    payloads,
                    key=lambda item: int(item.get("parallel_combo_index", 0) or 0),
                )
            ],
        }
        return aggregated

    def _discover_sources(self, *, state: AgentRunState) -> dict[str, Any]:
        state.status = AgentStatus.DISCOVERING_SOURCES.value
        report = discover_sources(SourceDiscoveryConfig(
            free_only=True,
            useful_for_sp500_only=True,
            include_integrated=False,
            output_dir=str(state.run_dir / "source_discovery"),
        ))
        recommendations = []
        if report is not None:
            unavailable = set(state.built_sources) | set(state.blocked_sources)
            recommendations = [
                item for item in report.recommended_new_sources
                if item.source_id not in unavailable
            ]
        if report is None or not recommendations:
            reason = (
                "no_recommendations"
                if report is None
                else "all_recommended_sources_already_handled"
            )
            state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
            state.blocked_routes.append("source_discovery_empty")
            append_jsonl(state.run_dir / "blocked_routes.jsonl", {
                "route": "source_discovery",
                "reason": reason,
            })
            return {"ok": False, "reason": reason}
        source = recommendations[0]
        state.status = AgentStatus.BUILDING_CONNECTOR.value
        task = {
            "action": AgentActionType.BUILD_SOURCE_CONNECTOR.value,
            "source": source.to_dict(),
            "status": "queued",
        }
        append_jsonl(state.run_dir / "source_tasks.jsonl", task)
        append_jsonl(state.run_dir / "action_queue.jsonl", task)
        return {
            "ok": True,
            "result": report.to_dict(),
            "next_action": task,
        }

    def _discover_strategy_ideas(self, *, state: AgentRunState) -> dict[str, Any]:
        state.status = AgentStatus.DISCOVERING_SOURCES.value
        report = discover_literature_strategy_ideas(
            query_offset=state.research_rounds + len(state.blocked_routes),
            max_queries=4,
            per_query=8,
            output_dir=state.run_dir / "estudios_literature",
            enrich_papers=True,
            download_pdfs=True,
            summarize_papers=True,
            max_papers_to_enrich=8,
        )
        for idea in report.ideas:
            append_jsonl(state.run_dir / "literature_ideas.jsonl", idea.to_dict())
        for artifact in report.paper_artifacts:
            append_jsonl(state.run_dir / "literature_papers.jsonl", artifact.to_dict())
        queued = [idea.to_dict() for idea in queue_ideas(state, report.ideas)]
        append_jsonl(state.run_dir / "decisions.jsonl", {
            "event": "estudios_strategy_ideas",
            "report": report.to_dict(),
            "queued_ideas": queued,
        })
        if queued:
            return {
                "ok": True,
                "result": report.to_dict(),
                "queued_ideas": queued,
                "next_action": {"action": AgentActionType.GENERATE_FEATURE_SET.value},
            }
        state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
        append_jsonl(state.run_dir / "blocked_routes.jsonl", {
            "route": AgentActionType.DISCOVER_STRATEGY_IDEAS.value,
            "reason": "no_new_literature_ideas",
            "errors": report.errors,
        })
        return {
            "ok": False,
            "result": report.to_dict(),
            "reason": "no_new_literature_ideas",
            "next_action": {"action": AgentActionType.ASK_CODEX_FOR_IDEAS.value},
        }

    def _build_source_connector(
        self,
        *,
        action: dict[str, object],
        state: AgentRunState,
    ) -> dict[str, Any]:
        state.status = AgentStatus.BUILDING_CONNECTOR.value
        result = self.connector_builder.build(action=action, state=state)
        if result.ok:
            state.status = AgentStatus.VALIDATING_DATA.value
            append_jsonl(state.run_dir / "source_tasks.jsonl", {
                "action": AgentActionType.BUILD_SOURCE_CONNECTOR.value,
                "request": action,
                "status": result.status,
                "source_id": result.source_id,
                "rows": result.rows,
            })
            return {"ok": True, "result": result.to_dict()}
        state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
        state.blocked_routes.append(f"source:{result.source_id}")
        if result.source_id not in state.blocked_sources:
            state.blocked_sources.append(result.source_id)
        append_jsonl(state.run_dir / "blocked_routes.jsonl", {
            "route": f"source:{result.source_id}",
            "reason": result.reason or result.status,
        })
        return {
            "ok": False,
            "result": result.to_dict(),
            "next_action": {
                "action": result.next_action,
                "source_id": result.source_id,
                "reason": result.reason or result.status,
            },
        }

    def _record_blocked(
        self,
        *,
        action: dict[str, object],
        state: AgentRunState,
        reason: str,
    ) -> dict[str, Any]:
        state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
        route = str(action.get("action", "unknown"))
        state.blocked_routes.append(route)
        append_jsonl(state.run_dir / "blocked_routes.jsonl", {
            "route": route,
            "reason": reason,
        })
        return {"ok": False, "reason": reason}

    def _record_codex_guidance(
        self,
        *,
        action: dict[str, object],
        state: AgentRunState,
    ) -> dict[str, Any]:
        state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
        queued: list[dict[str, object]] = []
        if action["action"] == AgentActionType.ASK_CODEX_FOR_IDEAS.value or (
            action["action"] == AgentActionType.ASK_CODEX_FOR_FAILURE_REVIEW.value
            and state.rounds_without_improvement >= 2
        ):
            ideas = ideas_from_action(action, state)
            queued = [idea.to_dict() for idea in queue_ideas(state, ideas)]
        append_jsonl(state.run_dir / "decisions.jsonl", {
            "event": "codex_guidance",
            "action": action,
            "queued_ideas": queued,
        })
        if queued:
            next_action = {"action": AgentActionType.GENERATE_FEATURE_SET.value}
        elif action["action"] == AgentActionType.ASK_CODEX_FOR_CONNECTOR_PLAN.value:
            next_action = {"action": AgentActionType.DISCOVER_SOURCES.value}
        else:
            next_action = {"action": AgentActionType.RUN_AUTOSEARCH.value}
        return {
            "ok": True,
            "guidance_recorded": True,
            "queued_ideas": queued,
            "next_action": next_action,
        }

    def _generate_feature_set(self, *, state: AgentRunState) -> dict[str, Any]:
        state.status = AgentStatus.GENERATING_FEATURES.value
        idea = next_unbuilt_idea(state)
        if idea is None:
            state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
            append_jsonl(state.run_dir / "blocked_routes.jsonl", {
                "route": AgentActionType.GENERATE_FEATURE_SET.value,
                "reason": "no_unbuilt_ideas",
            })
            return {
                "ok": False,
                "reason": "no_unbuilt_ideas",
                "next_action": {"action": AgentActionType.RUN_AUTOSEARCH.value},
            }
        pack = build_unique_feature_pack(idea, state)
        if pack is None:
            state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
            append_jsonl(state.run_dir / "blocked_routes.jsonl", {
                "route": AgentActionType.GENERATE_FEATURE_SET.value,
                "reason": "all_structural_feature_pack_recipes_exhausted",
            })
            return {
                "ok": False,
                "reason": "all_structural_feature_pack_recipes_exhausted",
                "next_action": {"action": AgentActionType.RUN_AUTOSEARCH.value},
            }
        record_feature_pack(state, pack)
        append_jsonl(state.run_dir / "decisions.jsonl", {
            "event": "feature_pack_generated",
            "idea": idea.to_dict(),
            "feature_pack": pack.to_dict(),
        })
        state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
        return {
            "ok": True,
            "idea": idea.to_dict(),
            "feature_pack": pack.to_dict(),
            "next_action": {"action": AgentActionType.RUN_AUTOSEARCH.value},
        }


__all__ = ["AgentActionExecutor"]


def _run_single_combo_autosearch_task(config: dict[str, Any]) -> dict[str, Any]:
    """Process entry point for one feature-combination search."""

    report = run_sp500_autosearch(AutosearchConfig(
        target_calmar=float(config["target_calmar"]),
        symbol=str(config["symbol"]),
        max_rounds=int(config["max_rounds"]),
        max_candidates_per_round=int(config["max_candidates_per_round"]),
        max_hours=float(config["max_hours"]),
        cpu_workers=int(config["cpu_workers"]),
        open_locked_final=bool(config["open_locked_final"]),
        output_dir=str(config["output_dir"]),
        round_offset=int(config["round_offset"]),
        feature_packs_path=str(config["feature_packs_path"]),
        blocked_features=tuple(config.get("blocked_features", ())),
        blocked_rule_signatures=tuple(config.get("blocked_rule_signatures", ())),
    ))
    return report.to_dict()


def _best_payload(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        payloads,
        key=lambda payload: (
            _extract_score(payload) if _extract_score(payload) is not None else float("-inf")
        ),
    )


def _best_value(payload: dict[str, Any], key: str) -> object | None:
    best = payload.get("best")
    if isinstance(best, dict):
        return best.get(key)
    return None


def _extract_score(payload: dict[str, Any]) -> float | None:
    best = payload.get("best")
    if isinstance(best, dict):
        for key in ("robust_train_score", "train_calmar"):
            value = best.get(key)
            if isinstance(value, int | float):
                return float(value)
        train = best.get("train")
        if isinstance(train, dict):
            metrics = train.get("metrics")
            if isinstance(metrics, dict):
                calmar = metrics.get("calmar")
                if isinstance(calmar, int | float):
                    return float(calmar)
    value = payload.get("robust_train_score")
    if isinstance(value, int | float):
        return float(value)
    return None
