"""R157 first-dataset orchestrator (package).

Bridges R155 + R156 provider connectors into a real, audited,
locally-persisted seed dataset and at least one approved snapshot. The
orchestrator is deliberately small: it walks a manifest (typically
``config/first_dataset.yaml``), tries the providers in order, validates
every frame against its declared contract, persists to the
:class:`~aurora.data_contracts.timeseries_store.TimeSeriesStore`, and
returns a :class:`BootstrapReport` that the CLI surfaces to the
operator.

Constraints:

* No live network in this module. Every provider client is injectable
  via the ``http_clients`` mapping. Tests pass deterministic stubs;
  production wires real ``urllib`` / ``requests`` wrappers.
* Refuses to persist a frame that fails its contract gate. The
  rejection is recorded in the report so coverage-report can explain
  it in plain English.
* All persistent paths flow through
  :func:`aurora.core.runtime_paths.cache_dir` -- no hardcoded paths.

Public surface (preserved from the pre-split flat module):

* :class:`FirstDatasetManifest`, :class:`FirstDatasetSection`
* :class:`SymbolResult`, :class:`SectionReport`, :class:`BootstrapReport`
* :func:`bootstrap_first_dataset`
* :func:`load_manifest`
* :func:`save_report`, :func:`load_report`, :func:`report_to_dict`,
  :func:`default_report_path`
* :func:`load_from_first_dataset`, :func:`freeze_from_first_dataset`
"""
from __future__ import annotations

from ._freeze import (
    freeze_from_first_dataset,
    freeze_many_from_first_dataset,
    load_from_first_dataset,
)
from ._manifest import (
    FirstDatasetManifest,
    FirstDatasetSection,
    load_manifest,
)
from ._persist import PersistenceContractViolation
from ._results import (
    BootstrapReport,
    SectionReport,
    SymbolResult,
    default_report_path,
    load_report,
    report_to_dict,
    save_report,
)
from ._symbol_map import (
    SymbolNormalisation,
    apply_normalisation,
    lookup_normalisation,
    normalise_symbol,
)
from ._walker import bootstrap_first_dataset


__all__ = [
    "FirstDatasetManifest",
    "FirstDatasetSection",
    "SymbolResult",
    "SectionReport",
    "BootstrapReport",
    "bootstrap_first_dataset",
    "load_manifest",
    "save_report",
    "load_report",
    "report_to_dict",
    "default_report_path",
    "load_from_first_dataset",
    "freeze_from_first_dataset",
    "freeze_many_from_first_dataset",
    "PersistenceContractViolation",
    "SymbolNormalisation",
    "apply_normalisation",
    "lookup_normalisation",
    "normalise_symbol",
]
