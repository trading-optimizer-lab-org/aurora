"""Compile every catalog explanation into a compact, verifiable recipe DAG map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.sp500_megarun.catalog_recipe_compiler import compile_recipes


_SCHEMA = pa.schema(
    [
        ("strategy_id", pa.string()),
        ("scientific_recipe_sha256", pa.string()),
        ("dag_sha256", pa.string()),
    ]
)


def _read_rows(catalog_path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in Path(catalog_path).read_text("utf-8").splitlines()
        if line
    ]


def write_recipe_dag_artifacts(
    catalog_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    compiled = compile_recipes(_read_rows(catalog_path))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dag_path = output_dir / "recipe_dag.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "strategy_id": item.strategy_id,
                    "scientific_recipe_sha256": item.scientific_recipe_sha256,
                    "dag_sha256": item.dag_sha256,
                }
                for item in compiled.recipes
            ],
            schema=_SCHEMA,
        ),
        dag_path,
        compression="zstd",
        use_dictionary=True,
    )
    identity: dict[str, object] = {
        "schema_version": 1,
        "recipe_count": compiled.recipe_count,
        "unique_dag_count": compiled.unique_dag_count,
        "equivalent_recipe_count": (
            compiled.recipe_count - compiled.unique_dag_count
        ),
        "compiler_sha256": compiled.compiler_sha256,
        "recipe_dag_sha256": sha256_file(dag_path),
        "validation_opened": False,
        "locked_opened": False,
    }
    manifest = {
        **identity,
        "manifest_sha256": canonical_sha256(identity),
    }
    (output_dir / "recipe_dag_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    return manifest


def verify_recipe_dag_artifacts(
    dag_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    payload = json.loads(Path(manifest_path).read_text("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CATALOG_RECIPE_DAG_MANIFEST_INVALID")
    identity = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if (
        canonical_sha256(identity) != payload.get("manifest_sha256")
        or payload.get("validation_opened") is not False
        or payload.get("locked_opened") is not False
        or sha256_file(Path(dag_path)) != payload.get("recipe_dag_sha256")
    ):
        raise ValueError("CATALOG_RECIPE_DAG_MANIFEST_INVALID")
    table = pq.read_table(dag_path)
    if table.schema != _SCHEMA or table.num_rows != int(payload["recipe_count"]):
        raise ValueError("CATALOG_RECIPE_DAG_TABLE_INVALID")
    strategy_ids = table.column("strategy_id").to_pylist()
    dag_ids = table.column("dag_sha256").to_pylist()
    if (
        strategy_ids != sorted(strategy_ids)
        or len(strategy_ids) != len(set(strategy_ids))
        or len(set(dag_ids)) != int(payload["unique_dag_count"])
    ):
        raise ValueError("CATALOG_RECIPE_DAG_TABLE_INVALID")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    write_recipe_dag_artifacts(args.catalog, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
