from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.field_ritter_ipo import (
    build_field_ritter_current_identity,
    calculate_field_ritter_ipo_signals,
    extract_causal_sec_rd_expense,
    load_field_ritter_ipo_workbook,
    select_openap_ipo_rows,
)
from aurora.research.openap_181.sec_companyfacts_149 import (
    build_companyfacts_identity,
)


_EXPECTED_FORMULA_HASHES = {
    "AgeIPO": "e3e6bb214aab63d92c5cbe278462c016d588ab61383cdea8c637b9c12f3f30b3",
    "IndIPO": "351163e16d519066360d6f598ecbdc9779de57fe5620564f67afbd01b1c0c37b",
    "RDIPO": "a6aa23c8388f49a16f710a70835b07be21a043193169704d6ce2b37ba4d3a568",
}


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_many(paths: list[Path], reader: Callable[[Path], pd.DataFrame]) -> pd.DataFrame:
    if not paths:
        raise RuntimeError("No files matched a required SEC input surface")
    return pd.concat([reader(path) for path in paths], ignore_index=True)


def _indexed_sec_paths(
    root: Path,
    *,
    prefix: str,
    suffix: str,
) -> dict[int, Path]:
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
    expected = set(range(48))
    if set(indexed) != expected:
        raise RuntimeError(
            f"SEC {prefix} shards are incomplete: found={sorted(indexed)}"
        )
    return indexed


def _sec_source_contract(
    root: Path,
) -> tuple[list[Path], list[Path], dict[str, Any]]:
    facts = _indexed_sec_paths(
        root,
        prefix="sec_companyfacts_",
        suffix=".parquet",
    )
    statuses = _indexed_sec_paths(
        root,
        prefix="sec_status_",
        suffix=".csv",
    )
    summaries = _indexed_sec_paths(
        root,
        prefix="sec_summary_",
        suffix=".json",
    )
    summary_hashes: dict[str, str] = {}
    companyfacts_rows = 0
    submissions_rows = 0
    status_rows = 0
    retrieved_at_values: list[pd.Timestamp] = []
    for chunk in range(48):
        payload = json.loads(summaries[chunk].read_text(encoding="utf-8"))
        ciks_expected = int(payload.get("ciks_expected", 0))
        companyfacts_ciks_ok = int(payload.get("companyfacts_ciks_ok", 0))
        submissions_ciks_ok = int(payload.get("submissions_ciks_ok", 0))
        retrieved_at = pd.to_datetime(
            payload.get("retrieved_at"), errors="coerce", utc=True
        )
        if (
            int(payload.get("chunk_index", -1)) != chunk
            or int(payload.get("total_chunks", 0)) != 48
            or payload.get("source_layout")
            != "official_api_shards_with_audited_readthrough"
            or ciks_expected <= 0
            or not 0 < companyfacts_ciks_ok <= ciks_expected
            or not 0 < submissions_ciks_ok <= ciks_expected
            or int(payload.get("companyfacts_rows", 0)) <= 0
            or int(payload.get("submissions_rows", 0)) <= 0
            or payload.get("all_facts_have_available_at") is not True
            or payload.get("locked_opened") is not False
            or pd.isna(retrieved_at)
        ):
            raise RuntimeError(f"SEC shard {chunk:03d} summary contract is invalid")
        status = pd.read_csv(statuses[chunk], keep_default_na=False)
        required_status_columns = {
            "cik",
            "symbol",
            "surface",
            "status",
            "source_mode",
            "source_url",
        }
        if (
            not required_status_columns.issubset(status.columns)
            or len(status) != ciks_expected * 2
            or status[["cik", "surface"]].duplicated(keep=False).any()
            or not status["surface"].isin({"companyfacts", "submissions"}).all()
            or not status["status"].isin({"ok", "error"}).all()
            or status["source_url"].astype(str).str.strip().eq("").any()
        ):
            raise RuntimeError(f"SEC shard {chunk:03d} status contract is invalid")
        per_cik_surfaces = status.groupby("cik")["surface"].agg(
            lambda values: frozenset(str(value) for value in values)
        )
        if not per_cik_surfaces.map(
            lambda values: values == {"companyfacts", "submissions"}
        ).all():
            raise RuntimeError(f"SEC shard {chunk:03d} status surfaces are incomplete")
        status_ok_counts = (
            status.loc[status["status"].eq("ok")]
            .groupby("surface")["cik"]
            .nunique()
        )
        if (
            int(status_ok_counts.get("companyfacts", 0)) != companyfacts_ciks_ok
            or int(status_ok_counts.get("submissions", 0)) != submissions_ciks_ok
        ):
            raise RuntimeError(
                f"SEC shard {chunk:03d} success counts disagree with its summary"
            )
        companyfacts_rows += int(payload["companyfacts_rows"])
        submissions_rows += int(payload["submissions_rows"])
        status_rows += len(status)
        retrieved_at_values.append(pd.Timestamp(retrieved_at))
        summary_hashes[f"sec_summary_{chunk:03d}.json"] = _sha256(
            summaries[chunk]
        )
    evidence = {
        "source_layout": "48_verified_sec_official_api_shards",
        "companyfacts_rows": companyfacts_rows,
        "submissions_rows": submissions_rows,
        "status_rows": status_rows,
        "retrieved_at_min": min(retrieved_at_values).isoformat(),
        "retrieved_at_max": max(retrieved_at_values).isoformat(),
        "companyfacts_sha256": {
            path.name: _sha256(path) for path in facts.values()
        },
        "status_sha256": {
            path.name: _sha256(path) for path in statuses.values()
        },
        "summary_sha256": summary_hashes,
    }
    return (
        [facts[chunk] for chunk in range(48)],
        [statuses[chunk] for chunk in range(48)],
        evidence,
    )


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


