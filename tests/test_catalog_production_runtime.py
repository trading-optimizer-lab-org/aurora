from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_catalog_production_runtime import verify_production_runtime


ROOT = Path(__file__).resolve().parents[1]


def test_real_optimized_lock_imports_the_complete_production_boundary(tmp_path: Path) -> None:
    output = tmp_path / "runtime-smoke.json"

    receipt = verify_production_runtime(
        lock_path=ROOT / "requirements/catalog-optimized.lock",
        import_names=(
            "cryptography",
            "numpy",
            "pandas",
            "pyarrow",
            "pydantic",
            "scipy",
            "aurora.infra.sp500_megarun.catalog_fast_path",
            "scripts.plan_sp500_optimized_catalog_run",
            "scripts.prepare_catalog_admission_candidates",
            "scripts.run_catalog_recipe_worker_guarded",
            "scripts.reduce_sp500_optimized_catalog_group",
            "scripts.reduce_sp500_optimized_catalog_run",
            "scripts.audit_catalog_runtime",
            "scripts.verify_catalog_terminal_science",
            "scripts.finalize_catalog_controller_run",
        ),
        required_distributions=(
            "cryptography",
            "numpy",
            "pandas",
            "pyarrow",
            "pydantic",
            "scipy",
        ),
        output_path=output,
    )

    assert receipt["status"] == "PREPARED"
    assert receipt["production_dependency_smoke_passed"] is True
    assert receipt["parquet_roundtrip_verified"] is True
    assert receipt["runtime_platform"]
    assert receipt["runtime_python_version"]
    assert receipt["network_install_performed"] is False
    assert json.loads(output.read_text("utf-8")) == receipt


def test_missing_transitive_production_dependency_is_rejected_before_launch(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "incomplete.lock"
    lock.write_text("pydantic==2.13.4 \\\n+    --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="CATALOG_PRODUCTION_DEPENDENCY_MISSING:pyarrow",
    ):
        verify_production_runtime(
            lock_path=lock,
            import_names=("pydantic",),
            required_distributions=("pydantic", "pyarrow"),
            output_path=tmp_path / "receipt.json",
        )


def test_import_failure_is_reported_with_the_exact_module(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="CATALOG_PRODUCTION_IMPORT_FAILED:aurora_module_that_does_not_exist",
    ):
        verify_production_runtime(
            lock_path=ROOT / "requirements/catalog-optimized.lock",
            import_names=("aurora_module_that_does_not_exist",),
            required_distributions=("pydantic",),
            output_path=tmp_path / "receipt.json",
        )


def test_failed_parquet_read_prevents_runtime_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pyarrow.parquet as parquet

    def fail_read(*args, **kwargs):
        raise OSError("test parquet read failure")

    monkeypatch.setattr(parquet, "read_table", fail_read)
    output = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="CATALOG_PRODUCTION_PARQUET_FAILED"):
        verify_production_runtime(
            lock_path=ROOT / "requirements/catalog-optimized.lock",
            import_names=("pyarrow",), required_distributions=("pyarrow",),
            output_path=output,
        )
    assert not output.exists()
