"""Fail-closed admission records for SP500 Atlas families."""

from __future__ import annotations

from typing import Literal, Mapping

from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, Sha256, canonical_sha256
from aurora.infra.sp500_megarun.feature_contract import FrozenFeatureContract


FamilyStatus = Literal[
    "accepted",
    "duplicate",
    "insufficient_history",
    "not_verifiable",
    "not_free",
]


class FamilyAdmissionV1(FrozenModel):
    family_id: str = Field(min_length=1)
    status: FamilyStatus
    source_ids: tuple[str, ...]
    source_sha256: Sha256 | None = None
    available_through: str | None = None
    available_at_mode: str | None = None
    duplicate_of: str | None = None
    reason: str = Field(min_length=1)


def classify_family(
    candidate: Mapping[str, object],
    existing: Mapping[str, Mapping[str, object]],
) -> FamilyAdmissionV1:
    """Classify a candidate without treating historical similarity as identity."""

    family_id = str(candidate.get("family_id", "")).strip()
    if not family_id:
        raise ValueError("ATLAS_FAMILY_ID_MISSING")
    if family_id in existing:
        return FamilyAdmissionV1(
            family_id=family_id,
            status="duplicate",
            source_ids=tuple(str(x) for x in candidate.get("source_ids", ())),
            source_sha256=(
                str(candidate["source_sha256"])
                if candidate.get("source_sha256") is not None
                else None
            ),
            available_through=(
                str(candidate["available_through"])
                if candidate.get("available_through") is not None
                else None
            ),
            available_at_mode=(
                str(candidate["available_at_mode"])
                if candidate.get("available_at_mode") is not None
                else None
            ),
            duplicate_of=family_id,
            reason="family_id already exists in the frozen contract",
        )
    status = str(candidate.get("status", "accepted"))
    if status not in {"accepted", "insufficient_history", "not_verifiable", "not_free"}:
        raise ValueError("ATLAS_FAMILY_STATUS_INVALID")
    if status == "accepted":
        required = ("source_ids", "source_sha256", "available_through", "available_at_mode")
        if any(not candidate.get(key) for key in required):
            raise ValueError("ATLAS_ACCEPTED_FAMILY_EVIDENCE_INCOMPLETE")
        if str(candidate["available_through"]) > "2010-12-31":
            raise ValueError("ATLAS_FAMILY_AFTER_TRAIN_END")
    return FamilyAdmissionV1(
        family_id=family_id,
        status=status,  # type: ignore[arg-type]
        source_ids=tuple(str(x) for x in candidate.get("source_ids", ())),
        source_sha256=(
            str(candidate["source_sha256"])
            if candidate.get("source_sha256") is not None
            else None
        ),
        available_through=(
            str(candidate["available_through"])
            if candidate.get("available_through") is not None
            else None
        ),
        available_at_mode=(
            str(candidate["available_at_mode"])
            if candidate.get("available_at_mode") is not None
            else None
        ),
        reason=str(candidate.get("reason", "classified by the closed admission contract")),
    )


def build_existing_family_manifest(contract: FrozenFeatureContract) -> tuple[FamilyAdmissionV1, ...]:
    """Create the auditable baseline: the 240 frozen executable families."""

    return tuple(
        FamilyAdmissionV1(
            family_id=lane.lane_id,
            status="accepted",
            source_ids=(f"feature_contract:{lane.lane_id}",),
            source_sha256=lane.canonical_sha256,
            available_through="2010-12-31",
            available_at_mode=lane.available_at_mode,
            reason="existing executable family in the frozen 240-lane contract",
        )
        for lane in sorted(contract.lanes, key=lambda item: item.lane_id)
    )


def family_manifest_payload(rows: tuple[FamilyAdmissionV1, ...]) -> dict[str, object]:
    if not rows:
        raise ValueError("ATLAS_FAMILY_MANIFEST_EMPTY")
    if len({row.family_id for row in rows}) != len(rows):
        raise ValueError("ATLAS_FAMILY_DUPLICATE_ID")
    identity = {
        "schema_version": 1,
        "families": [row.model_dump(mode="json") for row in rows],
        "accepted_count": sum(row.status == "accepted" for row in rows),
        "validation_opened": False,
        "locked_opened": False,
    }
    return {**identity, "manifest_sha256": canonical_sha256(identity)}


def formal_recipe_equivalence(
    left: Mapping[str, object],
    right: Mapping[str, object],
) -> bool:
    """Compare formal recipe meaning; never compare historical positions."""

    def canonical(row: Mapping[str, object]) -> dict[str, object]:
        components = tuple(str(x) for x in row.get("components", ()))
        composition = dict(row.get("composition", {}))
        kind = str(composition.get("kind"))
        if kind in {"and", "vote", "weighted_score"}:
            components = tuple(sorted(components))
        if kind == "weighted_score":
            weights = tuple(float(x) for x in composition.get("weights", ()))
            if len(weights) != len(components):
                return {"invalid": True}
            pairs = sorted(zip(components, weights, strict=True))
            components = tuple(x[0] for x in pairs)
            weights = tuple(x[1] for x in pairs)
            nonzero = [abs(x) for x in weights if x]
            if not nonzero:
                return {"invalid": True}
            scale = min(nonzero)
            weights = tuple(round(x / scale, 12) for x in weights)
            composition["weights"] = list(weights)
        return {
            "strategy_kind": row.get("strategy_kind"),
            "components": components,
            "composition": composition,
            "feature_contract_sha256": row.get("feature_contract_sha256"),
            "search_end": row.get("search_end"),
        }

    return canonical(left) == canonical(right)


__all__ = [
    "FamilyAdmissionV1",
    "build_existing_family_manifest",
    "classify_family",
    "family_manifest_payload",
    "formal_recipe_equivalence",
]
