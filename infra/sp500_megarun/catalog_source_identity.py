"""Separate scientific source identity from replaceable run infrastructure."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path


_SCIENCE_FIXED = (
    "infra/sp500_megarun/dehb_lane_registry.py",
    "infra/sp500_megarun/dehb_numeric_runtime.py",
    "infra/sp500_megarun/dehb_objective.py",
    "infra/sp500_megarun/dehb_worker.py",
    "infra/sp500_megarun/feature_input_normalizers.py",
    "infra/sp500_megarun/strategy_catalog.py",
    "infra/sp500_megarun/catalog_recipe_compiler.py",
    "infra/sp500_megarun/catalog_signal_codec.py",
    "infra/sp500_megarun/catalog_vector_engine.py",
    "scripts/run_sp500_strategy_catalog_shard.py",
)

_INFRA_FIXED = (
    ".github/workflows/catalog-component-worker.yml",
    ".github/workflows/catalog-optimized-run.yml",
    ".github/workflows/catalog-optimized-worker.yml",
    "scripts/build_sp500_component_store.py",
    "scripts/audit_sp500_catalog_actions_run.py",
    "scripts/merge_sp500_component_store.py",
    "scripts/plan_sp500_component_schedule.py",
    "scripts/plan_sp500_optimized_catalog_run.py",
    "scripts/reduce_sp500_optimized_catalog_run.py",
    "scripts/run_sp500_optimized_recipe_worker.py",
    "scripts/verify_sp500_component_store.py",
    "scripts/verify_sp500_optimized_run.py",
)


def _hash_paths(repo_root: Path, paths: Iterable[Path], *, domain: bytes) -> str:
    root = Path(repo_root).resolve()
    selected = tuple(sorted({Path(path).resolve() for path in paths}))
    if not selected:
        raise ValueError("CATALOG_SOURCE_IDENTITY_EMPTY")
    digest = hashlib.sha256(domain)
    for path in selected:
        if root != path and root not in path.parents:
            raise ValueError("CATALOG_SOURCE_IDENTITY_OUTSIDE_REPOSITORY")
        if not path.is_file():
            raise ValueError(f"CATALOG_SOURCE_IDENTITY_MISSING:{path.name}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def catalog_scientific_source_paths(repo_root: Path) -> tuple[Path, ...]:
    root = Path(repo_root).resolve()
    dynamic = tuple((root / "infra/sp500_megarun").glob("*feature_engine.py"))
    dynamic += tuple((root / "infra/sp500_megarun").glob("*feature_smoke.py"))
    return tuple(sorted({*(root / item for item in _SCIENCE_FIXED), *dynamic}))


def catalog_infrastructure_source_paths(repo_root: Path) -> tuple[Path, ...]:
    root = Path(repo_root).resolve()
    dynamic = tuple((root / "infra/sp500_megarun").glob("catalog_*.py"))
    science = set(catalog_scientific_source_paths(root))
    return tuple(
        sorted({*(root / item for item in _INFRA_FIXED), *dynamic} - science)
    )


def catalog_scientific_source_sha256(repo_root: Path) -> str:
    return _hash_paths(
        repo_root,
        catalog_scientific_source_paths(repo_root),
        domain=b"aurora-sp500-catalog-science-v2\0",
    )


def catalog_infrastructure_source_sha256(repo_root: Path) -> str:
    return _hash_paths(
        repo_root,
        catalog_infrastructure_source_paths(repo_root),
        domain=b"aurora-sp500-catalog-infrastructure-v1\0",
    )


__all__ = [
    "catalog_infrastructure_source_paths",
    "catalog_infrastructure_source_sha256",
    "catalog_scientific_source_paths",
    "catalog_scientific_source_sha256",
]
