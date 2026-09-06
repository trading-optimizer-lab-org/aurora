import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun import catalog_campaign_registry as registry


ROOT = Path(__file__).resolve().parents[1]


def test_reducer_resolves_catalog_from_registered_science() -> None:
    entries = registry.load_catalog_campaign_registry(ROOT / "config/catalog_campaign_registry_v1.json")
    entry = next(row for row in entries.campaigns if row.campaign_key == "sp500-optimized-catalog-v1")
    manifest = ROOT / entry.catalog_dir / "manifest.json"
    result = registry.resolve_catalog_for_reduction(
        repo_root=ROOT,
        scientific_contract_sha256=entry.scientific_contract_sha256,
        catalog_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )
    assert result == (ROOT / entry.catalog_dir / "catalog.jsonl").resolve()


def test_production_workflow_uses_registry_resolution_without_catalog_override() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml
    from scripts.reduce_sp500_optimized_catalog_run import _parser

    workflow = load_github_yaml(ROOT / ".github/workflows/catalog-optimized-run.yml")
    step = next(row for row in workflow["jobs"]["reduce"]["steps"]
                if row.get("name") == "Merge the sealed bounded reduction groups")
    assert "--catalog " not in step["run"]
    args = _parser().parse_args([
        "--input-root", "results", "--resolved-contract", "contract.json",
        "--resume-work-manifest", "resume.json", "--run-plan", "plan.json",
        "--admission-token", "a" * 64, "--reduction-plan", "reduction.json",
        "--output-dir", "out",
    ])
    assert args.catalog is None


@pytest.mark.parametrize("mutation", ("unknown", "wrong_manifest", "changed_catalog", "ambiguous"))
def test_reducer_rejects_unbound_catalog(tmp_path: Path, mutation: str) -> None:
    original = json.loads((ROOT / "config/catalog_campaign_registry_v1.json").read_text("utf-8"))
    entry = original["campaigns"][0]
    for field in registry._PATH_FIELDS:
        relative = entry[field]
        target = tmp_path / relative
        if field == "catalog_dir":
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
    catalog = tmp_path / entry["catalog_dir"] / "catalog.jsonl"
    catalog.write_text('{"strategy_id":"test-only"}\n', encoding="utf-8")
    manifest = catalog.with_name("manifest.json")
    manifest.write_text(json.dumps({"artifacts_sha256": {"catalog.jsonl": hashlib.sha256(catalog.read_bytes()).hexdigest()}, "validation_opened": False, "locked_opened": False}), encoding="utf-8")
    expected_manifest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    science = entry["scientific_contract_sha256"]
    if mutation == "unknown":
        science = "0" * 64
    elif mutation == "wrong_manifest":
        expected_manifest = "0" * 64
    elif mutation == "changed_catalog":
        catalog.write_text("changed", encoding="utf-8")
    else:
        original["campaigns"].append({**entry, "campaign_key": "another-active-campaign"})
    (tmp_path / "config/catalog_campaign_registry_v1.json").write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ValueError, match="CATALOG_REDUCER_CATALOG_"):
        registry.resolve_catalog_for_reduction(
            repo_root=tmp_path, scientific_contract_sha256=science,
            catalog_manifest_sha256=expected_manifest,
        )
