"""Fail-closed completion audit for the 181 OpenAP signals not yet ready."""

from .completion import (
    CURRENT_EXACT_31,
    CURRENT_EXCLUDED_27,
    CURRENT_PROXY_61,
    CompletionError,
    build_completion_manifest,
    build_source_catalog,
    write_completion_outputs,
)

__all__ = [
    "CURRENT_EXACT_31",
    "CURRENT_EXCLUDED_27",
    "CURRENT_PROXY_61",
    "CompletionError",
    "build_completion_manifest",
    "build_source_catalog",
    "write_completion_outputs",
]
