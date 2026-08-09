"""Fail-closed completion audit for the 181 OpenAP signals not yet ready."""

from .completion import (
    CURRENT_EXACT_31,
    CURRENT_EXCLUDED_27,
    CURRENT_PROXY_61,
    CompletionError,
    attach_runtime_evidence,
    build_completion_manifest,
    build_source_catalog,
    write_completion_outputs,
)
from .implementation_status import (
    IMPLEMENTATION_STATUS_COLUMNS,
    STRICT_INVENTORY_COLUMNS,
    build_signal_implementation_status,
    build_strict_score_inventory,
    render_implementation_validation_report,
    write_implementation_outputs,
)
from .sec_accounting_batch import (
    SEC_ACCOUNTING_BATCH,
    build_sec_accounting_batch_evidence,
    calculate_sec_accounting_batch,
    evaluate_sec_accounting_validation,
    normalize_sec_fsd_tables,
    write_sec_accounting_batch_outputs,
    write_sec_accounting_validation_outputs,
)
from .sec_fsd_inputs import bounded_quarters, prepare_sec_fsd_batch_inputs

__all__ = [
    "CURRENT_EXACT_31",
    "CURRENT_EXCLUDED_27",
    "CURRENT_PROXY_61",
    "CompletionError",
    "attach_runtime_evidence",
    "build_completion_manifest",
    "build_source_catalog",
    "write_completion_outputs",
    "IMPLEMENTATION_STATUS_COLUMNS",
    "STRICT_INVENTORY_COLUMNS",
    "build_signal_implementation_status",
    "build_strict_score_inventory",
    "render_implementation_validation_report",
    "write_implementation_outputs",
    "SEC_ACCOUNTING_BATCH",
    "build_sec_accounting_batch_evidence",
    "calculate_sec_accounting_batch",
    "evaluate_sec_accounting_validation",
    "normalize_sec_fsd_tables",
    "write_sec_accounting_batch_outputs",
    "write_sec_accounting_validation_outputs",
    "bounded_quarters",
    "prepare_sec_fsd_batch_inputs",
]