def _institutional_mapping(
    root: Path,
    *,
    expected_run_id: str,
) -> tuple[pd.DataFrame, dict[str, Any], Path]:
    mapping_paths = sorted(root.rglob("openfigi_cusip_map.parquet"))
    recovery_paths = sorted(
        root.rglob("openap_93_artifact_recovery_manifest.json")
    )
    if len(mapping_paths) != 1 or len(recovery_paths) != 1:
        raise RuntimeError(
            "Expected one selectively recovered OpenFIGI mapping and manifest"
        )
    recovery = json.loads(recovery_paths[0].read_text(encoding="utf-8"))
    if (
        recovery.get("recovery_profile") != "institutional_inputs"
        or str(recovery.get("source_run_id")) != str(expected_run_id)
        or recovery.get("full_artifact_downloaded") is not False
        or recovery.get("locked_opened") is not False
        or recovery.get("validation_used_for_selection") is not False
    ):
        raise RuntimeError("Institutional selective-recovery contract is invalid")
    recovered_hashes = recovery.get("recovered_hashes", {})
    expected_hashes = [
        str(value)
        for name, value in recovered_hashes.items()
        if Path(str(name)).name == mapping_paths[0].name
    ]
    if len(expected_hashes) != 1 or _sha256(mapping_paths[0]) != expected_hashes[0]:
        raise RuntimeError("Recovered OpenFIGI mapping hash does not match")
    mapping = pd.read_parquet(mapping_paths[0])
    expected_rows = int(recovery.get("openfigi_mapping_rows", 0))
    if expected_rows <= 0 or len(mapping) != expected_rows:
        raise RuntimeError("Recovered OpenFIGI mapping row count does not match")
    return mapping, recovery, mapping_paths[0]


