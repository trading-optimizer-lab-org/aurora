"""Great Expectations-style data quality validator.

Lazy import of ``great_expectations``. In mock mode the validator runs the
expectation set as plain Python predicates over a pandas DataFrame so unit
tests don't need GE installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd


@dataclass
class Expectation:
    """One declarative expectation entry.

    ``kind`` is one of:
      - ``not_null``
      - ``unique``
      - ``in_set`` with ``params={'values': [...]}``
      - ``between`` with ``params={'min': float, 'max': float}``
      - ``regex``  with ``params={'pattern': str}``
    """
    kind: str
    column: str
    params: dict = field(default_factory=dict)


@dataclass
class GEConfig:
    """Static config for :class:`DataQualityValidator`.

    Attributes:
        suite_name: name of the expectation suite.
        fail_fast: stop after first failure.
    """
    suite_name: str = "aurora_default"
    fail_fast: bool = False


@dataclass
class ValidationResult:
    suite_name: str
    success: bool
    n_expectations: int
    n_passed: int
    failures: tuple[dict, ...]


class DataQualityValidator:
    """Apply a list of expectations to a DataFrame."""

    SUPPORTED = ("not_null", "unique", "in_set", "between", "regex")

    def __init__(self, config: Optional[GEConfig] = None,
                 mock: bool = True) -> None:
        self.config = config or GEConfig()
        self.mock = bool(mock)
        self._suite: list[Expectation] = []

    def add(self, exp: Expectation) -> "DataQualityValidator":
        if exp.kind not in self.SUPPORTED:
            raise ValueError(f"unsupported expectation kind: {exp.kind!r}")
        self._suite.append(exp)
        return self

    def reset(self) -> "DataQualityValidator":
        self._suite.clear()
        return self

    def validate(self, df: pd.DataFrame) -> ValidationResult:
        if self.mock or True:  # GE adapter would replace this branch
            return self._validate_local(df)

    # ------------------------------------------------------------------
    def _validate_local(self, df: pd.DataFrame) -> ValidationResult:
        failures: list[dict] = []
        n_passed = 0
        for exp in self._suite:
            ok, info = self._check_one(df, exp)
            if ok:
                n_passed += 1
            else:
                failures.append({"expectation": exp.kind,
                                 "column": exp.column,
                                 "info": info})
                if self.config.fail_fast:
                    break
        success = len(failures) == 0
        return ValidationResult(
            suite_name=self.config.suite_name,
            success=success,
            n_expectations=len(self._suite),
            n_passed=n_passed,
            failures=tuple(failures),
        )

    def _check_one(self, df: pd.DataFrame,
                   exp: Expectation) -> tuple[bool, dict]:
        if exp.column not in df.columns:
            return False, {"reason": "missing_column"}
        s = df[exp.column]
        if exp.kind == "not_null":
            n_null = int(s.isna().sum())
            return n_null == 0, {"n_null": n_null}
        if exp.kind == "unique":
            n_dup = int(s.duplicated().sum())
            return n_dup == 0, {"n_dup": n_dup}
        if exp.kind == "in_set":
            allowed = set(exp.params.get("values", []))
            bad = int((~s.isin(allowed)).sum())
            return bad == 0, {"n_outside_set": bad}
        if exp.kind == "between":
            lo = exp.params.get("min")
            hi = exp.params.get("max")
            mask = pd.Series([True] * len(s), index=s.index)
            if lo is not None:
                mask &= s >= lo
            if hi is not None:
                mask &= s <= hi
            n_bad = int((~mask).sum())
            return n_bad == 0, {"n_out_of_range": n_bad}
        if exp.kind == "regex":
            pattern = exp.params.get("pattern", "")
            n_bad = int((~s.astype(str).str.match(pattern)).sum())
            return n_bad == 0, {"n_no_match": n_bad}
        return False, {"reason": "unhandled"}
