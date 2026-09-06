import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_catalog_production_runtime as runtime


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements/catalog-optimized.lock"


def _receipt_fixture():
    """Synthetic validator input; not evidence of an executed Linux runtime."""
    return {
        "schema_version": "1", "status": "PREPARED",
        "dependency_lock_sha256": hashlib.sha256(LOCK.read_bytes()).hexdigest(),
        "production_dependency_smoke_passed": True,
        "parquet_roundtrip_verified": True,
        "network_install_performed": False,
        "runtime_platform": "Linux", "runtime_python_version": "3.11.14",
        "verification_scope": "dependency_and_result_transport_only",
        "verified_imports": [
            "cryptography", "numpy", "pandas", "pyarrow", "pydantic", "scipy",
            "aurora.infra.sp500_megarun.catalog_fast_path",
            "scripts.plan_sp500_optimized_catalog_run",
            "scripts.prepare_catalog_admission_candidates",
            "scripts.run_catalog_recipe_worker_guarded",
            "scripts.reduce_sp500_optimized_catalog_group",
            "scripts.reduce_sp500_optimized_catalog_run",
            "scripts.audit_catalog_runtime", "scripts.verify_catalog_terminal_science",
            "scripts.finalize_catalog_controller_run",
        ],
        "required_distributions": ["cryptography", "numpy", "pandas", "pyarrow", "pydantic", "scipy"],
        "locked_distributions": sorted(runtime._locked_distributions(LOCK.read_text("utf-8"))),
    }


@pytest.mark.parametrize("mutation", (None, "platform", "python", "parquet", "lock", "import", "distribution", "hash", "network"))
def test_preparation_requires_complete_linux_runtime_evidence(mutation) -> None:
    receipt = _receipt_fixture()
    if mutation == "platform":
        receipt["runtime_platform"] = "Windows"
    elif mutation == "python":
        receipt["runtime_python_version"] = "3.14.3"
    elif mutation == "parquet":
        receipt["parquet_roundtrip_verified"] = False
    elif mutation == "lock":
        receipt["dependency_lock_sha256"] = "0" * 64
    elif mutation == "import":
        receipt["verified_imports"].remove("scripts.reduce_sp500_optimized_catalog_run")
    elif mutation == "distribution":
        receipt["required_distributions"].remove("pyarrow")
    elif mutation == "network":
        receipt["network_install_performed"] = True
    receipt["receipt_sha256"] = runtime._canonical_sha256(receipt)
    if mutation == "hash":
        receipt["runtime_python_version"] = "3.11.13"
    if mutation is None:
        runtime.validate_production_runtime_receipt(receipt, lock_path=LOCK)
    else:
        with pytest.raises(ValueError, match="CATALOG_PRODUCTION_RUNTIME_SMOKE_INVALID"):
            runtime.validate_production_runtime_receipt(receipt, lock_path=LOCK)


def test_campaign_preparation_rejects_windows_evidence_before_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import prepare_catalog_campaign as preparation

    root = tmp_path / "repo"
    lock = root / "requirements/catalog-optimized.lock"
    lock.parent.mkdir(parents=True)
    lock.write_bytes(LOCK.read_bytes())
    receipt = _receipt_fixture()
    receipt["runtime_platform"] = "Windows"
    receipt["receipt_sha256"] = runtime._canonical_sha256(receipt)
    smoke = tmp_path / "smoke.json"
    smoke.write_text(json.dumps(receipt), encoding="utf-8")
    for key, value in {
        "GITHUB_REPOSITORY": "trading-optimizer-lab-org/aurora",
        "GH_TOKEN": "unit-test-only",
        "CATALOG_PROTECTED_COMMIT_SHA": "a" * 40,
        "RUNNER_TEMP": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)

    def git_head(command, **kwargs):
        assert command == ["git", "-C", str(root.resolve()), "rev-parse", "HEAD"]
        return SimpleNamespace(stdout="a" * 40)

    def reject_discovery(*args, **kwargs):
        raise AssertionError("Registry discovery must not precede runtime verification")

    monkeypatch.setattr(preparation.subprocess, "run", git_head)
    monkeypatch.setattr(preparation, "load_catalog_campaign_registry", reject_discovery)
    output = tmp_path / "prepared"
    with pytest.raises(ValueError, match="CATALOG_PRODUCTION_RUNTIME_SMOKE_INVALID"):
        preparation.prepare_campaign(
            campaign_key="unit-test-campaign", repo_root=root,
            runtime_smoke_path=smoke, output_dir=output, github_output=None,
        )
    assert not output.exists()
