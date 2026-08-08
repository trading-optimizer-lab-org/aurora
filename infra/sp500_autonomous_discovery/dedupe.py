"""Canonical effective-rule deduplication with traceability."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .contracts import canonical_rule_hash


def build_dedupe_map(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for candidate in candidates:
        groups[canonical_rule_hash(candidate)].append(str(candidate["strategy_id"]))
    output: list[dict[str, Any]] = []
    for canonical_hash, strategy_ids in sorted(groups.items()):
        canonical_id = sorted(strategy_ids)[0]
        for strategy_id in sorted(strategy_ids):
            output.append(
                {
                    "strategy_id": strategy_id,
                    "canonical_hash": canonical_hash,
                    "canonical_strategy_id": canonical_id,
                    "deduped": strategy_id != canonical_id,
                }
            )
    return output
