"""Quota-safe archive decisions for dashboard artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


DEFAULT_QUOTA_BYTES = 7_516_192_768
MAX_SINGLE_ARCHIVE_BYTES = 50 * 1024 * 1024
READABLE_EXTENSIONS = {".csv", ".json", ".jsonl", ".md", ".markdown", ".txt", ".html", ".htm", ".xml", ".yaml", ".yml"}


@dataclass(frozen=True)
class ArchiveDecision:
    state: str
    reason: str
    should_archive: bool


def is_readable_artifact(name: str, content_type: str | None = None) -> bool:
    suffix = PurePosixPath(name.lower().split("?", 1)[0]).suffix
    if suffix in READABLE_EXTENSIONS:
        return True
    return bool(content_type and (content_type.startswith("text/") or content_type in {"application/json", "application/xml"}))


def archive_decision(
    name: str,
    size_bytes: int,
    content_type: str | None,
    used_bytes: int,
    quota_bytes: int = DEFAULT_QUOTA_BYTES,
    *,
    duplicate: bool = False,
    expired: bool = False,
) -> ArchiveDecision:
    if expired:
        return ArchiveDecision("expired", "GitHub artifact already expired", False)
    if size_bytes < 0 or used_bytes < 0 or quota_bytes <= 0:
        return ArchiveDecision("error", "invalid archive size or quota", False)
    if duplicate:
        return ArchiveDecision("source_only", "duplicate content already archived", False)
    if not is_readable_artifact(name, content_type):
        return ArchiveDecision("source_only", "binary or unsupported artifact format", False)
    if size_bytes > MAX_SINGLE_ARCHIVE_BYTES:
        return ArchiveDecision("source_only", "single artifact exceeds archive size policy", False)
    if used_bytes + size_bytes > quota_bytes:
        return ArchiveDecision("quota_blocked", "free-tier archive quota would be exceeded", False)
    return ArchiveDecision("archived", "readable artifact fits the reserved free-tier quota", True)
