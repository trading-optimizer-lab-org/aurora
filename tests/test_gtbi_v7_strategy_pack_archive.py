from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.materialize_gtbi_v7_strategy_pack import (
    StrategyPackArchiveError,
    build_archive,
    extract_archive,
)


def _shards(root: Path) -> None:
    root.mkdir()
    for shard in range(2):
        rows = [json.dumps({"strategy_id": f"s{shard}-{slot}"}) for slot in range(3)]
        (root / f"shard_{shard:03d}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_compact_strategy_archive_round_trip_is_exact(tmp_path: Path) -> None:
    shards = tmp_path / "source"
    _shards(shards)
    pack = tmp_path / "pack"
    first = build_archive(shards_root=shards, pack_root=pack, expected_shards=2, expected_rows_per_shard=3)
    output = tmp_path / "materialized"
    receipt = extract_archive(pack_root=pack, output_dir=output)
    assert first["strategy_count"] == 6
    assert receipt["verified"] is True
    assert receipt["strategy_count"] == 6
    for path in shards.iterdir():
        assert (output / "shards" / path.name).read_bytes() == path.read_bytes()


def test_compact_strategy_archive_is_reproducible(tmp_path: Path) -> None:
    shards = tmp_path / "source"
    _shards(shards)
    manifests = []
    archives = []
    for name in ("one", "two"):
        pack = tmp_path / name
        manifests.append(build_archive(shards_root=shards, pack_root=pack, expected_shards=2, expected_rows_per_shard=3))
        archives.append((pack / "strategy_shards.zip").read_bytes())
    assert manifests[0] == manifests[1]
    assert archives[0] == archives[1]


def test_compact_strategy_archive_rejects_unsafe_member(tmp_path: Path) -> None:
    shards = tmp_path / "source"
    _shards(shards)
    pack = tmp_path / "pack"
    build_archive(shards_root=shards, pack_root=pack, expected_shards=2, expected_rows_per_shard=3)
    with zipfile.ZipFile(pack / "strategy_shards.zip", "a") as archive:
        archive.writestr("../escape.jsonl", "{}\n")
    with pytest.raises(StrategyPackArchiveError, match="archive bytes"):
        extract_archive(pack_root=pack, output_dir=tmp_path / "output")
