from __future__ import annotations

import ast
from base64 import b64encode
from hashlib import sha256
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import pytest

from aurora.infra.sp500_megarun.catalog_request_contract import (
    _attestation_payload,
    canonical_model_bytes,
    CatalogLaunchTicketV1,
    CatalogRunIntentDraftV1,
    CatalogRunIntentV1,
)
from aurora.infra.sp500_megarun.catalog_run_request import (
    CatalogRunRequestV1,
    parse_catalog_run_request,
)


ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000001"
CAMPAIGN_DEFINITION = "1" * 64
PROMPT = "2" * 64
REQUESTER_TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
REQUESTER_TEST_PUBLIC_KEY = REQUESTER_TEST_PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)
GOLDEN_TICKET = ROOT / "tests/fixtures/catalog_launch_ticket_cross_runtime_v1.json"
GOLDEN_REQUEST = ROOT / "tests/fixtures/catalog_request_cross_runtime_v1.json"
GOLDEN_PUBLIC_KEY = (
    ROOT / "tests/fixtures/catalog_request_cross_runtime_public_key_v1.pem"
)


def _public_key_sha256(private_key: rsa.RSAPrivateKey) -> str:
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return sha256(public_der).hexdigest()


def sign_request_fixture(
    *, payload: dict[str, object], private_key: rsa.RSAPrivateKey
) -> dict[str, object]:
    intent = CatalogRunIntentV1.model_validate(payload)
    title = f"[AURORA CATALOG RUN REQUEST] {intent.request_id}"
    signature = private_key.sign(
        _attestation_payload(title, intent),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256().digest_size,
        ),
        hashes.SHA256(),
    )
    return {
        **payload,
        "requester_public_key_sha256": _public_key_sha256(private_key),
        "requester_attestation_algorithm": "rsa-pss-sha256-v1",
        "requester_attestation_b64": b64encode(signature).decode("ascii"),
    }


def _signed_body(**updates: object) -> str:
    payload: dict[str, object] = {
        "schema_version": "1",
        "request_id": REQUEST_ID,
        "campaign_key": "sp500-optimized-catalog-v1",
        "launch_generation": 1,
        "launch_ticket_sha256": "3" * 64,
        "previous_terminal_request_sha256": None,
        "campaign_definition_sha256": CAMPAIGN_DEFINITION,
        "prompt_sha256": PROMPT,
        "authorization": "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        "free_resources_only": True,
        "automatic_recovery": True,
        "max_same_failure_count": 3,
    }
    signed = sign_request_fixture(
        payload=payload,
        private_key=REQUESTER_TEST_PRIVATE_KEY,
    )
    signed.update(updates)
    canonical = json.dumps(
        signed,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "```json\n" + canonical + "\n```\n"


def test_parses_one_exact_non_executable_request() -> None:
    request = parse_catalog_run_request(
        f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}",
        _signed_body(),
        trusted_public_key=REQUESTER_TEST_PUBLIC_KEY,
    )
    assert isinstance(request, CatalogRunRequestV1)
    assert request.campaign_key == "sp500-optimized-catalog-v1"
    assert len(request.intent_sha256) == 64
    assert len(request.request_sha256) == 64


@pytest.mark.parametrize(
    "title,body",
    [
        ("wrong", _signed_body()),
        (f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}", "text\n" + _signed_body()),
        (
            f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}",
            _signed_body(command="rm"),
        ),
        (
            f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}",
            _signed_body(free_resources_only=False),
        ),
        (
            f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}",
            _signed_body(max_same_failure_count=4),
        ),
        (
            f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}",
            _signed_body().replace(
                '"schema_version":"1"',
                '"schema_version":"1","schema_version":"1"',
            ),
        ),
        (
            "[AURORA CATALOG RUN REQUEST] 018f47a2-6e91-6c34-8000-000000000001",
            _signed_body().replace(
                REQUEST_ID, "018f47a2-6e91-6c34-8000-000000000001"
            ),
        ),
    ],
)
def test_rejects_ambiguous_or_executable_requests(title: str, body: str) -> None:
    with pytest.raises(ValueError, match="CATALOG_REQUEST_INVALID"):
        parse_catalog_run_request(
            title,
            body,
            trusted_public_key=REQUESTER_TEST_PUBLIC_KEY,
        )


def test_rejects_noncanonical_json_whitespace() -> None:
    body = _signed_body().replace('\":\"', '\": \"')
    with pytest.raises(ValueError, match="CATALOG_REQUEST_NONCANONICAL"):
        parse_catalog_run_request(
            f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}",
            body,
            trusted_public_key=REQUESTER_TEST_PUBLIC_KEY,
        )


