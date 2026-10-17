from pathlib import Path

import pytest
import yaml

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


def test_ci_shards_cover_each_supported_runtime_without_exclusions() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/tests.yml').read_text())
    job = workflow['jobs']['test']
    matrix = job['strategy']['matrix']
    # Pushes to main run every Python x OS combination in two shards; pull
    # requests run Linux / 3.12 in six shards to keep the merge gate fast.
    assert """fromJSON('["3.11", "3.12", "3.13"]')""" in matrix['python']
    assert """fromJSON('["ubuntu-latest", "windows-latest"]')""" in matrix['os']
    assert "fromJSON('[0, 1]')" in matrix['shard']
    assert """fromJSON('["3.12"]')""" in matrix['python']
    assert "fromJSON('[0, 1, 2, 3, 4, 5]')" in matrix['shard']
    assert not matrix.get('exclude')
    assert job['timeout-minutes'] == 30
    command = next(step['run'] for step in job['steps'] if step.get('name') == 'Run tests')
    assert '--shard-index ${{ matrix.shard }}' in command
    assert "--shard-count ${{ github.event_name == 'pull_request' && 6 || 2 }}" in command
