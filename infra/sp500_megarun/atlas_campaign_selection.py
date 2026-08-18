"""Deterministic, hash-bound stratified selection for finite Atlas campaigns."""

from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
import math
from typing import Mapping


_SELECTION_DOMAIN = "AURORA-SP500-ATLAS-CAMPAIGN-SELECTION-V1"


def _sha256_payload(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _range_key(seed: int, range_id: str) -> str:
    return hashlib.sha256(f"{_SELECTION_DOMAIN}:{seed}:{range_id}".encode("utf-8")).hexdigest()


def _step_and_offset(seed: int, range_id: str, length: int) -> tuple[int, int]:
    if length <= 0:
        raise ValueError("ATLAS_SELECTION_RANGE_EMPTY")
    if length == 1:
        return 0, 0
    digest = hashlib.sha256(f"{_SELECTION_DOMAIN}:step:{seed}:{range_id}".encode("utf-8")).digest()
    offset = int.from_bytes(digest[:8], "big") % length
    step = int.from_bytes(digest[8:16], "big") % length
    if step == 0:
        step = 1
    while math.gcd(step, length) != 1:
        step = (step + 1) % length
        if step == 0:
            step = 1
    return offset, step


def build_campaign_selection(
    space_payload: Mapping[str, object],
    *,
    requested_recipe_count: int,
    seed: int,
) -> dict[str, object]:
    """Build a deterministic quota per canonical range without using a prefix.

    When the budget reaches every range, every range receives at least one
    recipe.  Remaining budget is distributed in a stable hash order.  When the
    budget is smaller, ranges themselves are sampled in the same stable order.
    """

    if requested_recipe_count <= 0:
        raise ValueError("ATLAS_SELECTION_COUNT_INVALID")
    raw_ranges = space_payload.get("ranges")
    if not isinstance(raw_ranges, list) or not raw_ranges:
        raise ValueError("ATLAS_SELECTION_RANGES_REQUIRED")
    ranges: list[dict[str, object]] = []
    for raw in raw_ranges:
        if not isinstance(raw, dict):
            raise ValueError("ATLAS_SELECTION_RANGE_OBJECT_REQUIRED")
        range_id = str(raw["range_id"])
        start = int(raw["start_ordinal"])
        stop = int(raw["stop_ordinal"])
        if stop <= start:
            raise ValueError("ATLAS_SELECTION_RANGE_INVALID")
        ranges.append({"range_id": range_id, "raw_start": start, "raw_stop": stop})
    ranges.sort(key=lambda item: (int(item["raw_start"]), str(item["range_id"])))
    capacity = sum(int(item["raw_stop"]) - int(item["raw_start"]) for item in ranges)
    if requested_recipe_count > capacity:
        raise ValueError("ATLAS_SELECTION_COUNT_EXCEEDS_CANONICAL")

    order = sorted(ranges, key=lambda item: _range_key(seed, str(item["range_id"])))
    quotas = {str(item["range_id"]): 0 for item in ranges}
    if requested_recipe_count < len(ranges):
        for item in order[:requested_recipe_count]:
            quotas[str(item["range_id"])] = 1
    else:
        for item in ranges:
            quotas[str(item["range_id"])] = 1
        remaining = requested_recipe_count - len(ranges)
        cursor = 0
        while remaining:
            item = order[cursor % len(order)]
            range_id = str(item["range_id"])
            if quotas[range_id] < int(item["raw_stop"]) - int(item["raw_start"]):
                quotas[range_id] += 1
                remaining -= 1
            cursor += 1
            if cursor > requested_recipe_count * 2 + len(order):
                raise AssertionError("ATLAS_SELECTION_QUOTA_INTERNAL_ERROR")

    selected_ranges: list[dict[str, object]] = []
    campaign_cursor = 0
    for item in ranges:
        range_id = str(item["range_id"])
        quota = quotas[range_id]
        if quota == 0:
            continue
        raw_start = int(item["raw_start"])
        raw_stop = int(item["raw_stop"])
        offset, step = _step_and_offset(seed, range_id, raw_stop - raw_start)
        selected_ranges.append(
            {
                "range_id": range_id,
                "raw_start": raw_start,
                "raw_stop": raw_stop,
                "campaign_start": campaign_cursor,
                "campaign_stop": campaign_cursor + quota,
                "quota": quota,
                "offset": offset,
                "step": step,
            }
        )
        campaign_cursor += quota
    identity = {
        "schema_version": "1",
        "selection_domain": _SELECTION_DOMAIN,
        "seed": int(seed),
        "requested_recipe_count": requested_recipe_count,
        "canonical_recipe_count": capacity,
        "ranges": selected_ranges,
    }
    return {
        **identity,
        "selection_sha256": _sha256_payload(identity),
    }


def selected_raw_ordinal(selection: Mapping[str, object], campaign_ordinal: int) -> int:
    """Map one campaign ordinal to a unique raw canonical ordinal."""

    ranges = selection.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        raise ValueError("ATLAS_SELECTION_RANGES_REQUIRED")
    starts = [int(item["campaign_start"]) for item in ranges]
    index = bisect_right(starts, campaign_ordinal) - 1
    if index < 0:
        raise IndexError("ATLAS_SELECTION_CAMPAIGN_ORDINAL_OUT_OF_RANGE")
    item = ranges[index]
    campaign_start = int(item["campaign_start"])
    campaign_stop = int(item["campaign_stop"])
    if campaign_ordinal >= campaign_stop:
        raise IndexError("ATLAS_SELECTION_CAMPAIGN_ORDINAL_OUT_OF_RANGE")
    local = campaign_ordinal - campaign_start
    length = int(item["raw_stop"]) - int(item["raw_start"])
    raw_offset = (int(item["offset"]) + local * int(item["step"])) % length
    return int(item["raw_start"]) + raw_offset


__all__ = ["build_campaign_selection", "selected_raw_ordinal"]
