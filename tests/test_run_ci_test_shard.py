from pathlib import Path

import pytest

from scripts.run_ci_test_shard import balanced_shards, discover_tests


def test_balanced_shards_are_complete_disjoint_and_deterministic(tmp_path: Path) -> None:
    paths = []
    for name, size in (("test_a.py", 100), ("test_b.py", 80), ("test_c.py", 20)):
        path = tmp_path / name
        path.write_bytes(b"x" * size)
        paths.append(path)

    first = balanced_shards(paths, 2)
    second = balanced_shards(list(reversed(paths)), 2)

    assert first == second
    assert sorted(path for shard in first for path in shard) == sorted(paths)
    assert set(first[0]).isdisjoint(first[1])


def test_discover_tests_preserves_policy_exclusions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_config.py").write_text("", encoding="utf-8")
    (tests / "test_property.py").write_text("", encoding="utf-8")
    kept = tests / "test_kept.py"
    kept.write_text("", encoding="utf-8")

    assert discover_tests(Path("tests")) == [Path("tests/test_kept.py")]


def test_balanced_shards_rejects_non_positive_count() -> None:
    with pytest.raises(ValueError, match="positive"):
        balanced_shards([], 0)
