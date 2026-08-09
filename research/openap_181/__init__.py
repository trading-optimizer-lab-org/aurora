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
]
