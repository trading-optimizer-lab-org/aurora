from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil

import jsonschema
import pytest

from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
    discover_catalog_campaign_definition,
    verify_catalog_campaign_definition,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    CatalogCampaignDefinitionEntryV1,
    CatalogCampaignDefinitionManifestV1,
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (
    canonical_model_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/catalog_campaign_registry_v1.json"
MANIFEST = (
    ROOT
    / "config/catalog_campaign_definitions/"
    "sp500-optimized-catalog-v1.manifest.json"
)
SCHEMA = ROOT / "schemas/catalog_campaign_definition_manifest_v1.schema.json"


def _load_checked() -> CatalogCampaignDefinitionManifestV1:
    return parse_catalog_campaign_definition_bytes(MANIFEST.read_bytes())


def _entry():
    registry = load_catalog_campaign_registry(REGISTRY)
    return resolve_catalog_campaign(
        registry,
        "sp500-optimized-catalog-v1",
        ROOT,
    )


def _copy_definition_checkout(
    tmp_path: Path,
    manifest: CatalogCampaignDefinitionManifestV1,
) -> Path:
    checkout = tmp_path / "checkout"
    checkout.mkdir(parents=True)
    for item in manifest.entries:
        source = ROOT / item.path
        target = checkout / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return checkout


def test_checked_manifest_is_the_exact_complete_transitive_closure() -> None:
    entry = _entry()
    checked = _load_checked()
    discovered = discover_catalog_campaign_definition(
        repo_root=ROOT,
        registry_entry=entry,
    )
    verified = verify_catalog_campaign_definition(
        repo_root=ROOT,
        registry_entry=entry,
        manifest=checked,
    )
    assert checked == discovered == verified
    paths = {item.path for item in checked.entries}
    for repository_path in entry.repository_paths:
        assert repository_path in paths or any(
            path.startswith(repository_path + "/") for path in paths
        )
    assert "schemas/catalog_campaign_definition_manifest_v1.schema.json" in paths
    assert "infra/sp500_megarun/catalog_campaign_definition_contract.py" in paths
    assert "infra/sp500_megarun/catalog_optimization_contract.py" in paths
    assert ".github/workflows/catalog-optimized-run.yml" in paths
    assert "requirements/dehb-official.lock" in paths
    assert "config/sp500_megarun_free_data_120.json" in paths
    assert entry.definition_manifest_path not in paths


def test_schema_is_closed_and_validates_checked_manifest() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(payload, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**payload, "commit_sha": "a" * 40}, schema)


def test_source_byte_drift_and_extra_entry_fail_closed(tmp_path: Path) -> None:
    checked = _load_checked()
    checkout = _copy_definition_checkout(tmp_path, checked)
    target = checkout / checked.entries[-1].path
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_DEFINITION_MISMATCH"):
        verify_catalog_campaign_definition(
            repo_root=checkout,
            registry_entry=_entry(),
            manifest=checked,
        )

    extra_path = "config/unrelated-extra.json"
    (checkout / extra_path).write_text("{}\n", encoding="utf-8")
    extra = CatalogCampaignDefinitionEntryV1.from_bytes(
        path=extra_path,
        role="configuration",
        content=(checkout / extra_path).read_bytes(),
    )
    entries = tuple(sorted((*checked.entries, extra), key=lambda item: item.path))
    altered = CatalogCampaignDefinitionManifestV1(
        schema_version="1",
        closure_algorithm="aurora-catalog-transitive-closure-v1",
        campaign_key=checked.campaign_key,
        registry_entry_sha256=checked.registry_entry_sha256,
        entries=entries,
    )
    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_DEFINITION_MISMATCH"):
        verify_catalog_campaign_definition(
            repo_root=checkout,
            registry_entry=_entry(),
            manifest=altered,
        )


def test_missing_transitive_import_or_declared_path_blocks(tmp_path: Path) -> None:
    checked = _load_checked()
    checkout = _copy_definition_checkout(tmp_path, checked)
    module = checkout / "infra/sp500_megarun/catalog_optimization_contract.py"
    module.write_text(
        module.read_text(encoding="utf-8")
        + "\nfrom aurora.infra.sp500_megarun.missing_definition_edge import nope\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="CATALOG_DEFINITION_EDGE_UNRESOLVED"):
        discover_catalog_campaign_definition(
            repo_root=checkout,
            registry_entry=_entry(),
        )

    checkout = _copy_definition_checkout(tmp_path / "second", checked)
    campaign_path = checkout / "config/sp500_megarun_dehb_campaign_v1.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    campaign["scientific_inputs"]["data_contract_path"] = "config/missing.json"
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
    with pytest.raises(ValueError, match="CATALOG_DEFINITION_EDGE_UNRESOLVED"):
        discover_catalog_campaign_definition(
            repo_root=checkout,
            registry_entry=_entry(),
        )


def test_unresolved_dynamic_import_blocks(tmp_path: Path) -> None:
    checked = _load_checked()
    checkout = _copy_definition_checkout(tmp_path, checked)
    module = checkout / "infra/sp500_megarun/catalog_optimization_contract.py"
    module.write_text(
        module.read_text(encoding="utf-8")
        + "\nimport importlib\n"
        + "def unsafe_dynamic_edge(name: str):\n"
        + "    return importlib.import_module(f'aurora.infra.{name}')\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="CATALOG_DEFINITION_DYNAMIC_EDGE_UNRESOLVED"):
        discover_catalog_campaign_definition(
            repo_root=checkout,
            registry_entry=_entry(),
        )


def test_pinned_external_action_subpaths_are_valid_definition_edges() -> None:
    from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
        _ClosureBuilder,
    )

    builder = _ClosureBuilder(ROOT, _entry())
    builder._consider_string_edge(
        ".github/workflows/example.yml",
        "uses",
        "actions/cache/restore@" + "a" * 40,
    )
    with pytest.raises(
        ValueError,
        match="CATALOG_DEFINITION_EXTERNAL_EDGE_UNPINNED",
    ):
        builder._consider_string_edge(
            ".github/workflows/example.yml",
            "uses",
            "actions/cache/restore@v4",
        )


def test_third_party_python_module_commands_are_not_repository_edges() -> None:
    from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
        _ClosureBuilder,
    )

    builder = _ClosureBuilder(ROOT, _entry())
    builder._scan_shell(
        ".github/workflows/example.yml",
        "python -m pip download --requirement locked.txt",
    )
    with pytest.raises(ValueError, match="CATALOG_DEFINITION_EDGE_UNRESOLVED"):
        builder._scan_shell(
            ".github/workflows/example.yml",
            "python -m scripts.missing_catalog_repository_module"
        )


