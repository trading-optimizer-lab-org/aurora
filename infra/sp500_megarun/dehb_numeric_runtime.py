"""Frozen numeric runtime contract for reproducible SP500 DEHB evaluations."""

from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
import platform
from typing import Mapping


DEHB_NUMERIC_ENV: Mapping[str, str] = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
    # Use one conservative x86-64 OpenBLAS kernel on every hosted runner.
    "OPENBLAS_CORETYPE": "NEHALEM",
    # Keep NumPy on the same SSE4.2-or-lower dispatch path on every runner.
    "NPY_DISABLE_CPU_FEATURES": (
        "AVX,F16C,FMA3,AVX2,AVX512F,AVX512CD,AVX512_KNL,AVX512_KNM,"
        "AVX512_SKX,AVX512_CLX,AVX512_CNL,AVX512_ICL"
    ),
}


class DehbNumericRuntimeError(RuntimeError):
    """Raised when a worker is not using the frozen numeric runtime."""


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def numeric_runtime_profile_sha256(
    profile: Mapping[str, str] = DEHB_NUMERIC_ENV,
) -> str:
    """Return the stable identity of the scientific numeric environment."""

    return _canonical_sha256(
        {
            "schema_version": 1,
            "environment": {str(key): str(value) for key, value in sorted(profile.items())},
        }
    )


def verify_numeric_runtime_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Fail closed unless every scientific runtime setting matches exactly."""

    actual = os.environ if environ is None else environ
    mismatches = {
        key: {"expected": expected, "actual": actual.get(key)}
        for key, expected in DEHB_NUMERIC_ENV.items()
        if actual.get(key) != expected
    }
    if mismatches:
        names = ",".join(sorted(mismatches))
        raise DehbNumericRuntimeError(f"DEHB_NUMERIC_RUNTIME_MISMATCH:{names}")
    return {
        "schema_version": 1,
        "profile_sha256": numeric_runtime_profile_sha256(),
        "environment": dict(DEHB_NUMERIC_ENV),
        "passed": True,
    }


def capture_numeric_runtime_report() -> dict[str, object]:
    """Verify the profile and record NumPy/OpenBLAS runtime provenance."""

    report = verify_numeric_runtime_environment()
    import numpy as np

    stream = io.StringIO()
    with redirect_stdout(stream):
        np.show_runtime()
    return {
        **report,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "numpy_version": np.__version__,
        "numpy_runtime": stream.getvalue().strip(),
    }


__all__ = [
    "DEHB_NUMERIC_ENV",
    "DehbNumericRuntimeError",
    "capture_numeric_runtime_report",
    "numeric_runtime_profile_sha256",
    "verify_numeric_runtime_environment",
]
