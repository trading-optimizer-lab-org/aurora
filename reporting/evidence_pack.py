"""R166 - Reproducible evidence pack for datasets and strategies.

An evidence pack is the unit of "what data and decisions produced a
result". It collects manifest references, provenance, validator output,
benchmark pack hash, identity status, quality decisions and the exact
commands needed to reproduce the work.

The pack object itself is small. Large artefacts (raw price frames,
snapshots, validation logs) are referenced by hash and storage location
rather than embedded inline.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ArtefactReference:
    """Hash-linked pointer to a file the pack does not embed."""

    role: str  # e.g. "snapshot", "validation_report", "benchmark_pack"
    location: str
    content_hash: str
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EvidencePack:
    """Self-contained record of a dataset or strategy validation result."""

    pack_id: str
    pack_kind: str  # "dataset" | "strategy"
    subject_id: str  # dataset name or strategy id
    generated_at: str
    policy_hash: str
    snapshot_hash: str
    manifest: Dict[str, Any]
    requested_vs_persisted: Dict[str, List[str]]
    provider_provenance: List[Dict[str, Any]]
    data_contract_results: List[Dict[str, Any]]
    quality_decisions: List[Dict[str, Any]]
    identity_status: Dict[str, List[str]]
    corporate_action_status: Dict[str, Any]
    snapshots: List[Dict[str, Any]]
    validation_report: Dict[str, Any]
    benchmark_pack: Dict[str, Any]
    research_ledger_excerpt: List[Dict[str, Any]]
    warnings: Tuple[str, ...]
    overrides: Tuple[Dict[str, Any], ...]
    reproduce_commands: Tuple[str, ...]
    artefacts: Tuple[ArtefactReference, ...] = field(default_factory=tuple)
    pack_hash: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pack_hash"] = self.pack_hash or compute_pack_hash(self)
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, default=str)

    def to_markdown(self) -> str:
        """Compact human-readable summary."""
        lines = [
            f"# Evidence Pack: {self.subject_id}",
            "",
            f"- **kind**: {self.pack_kind}",
            f"- **pack_id**: {self.pack_id}",
            f"- **generated_at**: {self.generated_at}",
            f"- **policy_hash**: {self.policy_hash}",
            f"- **snapshot_hash**: {self.snapshot_hash}",
            f"- **pack_hash**: {self.pack_hash or compute_pack_hash(self)}",
            "",
            "## Manifest",
            f"`{json.dumps(self.manifest, sort_keys=True)}`",
            "",
            "## Coverage",
        ]
        for label, syms in self.requested_vs_persisted.items():
            lines.append(f"- **{label}**: {len(syms)} ({', '.join(syms[:5])}{'...' if len(syms) > 5 else ''})")
        lines.append("")
        if self.warnings:
            lines.append("## Warnings")
            for w in self.warnings:
                lines.append(f"- {w}")
            lines.append("")
        if self.reproduce_commands:
            lines.append("## Reproduce")
            for cmd in self.reproduce_commands:
                lines.append(f"    {cmd}")
            lines.append("")
        return "\n".join(lines)


def compute_pack_hash(pack: EvidencePack) -> str:
    """Stable sha256 over the pack content (excluding ``pack_hash``)."""
    payload = asdict(pack)
    payload.pop("pack_hash", None)
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_dataset_pack(
    *,
    dataset_name: str,
    policy_hash: str,
    snapshot_hash: str,
    manifest: Mapping[str, Any],
    requested_symbols: List[str],
    persisted_symbols: List[str],
    provider_provenance: List[Mapping[str, Any]],
    data_contract_results: List[Mapping[str, Any]],
    quality_decisions: List[Mapping[str, Any]],
    identity_resolved: List[str],
    identity_unresolved: List[str],
    identity_ambiguous: List[str],
    corporate_action_status: Mapping[str, Any],
    snapshots: List[Mapping[str, Any]],
    warnings: List[str] | None = None,
    overrides: List[Mapping[str, Any]] | None = None,
    reproduce_commands: List[str] | None = None,
    artefacts: List[ArtefactReference] | None = None,
    pack_id: Optional[str] = None,
) -> EvidencePack:
    """Build an :class:`EvidencePack` for a dataset.

    The pack does not contain validation or benchmark fields because
    those are strategy-level; they remain empty for dataset packs.
    """
    pack_id = pack_id or _derive_pack_id("dataset", dataset_name)
    pack = EvidencePack(
        pack_id=pack_id,
        pack_kind="dataset",
        subject_id=dataset_name,
        generated_at=_now_iso(),
        policy_hash=policy_hash,
        snapshot_hash=snapshot_hash,
        manifest=dict(manifest),
        requested_vs_persisted={
            "requested": sorted(requested_symbols),
            "persisted": sorted(persisted_symbols),
            "missing": sorted(
                set(requested_symbols) - set(persisted_symbols)
            ),
        },
        provider_provenance=[dict(p) for p in provider_provenance],
        data_contract_results=[dict(r) for r in data_contract_results],
        quality_decisions=[dict(q) for q in quality_decisions],
        identity_status={
            "resolved": sorted(identity_resolved),
            "unresolved": sorted(identity_unresolved),
            "ambiguous": sorted(identity_ambiguous),
        },
        corporate_action_status=dict(corporate_action_status),
        snapshots=[dict(s) for s in snapshots],
        validation_report={},
        benchmark_pack={},
        research_ledger_excerpt=[],
        warnings=tuple(warnings or []),
        overrides=tuple(dict(o) for o in (overrides or [])),
        reproduce_commands=tuple(reproduce_commands or []),
        artefacts=tuple(artefacts or []),
    )
    return _stamp_hash(pack)


def build_strategy_pack(
    *,
    strategy_id: str,
    policy_hash: str,
    snapshot_hash: str,
    validation_report: Mapping[str, Any],
    benchmark_pack: Mapping[str, Any],
    manifest: Mapping[str, Any] | None = None,
    research_ledger_excerpt: List[Mapping[str, Any]] | None = None,
    quality_decisions: List[Mapping[str, Any]] | None = None,
    provider_provenance: List[Mapping[str, Any]] | None = None,
    requested_symbols: List[str] | None = None,
    persisted_symbols: List[str] | None = None,
    identity_resolved: List[str] | None = None,
    identity_unresolved: List[str] | None = None,
    identity_ambiguous: List[str] | None = None,
    corporate_action_status: Mapping[str, Any] | None = None,
    snapshots: List[Mapping[str, Any]] | None = None,
    warnings: List[str] | None = None,
    overrides: List[Mapping[str, Any]] | None = None,
    reproduce_commands: List[str] | None = None,
    artefacts: List[ArtefactReference] | None = None,
    pack_id: Optional[str] = None,
) -> EvidencePack:
    pack_id = pack_id or _derive_pack_id("strategy", strategy_id)
    pack = EvidencePack(
        pack_id=pack_id,
        pack_kind="strategy",
        subject_id=strategy_id,
        generated_at=_now_iso(),
        policy_hash=policy_hash,
        snapshot_hash=snapshot_hash,
        manifest=dict(manifest or {}),
        requested_vs_persisted={
            "requested": sorted(requested_symbols or []),
            "persisted": sorted(persisted_symbols or []),
            "missing": sorted(
                set(requested_symbols or []) - set(persisted_symbols or [])
            ),
        },
        provider_provenance=[dict(p) for p in (provider_provenance or [])],
        data_contract_results=[],
        quality_decisions=[dict(q) for q in (quality_decisions or [])],
        identity_status={
            "resolved": sorted(identity_resolved or []),
            "unresolved": sorted(identity_unresolved or []),
            "ambiguous": sorted(identity_ambiguous or []),
        },
        corporate_action_status=dict(corporate_action_status or {}),
        snapshots=[dict(s) for s in (snapshots or [])],
        validation_report=dict(validation_report),
        benchmark_pack=dict(benchmark_pack),
        research_ledger_excerpt=[
            dict(e) for e in (research_ledger_excerpt or [])
        ],
        warnings=tuple(warnings or []),
        overrides=tuple(dict(o) for o in (overrides or [])),
        reproduce_commands=tuple(reproduce_commands or []),
        artefacts=tuple(artefacts or []),
    )
    return _stamp_hash(pack)


def _derive_pack_id(kind: str, subject: str) -> str:
    base = f"{kind}:{subject}:{_now_iso()}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()[:16]


def _stamp_hash(pack: EvidencePack) -> EvidencePack:
    h = compute_pack_hash(pack)
    # ``EvidencePack`` is frozen; rebuild with the hash filled in.
    payload = asdict(pack)
    payload["pack_hash"] = h
    payload["artefacts"] = tuple(
        ArtefactReference(**a) if isinstance(a, dict) else a
        for a in payload["artefacts"]
    )
    return EvidencePack(**payload)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_pack(pack: EvidencePack) -> Tuple[bool, List[str]]:
    """Verify the pack's internal hashes.

    Returns ``(ok, problems)``. ``ok`` is True when ``pack_hash`` matches
    the recomputed hash. Per-artefact verification is the caller's
    responsibility because it requires file-system access; this helper
    returns the artefact list for the caller to walk.
    """
    problems: List[str] = []
    expected = compute_pack_hash(pack)
    if pack.pack_hash and pack.pack_hash != expected:
        problems.append(
            f"pack_hash mismatch: stored={pack.pack_hash[:12]} "
            f"computed={expected[:12]}"
        )
    return not problems, problems


def verify_artefact_files(
    pack: EvidencePack, base_dir: Optional[Path] = None,
) -> List[str]:
    """Walk ``pack.artefacts`` and verify that each file's sha256 matches."""
    problems: List[str] = []
    for art in pack.artefacts:
        path = Path(art.location)
        if base_dir is not None and not path.is_absolute():
            path = base_dir / path
        if not path.exists():
            problems.append(f"artefact missing: {path}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != art.content_hash:
            problems.append(
                f"artefact hash mismatch for {art.role} at {path}: "
                f"stored={art.content_hash[:12]} computed={digest[:12]}"
            )
    return problems


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def write_pack(
    pack: EvidencePack,
    out_dir: Path,
    *,
    write_markdown: bool = True,
) -> Dict[str, Path]:
    """Write the pack as ``json`` (and optionally ``md``) into ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"evidence_{pack.pack_id}.json"
    json_path.write_text(pack.to_json(), encoding="utf-8")
    paths = {"json": json_path}
    if write_markdown:
        md_path = out_dir / f"evidence_{pack.pack_id}.md"
        md_path.write_text(pack.to_markdown(), encoding="utf-8")
        paths["markdown"] = md_path
    return paths


def load_pack(path: Path) -> EvidencePack:
    """Load a pack from a ``.json`` file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["artefacts"] = tuple(
        ArtefactReference(**a) for a in payload.get("artefacts", [])
    )
    payload["warnings"] = tuple(payload.get("warnings", []))
    payload["overrides"] = tuple(payload.get("overrides", []))
    payload["reproduce_commands"] = tuple(payload.get("reproduce_commands", []))
    return EvidencePack(**payload)


__all__ = [
    "ArtefactReference",
    "EvidencePack",
    "build_dataset_pack",
    "build_strategy_pack",
    "compute_pack_hash",
    "load_pack",
    "verify_artefact_files",
    "verify_pack",
    "write_pack",
]
