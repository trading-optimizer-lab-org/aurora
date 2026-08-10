from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.sec_listing_identity import (
    build_current_sec_universe,
)
from aurora.research.openap_181.sec_spinoff import (
    SPINOFF_FORMULA_SHA256,
    SPINOFF_FORMULA_URL,
    calculate_sec_spinoff_current,
    select_sec_spinoff_filing_candidates,
)
from aurora.research.openap_181.sec_spinoff_access import (
    download_sec_spinoff_candidate_documents,
)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_csv_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _indexed_paths(root: Path, *, prefix: str, suffix: str) -> dict[int, Path]:
    pattern = re.compile(rf"^{re.escape(prefix)}([0-9]{{3}}){re.escape(suffix)}$")
    indexed: dict[int, Path] = {}
    for path in sorted(root.rglob(f"{prefix}*{suffix}")):
        match = pattern.fullmatch(path.name)
        if match is None:
            continue
        chunk = int(match.group(1))
        if chunk in indexed:
            raise RuntimeError(f"Duplicate SEC {prefix} shard {chunk:03d}")
        indexed[chunk] = path
    if set(indexed) != set(range(48)):
        raise RuntimeError(f"SEC {prefix} shards are incomplete")
    return indexed


def _sec_submissions_contract(
    root: Path,
    *,
    formation_at: pd.Timestamp,
) -> tuple[list[Path], dict[str, Any]]:
    submissions = _indexed_paths(
        root,
        prefix="sec_submissions_",
        suffix=".parquet",
    )
    summaries = _indexed_paths(root, prefix="sec_summary_", suffix=".json")
    rows = 0
    retrieved_values: list[pd.Timestamp] = []
    summary_hashes: dict[str, str] = {}
    for chunk in range(48):
        payload = json.loads(summaries[chunk].read_text(encoding="utf-8"))
        retrieved = pd.to_datetime(
            payload.get("retrieved_at"), errors="coerce", utc=True
        )
        if (
            int(payload.get("chunk_index", -1)) != chunk
            or int(payload.get("total_chunks", 0)) != 48
            or payload.get("source_layout")
            != "official_api_shards_with_audited_readthrough"
            or int(payload.get("submissions_rows", 0)) <= 0
            or payload.get("locked_opened") is not False
            or pd.isna(retrieved)
            or pd.Timestamp(retrieved) > formation_at
        ):
            raise RuntimeError(
                f"SEC submissions shard {chunk:03d} summary contract is invalid"
            )
        rows += int(payload["submissions_rows"])
        retrieved_values.append(pd.Timestamp(retrieved))
        summary_hashes[summaries[chunk].name] = _sha256(summaries[chunk])
    evidence = {
        "source_layout": "48_verified_sec_official_api_shards",
        "submissions_rows": rows,
        "retrieved_at_min": min(retrieved_values).isoformat(),
        "retrieved_at_max": max(retrieved_values).isoformat(),
        "submissions_sha256": {
            submissions[index].name: _sha256(submissions[index])
            for index in range(48)
        },
        "summary_sha256": summary_hashes,
    }
    return [submissions[index] for index in range(48)], evidence


def _formula_contract(root: Path) -> Path:
    matches = sorted(root.rglob("openap_181_formula_inventory.csv"))
    if len(matches) != 1:
        raise RuntimeError("Expected one pinned OpenAP formula inventory")
    inventory = pd.read_csv(matches[0], keep_default_na=False)
    hash_column = "formula_sha256" if "formula_sha256" in inventory else "sha256"
    selected = inventory.loc[inventory["signal"].eq("Spinoff")]
    if (
        len(selected) != 1
        or str(selected.iloc[0][hash_column]) != SPINOFF_FORMULA_SHA256
        or str(selected.iloc[0].get("source_url", "")) != SPINOFF_FORMULA_URL
    ):
        raise RuntimeError("Pinned Spinoff formula evidence does not match")
    return matches[0]


