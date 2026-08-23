"""Build a byte-for-byte deterministic bootstrap assistant archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEMBERS = {
    "__main__.py": "scripts/run_catalog_bootstrap_assistant.py",
    "config/catalog_bootstrap_app_manifests_v1.json": "config/catalog_bootstrap_app_manifests_v1.json",
    "infra/__init__.py": "infra/__init__.py",
    "infra/sp500_megarun/__init__.py": "infra/sp500_megarun/__init__.py",
    "infra/sp500_megarun/catalog_bootstrap_binding.py": "infra/sp500_megarun/catalog_bootstrap_binding.py",
    "infra/sp500_megarun/catalog_bootstrap_contract.py": "infra/sp500_megarun/catalog_bootstrap_contract.py",
    "infra/sp500_megarun/catalog_bootstrap_finalizer.py": "infra/sp500_megarun/catalog_bootstrap_finalizer.py",
    "infra/sp500_megarun/catalog_bootstrap_github.py": "infra/sp500_megarun/catalog_bootstrap_github.py",
    "infra/sp500_megarun/catalog_bootstrap_manifest.py": "infra/sp500_megarun/catalog_bootstrap_manifest.py",
    "infra/sp500_megarun/catalog_bootstrap_secrets.py": "infra/sp500_megarun/catalog_bootstrap_secrets.py",
    "infra/sp500_megarun/catalog_bootstrap_state.py": "infra/sp500_megarun/catalog_bootstrap_state.py",
    "infra/sp500_megarun/catalog_request_contract.py": "infra/sp500_megarun/catalog_request_contract.py",
}


def build(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "catalog-bootstrap-assistant.pyz"
    hashes: dict[str, str] = {}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        for member, source in sorted(MEMBERS.items()):
            data = (ROOT / source).read_bytes().replace(b"\r\n", b"\n")
            info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            bundle.writestr(info, data)
            hashes[member] = hashlib.sha256(data).hexdigest()
    manifest = {
        "schema_version": "1",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "members": hashes,
    }
    (output / "catalog-bootstrap-application-manifest-v1.json").write_bytes(
        (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
