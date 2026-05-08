"""Audit log rotation policy (R34).

Audit JSONL files (`audit_trail.jsonl`, `gateway_audit.jsonl`,
`auto_loop.jsonl`, factory archive, review queue) grow without bound.
This module provides a rotation primitive: rotate-on-size or
rotate-on-day with hash-chain continuity preserved across rotation
boundaries.

Design contract
---------------

* Rotation policy is **opt-in** -- callers must explicitly invoke
  :func:`rotate_if_needed` (or wire it into a writer abstraction). The
  default audit writer in `agent_gateway.audit` and elsewhere does NOT
  rotate automatically yet; switching them to use this primitive is an
  incremental follow-up per writer.
* The hash chain across the rotation boundary is preserved by writing
  the **last entry's chain hash** as the **first entry of the new
  file**, marked with `kind="rotation_anchor"`. A verifier can walk
  through both files and the chain remains intact.
* Retention is a separate concern. Rotation moves the active file to
  `<name>.<YYYYMMDD>-<seq>.jsonl[.gz]`. A retention sweep
  (`prune_old_segments`) deletes segments older than the configured
  number of days. Default retention: 90 days hot, archived after.
* Compression is opt-in via `compress=True`; rotated segments become
  `.jsonl.gz`.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_log = logging.getLogger("quantforge.core.audit_rotation")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass
class RotationPolicy:
    """Rotation knobs.

    Attributes:
        max_size_bytes: rotate when the active file exceeds this size.
            Defaults to 100 MB.
        rotate_daily: when True, rotate at the start of every UTC day
            even if size has not been reached.
        retention_days: keep rotated segments for this many days. None
            disables retention pruning.
        compress: when True, rotated segments are gzipped on rotation.
    """

    max_size_bytes: int = 100 * 1024 * 1024
    rotate_daily: bool = True
    retention_days: Optional[int] = 90
    compress: bool = True


DEFAULT_POLICY = RotationPolicy()


# --------------------------------------------------------------------------
# Hash chain anchor
# --------------------------------------------------------------------------


def _last_chain_hash(path: Path) -> Optional[str]:
    """Return the last `chain_hash` field in a JSONL file, or None.

    Tolerates malformed final lines by walking from the end and
    returning the most recent valid record.
    """
    if not path.exists() or path.stat().st_size == 0:
        return None
    # Walk forward; for moderate audit logs this is fine, and avoids the
    # complexity of a reverse-line iterator.
    last: Optional[str] = None
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ch = rec.get("chain_hash")
            if isinstance(ch, str) and ch:
                last = ch
    return last


def _write_rotation_anchor(path: Path, prior_chain_hash: str) -> None:
    """Append a rotation_anchor record to a fresh segment.

    The anchor lets a verifier rebuild the chain across files: the new
    segment's first record references the previous segment's last
    chain hash, so the chain remains continuous even after rotation.
    """
    record = {
        "kind": "rotation_anchor",
        "rotated_at": datetime.utcnow().isoformat(),
        "prior_chain_hash": prior_chain_hash,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# Rotation
# --------------------------------------------------------------------------


def _segment_path(path: Path, when: datetime, seq: int) -> Path:
    """Return the rotated-segment path for a given timestamp + sequence."""
    stem = path.stem
    suffix = path.suffix or ".jsonl"
    label = when.strftime("%Y%m%d") + f"-{seq:02d}"
    return path.with_name(f"{stem}.{label}{suffix}")


def _next_seq(path: Path, when: datetime) -> int:
    """Find the next available sequence number for `when`'s date."""
    parent = path.parent
    if not parent.exists():
        return 1
    label_prefix = path.stem + "." + when.strftime("%Y%m%d") + "-"
    seqs: list[int] = []
    for p in parent.iterdir():
        if not p.name.startswith(label_prefix):
            continue
        try:
            seq_str = p.name[len(label_prefix):].split(".")[0]
            seqs.append(int(seq_str))
        except (ValueError, IndexError):
            continue
    return max(seqs, default=0) + 1


def _should_rotate(path: Path, policy: RotationPolicy) -> bool:
    """Decide whether the active file is due for rotation."""
    if not path.exists():
        return False
    size = path.stat().st_size
    if size >= policy.max_size_bytes:
        return True
    if policy.rotate_daily:
        mtime = datetime.utcfromtimestamp(path.stat().st_mtime)
        today_utc = datetime.utcnow().date()
        if mtime.date() < today_utc:
            return True
    return False


def rotate_if_needed(
    path: Path | str,
    policy: RotationPolicy = DEFAULT_POLICY,
) -> Optional[Path]:
    """Rotate `path` if size or daily policy requires.

    Returns the path of the newly created segment when rotation
    happened, otherwise None. The active `path` is left empty (or, if
    a prior chain hash is available, seeded with a rotation_anchor
    record) so subsequent writers append into a fresh file.
    """
    path = Path(path)
    if not _should_rotate(path, policy):
        return None

    when = datetime.utcnow()
    seq = _next_seq(path, when)
    segment = _segment_path(path, when, seq)
    segment.parent.mkdir(parents=True, exist_ok=True)

    # Move the active file to its segment name. shutil.move handles
    # cross-device moves; on the same filesystem this is an atomic
    # rename.
    shutil.move(str(path), str(segment))

    # Compress in place if requested.
    if policy.compress:
        gz_path = segment.with_suffix(segment.suffix + ".gz")
        with segment.open("rb") as f_in:
            with gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        segment.unlink()
        segment = gz_path

    # Seed the new active file with a rotation anchor so the hash
    # chain is verifiable across the boundary.
    prior = _read_prior_chain_hash(segment, policy.compress)
    if prior:
        _write_rotation_anchor(path, prior)

    _log.info("rotated audit log %s -> %s", path, segment)
    return segment


def _read_prior_chain_hash(segment: Path, compressed: bool) -> Optional[str]:
    """Read the last chain_hash from the just-rotated segment."""
    if compressed and segment.suffix == ".gz":
        try:
            with gzip.open(segment, "rt", encoding="utf-8") as fh:
                last: Optional[str] = None
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ch = rec.get("chain_hash")
                    if isinstance(ch, str) and ch:
                        last = ch
                return last
        except OSError:
            return None
    return _last_chain_hash(segment)


# --------------------------------------------------------------------------
# Retention
# --------------------------------------------------------------------------


def prune_old_segments(
    path: Path | str,
    policy: RotationPolicy = DEFAULT_POLICY,
) -> int:
    """Delete rotated segments older than the configured retention.

    Returns the count of deleted files. Active file is never touched.
    """
    if policy.retention_days is None:
        return 0
    path = Path(path)
    parent = path.parent
    if not parent.exists():
        return 0
    cutoff = datetime.utcnow() - timedelta(days=policy.retention_days)
    label_prefix = path.stem + "."
    deleted = 0
    for p in parent.iterdir():
        if p == path:
            continue
        if not p.name.startswith(label_prefix):
            continue
        try:
            mtime = datetime.utcfromtimestamp(p.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                p.unlink()
                deleted += 1
            except OSError as exc:
                _log.warning("retention prune failed %s: %s", p, exc)
    return deleted


__all__ = [
    "RotationPolicy",
    "DEFAULT_POLICY",
    "rotate_if_needed",
    "prune_old_segments",
]
