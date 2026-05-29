"""Controlled connector builder for autonomous research loops.

This is intentionally not free-form code generation. The loop may only build
connectors that Aurora explicitly knows how to validate. Unknown sources are
recorded as blocked routes and the agent keeps looking elsewhere.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from aurora.research.agent_loop.state import AgentRunState, append_jsonl


_DEFERRED_SOURCE_REASONS = {
    "cboe_market_statistics": (
        "manual_terms_and_history_review_required"
    ),
    "bea_api": "api_key_required",
    "aaii_sentiment": "manual_terms_review_required",
}


@dataclass(frozen=True)
class ConnectorBuildResult:
    source_id: str
    ok: bool
    status: str
    rows: int = 0
    provider_name: str = ""
    library: str = ""
    reason: str = ""
    next_action: str = "RUN_AUTOSEARCH"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AgentConnectorBuilder:
    """Build and validate one supported source connector."""

    def build(
        self,
        *,
        action: dict[str, object],
        state: AgentRunState,
    ) -> ConnectorBuildResult:
        source_id = _source_id_from_action(action)
        if source_id == "cftc_cot":
            return self._build_cftc_cot(state=state)
        if source_id == "kenneth_french":
            return self._build_kenneth_french(state=state)
        if source_id == "federal_reserve_h15":
            return self._build_federal_reserve_h15(state=state)
        if source_id == "bls_public_api":
            return self._build_bls_public_api(state=state)
        if source_id == "yale_shiller":
            return self._build_yale_shiller(state=state)
        if source_id in _DEFERRED_SOURCE_REASONS:
            result = ConnectorBuildResult(
                source_id=source_id,
                ok=False,
                status="deferred",
                reason=_DEFERRED_SOURCE_REASONS[source_id],
                next_action="ASK_CODEX_FOR_CONNECTOR_PLAN",
            )
            self._record(state=state, result=result)
            return result
        result = ConnectorBuildResult(
            source_id=source_id or "unknown",
            ok=False,
            status="unsupported_source",
            reason="No controlled builder exists for this source yet.",
            next_action="ASK_CODEX_FOR_CONNECTOR_PLAN",
        )
        self._record(state=state, result=result)
        return result

    def _build_yale_shiller(self, *, state: AgentRunState) -> ConnectorBuildResult:
        from aurora.core.data_providers.yale_shiller import (
            YaleShillerProvider,
            sample_shiller_csv,
        )

        provider = YaleShillerProvider(client=lambda params: sample_shiller_csv())
        df, lineage = provider.fetch_monthly()
        if df.empty:
            result = ConnectorBuildResult(
                source_id="yale_shiller",
                ok=False,
                status="validated_empty",
                provider_name=provider.name,
                reason="Fixture validation returned no rows.",
            )
        else:
            result = ConnectorBuildResult(
                source_id="yale_shiller",
                ok=True,
                status="validated",
                rows=int(len(df)),
                provider_name=provider.name,
                library=str(lineage.extra.get("library", "valuation_monthly")),
            )
            if "yale_shiller" not in state.built_sources:
                state.built_sources.append("yale_shiller")
        self._record(state=state, result=result)
        return result

    def _build_bls_public_api(self, *, state: AgentRunState) -> ConnectorBuildResult:
        from aurora.core.data_providers.bls_public_api import (
            BLSPublicAPIProvider,
            sample_bls_json,
        )

        provider = BLSPublicAPIProvider(client=lambda params: sample_bls_json())
        df, lineage = provider.fetch_series("CPIAUCSL")
        if df.empty:
            result = ConnectorBuildResult(
                source_id="bls_public_api",
                ok=False,
                status="validated_empty",
                provider_name=provider.name,
                reason="Fixture validation returned no rows.",
            )
        else:
            result = ConnectorBuildResult(
                source_id="bls_public_api",
                ok=True,
                status="validated",
                rows=int(len(df)),
                provider_name=provider.name,
                library=str(lineage.extra.get("library", "macro_monthly")),
            )
            if "bls_public_api" not in state.built_sources:
                state.built_sources.append("bls_public_api")
        self._record(state=state, result=result)
        return result

    def _build_federal_reserve_h15(
        self,
        *,
        state: AgentRunState,
    ) -> ConnectorBuildResult:
        from aurora.core.data_providers.federal_reserve_h15 import (
            FederalReserveH15Provider,
            sample_h15_csv,
        )

        provider = FederalReserveH15Provider(client=lambda params: sample_h15_csv())
        df, lineage = provider.fetch_series("DGS10")
        if df.empty:
            result = ConnectorBuildResult(
                source_id="federal_reserve_h15",
                ok=False,
                status="validated_empty",
                provider_name=provider.name,
                reason="Fixture validation returned no rows.",
            )
        else:
            result = ConnectorBuildResult(
                source_id="federal_reserve_h15",
                ok=True,
                status="validated",
                rows=int(len(df)),
                provider_name=provider.name,
                library=str(lineage.extra.get("library", "rates_daily")),
            )
            if "federal_reserve_h15" not in state.built_sources:
                state.built_sources.append("federal_reserve_h15")
        self._record(state=state, result=result)
        return result

    def _build_kenneth_french(self, *, state: AgentRunState) -> ConnectorBuildResult:
        from aurora.core.data_providers.kenneth_french_factors import (
            KennethFrenchFactorsProvider,
            sample_french_factor_csv,
        )

        provider = KennethFrenchFactorsProvider(
            client=lambda params: sample_french_factor_csv(),
        )
        df, lineage = provider.fetch_factors()
        if df.empty:
            result = ConnectorBuildResult(
                source_id="kenneth_french",
                ok=False,
                status="validated_empty",
                provider_name=provider.name,
                reason="Fixture validation returned no rows.",
            )
        else:
            result = ConnectorBuildResult(
                source_id="kenneth_french",
                ok=True,
                status="validated",
                rows=int(len(df)),
                provider_name=provider.name,
                library=str(lineage.extra.get("library", "factors_daily")),
            )
            if "kenneth_french" not in state.built_sources:
                state.built_sources.append("kenneth_french")
        self._record(state=state, result=result)
        return result

    def _build_cftc_cot(self, *, state: AgentRunState) -> ConnectorBuildResult:
        from aurora.core.data_providers.cftc_cot_weekly import (
            CFTCCOTWeeklyProvider,
            sample_cot_csv,
        )

        provider = CFTCCOTWeeklyProvider(client=lambda params: sample_cot_csv())
        df, lineage = provider.fetch_report(market_filter="S&P 500")
        if df.empty:
            result = ConnectorBuildResult(
                source_id="cftc_cot",
                ok=False,
                status="validated_empty",
                provider_name=provider.name,
                reason="Fixture validation returned no rows.",
            )
        else:
            result = ConnectorBuildResult(
                source_id="cftc_cot",
                ok=True,
                status="validated",
                rows=int(len(df)),
                provider_name=provider.name,
                library=str(lineage.extra.get("library", "positioning_weekly")),
            )
            if "cftc_cot" not in state.built_sources:
                state.built_sources.append("cftc_cot")
        self._record(state=state, result=result)
        return result

    @staticmethod
    def _record(*, state: AgentRunState, result: ConnectorBuildResult) -> None:
        payload = result.to_dict()
        append_jsonl(state.run_dir / "connector_builds.jsonl", payload)
        append_jsonl(state.run_dir / "source_registry.jsonl", payload)
        if not result.ok:
            append_jsonl(state.run_dir / "connector_plan_required.jsonl", {
                "source_id": result.source_id,
                "status": result.status,
                "reason": result.reason,
                "safe_next_step": "ASK_CODEX_FOR_CONNECTOR_PLAN",
                "rules": [
                    "plan only in isolated worktree",
                    "prove legal access and point-in-time semantics first",
                    "add parser fixture tests before live fetch",
                    "do not use locked data for validation",
                ],
            })


def _source_id_from_action(action: dict[str, object]) -> str:
    source = action.get("source")
    if isinstance(source, dict):
        return str(source.get("source_id", "")).strip()
    source_id = action.get("source_id")
    if source_id is not None:
        return str(source_id).strip()
    return ""


__all__ = [
    "AgentConnectorBuilder",
    "ConnectorBuildResult",
]
