"""Maintenance stages committed public bytes; it never grants production authority."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.test_catalog_requester_packaging import ROOT, _git, _isolated_source_tree


def _source(tmp_path: Path) -> tuple[Path, str]:
    source, _ = _isolated_source_tree(tmp_path)
    sender = source / "scripts/submit_catalog_chat_intent.py"
    sender.parent.mkdir()
    shutil.copyfile(ROOT / "scripts/submit_catalog_chat_intent.py", sender)
    _git(source, "add", "scripts/submit_catalog_chat_intent.py")
    _git(source, "commit", "-m", "public sender fixture")
    return source, _git(source, "rev-parse", "HEAD")


def test_package_contains_both_apps_exact_public_inputs_and_separate_sender(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.catalog_requester import verify_installed_requester_application

    source, commit = _source(tmp_path)
    output = tmp_path / "candidate"
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.prepare_catalog_chat_maintenance",
         "--source-root", str(source), "--output-dir", str(output),
         "--expected-commit-sha", commit], cwd=ROOT,
        text=True, capture_output=True, timeout=90,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "CANDIDATE"
    assert result["production_verified"] is False
    assert result["protected_commit_sha"] == commit
    staged = output / "payload/CatalogRequester"
    for kind in ("client", "broker"):
        wrapper = verify_installed_requester_application(
            broker_root=staged, application_kind=kind,
            application_path=staged / f"bin/catalog-requester-{kind}.pyz",
        )
        core = wrapper["manifest_core"]
        assert isinstance(core, dict)
        assert core["protected_commit_sha"] == commit
        for record in core["public_inputs"]:
            assert hashlib.sha256((staged / record["path"]).read_bytes()).hexdigest() == record["sha256"]
    sender = output / "payload/CatalogChatSender"
    assert (sender / "submit_catalog_chat_intent.py").read_bytes() == (source / "scripts/submit_catalog_chat_intent.py").read_bytes()
    assert (sender / "catalog_campaign_registry_v1.json").read_bytes() == (staged / "config/catalog_campaign_registry_v1.json").read_bytes()
    inventory = json.loads((output / "candidate.json").read_bytes())
    files = {p.relative_to(output / "payload").as_posix() for p in (output / "payload").rglob("*") if p.is_file()}
    assert {r["path"] for r in inventory["files"]} == files
    assert not (staged / "config/production-enabled-v1.seal.json").exists()
    assert not (staged / "receipts").exists()
    for record in inventory["files"]:
        data = (output / "payload" / record["path"]).read_bytes()
        assert record["sha256"] == hashlib.sha256(data).hexdigest()
        assert record["size_bytes"] == len(data)


def test_dirty_source_cannot_produce_an_approved_candidate(tmp_path: Path) -> None:
    from scripts.prepare_catalog_chat_maintenance import prepare_package

    source, commit = _source(tmp_path)
    (source / "scripts/submit_catalog_chat_intent.py").write_text("changed", encoding="utf-8")
    output = tmp_path / "candidate"
    with pytest.raises(ValueError, match="DIRTY_SOURCE|SOURCE_MISMATCH"):
        prepare_package(source_root=source, output_dir=output, expected_commit_sha=commit)
    assert not (output / "candidate.json").exists()


def test_existing_output_is_never_replaced(tmp_path: Path) -> None:
    from scripts.prepare_catalog_chat_maintenance import prepare_package

    output = tmp_path / "candidate"
    output.mkdir()
    sentinel = output / "keep"
    sentinel.write_bytes(b"original")
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        prepare_package(source_root=tmp_path, output_dir=output, expected_commit_sha="a" * 40)
    assert sentinel.read_bytes() == b"original"


def test_different_second_build_never_publishes_a_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import prepare_catalog_chat_maintenance as package

    source, commit = _source(tmp_path)
    real_build = package.builder.build

    def changed_build(*, source_root: Path, output_dir: Path, expected_commit_sha: str) -> None:
        real_build(source_root=source_root, output_dir=output_dir, expected_commit_sha=expected_commit_sha)
        if output_dir.name == "build-b":
            with (output_dir / "catalog-requester-client.pyz").open("ab") as stream:
                stream.write(b"changed-build-output")

    # Model only an unstable build boundary; all Git and archive creation is real.
    monkeypatch.setattr(package.builder, "build", changed_build)
    output = tmp_path / "candidate"
    with pytest.raises(ValueError, match="NONDETERMINISTIC_BUILD"):
        package.prepare_package(source_root=source, output_dir=output, expected_commit_sha=commit)
    assert not (output / "candidate.json").exists()
    assert not (output / "payload").exists()


def _baseline(tmp_path: Path) -> tuple[Path, str, str]:
    from aurora.infra.sp500_megarun.catalog_bootstrap_finalizer import canonical_ready_receipt_bytes, finalize_bootstrap
    from tests.test_catalog_bootstrap_end_to_end import complete_evidence, _production_seal

    root = tmp_path / "installed-fixture"
    (root / "receipts").mkdir(parents=True)
    (root / "config").mkdir()
    ready = finalize_bootstrap(complete_evidence())
    ready_bytes = canonical_ready_receipt_bytes(ready)
    seal_bytes = json.dumps(_production_seal(ready).model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode() + b"\n"
    (root / "receipts/controller-bootstrap-v1.receipt.json").write_bytes(ready_bytes)
    (root / "config/production-enabled-v1.seal.json").write_bytes(seal_bytes)
    return root, hashlib.sha256(ready_bytes).hexdigest(), hashlib.sha256(seal_bytes).hexdigest()


def test_cli_binds_verified_apps_to_pinned_baseline_without_rewriting_ready(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.catalog_bootstrap_finalizer import CatalogRequesterMaintenanceReceiptV1
    from aurora.infra.sp500_megarun.catalog_requester import verify_installed_requester_application

    source, commit = _source(tmp_path)
    baseline, ready_hash, seal_hash = _baseline(tmp_path)
    before = {p.relative_to(baseline): p.read_bytes() for p in baseline.rglob("*") if p.is_file()}
    output = tmp_path / "bound-candidate"
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.prepare_catalog_chat_maintenance",
         "--source-root", str(source), "--output-dir", str(output), "--expected-commit-sha", commit,
         "--baseline-root", str(baseline), "--expected-ready-file-sha256", ready_hash,
         "--expected-seal-file-sha256", seal_hash],
        cwd=ROOT, text=True, capture_output=True, timeout=90,
    )
    assert completed.returncode == 0, completed.stderr
    candidate = json.loads((output / "candidate.json").read_bytes())
    assert candidate["status"] == "CANDIDATE"
    assert candidate["production_verified"] is False
    assert candidate["installation_authorized_by_this_file"] is False
    assert candidate["applications_verified_sealed_against_baseline"] is True
    payload = output / "payload/CatalogRequester"
    assert not (payload / "receipts/controller-bootstrap-v1.receipt.json").exists()
    maintenance = CatalogRequesterMaintenanceReceiptV1.model_validate_json(
        (payload / "receipts/requester-maintenance-v1.receipt.json").read_bytes()
    )
    assert maintenance.result == "UPDATED"
    assert maintenance.protected_commit_sha == commit
    assert maintenance.bootstrap_commit_sha == "a" * 40
    for kind in ("client", "broker"):
        verification = output / "verification/CatalogRequester"
        verify_installed_requester_application(
            broker_root=verification, application_kind=kind,
            application_path=verification / f"bin/catalog-requester-{kind}.pyz",
        )
    for record in candidate["files"]:
        assert hashlib.sha256((output / "payload" / record["path"]).read_bytes()).hexdigest() == record["sha256"]
    assert before == {p.relative_to(baseline): p.read_bytes() for p in baseline.rglob("*") if p.is_file()}


def test_unpinned_or_changed_baseline_blocks_before_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import prepare_catalog_chat_maintenance as package

    baseline, ready_hash, seal_hash = _baseline(tmp_path)
    def forbidden_build(**kwargs: object) -> None:
        pytest.fail("A mismatched baseline must be rejected before builds")
    monkeypatch.setattr(package.builder, "build", forbidden_build)
    with pytest.raises(ValueError, match="BASELINE_HASH_MISMATCH"):
        package.prepare_package(source_root=tmp_path, output_dir=tmp_path / "output", expected_commit_sha="f" * 40,
                                baseline_root=baseline, expected_ready_file_sha256=ready_hash,
                                expected_seal_file_sha256="0" * 64)
    assert not (tmp_path / "output").exists()
