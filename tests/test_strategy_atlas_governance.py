"""Tests for R173 strategy atlas governance.

Covers:
- Promotion gating for BLOCKED, BENCHMARK_ONLY, REJECTED entries
- Constructor validation: missing data_requirements,
  missing benchmark_expectation, invalid benchmark_expectation
- Graveyard pre-promote check (atlas-internal + on-disk archive)
- StrategyAtlasStatus alias and unique values
- CLI ``forge research atlas list / show / classify`` end-to-end
"""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from aurora.cli import cmd_research as _cmd_research
from aurora.cli.forge import build_parser
from aurora.research._atlas_seed import load_seed_atlas
from aurora.research.strategy_atlas import (
    AtlasStatus,
    StrategyAtlas,
    StrategyAtlasEntry,
    StrategyAtlasStatus,
    query_graveyard_before_promote,
)
from aurora.research.strategy_benchmarks import BenchmarkExpectation


def _good_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        name="Gov entry",
        asset_class="etf",
        data_requirements=("daily_ohlcv",),
        required_engine_capabilities=("multi_asset",),
        cost_sensitivity="low",
        overfit_risk="low",
        implementation_difficulty="easy",
        validation_gates=("walk_forward",),
        benchmark_expectation=BenchmarkExpectation.BUY_AND_HOLD.value,
        status=AtlasStatus.SUPPORTED,
        owner="research",
        notes="",
    )
    base.update(overrides)
    return base


# ---- StrategyAtlasStatus alias --------------------------------------------


def test_strategy_atlas_status_alias_is_atlas_status() -> None:
    assert StrategyAtlasStatus is AtlasStatus


def test_strategy_atlas_status_values_are_unique() -> None:
    values = [s.value for s in StrategyAtlasStatus]
    assert len(values) == len(set(values))


def test_strategy_atlas_status_includes_all_seven_buckets() -> None:
    expected = {
        "supported", "candidate", "blocked", "rejected",
        "benchmark_only", "external_data_only", "needs_engine_support",
    }
    actual = {s.value for s in StrategyAtlasStatus}
    assert expected.issubset(actual), expected - actual


# ---- Promotion gating ------------------------------------------------------


def test_blocked_entry_promotion_is_refused() -> None:
    atlas = StrategyAtlas()
    entry = StrategyAtlasEntry(
        **_good_kwargs(
            name="Blocked thing",
            status=AtlasStatus.BLOCKED,
            notes="data not available",
        )
    )
    atlas.register(entry)
    assert atlas.is_promotable("Blocked thing") is False


def test_benchmark_only_entry_promotion_is_refused() -> None:
    atlas = StrategyAtlas()
    entry = StrategyAtlasEntry(
        **_good_kwargs(
            name="Benchmark thing",
            status=AtlasStatus.BENCHMARK_ONLY,
        )
    )
    atlas.register(entry)
    assert atlas.is_promotable("Benchmark thing") is False


def test_rejected_entry_promotion_is_refused() -> None:
    atlas = StrategyAtlas()
    entry = StrategyAtlasEntry(
        **_good_kwargs(
            name="Rejected thing",
            status=AtlasStatus.REJECTED,
        )
    )
    atlas.register(entry)
    assert atlas.is_promotable("Rejected thing") is False


def test_supported_entry_passes_promotion_check() -> None:
    atlas = StrategyAtlas()
    entry = StrategyAtlasEntry(
        **_good_kwargs(name="Sup", status=AtlasStatus.SUPPORTED)
    )
    atlas.register(entry)
    assert atlas.is_promotable("Sup") is True


# ---- Constructor validation ------------------------------------------------


def test_missing_data_requirements_raises() -> None:
    with pytest.raises(ValueError, match="data_requirements"):
        StrategyAtlasEntry(**_good_kwargs(data_requirements=()))


def test_missing_benchmark_expectation_raises() -> None:
    with pytest.raises(ValueError, match="benchmark_expectation"):
        StrategyAtlasEntry(**_good_kwargs(benchmark_expectation=""))


def test_invalid_benchmark_expectation_value_raises() -> None:
    with pytest.raises(ValueError, match="benchmark_expectation"):
        StrategyAtlasEntry(
            **_good_kwargs(benchmark_expectation="not-a-real-benchmark")
        )


