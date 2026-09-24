"""Maintenance prepares new bytes; the existing protected transaction applies them."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun.catalog_request_contract import CatalogLaunchTicketV1
from aurora.infra.sp500_megarun.catalog_requester import CatalogRequesterCampaignStatusV1
from aurora.infra.sp500_megarun.catalog_requester_broker import _ticket_journal
from tests.test_catalog_fast_authority import _lineage_boundary


NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


def test_atlas_generation_two_uses_only_the_closed_first_request_and_current_definition():
    from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import parse_catalog_campaign_definition_bytes
    from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition

    root = Path(__file__).resolve().parents[1]
    definition = parse_catalog_campaign_definition_bytes(
        (root / "config/catalog_campaign_definitions/sp500-atlas-v1.manifest.json").read_bytes()
    )
    prompt_sha256 = hashlib.sha256(
        (root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()
    ).hexdigest()
    ticket = CatalogLaunchTicketV1(
        schema_version="1", request_id="018f47a2-6e91-7c34-8000-000000000020",
        campaign_key="sp500-atlas-v1", launch_generation=2,
        previous_terminal_request_sha256="50c97b410f5bd9659e90c3c16c20b6717c70afc919d2a5f057159f406d5c6bb1",
        campaign_definition_sha256=definition.campaign_definition_sha256,
        prompt_sha256=prompt_sha256,
    )
    approval = load_lineage_transition(root, ticket)
    assert approval is not None
    assert approval.previous_request_sha256 == ticket.previous_terminal_request_sha256
    assert approval.target_definition_sha256 == ticket.campaign_definition_sha256
    assert approval.target_prompt_sha256 == ticket.prompt_sha256
    assert approval.source_ticket_contexts == ()


@pytest.mark.parametrize("campaign,generation,predecessor,installed_definition", [
    ("sp500-optimized-catalog-v1", 7,
     "1f73eadbb2404095072c61fb67f36f813cff8b119bc17bbb3d5df8852ad333f7",
     "f4bd664a2755e6586c0376c2fb358c6e5a557e96f753b5f0c8dae78cf02d13f8"),
    ("sp500-optimized-catalog-v1", 7,
     "1f73eadbb2404095072c61fb67f36f813cff8b119bc17bbb3d5df8852ad333f7",
     "13c9fa8f2cbaf1762b05104d338f7be2def612a4824c1c7ab0a678616d5a7db3"),
    ("sp500-optimized-catalog-v1", 7,
     "1f73eadbb2404095072c61fb67f36f813cff8b119bc17bbb3d5df8852ad333f7",
     "684f349ba2e97f1f6fe03a78c7649f44baf22111691c11cc92909102cd7e0334"),
    ("sp500-optimized-catalog-v1", 7,
     "1f73eadbb2404095072c61fb67f36f813cff8b119bc17bbb3d5df8852ad333f7",
     "a1552e41117d918ce8e1886d2a75d2cfb09fbc0f46a79cefbe3d16c6e5b774ad"),
    ("sp500-optimized-catalog-v1", 7,
     "1f73eadbb2404095072c61fb67f36f813cff8b119bc17bbb3d5df8852ad333f7",
     "e8fa1cb7e37eef683044b1f9a3c537e02bb0ca338adfe063af3e433ca8de893e"),
])
def test_consumed_sp500_generation_seven_keeps_its_historical_release_boundary(
    campaign, generation, predecessor, installed_definition,
):
    from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition

    root = Path(__file__).resolve().parents[1]
    prompt_hash = "c69e7e311f2d2c728d41573a7512276a94ca6d7360d06d1f3f8b2e37b5bb42d3"
    # Both sides of the consumed migration remain historical, independently
    # of the manifest and prompt packaged for a later generation.
    installed_prompt_hash = "7eeb12311d4d109bb0da25c617ad1684568c47dd6ff0996f3c4f72cc2e633c49"
    ticket = CatalogLaunchTicketV1(
        schema_version="1", request_id="018f47a2-6e91-7c34-8000-000000000002",
        campaign_key=campaign, launch_generation=generation,
        previous_terminal_request_sha256=predecessor,
        campaign_definition_sha256=installed_definition, prompt_sha256=installed_prompt_hash,
    )
    approval = load_lineage_transition(root, ticket)
    assert approval is not None
    assert approval.next_generation == 7
    assert approval.previous_request_sha256 == predecessor
    assert approval.target_definition_sha256 == "60eec37650ab3293fe591f1563abf3dde7cb84d191f9814ac8a3c67ab0faac2a"
    assert approval.target_prompt_sha256 == prompt_hash
    if campaign == "sp500-optimized-catalog-v1" or installed_definition in {
        "452dcdce598620547ec44a035610b653167c7e4226de89ff35af3b45716da37a",
        "5974d90710e3f62b0b4fb554dbd751df6fec472543e28bd7aca651cf11a2368e",
    }:
        contexts = {
            (context.campaign_definition_sha256, context.prompt_sha256)
            for context in approval.source_ticket_contexts
        }
        assert (installed_definition, installed_prompt_hash) in contexts
        assert installed_prompt_hash != prompt_hash
        assert (installed_definition, prompt_hash) not in contexts


def test_sp500_generation_ten_keeps_its_approved_definition_after_request_360():
    from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import parse_catalog_campaign_definition_bytes
    from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition

    root = Path(__file__).resolve().parents[1]
    definition = parse_catalog_campaign_definition_bytes(
        (root / "config/catalog_campaign_definitions/sp500-optimized-catalog-v1.manifest.json").read_bytes()
    )
    ticket = CatalogLaunchTicketV1(
        schema_version="1", request_id="018f47a2-6e91-7c34-8000-000000000010",
        campaign_key="sp500-optimized-catalog-v1", launch_generation=10,
        previous_terminal_request_sha256="a0fdcfe2209caf1f03d6ee4db54fcc34b1488198cafb41bc0ef7461332b409bd",
        campaign_definition_sha256="9d13146fa009f894e25b92a3d106329a12105f839b62407f7f09bae08b7bd4eb",
        prompt_sha256=hashlib.sha256(
            (root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()
        ).hexdigest(),
    )
    approval = load_lineage_transition(root, ticket)
    assert approval is not None, "SP500 gen10 requires its own protected transition after #360"
    assert approval.next_generation == 10
    assert approval.previous_request_sha256 == ticket.previous_terminal_request_sha256
    assert approval.target_definition_sha256 == ticket.campaign_definition_sha256
    assert definition.campaign_definition_sha256 != ticket.campaign_definition_sha256
    assert approval.target_prompt_sha256 == ticket.prompt_sha256
    assert approval.source_ticket_contexts == ()


def test_consumed_sp500_generation_nine_keeps_its_historical_release_boundary():
    from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition

    root = Path(__file__).resolve().parents[1]
    ticket = CatalogLaunchTicketV1(
        schema_version="1", request_id="018f47a2-6e91-7c34-8000-000000000009",
        campaign_key="sp500-optimized-catalog-v1", launch_generation=9,
        previous_terminal_request_sha256="f337320f4ebb3c863581b632e18e15eeba364621363310ed31fc120677f84fe0",
        campaign_definition_sha256="3d18b6610f19be4331f3da6ca25b98dbf1115bbea912b9c2a0a099d2e20edcb2",
        prompt_sha256="c69e7e311f2d2c728d41573a7512276a94ca6d7360d06d1f3f8b2e37b5bb42d3",
    )
    approval = load_lineage_transition(root, ticket)
    assert approval is not None
    assert approval.next_generation == 9
    assert approval.previous_request_sha256 == ticket.previous_terminal_request_sha256
    assert approval.target_definition_sha256 == ticket.campaign_definition_sha256
    assert approval.target_prompt_sha256 == ticket.prompt_sha256
    assert approval.source_ticket_contexts == ()


def test_consumed_sp500_generation_eight_keeps_its_historical_release_boundary():
    from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition

    root = Path(__file__).resolve().parents[1]
    ticket = CatalogLaunchTicketV1(
        schema_version="1", request_id="018f47a2-6e91-7c34-8000-000000000008",
        campaign_key="sp500-optimized-catalog-v1", launch_generation=8,
        previous_terminal_request_sha256="db7838f228058a301bb369a02e7133096cc48846cf0be8d6dac79372152ba2e1",
        campaign_definition_sha256="a0faab0dec41d44b6183903b0165406d0e82af71be0bdbb9b43c14db41893b81",
        prompt_sha256="c69e7e311f2d2c728d41573a7512276a94ca6d7360d06d1f3f8b2e37b5bb42d3",
    )
    approval = load_lineage_transition(root, ticket)
    assert approval is not None
    assert approval.previous_request_sha256 == ticket.previous_terminal_request_sha256
    assert approval.target_definition_sha256 == ticket.campaign_definition_sha256
    assert approval.target_prompt_sha256 == ticket.prompt_sha256
    assert approval.source_ticket_contexts == ()


def test_ordinary_canary_generation_twelve_keeps_its_approved_definition():
    from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import parse_catalog_campaign_definition_bytes
    from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition

    root = Path(__file__).resolve().parents[1]
    definition = parse_catalog_campaign_definition_bytes(
        (root / 'config/catalog_campaign_definitions/catalog-fast-canary-v1.manifest.json').read_bytes()
    )
    ticket = CatalogLaunchTicketV1(
        schema_version='1', request_id='018f47a2-6e91-7c34-8000-000000000012',
        campaign_key='catalog-fast-canary-v1', launch_generation=12,
        previous_terminal_request_sha256='d46799a897dd2d8f4d51837e6783e4c03e84b9773c3da243225a016ab9e5ed6d',
        campaign_definition_sha256="9eb2313d6d6abfdc31ed5b84d33705827994ea7fb650eb78dce534adb86f02aa",
        prompt_sha256=hashlib.sha256((root / 'docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md').read_bytes()).hexdigest(),
    )
    approval = load_lineage_transition(root, ticket)
    assert approval is not None
    assert approval.next_generation == 12
    assert approval.previous_request_sha256 == ticket.previous_terminal_request_sha256
    assert approval.target_definition_sha256 == ticket.campaign_definition_sha256
    assert definition.campaign_definition_sha256 != ticket.campaign_definition_sha256
    assert approval.target_prompt_sha256 == ticket.prompt_sha256
    assert approval.source_ticket_contexts == ()


def test_consumed_canary_generation_eleven_keeps_its_historical_release_boundary():
    from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition

    root = Path(__file__).resolve().parents[1]
    ticket = CatalogLaunchTicketV1(
        schema_version="1", request_id="018f47a2-6e91-7c34-8000-000000000011",
        campaign_key="catalog-fast-canary-v1", launch_generation=11,
        previous_terminal_request_sha256="655d64878185f1066590c4acafcd76e6b48c6626e03e5c331371caa735a5193b",
        campaign_definition_sha256="1383c18b231d67fb94e6cc2b26dc9d670a6f2e2923ba169af350a37dfb39d380",
        prompt_sha256="c69e7e311f2d2c728d41573a7512276a94ca6d7360d06d1f3f8b2e37b5bb42d3",
    )
    approval = load_lineage_transition(root, ticket)
    assert approval is not None
    assert approval.next_generation == 11
    assert approval.previous_request_sha256 == ticket.previous_terminal_request_sha256
    assert approval.target_definition_sha256 == ticket.campaign_definition_sha256
    assert approval.target_prompt_sha256 == ticket.prompt_sha256
    assert approval.source_ticket_contexts == ()


def test_consumed_canary_generation_keeps_its_original_release_boundary():
    """A repair must not reinterpret the already consumed generation five."""
    from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition

    root = Path(__file__).resolve().parents[1]
    ticket = CatalogLaunchTicketV1(
        schema_version="1", request_id="01a09a8f-edbd-731a-960b-07d35093f827",
        campaign_key="catalog-fast-canary-v1", launch_generation=5,
        previous_terminal_request_sha256="b0b7ccec0aa237cf8d84b39914c52d1db58a75e6d83f619ec174cf820f5fa82e",
        campaign_definition_sha256="cfd429946702b469aaef76d4a8d1573d51a6aeafde915c72c51fb24d9b79da00",
        prompt_sha256="7eeb12311d4d109bb0da25c617ad1684568c47dd6ff0996f3c4f72cc2e633c49",
    )
    approval = load_lineage_transition(root, ticket)
    assert approval is not None
    assert approval.previous_request_sha256 == ticket.previous_terminal_request_sha256
    assert approval.target_definition_sha256 == ticket.campaign_definition_sha256
    assert approval.target_prompt_sha256 == ticket.prompt_sha256


def test_post308_canary_preserves_consumed_generation_and_requires_generation_six_boundary():
    """The failed #308 boundary stays historical; only its successor may migrate."""
    from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition

    root = Path(__file__).resolve().parents[1]
    prompt_hash = hashlib.sha256((root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()).hexdigest()
    consumed = CatalogLaunchTicketV1(
        schema_version="1", request_id="01a09a8f-edbd-731a-960b-07d35093f827",
        campaign_key="catalog-fast-canary-v1", launch_generation=5,
        previous_terminal_request_sha256="b0b7ccec0aa237cf8d84b39914c52d1db58a75e6d83f619ec174cf820f5fa82e",
        campaign_definition_sha256="cfd429946702b469aaef76d4a8d1573d51a6aeafde915c72c51fb24d9b79da00",
        prompt_sha256=prompt_hash,
    )
    consumed_boundary = load_lineage_transition(root, consumed)
    assert consumed_boundary is not None
    assert consumed_boundary.next_generation == 5
    assert consumed_boundary.previous_request_sha256 == consumed.previous_terminal_request_sha256
    assert consumed_boundary.target_definition_sha256 == consumed.campaign_definition_sha256

    successor = CatalogLaunchTicketV1(
        schema_version="1", request_id="01a09a8f-edbd-731a-960b-07d35093f828",
        campaign_key=consumed.campaign_key, launch_generation=6,
        previous_terminal_request_sha256="362e3456c1ccbb00e1c40b0331ba53f8fdf697731ecb83a0537b4b30fda5fbfc",
        campaign_definition_sha256=consumed.campaign_definition_sha256,
        prompt_sha256=prompt_hash,
    )
    successor_boundary = load_lineage_transition(root, successor)
    assert successor_boundary is not None
    assert successor_boundary.previous_request_sha256 == "362e3456c1ccbb00e1c40b0331ba53f8fdf697731ecb83a0537b4b30fda5fbfc"
    assert successor_boundary.next_generation == 6
    assert successor_boundary.target_definition_sha256 == "66e9289acb4bdbf527a6cb68c48ea2550654b786463f367576801bfdd0523bf3"
    assert successor_boundary.target_prompt_sha256 == prompt_hash

    after_expired = successor.model_copy(update={
        "launch_generation": 7,
        "previous_terminal_request_sha256": "67776ce5015c762184bdd8eb01fb2aca8c598c186dfeb656b64bdd41c271d53c",
        "campaign_definition_sha256": successor_boundary.target_definition_sha256,
    })
    next_boundary = load_lineage_transition(root, after_expired)
    assert next_boundary is not None
    assert next_boundary.next_generation == 7
    assert next_boundary.previous_request_sha256 == after_expired.previous_terminal_request_sha256
    # Generation seven was consumed by request 323; preserve its release boundary.
    assert next_boundary.target_definition_sha256 == "53d55700dd84340a154184c2c32594e7710ef278ce1f6096475fc72e7d982fc5"
    assert next_boundary.target_prompt_sha256 == prompt_hash


def _available_models():
    state, request, approval = _lineage_boundary()
    previous = state.campaigns[0].request
    ticket = CatalogLaunchTicketV1(
        schema_version="1", request_id=request.request_id, campaign_key=previous.campaign_key,
        launch_generation=7, previous_terminal_request_sha256=previous.request_sha256,
        campaign_definition_sha256=previous.campaign_definition_sha256,
        prompt_sha256=previous.prompt_sha256,
    )
    journal = _ticket_journal(ticket=ticket, state="available", submission_key_sha256=None,
        request_sha256=None, issue_number=None, created_at=NOW, updated_at=NOW)
    status = CatalogRequesterCampaignStatusV1.create(campaign_key=ticket.campaign_key,
        state="ticket_available", launch_generation=7, launch_ticket_sha256=ticket.launch_ticket_sha256,
        updated_at=NOW)
    return previous, approval, ticket, journal, status


def test_available_migration_preserves_identity_predecessor_and_old_models():
    from aurora.infra.sp500_megarun.catalog_lineage_migration import prepare_available_lineage_models

    previous, approval, ticket, journal, status = _available_models()
    originals = [model.model_dump_json() for model in (previous, ticket, journal, status)]
    updated = prepare_available_lineage_models(previous_request=previous, transition=approval,
        ticket=ticket, journal=journal, status=status, observed_at=NOW + timedelta(seconds=1))
    next_ticket, next_journal, next_status = updated
    assert next_ticket.request_id == ticket.request_id
    assert next_ticket.launch_generation == 7
    assert next_ticket.previous_terminal_request_sha256 == previous.request_sha256
    assert next_ticket.campaign_definition_sha256 == "a" * 64
    assert next_ticket.prompt_sha256 == "b" * 64
    assert next_journal.ticket == next_ticket
    assert next_journal.created_at == NOW
    assert next_journal.state == "available"
    assert next_status.launch_ticket_sha256 == next_ticket.launch_ticket_sha256
    assert next_status.state == "ticket_available"
    assert [model.model_dump_json() for model in (previous, ticket, journal, status)] == originals
    assert prepare_available_lineage_models(previous_request=previous, transition=approval,
        ticket=next_ticket, journal=next_journal, status=next_status,
        observed_at=NOW + timedelta(seconds=2)) == updated


@pytest.mark.parametrize("permission", ["exact", "missing", "wrong_definition", "wrong_prompt",
    "wrong_generation", "wrong_predecessor", "claimed"])
def test_unused_intermediate_ticket_requires_exact_protected_source_permission(permission):
    from aurora.infra.sp500_megarun.catalog_lineage_migration import prepare_available_lineage_models

    previous, approval, ticket, _, _ = _available_models()
    ticket = CatalogLaunchTicketV1.model_validate({**ticket.model_dump(),
        "campaign_definition_sha256": "c" * 64, "prompt_sha256": "d" * 64})
    if permission == "wrong_generation":
        ticket = CatalogLaunchTicketV1.model_validate({**ticket.model_dump(), "launch_generation": 8})
    elif permission == "wrong_predecessor":
        ticket = CatalogLaunchTicketV1.model_validate({**ticket.model_dump(), "previous_terminal_request_sha256": "e" * 64})
    journal = _ticket_journal(ticket=ticket, state="claiming" if permission == "claimed" else "available",
        submission_key_sha256="e" * 64 if permission == "claimed" else None,
        request_sha256=None, issue_number=None, created_at=NOW, updated_at=NOW)
    status = CatalogRequesterCampaignStatusV1.create(campaign_key=ticket.campaign_key,
        state="ticket_available", launch_generation=ticket.launch_generation, launch_ticket_sha256=ticket.launch_ticket_sha256,
        updated_at=NOW)
    if permission != "missing":
        approval = type(approval).model_validate({**approval.model_dump(), "source_ticket_contexts": [{
            "campaign_definition_sha256": ("e" if permission == "wrong_definition" else "c") * 64,
            "prompt_sha256": ("e" if permission == "wrong_prompt" else "d") * 64,
        }]})
    before = [model.model_dump_json() for model in (previous, ticket, journal, status)]
    def prepare():
        return prepare_available_lineage_models(previous_request=previous, transition=approval,
            ticket=ticket, journal=journal, status=status, observed_at=NOW + timedelta(seconds=1))
    if permission == "exact":
        migrated, next_journal, next_status = prepare()
        assert migrated.request_id == ticket.request_id
        assert migrated.launch_generation == 7
        assert migrated.previous_terminal_request_sha256 == previous.request_sha256
        assert (migrated.campaign_definition_sha256, migrated.prompt_sha256) == ("a" * 64, "b" * 64)
        assert next_journal.state == "available"
        assert next_journal.ticket == migrated
        assert next_status.launch_ticket_sha256 == migrated.launch_ticket_sha256
        assert not approval.authorizes(previous, ticket)
        assert approval.authorizes(previous, migrated)
    else:
        with pytest.raises(ValueError, match="REQUESTER_LINEAGE_MIGRATION_INVALID"):
            prepare()
    assert [model.model_dump_json() for model in (previous, ticket, journal, status)] == before


@pytest.mark.parametrize("defect", ["duplicate", "oversized", "extra_field", "invalid_digest"])
def test_source_ticket_permission_rejects_ambiguous_or_malformed_contexts(defect):
    _, approval, _, _, _ = _available_models()
    context = {"campaign_definition_sha256": "c" * 64, "prompt_sha256": "d" * 64}
    contexts = [context]
    if defect == "duplicate":
        contexts *= 2
    elif defect == "oversized":
        contexts = [{**context, "campaign_definition_sha256": f"{index:064x}"} for index in range(17)]
    elif defect == "extra_field":
        contexts = [{**context, "allow_any_source": True}]
    else:
        contexts = [{**context, "prompt_sha256": "invalid"}]
    with pytest.raises(ValueError):
        type(approval).model_validate({**approval.model_dump(), "source_ticket_contexts": contexts})


@pytest.mark.parametrize("defect", ["claiming", "status_ticket", "ticket_context", "predecessor", "time"])
def test_available_migration_rejects_inconsistent_or_claimed_state(defect):
    from aurora.infra.sp500_megarun.catalog_lineage_migration import prepare_available_lineage_models

    previous, approval, ticket, journal, status = _available_models()
    if defect == "claiming":
        journal = _ticket_journal(ticket=ticket, state="claiming", submission_key_sha256="e" * 64,
            request_sha256=None, issue_number=None, created_at=NOW, updated_at=NOW)
    elif defect == "status_ticket":
        status = CatalogRequesterCampaignStatusV1.create(campaign_key=ticket.campaign_key,
            state="ticket_available", launch_generation=7, launch_ticket_sha256="f" * 64, updated_at=NOW)
    elif defect in {"ticket_context", "predecessor"}:
        field = "campaign_definition_sha256" if defect == "ticket_context" else "previous_terminal_request_sha256"
        ticket = CatalogLaunchTicketV1.model_validate({**ticket.model_dump(), field: "f" * 64})
    with pytest.raises(ValueError, match="REQUESTER_LINEAGE_MIGRATION_INVALID"):
        prepare_available_lineage_models(previous_request=previous, transition=approval,
            ticket=ticket, journal=journal, status=status,
            observed_at=NOW - timedelta(seconds=1) if defect == "time" else NOW)


def _disk_state(tmp_path, *, use_request_hash_as_submission_key=False):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes, canonical_sha256
    from aurora.infra.sp500_megarun.catalog_requester import CatalogRequesterConfigV1
    from aurora.infra.sp500_megarun.catalog_requester_broker import CatalogBrokerProcessingRecordV1
    from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
    from aurora.infra.sp500_megarun.catalog_lineage_transition import CatalogLineageTransitionV1
    from tests.test_inspect_catalog_fast_request import _signed_request

    config = CatalogRequesterConfigV1.model_validate_json(
        (Path(__file__).resolve().parents[1] / "config/catalog_requester_v1.json").read_text("utf-8"))
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    title, body = _signed_request(private, launch_generation=6, previous_terminal_request_sha256="e" * 64)
    previous = parse_catalog_run_request(title, body, public)
    submission_key = previous.intent.submission_key_sha256
    assert submission_key != previous.request_sha256
    if use_request_hash_as_submission_key:
        submission_key = previous.request_sha256
    record = CatalogBrokerProcessingRecordV1.model_construct(
        schema_version="1", stage="signed_before_post", title=title, body=body,
        intent_sha256=previous.intent_sha256, request_sha256=previous.request_sha256,
        request=previous, signed_at=NOW, processing_record_sha256="0" * 64,
    )
    record = CatalogBrokerProcessingRecordV1.model_validate({**record.model_dump(mode="json"),
        "processing_record_sha256": canonical_sha256(record)})
    old_ticket = CatalogLaunchTicketV1(schema_version="1", request_id=previous.request_id,
        campaign_key=previous.campaign_key, launch_generation=6,
        campaign_definition_sha256=previous.campaign_definition_sha256, prompt_sha256=previous.prompt_sha256,
        previous_terminal_request_sha256=previous.previous_terminal_request_sha256)
    ticket = CatalogLaunchTicketV1.model_validate({**old_ticket.model_dump(), "launch_generation": 7,
        "request_id": "018f47a2-6e91-7c34-8000-000000000002",
        "previous_terminal_request_sha256": previous.request_sha256})
    journal = _ticket_journal(ticket=ticket, state="available", submission_key_sha256=None,
        request_sha256=None, issue_number=None, created_at=NOW, updated_at=NOW)
    terminal = _ticket_journal(ticket=old_ticket, state="terminal",
        submission_key_sha256=submission_key, request_sha256=previous.request_sha256,
        issue_number=276, created_at=NOW, updated_at=NOW)
    status = CatalogRequesterCampaignStatusV1.create(campaign_key=ticket.campaign_key,
        state="ticket_available", launch_generation=7, launch_ticket_sha256=ticket.launch_ticket_sha256, updated_at=NOW)
    for relative in (config.broker.campaign_status, config.broker.launch_tickets, config.broker.processing, config.broker.inbox):
        (tmp_path / relative).mkdir(parents=True)
    files = {
        f"{config.broker.campaign_status}/{ticket.campaign_key}.journal.json": journal,
        f"{config.broker.campaign_status}/{ticket.campaign_key}.status.json": status,
        f"{config.broker.launch_tickets}/{ticket.campaign_key}.ticket.json": ticket,
        f"{config.broker.campaign_status}/{ticket.campaign_key}.generation-0000000006.terminal.json": terminal,
        f"{config.broker.processing}/{submission_key}.signed.json": record,
    }
    for relative, model in files.items():
        (tmp_path / relative).write_bytes(canonical_model_bytes(model) + b"\n")
    transition = CatalogLineageTransitionV1(campaign_key=ticket.campaign_key,
        previous_request_sha256=previous.request_sha256, next_generation=7,
        target_definition_sha256="a" * 64, target_prompt_sha256="b" * 64)
    return config, public, transition, files


@pytest.mark.parametrize("defect", [None, "pending_input", "unverified_signature", "missing_terminal", "request_hash_as_submission_key"])
def test_migration_file_proposal_authenticates_history_without_writing_spool(tmp_path, defect):
    from aurora.infra.sp500_megarun.catalog_lineage_migration import prepare_available_lineage_files

    config, public, transition, files = _disk_state(tmp_path,
        use_request_hash_as_submission_key=defect == "request_hash_as_submission_key")
    if defect == "pending_input":
        (tmp_path / config.broker.inbox / "pending.json").write_text("{}")
    elif defect == "unverified_signature":
        public = b"invalid public key"
    elif defect == "missing_terminal":
        next(tmp_path.rglob("*.terminal.json")).unlink()
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    def prepare():
        return prepare_available_lineage_files(broker_root=tmp_path, config=config,
            transition=transition, public_key=public, observed_at=NOW + timedelta(seconds=1))
    if defect:
        with pytest.raises(ValueError, match="REQUESTER_LINEAGE_"):
            prepare()
    else:
        records = prepare()
        assert len(records) == 3
        assert {row["path"] for row in records} == {
            "CatalogRequester/" + relative for relative in files
            if relative.endswith((".journal.json", ".status.json", ".ticket.json"))
        }
        for row in records:
            old = before[row["path"].removeprefix("CatalogRequester/")]
            assert row["expected_old_sha256"] == hashlib.sha256(old).hexdigest()
            assert row["sha256"] == hashlib.sha256(row["content"]).hexdigest()
            assert json.loads(row["content"])["schema_version"] == "1"
    assert {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("intermediate", [False, True])
@pytest.mark.parametrize("defect", [None, "target_definition", "target_prompt", "public_key", "approval_missing"])
def test_candidate_migration_binds_approval_to_packaged_context(tmp_path, defect, intermediate):
    from aurora.infra.sp500_megarun.catalog_lineage_migration import prepare_candidate_lineage_files
    from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import parse_catalog_campaign_definition_bytes

    live = tmp_path / "live"
    live.mkdir()
    config, public, transition, files = _disk_state(live)
    if intermediate:
        from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes

        ticket = next(model for relative, model in files.items() if relative.endswith(".ticket.json"))
        ticket = CatalogLaunchTicketV1.model_validate({**ticket.model_dump(),
            "campaign_definition_sha256": "c" * 64, "prompt_sha256": "d" * 64})
        updated = {
            f"{config.broker.launch_tickets}/{ticket.campaign_key}.ticket.json": ticket,
            f"{config.broker.campaign_status}/{ticket.campaign_key}.journal.json": _ticket_journal(
                ticket=ticket, state="available", submission_key_sha256=None, request_sha256=None,
                issue_number=None, created_at=NOW, updated_at=NOW),
            f"{config.broker.campaign_status}/{ticket.campaign_key}.status.json": CatalogRequesterCampaignStatusV1.create(
                campaign_key=ticket.campaign_key, state="ticket_available", launch_generation=7,
                launch_ticket_sha256=ticket.launch_ticket_sha256, updated_at=NOW),
        }
        for relative, model in updated.items():
            (live / relative).write_bytes(canonical_model_bytes(model) + b"\n")
        transition = type(transition).model_validate({**transition.model_dump(), "source_ticket_contexts": [{
            "campaign_definition_sha256": "c" * 64, "prompt_sha256": "d" * 64,
        }]})
    source = Path(__file__).resolve().parents[1]
    candidate = tmp_path / "candidate"
    registry = json.loads((source / "config/catalog_campaign_registry_v1.json").read_bytes())
    entry = next(row for row in registry["campaigns"] if row["campaign_key"] == transition.campaign_key)
    manifest_bytes = (source / entry["definition_manifest_path"]).read_bytes()
    manifest = parse_catalog_campaign_definition_bytes(manifest_bytes)
    prompt = (source / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()
    transition = transition.model_copy(update={"target_definition_sha256": manifest.campaign_definition_sha256,
        "target_prompt_sha256": hashlib.sha256(prompt).hexdigest()})
    if defect in {"target_definition", "target_prompt"}:
        transition = transition.model_copy(update={defect + "_sha256": "f" * 64})
    assets = {
        "config/catalog_requester_v1.json": config.model_dump_json().encode(),
        "config/catalog_requester_public_key_v1.pem": public,
        "config/catalog_campaign_registry_v1.json": json.dumps({"schema_version": "1", "campaigns": [entry]}).encode(),
        entry["definition_manifest_path"]: manifest_bytes,
        "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md": prompt,
        "config/catalog_lineage_transitions_v1.json": json.dumps({"schema_version": "1", "transitions":
            [] if defect == "approval_missing" else [transition.model_dump(mode="json")]}).encode(),
    }
    for relative, content in assets.items():
        path = candidate / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (live / "config").mkdir()
    for relative in ("config/catalog_requester_v1.json", "config/catalog_requester_public_key_v1.pem"):
        (live / relative).write_bytes(assets[relative])
    if defect == "public_key":
        (candidate / "config/catalog_requester_public_key_v1.pem").write_bytes(b"different key")
    before = {path.relative_to(live): path.read_bytes() for path in live.rglob("*") if path.is_file()}
    if defect:
        with pytest.raises(ValueError, match="REQUESTER_LINEAGE_"):
            prepare_candidate_lineage_files(broker_root=live, candidate_root=candidate, observed_at=NOW)
    else:
        records = prepare_candidate_lineage_files(broker_root=live, candidate_root=candidate, observed_at=NOW)
        assert len(records) == 3
        ticket = json.loads(next(row["content"] for row in records if row["path"].endswith(".ticket.json")))
        assert ticket["campaign_definition_sha256"] == manifest.campaign_definition_sha256
        assert ticket["prompt_sha256"] == hashlib.sha256(prompt).hexdigest()
    assert {path.relative_to(live): path.read_bytes() for path in live.rglob("*") if path.is_file()} == before
    if defect is None:
        for row in records:
            (live / row["path"].removeprefix("CatalogRequester/")).write_bytes(row["content"])
        assert prepare_candidate_lineage_files(broker_root=live, candidate_root=candidate,
            observed_at=NOW + timedelta(seconds=1)) == ()
