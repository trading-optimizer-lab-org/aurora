from __future__ import annotations

from base64 import b64encode
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from aurora.infra.sp500_megarun.catalog_campaign_registry import CatalogCampaignEntryV1
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogPreparationIdentityV1
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogLaunchTicketV1,
    CatalogRunIntentV1,
    CatalogRunRequestV1,
    _attestation_payload,
)
from scripts import inspect_catalog_fast_request as inspector


COMMIT = "a" * 40
CURRENT_DEFINITION = "c" * 64
INSTALLED_DEFINITION = "0" * 64
REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000001"


def _entry() -> CatalogCampaignEntryV1:
    return CatalogCampaignEntryV1(
        campaign_key="sp500-optimized-catalog-v1",
        engine_id="optimized_catalog_v1",
        definition_manifest_path="config/definition.json",
        optimization_policy_path="config/optimization.json",
        campaign_contract_path="config/campaign.json",
        catalog_dir="catalog",
        selected_config_path="config/selected.json",
        admission_evidence_path="config/admission.json",
        data_contract_path="config/data.json",
        feature_contract_path="config/features.json",
        runtime_input_run_id=1,
        reference_run_id=2,
        scientific_contract_sha256="b" * 64,
        max_free_workers=360,
        allowed_protected_branch="main",
        source_artifact_contracts=("runtime_input_pack_v1", "reference_oracle_v1"),
        component_store_family="sp500_component_store_v1",
        reducer_family="catalog_hierarchical_reducer_v1",
        active=True,
    )


def _identity() -> CatalogPreparationIdentityV1:
    return CatalogPreparationIdentityV1(
        schema_version="1",
        campaign_key=_entry().campaign_key,
        engine_id=_entry().engine_id,
        protected_commit_sha=COMMIT,
        campaign_definition_sha256=CURRENT_DEFINITION,
        scientific_contract_sha256="b" * 64,
        dependency_lock_sha256="d" * 64,
        optimization_policy_sha256="e" * 64,
        data_contract_sha256="f" * 64,
        feature_contract_sha256="1" * 64,
        catalog_manifest_sha256="2" * 64,
        selected_config_sha256="3" * 64,
    )


def _signed_request(private_key: rsa.RSAPrivateKey) -> tuple[str, str]:
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key=_entry().campaign_key,
        launch_generation=1,
        campaign_definition_sha256=INSTALLED_DEFINITION,
        prompt_sha256="4" * 64,
        previous_terminal_request_sha256=None,
    )
    intent = CatalogRunIntentV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key=_entry().campaign_key,
        launch_generation=1,
        launch_ticket_sha256=ticket.launch_ticket_sha256,
        previous_terminal_request_sha256=None,
        campaign_definition_sha256=INSTALLED_DEFINITION,
        prompt_sha256="4" * 64,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )
    title = f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}"
    signature = private_key.sign(
        _attestation_payload(title, intent),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256().digest_size,
        ),
        hashes.SHA256(),
    )
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    from hashlib import sha256

    request = CatalogRunRequestV1(
        **intent.model_dump(mode="json"),
        requester_public_key_sha256=sha256(public_der).hexdigest(),
        requester_attestation_algorithm="rsa-pss-sha256-v1",
        requester_attestation_b64=b64encode(signature).decode("ascii"),
    )
    payload = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return title, f"```json\n{payload}\n```\n"


def test_installed_signed_request_uses_current_registered_preparation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    runner_temp = tmp_path / "runner"
    (root / "config").mkdir(parents=True)
    (root / "keys").mkdir()
    (root / "catalog").mkdir()
    runner_temp.mkdir()

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (root / "keys/requester.pem").write_bytes(public_key)
    (root / "config/catalog_controller_actors_v1.json").write_text(
        json.dumps(
            {
                "request_actors": ["requester"],
                "requester_public_key_path": "keys/requester.pem",
            }
        ),
        encoding="utf-8",
    )
    (root / "catalog/manifest.json").write_text(
        json.dumps({"strategy_count": 37_258}),
        encoding="utf-8",
    )
    title, body = _signed_request(private_key)
    issue = runner_temp / "issue.json"
    issue.write_text(
        json.dumps(
            {
                "number": 123,
                "title": title,
                "body": body,
                "created_at": "2026-09-04T12:00:00Z",
                "updated_at": "2026-09-04T12:00:00Z",
                "labels": [],
                "user": {"login": "requester"},
            }
        ),
        encoding="utf-8",
    )
    output = runner_temp / "context.json"
    github_output = runner_temp / "github-output.txt"

    monkeypatch.setenv("CATALOG_PROTECTED_COMMIT_SHA", COMMIT)
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setattr(
        inspector.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=f"{COMMIT}\n"),
    )
    monkeypatch.setattr(inspector, "load_catalog_campaign_registry", lambda _path: object())
    monkeypatch.setattr(inspector, "resolve_catalog_campaign", lambda *_args: _entry())
    monkeypatch.setattr(inspector, "build_catalog_preparation_identity", lambda **_kwargs: _identity())

    context = inspector.inspect_request(
        issue_path=issue,
        repo_root=root,
        output_path=output,
        github_output=github_output,
    )

    request_context = cast(dict[str, object], context["request"])
    identity_context = cast(dict[str, object], context["identity"])
    assert request_context["campaign_definition_sha256"] == INSTALLED_DEFINITION
    assert identity_context["campaign_definition_sha256"] == CURRENT_DEFINITION
    assert "prepared_cache_restore_prefix=aurora-catalog-prepared-v1-" in github_output.read_text("utf-8")
