"""Structured strategy ideas and safe feature-pack generation."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha1
from pathlib import Path
from typing import Any, Iterable

from aurora.research.agent_loop.state import AgentRunState, append_jsonl


_FORBIDDEN_TEXT = ("locked", "future", "lookahead", "live trading", "leverage")
_FAMILIES = (
    "drawdown_volatility",
    "trend_stress_combo",
    "defensive_ratio_blend",
    "yield_curve_macro",
    "vix_term_structure",
    "breadth_proxy_regime",
    "sector_rotation_momentum",
    "crash_asymmetry",
    "mean_reversion_stress",
)
_VARIANT_COUNT = 18
_IDEA_FEATURE_SUFFIXES = (
    "dd_vol_pressure",
    "vol_trend_pressure",
    "ret_to_vol",
    "dd_recovery",
    "vix_drawdown_pressure",
    "vix_trend_mix",
    "trend_stress_short",
    "trend_stress_medium",
    "stress_acceleration",
    "trend_quality",
    "credit_momentum_blend",
    "credit_stress_divergence",
    "defensive_blend",
    "defensive_trend",
    "defensive_shock",
    "credit_defensive_spread",
    "yield_slope_momentum",
    "yield_stress_blend",
    "real_rate_pressure",
    "vix_term_pressure",
    "vix_spike_reversal",
    "volatility_risk_premium_proxy",
    "breadth_momentum",
    "breadth_trend_quality",
    "smallcap_divergence",
    "sector_risk_on",
    "sector_defensive_rotation",
    "financials_rate_blend",
    "crash_pressure",
    "crash_recovery_quality",
    "left_tail_vol_pressure",
    "mean_reversion_stress",
    "reversion_quality",
    "oversold_stress_release",
    "generic_combo",
)


@dataclass(frozen=True)
class StrategyIdea:
    idea_id: str
    features: tuple[str, ...]
    rule_family: str
    hypothesis: str
    allowed_data: tuple[str, ...]
    forbidden: tuple[str, ...]
    source: str = "codex"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FeaturePack:
    pack_id: str
    idea_id: str
    round_name: str
    feature_family: str
    hypothesis: str
    source: str = "agent_loop"
    feature_variant: int = 0
    structure_fingerprint: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def ideas_from_action(action: dict[str, object], state: AgentRunState) -> list[StrategyIdea]:
    """Extract safe ideas from planner output, falling back to controlled templates."""

    raw = action.get("ideas")
    parsed: list[StrategyIdea] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(_idea_from_mapping(item, source="codex"))
            except ValueError as exc:
                append_jsonl(state.run_dir / "rejected_ideas.jsonl", {
                    "raw": item,
                    "reason": str(exc),
                })
    if parsed:
        return _unique_new_ideas(parsed, state)
    return [_next_template_idea(state)]


def build_feature_pack(idea: StrategyIdea) -> FeaturePack:
    """Convert a validated idea into one controlled feature-pack family."""

    family = _family_for_idea(idea)
    variant = _preferred_variants(idea.idea_id)[0]
    return _feature_pack_for(idea, family=family, variant=variant)


def build_unique_feature_pack(
    idea: StrategyIdea,
    state: AgentRunState,
    *,
    avoid_families: Iterable[str] = (),
) -> FeaturePack | None:
    """Build a pack only if its structural recipe has not already been tried."""

    preferred = _family_for_idea(idea)
    used = _used_pack_fingerprints(state.run_dir)
    blocked = set(_blocked_pack_fingerprints(state.run_dir))
    avoid = set(avoid_families)
    family_order = (
        preferred,
        *[family for family in _FAMILIES if family != preferred],
    )
    for family in family_order:
        if family in avoid and len(avoid) < len(_FAMILIES):
            continue
        for variant in _candidate_variants(idea.idea_id, family, used | blocked):
            fingerprint = _pack_fingerprint(family, variant)
            if fingerprint in used or fingerprint in blocked:
                continue
            return _feature_pack_for(idea, family=family, variant=variant)
    append_jsonl(state.run_dir / "rejected_ideas.jsonl", {
        "idea_id": idea.idea_id,
        "reason": "all_structural_feature_pack_recipes_exhausted",
    })
    return None


def _feature_pack_for(idea: StrategyIdea, *, family: str, variant: int) -> FeaturePack:
    variant = int(variant)
    return FeaturePack(
        pack_id=f"pack_{idea.idea_id}",
        idea_id=idea.idea_id,
        round_name=f"idea_{idea.idea_id}",
        feature_family=family,
        hypothesis=idea.hypothesis,
        feature_variant=variant,
        structure_fingerprint=_pack_fingerprint(family, variant),
    )


def load_queued_ideas(run_dir: Path) -> list[StrategyIdea]:
    return [
        _idea_from_mapping(item, source=str(item.get("source", "queued")))
        for item in _read_jsonl(run_dir / "idea_queue.jsonl")
        if isinstance(item, dict)
    ]


def load_feature_packs(run_dir: Path) -> list[FeaturePack]:
    out: list[FeaturePack] = []
    for item in _read_jsonl(run_dir / "feature_packs.jsonl"):
        if not isinstance(item, dict):
            continue
        out.append(FeaturePack(
            pack_id=str(item["pack_id"]),
            idea_id=str(item["idea_id"]),
            round_name=str(item["round_name"]),
            feature_family=str(item["feature_family"]),
            hypothesis=str(item.get("hypothesis", "")),
            source=str(item.get("source", "agent_loop")),
            feature_variant=int(item.get("feature_variant", 0)),
            structure_fingerprint=str(item.get("structure_fingerprint", "")),
        ))
    return out


def queue_ideas(state: AgentRunState, ideas: Iterable[StrategyIdea]) -> list[StrategyIdea]:
    queued: list[StrategyIdea] = []
    existing = _known_idea_ids(state)
    for idea in ideas:
        if idea.idea_id in existing:
            continue
        append_jsonl(state.run_dir / "idea_queue.jsonl", idea.to_dict())
        queued.append(idea)
        existing.add(idea.idea_id)
    return queued


def next_unbuilt_idea(state: AgentRunState) -> StrategyIdea | None:
    built = {pack.idea_id for pack in load_feature_packs(state.run_dir)}
    for idea in load_queued_ideas(state.run_dir):
        if idea.idea_id not in built:
            return idea
    return None


def record_feature_pack(state: AgentRunState, pack: FeaturePack) -> None:
    append_jsonl(state.run_dir / "feature_packs.jsonl", pack.to_dict())
    append_jsonl(state.run_dir / "idea_results.jsonl", {
        "idea_id": pack.idea_id,
        "status": "feature_pack_generated",
        "pack_id": pack.pack_id,
        "round_name": pack.round_name,
        "feature_family": pack.feature_family,
        "feature_variant": pack.feature_variant,
        "structure_fingerprint": pack.structure_fingerprint,
    })


def ensure_fresh_round_feature_pack(state: AgentRunState) -> list[FeaturePack]:
    """Guarantee that every autosearch round has at least one fresh feature pack."""

    return ensure_fresh_round_feature_packs(state, count=1)


def ensure_fresh_round_feature_packs(
    state: AgentRunState,
    *,
    count: int,
) -> list[FeaturePack]:
    """Guarantee several structurally fresh feature packs for a search batch."""

    generated: list[FeaturePack] = []
    target = max(1, int(count))
    recent_window = max(target * 2, 6)
    used_families = {
        pack.feature_family for pack in load_feature_packs(state.run_dir)[-recent_window:]
    }
    while len(generated) < target:
        queued = next_unbuilt_idea(state)
        if queued is None:
            break
        queued_pack = build_unique_feature_pack(queued, state, avoid_families=used_families)
        if queued_pack is not None:
            record_feature_pack(state, queued_pack)
            generated.append(queued_pack)
            used_families.add(queued_pack.feature_family)
        else:
            break

    while len(generated) < target:
        round_id = state.research_rounds + len(generated) + 1
        idea_id = f"round_{round_id}_fresh_features"
        while idea_id in {pack.idea_id for pack in load_feature_packs(state.run_dir)}:
            round_id += 1
            idea_id = f"round_{round_id}_fresh_features"
        idea = _round_explorer_idea(round_id, avoid_families=used_families)
        append_jsonl(state.run_dir / "idea_queue.jsonl", idea.to_dict())
        pack = build_unique_feature_pack(idea, state, avoid_families=used_families)
        if pack is not None:
            record_feature_pack(state, pack)
            generated.append(pack)
            used_families.add(pack.feature_family)
        else:
            break
    return generated


def repeated_best_features(
    state: AgentRunState,
    *,
    threshold: int = 3,
    rule_threshold: int = 1,
) -> list[str]:
    counts: dict[str, int] = {}
    rule_counts: dict[str, int] = {}
    rule_features: dict[str, list[str]] = {}
    for item in _read_jsonl(state.run_dir / "trials.jsonl"):
        if not isinstance(item, dict):
            continue
        for feature in _best_features(item):
            counts[feature] = counts.get(feature, 0) + 1
        signature = _best_rule_content_signature(item)
        if signature:
            rule_counts[signature] = rule_counts.get(signature, 0) + 1
            rule_features.setdefault(signature, _best_features(item))
    already = set(blocked_features(state.run_dir))
    blocked: list[str] = []
    for feature, count in sorted(counts.items()):
        if count >= threshold and feature not in already:
            append_jsonl(state.run_dir / "blocked_features.jsonl", {
                "feature": feature,
                "reason": "repeated_best_feature",
                "count": count,
            })
            blocked.append(feature)
            already.add(feature)
    blocked_rules = _blocked_rule_signatures(state.run_dir)
    for signature, count in sorted(rule_counts.items()):
        if count < rule_threshold or signature in blocked_rules:
            continue
        append_jsonl(state.run_dir / "blocked_rule_signatures.jsonl", {
            "signature": signature,
            "reason": "seen_best_rule_content",
            "count": count,
        })
    return blocked


def blocked_features(run_dir: Path) -> tuple[str, ...]:
    features: list[str] = []
    for item in _read_jsonl(run_dir / "blocked_features.jsonl"):
        if isinstance(item, dict) and item.get("feature"):
            features.append(str(item["feature"]))
    return tuple(dict.fromkeys(features))


def blocked_pack_fingerprints(run_dir: Path) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_blocked_pack_fingerprints(run_dir)))


def blocked_rule_signatures(run_dir: Path) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_blocked_rule_signatures(run_dir)))


def _idea_from_mapping(item: dict[str, object], *, source: str) -> StrategyIdea:
    idea_id = _safe_id(str(item.get("idea_id", "")))
    if not idea_id:
        raise ValueError("idea_id required")
    features = tuple(str(x) for x in item.get("features", ()) if str(x).strip())
    if not features:
        raise ValueError("features required")
    rule_family = _safe_id(str(item.get("rule_family", "regime_switch")))
    hypothesis = str(item.get("hypothesis", "")).strip()
    allowed_data = tuple(str(x).lower() for x in item.get("allowed_data", ("train only",)))
    forbidden = tuple(str(x).lower() for x in item.get("forbidden", ("locked", "future data")))
    text = " ".join((idea_id, " ".join(features), rule_family, hypothesis, " ".join(allowed_data)))
    if "locked" not in " ".join(forbidden):
        raise ValueError("idea must explicitly forbid locked data")
    if any(term in text.lower() for term in _FORBIDDEN_TEXT):
        raise ValueError("idea text requests forbidden data or behaviour")
    return StrategyIdea(
        idea_id=idea_id,
        features=features,
        rule_family=rule_family,
        hypothesis=hypothesis,
        allowed_data=allowed_data,
        forbidden=forbidden,
        source=source,
    )


def _next_template_idea(state: AgentRunState) -> StrategyIdea:
    existing = _known_idea_ids(state)
    for idea in _template_ideas():
        if idea.idea_id not in existing:
            return idea
    suffix = len(existing) + 1
    return StrategyIdea(
        idea_id=f"fresh_combo_{suffix}",
        features=("SPY trend", "stress filter", "defensive ratio"),
        rule_family="regime_switch",
        hypothesis="Force a fresh controlled combo after prior ideas were exhausted.",
        allowed_data=("train only",),
        forbidden=("locked", "future data"),
        source="template",
    )


def _round_explorer_idea(
    round_id: int,
    *,
    avoid_families: Iterable[str] = (),
) -> StrategyIdea:
    recipes = (
        (
            "drawdown_volatility",
            ("SPY drawdown", "SPY realized volatility", "VIX term"),
            "Probe drawdown and volatility pressure with a fresh parameter mix.",
        ),
        (
            "trend_stress_combo",
            ("SPY momentum", "credit stress", "rates slope"),
            "Probe trend against stress signals with a fresh parameter mix.",
        ),
        (
            "defensive_ratio_blend",
            ("defensive sector ratio", "credit ratio", "SPY trend"),
            "Probe defensive leadership against SPY trend with a fresh parameter mix.",
        ),
        (
            "yield_curve_macro",
            ("rates slope", "Treasury yield", "SPY trend"),
            "Probe equity timing against causal yield-curve pressure.",
        ),
        (
            "vix_term_structure",
            ("VIX term structure", "VIX spike", "SPY trend"),
            "Probe volatility term structure as a crash-risk regime signal.",
        ),
        (
            "breadth_proxy_regime",
            ("equal weight breadth", "small cap breadth", "SPY momentum"),
            "Probe weak breadth before broad index stress.",
        ),
        (
            "sector_rotation_momentum",
            ("sector rotation", "financials", "defensive sectors"),
            "Probe sector leadership rotation before SPY regime shifts.",
        ),
        (
            "crash_asymmetry",
            ("left tail pressure", "drawdown recovery", "volatility shock"),
            "Probe asymmetric crash pressure and recovery quality.",
        ),
        (
            "mean_reversion_stress",
            ("oversold SPY", "stress release", "VIX reversal"),
            "Probe mean reversion only when stress is not worsening.",
        ),
    )
    avoid = set(avoid_families)
    ordered = recipes[(round_id - 1) % len(recipes):] + recipes[:(round_id - 1) % len(recipes)]
    family, features, hypothesis = ordered[0]
    for candidate in ordered:
        if candidate[0] not in avoid or len(avoid) >= len(recipes):
            family, features, hypothesis = candidate
            break
    return StrategyIdea(
        idea_id=f"round_{round_id}_fresh_features",
        features=features,
        rule_family=family,
        hypothesis=hypothesis,
        allowed_data=("train only",),
        forbidden=("locked", "future data"),
        source="round_explorer",
    )


def _template_ideas() -> tuple[StrategyIdea, ...]:
    return (
        StrategyIdea(
            idea_id="spy_drawdown_volatility_pressure_v1",
            features=("SPY drawdown", "SPY realized volatility", "VIX term"),
            rule_family="drawdown_volatility",
            hypothesis="Short SPY only when drawdown and volatility pressure align.",
            allowed_data=("train only",),
            forbidden=("locked", "future data"),
            source="template",
        ),
        StrategyIdea(
            idea_id="credit_momentum_stress_v1",
            features=("SPY momentum", "credit stress", "NFCI change"),
            rule_family="trend_stress_combo",
            hypothesis="Use credit stress to avoid weak trend regimes.",
            allowed_data=("train only",),
            forbidden=("locked", "future data"),
            source="template",
        ),
        StrategyIdea(
            idea_id="defensive_sector_pressure_v1",
            features=("cyclical defensive ratio", "credit ratio", "SPY trend"),
            rule_family="defensive_ratio_blend",
            hypothesis="Short SPY when defensive sectors and credit both lead.",
            allowed_data=("train only",),
            forbidden=("locked", "future data"),
            source="template",
        ),
        StrategyIdea(
            idea_id="yield_curve_equity_pressure_v1",
            features=("rates slope", "Treasury yield", "SPY trend"),
            rule_family="yield_curve_macro",
            hypothesis="Use yield-curve pressure as a causal market regime filter.",
            allowed_data=("train only",),
            forbidden=("locked", "future data"),
            source="template",
        ),
        StrategyIdea(
            idea_id="vix_term_structure_crash_v1",
            features=("VIX term", "VIX spike", "SPY trend"),
            rule_family="vix_term_structure",
            hypothesis="Use VIX term structure to detect stress regimes.",
            allowed_data=("train only",),
            forbidden=("locked", "future data"),
            source="template",
        ),
        StrategyIdea(
            idea_id="breadth_proxy_regime_v1",
            features=("RSP/SPY", "IWM/SPY", "market breadth"),
            rule_family="breadth_proxy_regime",
            hypothesis="Weak breadth can precede weaker SPY regimes.",
            allowed_data=("train only",),
            forbidden=("locked", "future data"),
            source="template",
        ),
    )


def _family_for_idea(idea: StrategyIdea) -> str:
    allowed = set(_FAMILIES)
    if idea.rule_family in allowed:
        return idea.rule_family
    text = " ".join((*idea.features, idea.rule_family, idea.hypothesis)).lower()
    if "breadth" in text or "rsp" in text or "iwm" in text or "equal weight" in text:
        return "breadth_proxy_regime"
    if "yield" in text or "rates" in text or "treasury" in text or "curve" in text:
        return "yield_curve_macro"
    if "vix" in text or "term structure" in text:
        return "vix_term_structure"
    if "sector" in text or "rotation" in text or "xly" in text or "xlp" in text:
        return "sector_rotation_momentum"
    if "crash" in text or "tail" in text:
        return "crash_asymmetry"
    if "reversion" in text or "oversold" in text:
        return "mean_reversion_stress"
    if "drawdown" in text or "vol" in text:
        return "drawdown_volatility"
    if "credit" in text or "stress" in text:
        return "trend_stress_combo"
    return "defensive_ratio_blend"


def _unique_new_ideas(ideas: list[StrategyIdea], state: AgentRunState) -> list[StrategyIdea]:
    existing = _known_idea_ids(state)
    out: list[StrategyIdea] = []
    for idea in ideas:
        if idea.idea_id in existing:
            continue
        out.append(idea)
        existing.add(idea.idea_id)
    return out or [_next_template_idea(state)]


def _known_idea_ids(state: AgentRunState) -> set[str]:
    ids = {item.idea_id for item in load_queued_ideas(state.run_dir)}
    ids.update(pack.idea_id for pack in load_feature_packs(state.run_dir))
    return ids


def _best_features(item: dict[str, object]) -> list[str]:
    result = item.get("result")
    if not isinstance(result, dict):
        return []
    best = result.get("best")
    if not isinstance(best, dict):
        return []
    rule = best.get("rule")
    if not isinstance(rule, dict):
        return []
    return list(dict.fromkeys(_rule_features(rule)))


def _rule_features(rule: dict[str, object]) -> list[str]:
    kind = rule.get("type")
    if kind == "single":
        feature = rule.get("feature")
        return [_normalise_feature_name(feature)] if isinstance(feature, str) else []
    if kind in {"and", "or"}:
        out: list[str] = []
        left = rule.get("left")
        right = rule.get("right")
        if isinstance(left, dict):
            out.extend(_rule_features(left))
        if isinstance(right, dict):
            out.extend(_rule_features(right))
        return out
    if kind == "riskoff":
        out = []
        for key in ("trend", "stress"):
            value = rule.get(key)
            if isinstance(value, str):
                out.append(_normalise_feature_name(value))
        return out
    return []


def _best_rule_signature(item: dict[str, object]) -> str | None:
    result = item.get("result")
    if not isinstance(result, dict):
        return None
    best = result.get("best")
    if not isinstance(best, dict):
        return None
    rule = best.get("rule")
    if not isinstance(rule, dict):
        return None
    return _rule_signature(rule)


def _best_rule_content_signature(item: dict[str, object]) -> str | None:
    result = item.get("result")
    if not isinstance(result, dict):
        return None
    best = result.get("best")
    if not isinstance(best, dict):
        return None
    rule = best.get("rule")
    if not isinstance(rule, dict):
        return None
    return _rule_content_signature(rule)


def _rule_signature(rule: dict[str, object]) -> str:
    kind = str(rule.get("type", "unknown"))
    invert = "!" if rule.get("invert") else ""
    if kind == "single":
        feature = _normalise_feature_name(rule.get("feature"))
        threshold = _bucket_threshold(rule.get("threshold"))
        return f"{invert}{kind}:{feature}:{threshold}"
    if kind in {"and", "or"}:
        left = rule.get("left")
        right = rule.get("right")
        left_sig = _rule_signature(left) if isinstance(left, dict) else "?"
        right_sig = _rule_signature(right) if isinstance(right, dict) else "?"
        return f"{invert}{kind}({left_sig},{right_sig})"
    if kind == "riskoff":
        trend = _normalise_feature_name(rule.get("trend"))
        stress = _normalise_feature_name(rule.get("stress"))
        return (
            f"{invert}{kind}:{trend}:{_bucket_threshold(rule.get('trend_threshold'))}"
            f"|{stress}:{_bucket_threshold(rule.get('stress_threshold'))}"
        )
    return kind


def _rule_content_signature(rule: dict[str, object]) -> str:
    kind = str(rule.get("type", "unknown"))
    invert = "!" if rule.get("invert") else ""
    if kind == "single":
        feature = _normalise_feature_name(rule.get("feature"))
        return f"{invert}{kind}:{feature}"
    if kind in {"and", "or"}:
        left = rule.get("left")
        right = rule.get("right")
        parts = [
            _rule_content_signature(part)
            for part in (left, right)
            if isinstance(part, dict)
        ]
        if kind in {"and", "or"}:
            parts = sorted(parts)
        return f"{invert}{kind}({','.join(parts)})"
    if kind == "riskoff":
        trend = _normalise_feature_name(rule.get("trend"))
        stress = _normalise_feature_name(rule.get("stress"))
        return f"{invert}{kind}:{trend}|{stress}"
    return f"{invert}{kind}"


def _normalise_feature_name(value: object) -> str:
    feature = str(value or "")
    for suffix in _IDEA_FEATURE_SUFFIXES:
        if feature.endswith(f"_{suffix}"):
            return f"idea:*:{suffix}"
    return feature


def _bucket_threshold(value: object) -> str:
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return "?"


def _preferred_variants(seed: str) -> tuple[int, ...]:
    start = (
        int(
            sha1(
                seed.encode("utf-8"), usedforsecurity=False
            ).hexdigest()[:2],
            16,
        )
        % _VARIANT_COUNT
    )
    return tuple(start + i for i in range(_VARIANT_COUNT))


def _candidate_variants(
    seed: str,
    family: str,
    existing_fingerprints: set[str],
) -> tuple[int, ...]:
    preferred = list(_preferred_variants(seed))
    used = [
        parsed
        for fingerprint in existing_fingerprints
        if (parsed := _variant_from_fingerprint(family, fingerprint)) is not None
    ]
    extra_start = max([_VARIANT_COUNT, *used], default=_VARIANT_COUNT) + 1
    variants = preferred + list(range(extra_start, extra_start + _VARIANT_COUNT))
    return tuple(dict.fromkeys(variants))


def _pack_fingerprint(family: str, variant: int) -> str:
    return f"{family}|variant:{int(variant)}"


def _variant_from_fingerprint(family: str, fingerprint: str) -> int | None:
    prefix = f"{family}|variant:"
    if not fingerprint.startswith(prefix):
        return None
    try:
        return int(fingerprint.removeprefix(prefix))
    except ValueError:
        return None


def _used_pack_fingerprints(run_dir: Path) -> set[str]:
    out: set[str] = set()
    for pack in load_feature_packs(run_dir):
        out.add(pack.structure_fingerprint or _pack_fingerprint(
            pack.feature_family,
            pack.feature_variant,
        ))
    return out


def _blocked_pack_fingerprints(run_dir: Path) -> list[str]:
    out: list[str] = []
    for item in _read_jsonl(run_dir / "blocked_feature_packs.jsonl"):
        if isinstance(item, dict) and item.get("structure_fingerprint"):
            out.append(str(item["structure_fingerprint"]))
    return out


def _blocked_rule_signatures(run_dir: Path) -> set[str]:
    out: set[str] = set()
    for item in _read_jsonl(run_dir / "blocked_rule_signatures.jsonl"):
        if isinstance(item, dict) and item.get("signature"):
            out.add(str(item["signature"]))
    return out


def _read_jsonl(path: Path) -> list[object]:
    if not path.exists():
        return []
    out: list[object] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")[:80]


__all__ = [
    "FeaturePack",
    "StrategyIdea",
    "blocked_features",
    "blocked_pack_fingerprints",
    "blocked_rule_signatures",
    "build_feature_pack",
    "build_unique_feature_pack",
    "ensure_fresh_round_feature_pack",
    "ensure_fresh_round_feature_packs",
    "ideas_from_action",
    "load_feature_packs",
    "next_unbuilt_idea",
    "queue_ideas",
    "record_feature_pack",
    "repeated_best_features",
]
