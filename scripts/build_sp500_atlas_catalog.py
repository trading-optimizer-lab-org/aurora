"""Prepare the complete compact SP500_ATLAS_1 catalog.

This is a metadata-only builder.  It enumerates all valid component
configurations and writes an exact ordinal recipe space for all authorised
pairwise compositions and their inverses.  It does not load market data and
does not run a backtest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_atlas_space import (
    build_atlas_space,
    write_component_index,
)
from aurora.infra.sp500_megarun.catalog_family_admission import (
    build_existing_family_manifest,
    family_manifest_payload,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> str:
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    raw = data.encode("utf-8")
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def build_catalog(
    *,
    data_contract_path: Path,
    feature_contract_path: Path,
    output_dir: Path,
    catalog_id: str = "sp500-atlas-1",
    target_end_iso: str = "2026-08-20T07:31:00+02:00",
) -> dict[str, object]:
    output_dir = Path(output_dir)
    reuse_components = False
    if output_dir.exists():
        if not output_dir.is_dir():
            raise ValueError(f"ATLAS_OUTPUT_NOT_DIRECTORY:{output_dir}")
        required = (output_dir / "components.jsonl", output_dir / "component_index.json")
        if not all(path.is_file() for path in required):
            raise ValueError(f"ATLAS_OUTPUT_INCOMPLETE:{output_dir}")
        reuse_components = True
    data_contract = load_and_validate_contract(Path(data_contract_path))
    feature_contract = load_and_validate_feature_contract(
        Path(feature_contract_path), data_contract
    )
    if data_contract.boundaries.validation_opened or data_contract.boundaries.locked_opened:
        raise ValueError("ATLAS_DATA_BOUNDARY_OPEN")
    if feature_contract.validation_opened or feature_contract.locked_opened:
        raise ValueError("ATLAS_FEATURE_BOUNDARY_OPEN")
    if feature_contract.search_end.isoformat() != "2010-12-31":
        raise ValueError("ATLAS_SEARCH_END_INVALID")
    if len(feature_contract.lanes) != 240 or len(feature_contract.cross_rules) != 14:
        raise ValueError("ATLAS_CONTRACT_SIZE_INVALID")
    # Rules may advertise higher arities for ATLAS_2.  ATLAS_1 deliberately
    # consumes only their authorised pair endpoints.

    space, components = build_atlas_space(feature_contract, catalog_id=catalog_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    component_path = output_dir / "components.jsonl"
    if not reuse_components:
        with component_path.open("x", encoding="utf-8", newline="\n") as handle:
            for lane_id in sorted(components):
                for component in components[lane_id]:
                    payload = component.to_payload()
                    handle.write(
                        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    )

    component_index_path = output_dir / "component_index.json"
    component_index_sha256 = write_component_index(component_index_path, components)
    family_path = output_dir / "family_admission.json"
    family_sha256 = _write_json(
        family_path,
        family_manifest_payload(build_existing_family_manifest(feature_contract)),
    )
    space_path = output_dir / "recipe_space.json"
    space_payload = space.to_payload()
    space_sha256 = _write_json(space_path, space_payload)

    counts = {
        "component_count": sum(space.lane_component_counts.values()),
        "lane_count": len(space.lane_component_counts),
        "range_count": len(space.ranges),
        "raw_requested_recipe_count": space.raw_requested_recipe_count,
        "canonical_recipe_count": space.canonical_recipe_count,
        "formal_duplicate_count": space.formal_duplicate_count,
        "formal_alias_group_count": sum(
            int(item.formal_source_variant_count > 1) for item in space.ranges
        ),
    }
    readme = """# SP500_ATLAS_1\n\n""" + f"""Catálogo completo, cerrado y preparado; todavía no ejecutado.\n\n- Entrenamiento: hasta `2010-12-31`\n- Validation 2011-2020 abierta: `false`\n- Locked 2021+ abierto: `false`\n- Familias ejecutables: 240\n- Reglas de cruce: 14\n- Configuraciones de componentes: {counts['component_count']:,}\n- Recetas solicitadas antes de equivalencia formal: {counts['raw_requested_recipe_count']:,}\n- Recetas canónicas físicas: {counts['canonical_recipe_count']:,}\n- Recetas unidas por equivalencia formal: {counts['formal_duplicate_count']:,}\n- Representación: rangos ordinales compactos, sin duplicados artificiales\n- Objetivo temporal de planificación: `{target_end_iso}`\n\n`components.jsonl` contiene cada configuración válida de las 240 familias. `recipe_space.json` describe de forma determinista cada receta canónica, su rango, composición, dirección e historial de alias formales. No se han backtesteado recetas.\n"""
    (output_dir / "README.md").write_bytes(readme.encode("utf-8"))

    artifacts = {
        "components.jsonl": _sha256(component_path),
        "component_index.json": _sha256(component_index_path),
        "family_admission.json": family_sha256,
        "recipe_space.json": space_sha256,
        "README.md": _sha256(output_dir / "README.md"),
    }
    identity = {
        "schema_version": 1,
        "catalog_id": catalog_id,
        "catalog_format": "atlas_compact_ordinal_ranges_v1",
        "data_contract_sha256": data_contract.sha256,
        "feature_contract_sha256": feature_contract.sha256,
        "search_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "performance_status": "not_evaluated",
        "target_end_iso": target_end_iso,
        "counts": counts,
        "artifacts_sha256": artifacts,
        "execution_authorized": False,
    }
    _write_json(output_dir / "manifest.json", identity | {"manifest_sha256": "pending"})
    manifest_path = output_dir / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    _write_json(manifest_path, manifest_data)
    return manifest_data


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--catalog-id", default="sp500-atlas-1")
    parser.add_argument("--target-end-iso", default="2026-08-20T07:31:00+02:00")
    return parser


def main() -> int:
    args = _parser().parse_args()
    payload = build_catalog(
        data_contract_path=args.data_contract,
        feature_contract_path=args.feature_contract,
        output_dir=args.output_dir,
        catalog_id=args.catalog_id,
        target_end_iso=args.target_end_iso,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
