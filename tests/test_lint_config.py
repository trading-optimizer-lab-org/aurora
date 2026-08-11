"""Tests that lint/type config in pyproject.toml is present and parseable.

These guard against accidental removal or breakage of dev tooling config in
pyproject.toml. Pre-commit YAML coverage lives in
``test_pre_commit.py``; this module focuses purely on TOML-side knobs and
the ``.coveragerc`` shape.
"""
from __future__ import annotations

from pathlib import Path


_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _load_pyproject() -> dict:
    try:
        import tomllib  # 3.11+
    except ImportError:
        import tomli as tomllib
    with _PYPROJECT.open("rb") as f:
        return tomllib.load(f)


def test_ruff_config_valid_yaml_or_toml():
    """[tool.ruff] and [tool.ruff.lint] must be present in pyproject.toml."""
    assert _PYPROJECT.exists(), f"pyproject.toml not found at {_PYPROJECT}"
    data = _load_pyproject()
    tool = data.get("tool", {})
    assert "ruff" in tool, "[tool.ruff] section missing"
    ruff_cfg = tool["ruff"]
    # baseline: line-length and target-version
    assert "line-length" in ruff_cfg
    assert "target-version" in ruff_cfg
    assert "lint" in ruff_cfg, "[tool.ruff.lint] missing"
    lint_cfg = ruff_cfg["lint"]
    assert "select" in lint_cfg, "[tool.ruff.lint] missing 'select'"
    assert isinstance(lint_cfg["select"], list)


def test_mypy_config_present():
    """[tool.mypy] must be declared in pyproject.toml."""
    data = _load_pyproject()
    tool = data.get("tool", {})
    assert "mypy" in tool, "[tool.mypy] section missing"
    mypy_cfg = tool["mypy"]
    assert mypy_cfg.get("python_version") == "3.10"
    assert mypy_cfg.get("ignore_missing_imports") is True
    # gradual typing — check_untyped_defs intentionally False for now
    assert mypy_cfg.get("check_untyped_defs") is False


def test_coveragerc_exists():
    """`.coveragerc` should live next to pyproject.toml with branch coverage."""
    coveragerc = _PYPROJECT.parent / ".coveragerc"
    assert coveragerc.exists(), f".coveragerc missing at {coveragerc}"
    text = coveragerc.read_text(encoding="utf-8")
    assert "[run]" in text
    assert "branch = True" in text
    assert "[report]" in text
    assert "fail_under" in text


def test_no_unmarked_live_data_loads():
    """Tests that load the SPY parquet cache must be marked `integration`.

    Walks every ``test_*.py`` under ``aurora/tests/`` with the AST and
    flags any test function that references ``SPY.parquet`` (or calls
    ``load_asset("SPY", ...)``) without the ``@pytest.mark.integration``
    decorator. Catches the regression class where a contributor adds a
    test that loads cached vendor data unconditionally and breaks CI on
    fresh checkouts.

    Self-exempt: this test itself, and explicit negative-path tests that
    only assert raising behavior (listed in ``EXEMPT_TESTS`` below).
    """
    import ast

    tests_dir = Path(__file__).resolve().parent
    offenders: list[str] = []

    # Tests that mention "SPY" or call load_oos("SPY") only to assert a
    # RuntimeError / negative-path behavior. They never actually read the
    # parquet because they expect/assert the call to raise BEFORE I/O.
    EXEMPT_TESTS = {
        # this very test scans for the literal string in source
        ("test_lint_config.py", "test_no_unmarked_live_data_loads"),
        # asserts load_oos("SPY") raises before touching the disk
        ("test_oos_isolation.py", "test_oosguard_blocks_unauth_access"),
        # uploads the literal "data/2024/SPY.parquet" key to a fake S3
        # backend; never reads cached vendor data
        ("test_infra_cloud_sync.py", "test_list_keys_after_upload"),
        # asserts that the GitHub-only workflow creates its SPY benchmark;
        # it only inspects workflow text and never opens the parquet
        (
            "test_global_technical_buy_indicator.py",
            "test_external_pack_workflow_is_github_only_manual_ubuntu_hosted",
        ),
        # These mega-run tests build tiny synthetic SPY parquet fixtures under
        # pytest's isolated tmp_path. They never consult the vendor cache.
        (
            "test_sp500_megarun_dehb_runtime_inputs.py",
            "test_runtime_input_pack_is_self_verifying_and_train_only",
        ),
        (
            "test_sp500_megarun_dehb_runtime_inputs.py",
            "test_runtime_input_pack_rejects_tampered_file",
        ),
        (
            "test_sp500_megarun_dehb_worker.py",
            "test_train_snapshot_loader_requires_exact_partition_manifest_and_adjusted_close",
        ),
        (
            "test_sp500_megarun_dehb_worker.py",
            "test_train_snapshot_loader_rejects_unbound_manifest_or_spy_hash",
        ),
        (
            "test_sp500_megarun_dehb_worker.py",
            "test_train_lane_registry_verified_prefix_hides_later_dataset_rows",
        ),
    }

    def _has_integration_marker(fn: ast.FunctionDef) -> bool:
        for d in fn.decorator_list:
            # @pytest.mark.integration  (Attribute)
            if isinstance(d, ast.Attribute) and d.attr == "integration":
                return True
            # @pytest.mark.integration() (Call wrapping the Attribute)
            if isinstance(d, ast.Call):
                target = d.func
                if isinstance(target, ast.Attribute) and target.attr == "integration":
                    return True
        return False

    def _references_spy_parquet(fn: ast.FunctionDef) -> bool:
        for node in ast.walk(fn):
            # String literal "SPY.parquet" anywhere in the function
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "SPY.parquet" in node.value:
                    return True
            # Call to load_asset("SPY", ...) or load_oos("SPY")
            if isinstance(node, ast.Call):
                tgt = node.func
                name = None
                if isinstance(tgt, ast.Name):
                    name = tgt.id
                elif isinstance(tgt, ast.Attribute):
                    name = tgt.attr
                if name in {"load_asset", "load_oos"}:
                    if node.args and isinstance(node.args[0], ast.Constant):
                        if node.args[0].value == "SPY":
                            return True
        return False

    for path in sorted(tests_dir.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            if (path.name, node.name) in EXEMPT_TESTS:
                continue
            if not _references_spy_parquet(node):
                continue
            if _has_integration_marker(node):
                continue
            offenders.append(f"{path.name}::{node.name} (line {node.lineno})")

    assert not offenders, (
        "Unmarked tests load SPY cache without @pytest.mark.integration:\n  "
        + "\n  ".join(offenders)
    )