def test_inline_python_imports_are_in_the_transitive_definition() -> None:
    from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
        _ClosureBuilder,
    )

    builder = _ClosureBuilder(ROOT, _entry())
    builder._scan_shell(
        ".github/workflows/example.yml",
        "python - <<'PY'\n"
        "from scripts.run_catalog_artifact_keeper import _safe_extract\n"
        "PY\n",
    )
    assert "scripts/run_catalog_artifact_keeper.py" in builder.roles


def test_unrelated_dirty_path_does_not_change_definition(tmp_path: Path) -> None:
    checked = _load_checked()
    checkout = _copy_definition_checkout(tmp_path, checked)
    before = discover_catalog_campaign_definition(
        repo_root=checkout,
        registry_entry=_entry(),
    )
    unrelated = checkout / "notes/unrelated.tmp"
    unrelated.parent.mkdir()
    unrelated.write_text("dirty but out of scope\n", encoding="utf-8")
    after = discover_catalog_campaign_definition(
        repo_root=checkout,
        registry_entry=_entry(),
    )
    assert before == after == checked


def test_registry_row_drift_changes_definition_identity() -> None:
    checked = _load_checked()
    changed = _entry().model_copy(update={"max_free_workers": 120})
    with pytest.raises(ValueError, match="CATALOG_REGISTRY_ROW_MISMATCH"):
        verify_catalog_campaign_definition(
            repo_root=ROOT,
            registry_entry=changed,
            manifest=checked,
        )


def test_case_collision_and_noncanonical_paths_are_rejected() -> None:
    first = CatalogCampaignDefinitionEntryV1.from_bytes(
        path="config/A.json",
        role="configuration",
        content=b"{}",
    )
    second = CatalogCampaignDefinitionEntryV1.from_bytes(
        path="config/a.json",
        role="configuration",
        content=b"{}",
    )
    with pytest.raises(ValueError, match="CATALOG_DEFINITION_CASE_COLLISION"):
        CatalogCampaignDefinitionManifestV1(
            schema_version="1",
            closure_algorithm="aurora-catalog-transitive-closure-v1",
            campaign_key="sp500-optimized-catalog-v1",
            registry_entry_sha256="a" * 64,
            entries=(first, second),
        )
    with pytest.raises(ValueError):
        CatalogCampaignDefinitionEntryV1.from_bytes(
            path="../outside.json",
            role="configuration",
            content=b"{}",
        )


def test_symlinked_definition_input_is_rejected(tmp_path: Path) -> None:
    checked = _load_checked()
    checkout = _copy_definition_checkout(tmp_path, checked)
    target = checkout / checked.entries[0].path
    outside = tmp_path / "outside.bin"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        os.symlink(outside, target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(ValueError, match="CATALOG_DEFINITION_SYMLINK_FORBIDDEN"):
        discover_catalog_campaign_definition(
            repo_root=checkout,
            registry_entry=_entry(),
        )


def test_definition_hash_is_cross_runtime_canonical_and_deterministic(
    tmp_path: Path,
) -> None:
    checked = _load_checked()
    assert checked.campaign_definition_sha256 == (
        _load_checked().campaign_definition_sha256
    )
    sealed_copy = tmp_path / "sealed.json"
    sealed_copy.write_bytes(canonical_model_bytes(checked) + b"\n")
    reparsed = parse_catalog_campaign_definition_bytes(sealed_copy.read_bytes())
    assert reparsed == checked
    assert reparsed.campaign_definition_sha256 == checked.campaign_definition_sha256


def test_pure_contract_does_not_read_checkout_or_import_builder() -> None:
    path = ROOT / "infra/sp500_megarun/catalog_campaign_definition_contract.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("catalog_campaign_definition_builder" in item for item in imports)
    assert ".read_text(" not in text
    assert ".read_bytes(" not in text
    assert "Path(" not in text