def test_blocked_entry_without_notes_raises() -> None:
    with pytest.raises(ValueError, match="BLOCKED"):
        StrategyAtlasEntry(
            **_good_kwargs(status=AtlasStatus.BLOCKED, notes="")
        )


# ---- query_graveyard_before_promote ---------------------------------------


def test_graveyard_collision_atlas_internal_raises() -> None:
    """A previously rejected atlas entry blocks re-promotion."""
    atlas = StrategyAtlas()
    rejected = StrategyAtlasEntry(
        **_good_kwargs(
            name="Ghost",
            status=AtlasStatus.REJECTED,
        )
    )
    atlas.register(rejected)
    candidate = StrategyAtlasEntry(
        **_good_kwargs(
            name="Ghost",
            status=AtlasStatus.SUPPORTED,
        )
    )
    with pytest.raises(ValueError, match="already rejected"):
        query_graveyard_before_promote(candidate, atlas=atlas)


def test_graveyard_archive_collision_raises(tmp_path: Path) -> None:
    """A matching strategy_id in the on-disk archive blocks promotion."""
    archive = tmp_path / "archive.jsonl"
    rows = [
        {
            "event": "rejected",
            "strategy_id": "Ghost",
            "version": "v1",
            "rejection_reason": "deflated_sharpe failed",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    archive.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    candidate = StrategyAtlasEntry(
        **_good_kwargs(name="Ghost", status=AtlasStatus.SUPPORTED)
    )
    with pytest.raises(ValueError, match="graveyard"):
        query_graveyard_before_promote(candidate, archive_path=archive)


def test_graveyard_check_passes_when_no_collision(tmp_path: Path) -> None:
    """Fresh entry with no prior rejection passes the gate."""
    atlas = StrategyAtlas()
    archive = tmp_path / "archive.jsonl"
    archive.write_text("", encoding="utf-8")
    candidate = StrategyAtlasEntry(
        **_good_kwargs(name="Fresh", status=AtlasStatus.SUPPORTED)
    )
    # Should not raise.
    query_graveyard_before_promote(
        candidate, atlas=atlas, archive_path=archive
    )


# ---- CLI: atlas list / show / classify -------------------------------------


def _run_cli(argv: list[str]) -> tuple[int, str]:
    parser = build_parser()
    ns = parser.parse_args(argv)
    buf = StringIO()
    with patch("sys.stdout", buf):
        rc = ns.func(ns)
    return int(rc), buf.getvalue()


def test_cli_atlas_list_runs_offline() -> None:
    rc, out = _run_cli(["research", "atlas", "list"])
    assert rc == 0
    # At least the canonical SUPPORTED entries should appear.
    assert "ETF momentum rotation" in out
    assert "Dual momentum" in out


def test_cli_atlas_list_filtered_by_status_shows_only_blocked() -> None:
    rc, out = _run_cli(
        ["research", "atlas", "list", "--status", "blocked"]
    )
    assert rc == 0
    assert "Options-heavy strategies" in out
    # SUPPORTED entries must not leak into a BLOCKED filter.
    assert "ETF momentum rotation" not in out


def test_cli_atlas_show_returns_specified_entry() -> None:
    rc, out = _run_cli(
        ["research", "atlas", "show", "ETF momentum rotation"]
    )
    assert rc == 0
    assert "ETF momentum rotation" in out
    assert "supported" in out
    assert "etf" in out


def test_cli_atlas_show_unknown_entry_returns_nonzero() -> None:
    rc, _out = _run_cli(
        ["research", "atlas", "show", "does-not-exist-XYZ"]
    )
    assert rc != 0


def test_cli_atlas_classify_reports_counts_per_status() -> None:
    rc, out = _run_cli(
        ["research", "atlas", "classify", "--json"]
    )
    assert rc == 0
    counts = json.loads(out)
    assert "supported" in counts
    assert "blocked" in counts
    assert counts["supported"] >= 6
    assert counts["blocked"] >= 5
    assert counts["benchmark_only"] >= 3
    # Sum equals registry size.
    seeded = load_seed_atlas()
    assert sum(counts.values()) == len(seeded)
