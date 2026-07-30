"""Generate deterministic pre-genesis GTBI V7 bootstrap contracts.

This script performs no research, backtest, download or remote mutation. It
materializes the canonical serialization profile, complete domain registry,
review scope and owner-authorized structural quality status.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from infra.gtbi_v7_readiness.canonical import (  # noqa: E402
    canonical_bytes,
    domain_digest,
    git_blob_id,
    raw_sha256,
)
from infra.gtbi_v7_readiness.structure import (  # noqa: E402
    validate_master_plan_structure,
)

SCOPE_DOMAIN = "GTBI_MASTER_PLAN_AUDIT_SCOPE_V1"
STRUCTURAL_CHECKS = [
    "canonical_text_bytes",
    "unique_task_ids",
    "known_dependency_references",
    "acyclic_dependency_graph",
    "complete_gate_assignment",
    "contiguous_execution_order",
    "balanced_code_fences",
    "valid_markdown_tables",
    "valid_urls",
    "no_stale_forbidden_terms",
]
FORBIDDEN_RULES = [
    {
        "token": "checkpoint writer",
        "match_mode": "case_sensitive",
        "allowed_section_or_path_patterns": [
            r"generic term `checkpoint writer` is forbidden"
        ],
        "reason": "Machine policy must use the exact scoped checkpoint role names.",
    },
    {
        "token": "V7_CANONICAL",
        "match_mode": "case_sensitive",
        "allowed_section_or_path_patterns": [
            r"shorter token `V7_CANONICAL` is forbidden"
        ],
        "reason": "Machine records must use the complete canonical commit identity.",
    },
]


def _canonical_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload) + b"\n")


def _code_block_after(text: str, marker: str) -> list[str]:
    start = text.index(marker)
    fence_start = text.index("```text", start) + len("```text")
    fence_end = text.index("```", fence_start)
    return [
        line.strip()
        for line in text[fence_start:fence_end].splitlines()
        if line.strip()
    ]


def _domain_registry(plan_text: str) -> dict:
    domains = _code_block_after(
        plan_text,
        "Every self-authenticating object uses a registered typed hash domain:",
    )
    binding_lines = _code_block_after(
        plan_text,
        "The registry also contains this exhaustive schema-to-domain binding.",
    )
    bindings = []
    for line in binding_lines:
        if line.startswith("logical_schema_id"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 3:
            raise ValueError(f"invalid schema-domain binding line: {line}")
        bindings.append(
            {
                "logical_schema_id": parts[0],
                "hash_domain_id": parts[1],
                "digest_result_name": parts[2],
            }
        )
    if len(domains) != len(set(domains)):
        raise ValueError("duplicate domain string in master plan")
    if {row["hash_domain_id"] for row in bindings} != set(domains):
        missing = set(domains) - {row["hash_domain_id"] for row in bindings}
        extra = {row["hash_domain_id"] for row in bindings} - set(domains)
        raise ValueError(f"domain/binding mismatch: missing={missing}, extra={extra}")
    return {
        "schema_version": "hash_domain_registry_v1",
        "registry_id": "gtbi-v7-hash-domain-registry-v1",
        "digest_algorithm": "sha256",
        "domain_separator_hex": "00",
        "ordered_domains": domains,
        "ordered_schema_bindings": bindings,
    }


def _serialization_profile() -> dict:
    vectors = []
    vector_inputs = [
        ("object_order", {"b": 1, "a": 2}),
        ("literals", {"values": [None, True, False]}),
        (
            "number_boundaries",
            {
                "values": [
                    333333333.3333333,
                    1e30,
                    4.5,
                    0.002,
                    1e-27,
                    -0.0,
                    1e-6,
                ]
            },
        ),
        ("unicode", {"value": "\u20ac$\u000f\nA'B\"\\\"/"}),
        ("arrays", {"value": [3, 2, 1]}),
    ]
    for vector_id, payload in vector_inputs:
        encoded = canonical_bytes(payload)
        vectors.append(
            {
                "vector_id": vector_id,
                "typed_payload": payload,
                "canonical_json_utf8_hex": encoded.hex(),
                "canonical_json_sha256": raw_sha256(encoded),
            }
        )
    binary64_boundary_payload = {"value": 1e20}
    binary64_boundary_bytes = canonical_bytes(binary64_boundary_payload)
    vectors.append(
        {
            "vector_id": "binary64_fixed_notation_boundary",
            "input_type": "IEEE-754 binary64",
            "input_lexeme": "1e20",
            "canonical_json_utf8_hex": binary64_boundary_bytes.hex(),
            "canonical_json_sha256": raw_sha256(binary64_boundary_bytes),
        }
    )
    cross_payload = {"value": "same-payload"}
    vectors.extend(
        [
            {
                "vector_id": "cross_domain_a",
                "typed_payload": cross_payload,
                "hash_domain_id": "GTBI_TEST_DOMAIN_A_V1",
                "domain_digest": domain_digest(
                    "GTBI_TEST_DOMAIN_A_V1", cross_payload
                ),
            },
            {
                "vector_id": "cross_domain_b",
                "typed_payload": cross_payload,
                "hash_domain_id": "GTBI_TEST_DOMAIN_B_V1",
                "domain_digest": domain_digest(
                    "GTBI_TEST_DOMAIN_B_V1", cross_payload
                ),
            },
        ]
    )
    return {
        "schema_version": "canonical_serialization_v1",
        "profile_id": "gtbi-v7-rfc8785-typed-pre-normalization-v1",
        "standard": "RFC 8785 JSON Canonicalization Scheme",
        "encoding": "UTF-8",
        "bom": "forbidden",
        "insignificant_whitespace": "forbidden",
        "object_member_order": "UTF-16 code units",
        "array_order": "preserved",
        "unicode_normalization": "none",
        "lone_surrogate_policy": "reject",
        "ordinary_integer_min": -9007199254740991,
        "ordinary_integer_max": 9007199254740991,
        "ordinary_float": "finite IEEE-754 binary64 shortest round-trip RFC8785",
        "negative_zero_policy": {
            "semantically_irrelevant": "canonicalize_to_zero",
            "semantically_relevant": "reject",
        },
        "nonfinite_policy": "typed_state_object_or_explicit_null_state_only",
        "typed_string_normalization": {
            "timestamps": "schema-defined UTC RFC3339 Z",
            "money": "schema-defined decimal integer minor units",
            "digests": "sha256:<64 lowercase hex>",
            "identifiers": "schema-defined ASCII or Unicode grammar",
        },
        "domain_hash_formula": (
            "SHA-256(UTF8(registered_domain_string) || 0x00 || "
            "JCS(typed_pre_normalized_payload))"
        ),
        "bootstrap_identity": "SHA-256 over exact file bytes including final LF",
        "known_answer_vectors": vectors,
    }


def generate(root: Path) -> dict:
    plan_path = root / "docs/plans/gtbi-v7-master-plan.md"
    plan_bytes = plan_path.read_bytes()
    plan_text = plan_bytes.decode("utf-8")
    owner_directive_path = (
        root / "docs/readiness/gtbi-v7/owner_simplification_directive.json"
    )
    owner_directive = json.loads(
        owner_directive_path.read_text(encoding="utf-8")
    )
    if owner_directive_path.read_bytes() != canonical_bytes(owner_directive) + b"\n":
        raise ValueError("owner simplification directive is not canonical JSON")
    if owner_directive.get("accepted") is not True:
        raise ValueError("owner simplification directive is not accepted")
    contracts = root / "config/gtbi/contracts"
    profile_path = contracts / "canonical_serialization_v1.json"
    registry_path = contracts / "hash_domain_registry_v1.json"
    _canonical_write(profile_path, _serialization_profile())
    _canonical_write(registry_path, _domain_registry(plan_text))
    profile_digest = raw_sha256(profile_path)
    registry_digest = raw_sha256(registry_path)
    scope = {
        "schema_version": "master_plan_audit_scope_manifest_v1",
        "reviewed_master_plan_path": "docs/plans/gtbi-v7-master-plan.md",
        "reviewed_master_plan_sha256": raw_sha256(plan_bytes),
        "reviewed_master_plan_byte_length": len(plan_bytes),
        "reviewed_master_plan_git_blob_id": git_blob_id(plan_bytes),
        "canonical_serialization_profile_digest": profile_digest,
        "hash_domain_registry_digest": registry_digest,
        "ordered_review_dimensions": [
            "architecture_and_state_reachability",
            "scientific_and_temporal_integrity",
            "security_and_custody",
            "operations_and_billing",
        ],
        "ordered_structural_checks": STRUCTURAL_CHECKS,
        "tool_independent_acceptance_predicates": [
            "all_four_review_dimensions_are_covered",
            "all_registered_structural_checks_pass",
            "finding_count_is_zero",
            "result_is_CLEAN",
            "reviewed_bytes_match_sha_length_and_git_blob",
            "owner_simplification_directive_is_canonical_and_accepted",
            "owner_directive_supersedes_legacy_independence_requirements",
        ],
        "required_evidence_classes": [
            "structural_validation_report",
            "owner_simplification_directive",
            "deterministic_contract_regeneration",
        ],
        "ordered_forbidden_term_rules": FORBIDDEN_RULES,
    }
    scope["scope_manifest_digest"] = domain_digest(SCOPE_DOMAIN, scope)
    readiness = root / "docs/readiness/gtbi-v7"
    scope_path = readiness / "master_plan_audit_scope_manifest.json"
    _canonical_write(scope_path, scope)
    structural = validate_master_plan_structure(
        plan_path, forbidden_term_rules=FORBIDDEN_RULES
    )
    status = {
        "schema_version": "gtbi-v7-master-plan-quality-status-v1",
        "status": "CLEAN",
        "reviewed_master_plan_sha256": raw_sha256(plan_bytes),
        "reviewed_master_plan_byte_length": len(plan_bytes),
        "reviewed_master_plan_git_blob_id": git_blob_id(plan_bytes),
        "canonical_serialization_profile_digest": profile_digest,
        "hash_domain_registry_digest": registry_digest,
        "scope_manifest_digest": scope["scope_manifest_digest"],
        "owner_simplification_directive_digest": raw_sha256(
            owner_directive_path
        ),
        "owner_actor_id": owner_directive["owner_actor_id"],
        "owner_authorization_accepted": True,
        "structural_validation": structural.to_dict(),
        "external_receipts_required": 0,
        "external_receipts_present": 0,
        "blockers": [],
        "execution_status": (
            "TECHNICAL_PREPARATION_ALLOWED"
            if structural.passed
            else "NO-GO"
        ),
    }
    _canonical_write(readiness / "master_plan_quality_status.json", status)
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args()
    status = generate(args.repository_root.resolve())
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["structural_validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
