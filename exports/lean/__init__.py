"""Lean (QuantConnect) export adapter for QuantForge strategies.

Public API:

* :class:`LeanExporter` -- converts a :class:`StrategySpec` (factory or GA
  variant) into a Lean C# algorithm skeleton + project metadata.
* :class:`LeanExportConfig` -- parameters for the export run (target dir,
  cash, dates, resolution, ...).
* :class:`LeanProjectArtifact` -- the immutable result record returned by
  :meth:`LeanExporter.export`.

Design contract:

* Export-only. There is no Lean importer. A Lean project produced here is
  for cross-validation; promotion to live still goes through the QuantForge
  protocol (see ``RESEARCH_PROTOCOL.md``).
* No Lean runtime dep. Pure-Python text generation using
  :class:`string.Template`.
* Every artifact carries provenance (``policy_hash``, ``spec_hash``,
  ``qf_version``, ``exported_at``) so a Lean run can be tied back to the
  exact QuantForge configuration that produced it.
"""
from quantforge.exports.lean.exporter import (
    LeanExportConfig,
    LeanExporter,
    LeanProjectArtifact,
)

__all__ = [
    "LeanExportConfig",
    "LeanExporter",
    "LeanProjectArtifact",
]
