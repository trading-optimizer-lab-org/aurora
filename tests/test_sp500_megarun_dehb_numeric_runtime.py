from __future__ import annotations

import pytest


def test_numeric_runtime_profile_is_stable_and_fail_closed() -> None:
    from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
        DEHB_NUMERIC_ENV,
        DehbNumericRuntimeError,
        numeric_runtime_profile_sha256,
        verify_numeric_runtime_environment,
    )

    first = numeric_runtime_profile_sha256()
    second = numeric_runtime_profile_sha256()

    assert first == second
    assert len(first) == 64
    assert DEHB_NUMERIC_ENV["OPENBLAS_CORETYPE"] == "NEHALEM"
    assert "AVX" in DEHB_NUMERIC_ENV["NPY_DISABLE_CPU_FEATURES"].split(",")
    assert verify_numeric_runtime_environment(dict(DEHB_NUMERIC_ENV))["passed"] is True

    incompatible = dict(DEHB_NUMERIC_ENV)
    incompatible["OPENBLAS_CORETYPE"] = "HASWELL"
    with pytest.raises(DehbNumericRuntimeError, match="DEHB_NUMERIC_RUNTIME_MISMATCH"):
        verify_numeric_runtime_environment(incompatible)


def test_numeric_runtime_profile_changes_if_scientific_environment_changes() -> None:
    from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
        DEHB_NUMERIC_ENV,
        numeric_runtime_profile_sha256,
    )

    changed = dict(DEHB_NUMERIC_ENV)
    changed["OPENBLAS_CORETYPE"] = "HASWELL"

    assert numeric_runtime_profile_sha256(changed) != numeric_runtime_profile_sha256()