def _formula_inventory(root: Path) -> tuple[Path, dict[str, str]]:
    matches = sorted(root.rglob("openap_181_formula_inventory.csv"))
    if len(matches) != 1:
        raise RuntimeError("Expected one pinned OpenAP formula inventory")
    formulas = pd.read_csv(matches[0], keep_default_na=False)
    hash_column = "formula_sha256" if "formula_sha256" in formulas else "sha256"
    actual = formulas.set_index("signal")[hash_column].astype(str).to_dict()
    selected = {signal: actual.get(signal, "") for signal in _EXPECTED_FORMULA_HASHES}
    if selected != _EXPECTED_FORMULA_HASHES:
        raise RuntimeError("Pinned IPO formula hashes do not match the contract")
    return matches[0], selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--field-ritter-workbook", type=Path, required=True)
    parser.add_argument("--field-ritter-source-manifest", type=Path, required=True)
    parser.add_argument("--sec-root", type=Path, required=True)
    parser.add_argument("--institutional-root", type=Path, required=True)
    parser.add_argument("--formula-root", type=Path, required=True)
    parser.add_argument("--formation-at", required=True)
    parser.add_argument("--identity-available-at", required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--sec-source-run-id", required=True)
    parser.add_argument("--institutional-source-run-id", required=True)
    parser.add_argument("--formula-source-run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 Field-Ritter IPO current reconstruction"
    )

    implementation_sha = str(args.implementation_sha).strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", implementation_sha) is None:
        raise ValueError("implementation SHA must be a full hexadecimal commit")
    formation = pd.to_datetime(args.formation_at, errors="coerce", utc=True)
    identity_available = pd.to_datetime(
        args.identity_available_at,
        errors="coerce",
        utc=True,
    )
    if pd.isna(formation) or pd.isna(identity_available):
        raise ValueError("formation and identity availability must be valid timestamps")
    if identity_available > formation:
        raise ValueError("identity availability must not follow formation")
    for label, value in {
        "sec source run": args.sec_source_run_id,
        "institutional source run": args.institutional_source_run_id,
        "formula source run": args.formula_source_run_id,
    }.items():
        if re.fullmatch(r"[1-9][0-9]*", str(value).strip()) is None:
            raise ValueError(f"{label} id must be a positive integer")

    facts_paths, status_paths, sec_source_evidence = _sec_source_contract(
        args.sec_root
    )
    source_file_counts = {
        "companyfacts": len(facts_paths),
        "status": len(status_paths),
        "summary": len(sec_source_evidence["summary_sha256"]),
    }
    companyfacts = _read_many(facts_paths, pd.read_parquet)
    if len(companyfacts) != int(sec_source_evidence["companyfacts_rows"]):
        raise RuntimeError("SEC CompanyFacts rows do not match shard summaries")
    status = _read_many(
        status_paths,
        lambda path: pd.read_csv(path, keep_default_na=False),
    )
    mapping, recovery, mapping_path = _institutional_mapping(
        args.institutional_root,
        expected_run_id=args.institutional_source_run_id,
    )
    formula_path, formula_hashes = _formula_inventory(args.formula_root)

    source_manifest = pd.read_csv(
        args.field_ritter_source_manifest,
        keep_default_na=False,
    )
    ipo_rows, source_rejections, source_summary = (
        load_field_ritter_ipo_workbook(
            args.field_ritter_workbook,
            source_manifest,
        )
    )
    selected_ipos = select_openap_ipo_rows(ipo_rows)
    linked, identity_rejections = build_field_ritter_current_identity(
        selected_ipos,
        mapping,
        companyfacts,
        status,
        formation_at=formation,
        identity_available_at=identity_available,
    )
    if linked.empty:
        raise RuntimeError(
            "No current SEC security passed the Field-Ritter identity contract"
        )

    rd = extract_causal_sec_rd_expense(
        companyfacts,
        status,
        formation_at=formation,
    )
    current_identity = build_companyfacts_identity(status).rename(
        columns={"symbol": "ticker"}
    )[["security_id", "ticker", "cik"]]
    values = calculate_field_ritter_ipo_signals(
        current_identity,
        linked,
        rd,
        formation_at=formation,
        retrieved_at=source_manifest.iloc[0]["retrieved_at"],
    )
    if values.empty or set(values["signal"]) != set(_EXPECTED_FORMULA_HASHES):
        raise RuntimeError("Field-Ritter batch did not emit all three IPO signals")
    if not values["formula_sha256"].map(
        lambda value: re.fullmatch(r"[0-9a-f]{64}", str(value)) is not None
    ).all():
        raise RuntimeError("Field-Ritter output has an invalid formula hash")
    finite = values.loc[values["current_usable"].eq(True)].copy()  # noqa: E712
    if finite.empty or not finite["signal"].eq("IndIPO").any():
        raise RuntimeError("Field-Ritter batch produced no current finite IPO value")

    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    output.mkdir(parents=True, exist_ok=True)
    frames = {
        "openap_149_field_ritter_ipo_current.csv": values,
        "field_ritter_source_rejections.csv": source_rejections,
        "field_ritter_identity_rejections.csv": identity_rejections,
    }
    for name, frame in frames.items():
        _write_csv_atomic(output / name, frame)
    parquets = {
        "openap_149_field_ritter_ipo_current.parquet": values,
        "field_ritter_current_identity_links.parquet": linked,
    }
    for name, frame in parquets.items():
        _write_parquet_atomic(output / name, frame)

    manifest = {
        "implementation_sha": implementation_sha,
        "formation_at": pd.Timestamp(formation).isoformat(),
        "identity_available_at": pd.Timestamp(identity_available).isoformat(),
        "sec_source_run_id": str(args.sec_source_run_id),
        "institutional_source_run_id": str(args.institutional_source_run_id),
        "formula_source_run_id": str(args.formula_source_run_id),
        "sec_source_file_counts": source_file_counts,
        "sec_source_evidence": sec_source_evidence,
        "companyfacts_rows": int(len(companyfacts)),
        "status_rows": int(len(status)),
        "openfigi_mapping_rows": int(len(mapping)),
        "openfigi_mapping_sha256": _sha256(mapping_path),
        "institutional_recovery": recovery,
        "field_ritter_workbook_sha256": _sha256(args.field_ritter_workbook),
        "field_ritter_manifest_sha256": _sha256(
            args.field_ritter_source_manifest
        ),
        "field_ritter_source_summary": source_summary,
        "field_ritter_selected_permnos": int(len(selected_ipos)),
        "field_ritter_source_rejected_rows": int(len(source_rejections)),
        "field_ritter_identity_link_rows": int(len(linked)),
        "field_ritter_identity_rejected_rows": int(len(identity_rejections)),
        "explicit_sec_rd_rows": int(len(rd)),
        "current_output_rows": int(len(values)),
        "finite_current_value_rows": int(len(finite)),
        "finite_current_value_counts": {
            str(signal): int(count)
            for signal, count in finite.groupby("signal").size().items()
        },
        "formula_inventory_sha256": _sha256(formula_path),
        "formula_sha256": formula_hashes,
        "identity_bridge": {
            "join_contract": (
                "field_ritter_cusip_to_unique_us_common_shareclass_figi_then_"
                "matching_field_ritter_openfigi_sec_ticker_and_issuer_name"
            ),
            "ticker_only_join_allowed": False,
            "historical_ticker_interval_verified": False,
            "ambiguous_identity_behavior": "omit_value_fail_closed",
        },
        "field_ritter_raw_workbook_in_output": False,
        "classification": "reconstructed_not_strict",
        "strict_score_eligible": False,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
        "output_sha256": {
            name: _sha256(output / name)
            for name in sorted(tuple(frames) + tuple(parquets))
        },
    }
    _write_json_atomic(
        output / "openap_149_field_ritter_ipo_manifest.json",
        manifest,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
