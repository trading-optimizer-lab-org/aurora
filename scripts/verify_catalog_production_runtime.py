"""Verify the exact catalog production dependency boundary without installing."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import platform
import re
from tempfile import TemporaryDirectory
from typing import Mapping, Sequence


_LOCKED_DISTRIBUTION = re.compile(r"^([A-Za-z0-9_.-]+)==[^\s\\]+(?:\s|\\|$)")
_REQUIRED_PRODUCTION_DISTRIBUTIONS = frozenset({"cryptography", "numpy", "pandas", "pyarrow", "pydantic", "scipy"})
_REQUIRED_PRODUCTION_IMPORTS = frozenset({
    *_REQUIRED_PRODUCTION_DISTRIBUTIONS,
    "aurora.infra.sp500_megarun.catalog_fast_path",
    "scripts.plan_sp500_optimized_catalog_run",
    "scripts.prepare_catalog_admission_candidates",
    "scripts.run_catalog_recipe_worker_guarded",
    "scripts.reduce_sp500_optimized_catalog_group",
    "scripts.reduce_sp500_optimized_catalog_run",
    "scripts.audit_catalog_runtime",
    "scripts.verify_catalog_terminal_science",
    "scripts.finalize_catalog_controller_run",
})


def _normalize_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _locked_distributions(lock_text: str) -> frozenset[str]:
    result: set[str] = set()
    current: str | None = None
    current_has_hash = False
    for line in lock_text.splitlines():
        match = _LOCKED_DISTRIBUTION.match(line)
        if match is not None:
            if current is not None and not current_has_hash:
                raise ValueError(f"CATALOG_PRODUCTION_DEPENDENCY_HASH_MISSING:{current}")
            current = _normalize_distribution(match.group(1))
            current_has_hash = "--hash=sha256:" in line
            result.add(current)
        elif current is not None and "--hash=sha256:" in line:
            current_has_hash = True
    if current is not None and not current_has_hash:
        raise ValueError(f"CATALOG_PRODUCTION_DEPENDENCY_HASH_MISSING:{current}")
    if not result:
        raise ValueError("CATALOG_PRODUCTION_DEPENDENCY_LOCK_EMPTY")
    return frozenset(result)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_production_runtime_receipt(
    receipt: Mapping[str, object], *, lock_path: Path,
) -> None:
    """Validate protected preparation evidence without repeating its probe."""
    error = "CATALOG_PRODUCTION_RUNTIME_SMOKE_INVALID"
    identity = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    version = receipt.get("runtime_python_version")
    lock_bytes = lock_path.read_bytes()
    if (
        receipt.get("receipt_sha256") != _canonical_sha256(identity)
        or receipt.get("schema_version") != "1"
        or receipt.get("status") != "PREPARED"
        or receipt.get("production_dependency_smoke_passed") is not True
        or receipt.get("parquet_roundtrip_verified") is not True
        or receipt.get("network_install_performed") is not False
        or receipt.get("runtime_platform") != "Linux"
        or not isinstance(version, str)
        or re.fullmatch(r"3\.11\.\d+", version) is None
        or receipt.get("verification_scope") != "dependency_and_result_transport_only"
        or receipt.get("dependency_lock_sha256") != hashlib.sha256(lock_bytes).hexdigest()
    ):
        raise ValueError(error)
    sets: dict[str, set[str]] = {}
    for field in ("verified_imports", "required_distributions", "locked_distributions"):
        values = receipt.get(field)
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise ValueError(error)
        if len(values) != len(set(values)):
            raise ValueError(error)
        sets[field] = set(values)
    if (
        not _REQUIRED_PRODUCTION_IMPORTS <= sets["verified_imports"]
        or not _REQUIRED_PRODUCTION_DISTRIBUTIONS <= sets["required_distributions"]
        or sets["locked_distributions"] != _locked_distributions(lock_bytes.decode("utf-8"))
        or not sets["required_distributions"] <= sets["locked_distributions"]
    ):
        raise ValueError(error)


def _verify_result_transport() -> None:
    """Exercise production Parquet encoding and manifest reopening, not science."""
    try:
        import pyarrow.parquet as parquet
        from aurora.infra.sp500_megarun.catalog_result_store import (
            CatalogResultStore, CatalogResultWriter,
        )

        rows = [{
            "strategy_id": f"runtime-transport-probe-{index}",
            "recipe_sha256": str(index) * 64,
            "position_sha256": "a" * 64,
            "annualized_return": 0.125 * index,
            "weekly_positive_rate": 0.5,
        } for index in (1, 2)]
        with TemporaryDirectory(prefix="aurora-runtime-transport-") as temporary:
            root = Path(temporary) / "results"
            writer = CatalogResultWriter(root, contract_sha256="b" * 64)
            for row in rows:
                writer.add(row)
            manifest = writer.commit()
            reopened = CatalogResultStore.open(root)
            if reopened.manifest != manifest or list(reopened.iter_rows()) != rows:
                raise ValueError("RESULT_TRANSPORT_ROUNDTRIP_MISMATCH")
            if parquet.read_table(root / manifest.partitions[0].path).to_pylist() != rows:
                raise ValueError("PARQUET_ROUNDTRIP_MISMATCH")
    except Exception as exc:
        raise ValueError("CATALOG_PRODUCTION_PARQUET_FAILED") from exc


def verify_production_runtime(
    *,
    lock_path: Path,
    import_names: Sequence[str],
    required_distributions: Sequence[str],
    output_path: Path,
) -> dict[str, object]:
    """Reject an incomplete lock or import closure before a run can be admitted."""

    lock = Path(lock_path).resolve(strict=True)
    if not lock.is_file():
        raise ValueError("CATALOG_PRODUCTION_DEPENDENCY_LOCK_INVALID")
    lock_bytes = lock.read_bytes()
    try:
        lock_text = lock_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("CATALOG_PRODUCTION_DEPENDENCY_LOCK_INVALID") from exc
    locked = _locked_distributions(lock_text)
    required = tuple(_normalize_distribution(value) for value in required_distributions)
    if not required or len(required) != len(set(required)):
        raise ValueError("CATALOG_PRODUCTION_DEPENDENCY_SET_INVALID")
    for distribution in required:
        if distribution not in locked:
            raise ValueError(f"CATALOG_PRODUCTION_DEPENDENCY_MISSING:{distribution}")

    imports = tuple(str(value) for value in import_names)
    if not imports or len(imports) != len(set(imports)):
        raise ValueError("CATALOG_PRODUCTION_IMPORT_SET_INVALID")
    for module_name in imports:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            raise ValueError(f"CATALOG_PRODUCTION_IMPORT_FAILED:{module_name}") from exc

    _verify_result_transport()
    identity: dict[str, object] = {
        "schema_version": "1",
        "status": "PREPARED",
        "dependency_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "locked_distributions": sorted(locked),
        "required_distributions": list(required),
        "verified_imports": list(imports),
        "production_dependency_smoke_passed": True,
        "parquet_roundtrip_verified": True,
        "runtime_platform": platform.system(),
        "runtime_python_version": platform.python_version(),
        "verification_scope": "dependency_and_result_transport_only",
        "network_install_performed": False,
    }
    receipt = {**identity, "receipt_sha256": _canonical_sha256(identity)}
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--import", dest="imports", action="append", required=True)
    parser.add_argument(
        "--require-distribution",
        dest="required_distributions",
        action="append",
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    verify_production_runtime(
        lock_path=args.lock,
        import_names=tuple(args.imports),
        required_distributions=tuple(args.required_distributions),
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