def test_any_title_or_body_edit_breaks_requester_attestation() -> None:
    title = f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}"
    body = _signed_body()
    for edited_title, edited_body in (
        (title + "x", body),
        (title, body.replace("sp500-optimized", "sp500-altered")),
        (title, body.replace('"prompt_sha256":"' + PROMPT, '"prompt_sha256":"' + "4" * 64)),
    ):
        with pytest.raises(ValueError, match="CATALOG_REQUEST_"):
            parse_catalog_run_request(
                edited_title,
                edited_body,
                trusted_public_key=REQUESTER_TEST_PUBLIC_KEY,
            )


def test_rejects_wrong_public_key_and_fingerprint() -> None:
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_public = wrong_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(ValueError, match="CATALOG_REQUEST_ATTESTATION_INVALID"):
        parse_catalog_run_request(
            f"[AURORA CATALOG RUN REQUEST] {REQUEST_ID}",
            _signed_body(),
            trusted_public_key=wrong_public,
        )


def test_request_contains_no_execution_choices() -> None:
    allowed_intent = {
        "schema_version",
        "request_id",
        "campaign_key",
        "launch_generation",
        "launch_ticket_sha256",
        "previous_terminal_request_sha256",
        "campaign_definition_sha256",
        "prompt_sha256",
        "authorization",
        "free_resources_only",
        "automatic_recovery",
        "max_same_failure_count",
    }
    assert set(CatalogRunIntentDraftV1.model_fields) == allowed_intent
    assert set(CatalogRunRequestV1.model_fields) == allowed_intent | {
        "requester_public_key_sha256",
        "requester_attestation_algorithm",
        "requester_attestation_b64",
    }
    assert not {
        "commit",
        "commit_sha",
        "ref",
        "path",
        "workflow",
        "workers",
        "parameters",
        "command",
    } & set(CatalogRunRequestV1.model_fields)


def test_launch_ticket_enforces_uuid7_and_generation_predecessor_shape() -> None:
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=REQUEST_ID,
        campaign_key="sp500-optimized-catalog-v1",
        launch_generation=1,
        campaign_definition_sha256=CAMPAIGN_DEFINITION,
        prompt_sha256=PROMPT,
        previous_terminal_request_sha256=None,
    )
    assert len(ticket.launch_ticket_sha256) == 64
    with pytest.raises(ValueError):
        ticket.model_copy(
            update={"launch_generation": 2},
        ).__class__.model_validate(
            {**ticket.model_dump(mode="json"), "launch_generation": 2}
        )
    with pytest.raises(ValueError):
        CatalogLaunchTicketV1.model_validate(
            {
                **ticket.model_dump(mode="json"),
                "request_id": "018f47a2-6e91-6c34-8000-000000000001",
            }
        )


def test_contract_import_boundary_is_pure() -> None:
    path = ROOT / "infra/sp500_megarun/catalog_request_contract.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    assert roots <= {
        "__future__",
        "hashlib",
        "json",
        "re",
        "typing",
        "uuid",
        "pydantic",
    }
    assert "cryptography" not in path.read_text(encoding="utf-8")


def test_cross_runtime_golden_ticket_and_request() -> None:
    ticket_vector = json.loads(GOLDEN_TICKET.read_text(encoding="utf-8"))
    request_vector = json.loads(GOLDEN_REQUEST.read_text(encoding="utf-8"))
    ticket = CatalogLaunchTicketV1.model_validate(ticket_vector["ticket"])
    assert canonical_model_bytes(ticket).decode("utf-8") == ticket_vector["canonical_ticket_json"]
    assert ticket.launch_ticket_sha256 == ticket_vector["launch_ticket_sha256"]
    request = parse_catalog_run_request(
        request_vector["title"],
        request_vector["body"],
        trusted_public_key=GOLDEN_PUBLIC_KEY.read_bytes(),
    )
    assert canonical_model_bytes(request.intent).decode("utf-8") == request_vector[
        "canonical_intent_json"
    ]
    assert request.intent_sha256 == request_vector["intent_sha256"]
    assert request.request_sha256 == request_vector["request_sha256"]
    assert request.launch_ticket_sha256 == ticket.launch_ticket_sha256
    assert request.request_id == ticket.request_id
    assert request.campaign_key == ticket.campaign_key


def test_no_private_key_bytes_are_tracked_or_printed(capsys: pytest.CaptureFixture[str]) -> None:
    for path in (GOLDEN_TICKET, GOLDEN_REQUEST, GOLDEN_PUBLIC_KEY):
        data = path.read_bytes()
        assert b"PRIVATE KEY" not in data
        assert b"BEGIN RSA PRIVATE" not in data
    _signed_body()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