def _identity_transport_contract(
    path: Path,
    *,
    canonical_json: Path,
    source_url: str,
    retrieved_at: str,
) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SEC identity transport manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("SEC identity transport manifest must be an object")
    method = str(manifest.get("access_method") or "")
    expected_access_url = (
        source_url
        if method == "sec_official_direct"
        else "https://r.jina.ai/http://" + source_url.removeprefix("https://")
    )
    retrieved = pd.to_datetime(retrieved_at, errors="coerce", utc=True)
    manifest_retrieved = pd.to_datetime(
        manifest.get("retrieved_at"), errors="coerce", utc=True
    )
    if (
        method not in {"sec_official_direct", "sec_via_jina_readthrough"}
        or str(manifest.get("source_url") or "") != source_url
        or str(manifest.get("access_url") or "") != expected_access_url
        or pd.isna(retrieved)
        or pd.isna(manifest_retrieved)
        or retrieved != manifest_retrieved
        or re.fullmatch(
            r"[0-9a-f]{64}", str(manifest.get("transport_sha256") or "")
        )
        is None
        or str(manifest.get("canonical_sha256") or "")
        != _sha256(canonical_json)
    ):
        raise RuntimeError("SEC identity transport provenance does not match")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-root", type=Path, required=True)
    parser.add_argument("--current-sec-identity-json", type=Path, required=True)
    parser.add_argument("--current-sec-identity-source-url", required=True)
    parser.add_argument("--identity-retrieved-at", required=True)
    parser.add_argument(
        "--identity-transport-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument("--formula-root", type=Path, required=True)
    parser.add_argument("--sec-source-run-id", required=True)
    parser.add_argument("--formula-source-run-id", required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--formation-at", required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 SEC Spinoff current reconstruction"
    )

    implementation_sha = str(args.implementation_sha).strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", implementation_sha) is None:
        raise ValueError("implementation SHA must be a full hexadecimal commit")
    formation = pd.to_datetime(args.formation_at, errors="coerce", utc=True)
    if pd.isna(formation):
        raise ValueError("formation_at is not a valid timestamp")
    for label, value in {
        "SEC source run": args.sec_source_run_id,
        "formula source run": args.formula_source_run_id,
    }.items():
        if re.fullmatch(r"[1-9][0-9]*", str(value).strip()) is None:
            raise ValueError(f"{label} id must be a positive integer")

    submission_paths, sec_evidence = _sec_submissions_contract(
        args.sec_root,
        formation_at=pd.Timestamp(formation),
    )
    submissions = pd.concat(
        [pd.read_parquet(path) for path in submission_paths],
        ignore_index=True,
    )
    if len(submissions) != int(sec_evidence["submissions_rows"]):
        raise RuntimeError("SEC submissions rows do not match shard summaries")
    try:
        identity_payload = json.loads(
            args.current_sec_identity_json.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("official SEC current identity JSON is invalid") from exc
    identity_transport = _identity_transport_contract(
        args.identity_transport_manifest,
        canonical_json=args.current_sec_identity_json,
        source_url=args.current_sec_identity_source_url,
        retrieved_at=args.identity_retrieved_at,
    )
    identity_retrieved = pd.to_datetime(
        args.identity_retrieved_at,
        errors="coerce",
        utc=True,
    )
    if pd.isna(identity_retrieved) or identity_retrieved > formation:
        raise RuntimeError("SEC current identity is unavailable at formation")
    current_universe, current_rejections = build_current_sec_universe(
        identity_payload,
        retrieved_at=args.identity_retrieved_at,
        source_url=args.current_sec_identity_source_url,
    )
    ambiguous_classes = current_universe.loc[
        current_universe["issuer_share_class_count"].ne(1)
    ].copy()
    if not ambiguous_classes.empty:
        ambiguous_rejections = ambiguous_classes[
            ["cik", "ticker", "exchange_family"]
        ].rename(columns={"exchange_family": "exchange"})
        ambiguous_rejections["reason_if_rejected"] = (
            "ambiguous_current_issuer_share_classes"
        )
        current_rejections = pd.concat(
            [current_rejections, ambiguous_rejections],
            ignore_index=True,
        )
    current_universe = current_universe.loc[
        current_universe["issuer_share_class_count"].eq(1)
    ].reset_index(drop=True)
    if current_universe.empty:
        raise RuntimeError("no unambiguous official SEC current securities remain")
    formula_inventory = _formula_contract(args.formula_root)

    candidates = select_sec_spinoff_filing_candidates(
        submissions,
        current_universe,
        formation_at=formation,
    )
    _, evidence, access_manifest, access_summary = (
        download_sec_spinoff_candidate_documents(
            candidates,
            formation_at=formation,
            user_agent=args.user_agent,
        )
    )
    retrieved = pd.Timestamp(datetime.now(UTC).replace(microsecond=0))
    if not access_manifest.empty:
        manifest_retrieved = pd.to_datetime(
            access_manifest["retrieved_at"], errors="coerce", utc=True
        ).max()
        if pd.notna(manifest_retrieved):
            retrieved = pd.Timestamp(manifest_retrieved)
    values = calculate_sec_spinoff_current(
        evidence,
        current_universe,
        formation_at=formation,
        retrieved_at=retrieved,
    )

    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    output.mkdir(parents=True, exist_ok=True)
    csv_frames = {
        "current_universe_rejected.csv": current_rejections,
        "sec_spinoff_filing_candidates.csv": candidates,
        "sec_spinoff_access_manifest.csv": access_manifest,
        "sec_spinoff_completion_evidence.csv": evidence,
        "openap_149_sec_spinoff_current.csv": values,
    }
    for name, frame in csv_frames.items():
        _write_csv_atomic(output / name, frame)
    parquet_frames = {
        "sec_spinoff_completion_evidence.parquet": evidence,
        "openap_149_sec_spinoff_current.parquet": values,
    }
    for name, frame in parquet_frames.items():
        _write_parquet_atomic(output / name, frame)

    output_names = tuple(csv_frames) + tuple(parquet_frames)
    finite = values.loc[values["current_usable"].eq(True)]  # noqa: E712
    manifest = {
        "implementation_sha": implementation_sha,
        "formation_at": pd.Timestamp(formation).isoformat(),
        "sec_source_run_id": str(args.sec_source_run_id),
        "formula_source_run_id": str(args.formula_source_run_id),
        "identity_source_url": str(args.current_sec_identity_source_url),
        "identity_source_mode": "sec_official_live_with_audited_transport",
        "identity_source_sha256": _sha256(args.current_sec_identity_json),
        "identity_access_url": str(identity_transport["access_url"]),
        "identity_access_method": str(identity_transport["access_method"]),
        "identity_transport_sha256": str(identity_transport["transport_sha256"]),
        "identity_transport_manifest_sha256": _sha256(
            args.identity_transport_manifest
        ),
        "identity_retrieved_at": pd.Timestamp(identity_retrieved).isoformat(),
        "formula_inventory_sha256": _sha256(formula_inventory),
        "formula_sha256": SPINOFF_FORMULA_SHA256,
        "sec_source_evidence": sec_evidence,
        "current_universe_rows": int(len(current_universe)),
        "current_universe_rejected_rows": int(len(current_rejections)),
        "candidate_filing_rows": int(len(candidates)),
        "access_summary": access_summary,
        "completion_evidence_rows": int(len(evidence)),
        "current_output_rows": int(len(values)),
        "finite_current_value_rows": int(len(finite)),
        "signal": "Spinoff",
        "classification": "reconstructed_not_strict",
        "raw_filing_documents_retained": False,
        "current_signal_computed": bool(not finite.empty),
        "strict_score_eligible": False,
        "locked_opened": False,
        "forward_opened": False,
        "output_sha256": {
            name: _sha256(output / name) for name in sorted(output_names)
        },
    }
    _write_json_atomic(output / "openap_149_sec_spinoff_manifest.json", manifest)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
