"""Strict cryptographic verification of one catalog request."""

from __future__ import annotations

from base64 import b64decode
from binascii import Error as BinasciiError
from hashlib import sha256
import json

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from aurora.infra.sp500_megarun.catalog_request_contract import (
    _attestation_payload,
    _BODY,
    _reject_duplicate_keys,
    _reject_nonfinite,
    _TITLE,
    MAX_BODY_BYTES,
    MAX_TITLE_CHARS,
    CatalogRunRequestV1,
)


def parse_catalog_run_request(
    title: str,
    body: str,
    trusted_public_key: bytes,
) -> CatalogRunRequestV1:
    if len(str(title)) > MAX_TITLE_CHARS:
        raise ValueError("CATALOG_REQUEST_INVALID")
    if len(str(body).encode("utf-8")) > MAX_BODY_BYTES:
        raise ValueError("CATALOG_REQUEST_INVALID")
    title_match = _TITLE.fullmatch(str(title))
    body_match = _BODY.fullmatch(str(body))
    if title_match is None or body_match is None:
        raise ValueError("CATALOG_REQUEST_INVALID")
    try:
        payload_text = body_match.group("payload")
        raw = json.loads(
            payload_text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        request = CatalogRunRequestV1.model_validate(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("CATALOG_REQUEST_INVALID") from exc
    if request.request_id != title_match.group("request_id"):
        raise ValueError("CATALOG_REQUEST_INVALID")
    canonical = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    if payload_text != canonical:
        raise ValueError("CATALOG_REQUEST_NONCANONICAL")
    try:
        public_key = serialization.load_pem_public_key(trusted_public_key)
        if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
            raise ValueError("untrusted requester key type/size")
        public_der = public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if sha256(public_der).hexdigest() != request.requester_public_key_sha256:
            raise ValueError("requester public-key fingerprint mismatch")
        public_key.verify(
            b64decode(request.requester_attestation_b64, validate=True),
            _attestation_payload(str(title), request.intent),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=hashes.SHA256().digest_size,
            ),
            hashes.SHA256(),
        )
    except (
        BinasciiError,
        InvalidSignature,
        UnsupportedAlgorithm,
        ValueError,
        TypeError,
    ) as exc:
        raise ValueError("CATALOG_REQUEST_ATTESTATION_INVALID") from exc
    return request
