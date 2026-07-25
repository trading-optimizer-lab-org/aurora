"""Reusable contracts and orchestration for efficient GitHub-only runs."""

from __future__ import annotations

from .contracts import RunSpec, canonical_sha256

__all__ = ["RunSpec", "canonical_sha256"]
