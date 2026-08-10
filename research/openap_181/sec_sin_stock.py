"""Positive-only SEC reconstruction of the OpenAP ``sinAlgo`` signal."""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from .sec_companyfacts_149 import build_companyfacts_identity


SINALGO_FORMULA_SHA256 = (
    "18c16b295bd0aab19e7e7581f31f10405fb00c48c01574862805a76d3fd4863f"
)
SINALGO_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/"
    "Predictors/sinAlgo.py"
)

_SUBMISSION_COLUMNS = frozenset(
    {"cik", "accession_number", "accepted_at", "sic"}
)
_OUTPUT_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "signal",
    "formation_at",
    "period_end",
    "filed_at",
    "available_at",
    "retrieved_at",
    "value",
    "fidelity_class",
    "current_usable",
    "source_id",
    "source_url",
    "formula_id",
    "formula_sha256",
    "observation_count",
    "reason_if_missing",
    "caveat",
)


def _require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    label: str,
) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def _timestamp(value: object) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return pd.NaT if pd.isna(parsed) else pd.Timestamp(parsed)


def _latest_sic(
    submissions: pd.DataFrame,
    *,
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    _require_columns(submissions, _SUBMISSION_COLUMNS, "SEC submissions")
    frame = submissions.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["sic"] = pd.to_numeric(frame["sic"], errors="coerce")
    frame["accepted_at"] = pd.to_datetime(
        frame["accepted_at"], errors="coerce", utc=True
    )
    frame = frame.loc[
        frame["cik"].notna()
        & frame["sic"].notna()
        & frame["sic"].between(1, 9999)
        & frame["accepted_at"].notna()
        & frame["accepted_at"].le(cutoff)
    ].copy()
    if frame.empty:
        return frame
    latest_at = frame.groupby("cik")["accepted_at"].transform("max")
    latest = frame.loc[frame["accepted_at"].eq(latest_at)].copy()
    conflicts = latest.groupby("cik")["sic"].transform("nunique").gt(1)
    latest = latest.loc[~conflicts].copy()
    return (
        latest.sort_values(["cik", "accepted_at", "accession_number"])
        .drop_duplicates("cik", keep="last")
        .assign(sic=lambda current: current["sic"].astype(int))
        .reset_index(drop=True)
    )


def _is_positive_sin_sic(sic: int) -> bool:
    return 2080 <= sic <= 2085 or 2100 <= sic <= 2199


def _row(
    *,
    identity: Any,
    latest: pd.Series | None,
    formation: pd.Timestamp,
    retrieved: pd.Timestamp,
) -> dict[str, Any]:
    cik = int(identity.cik)
    positive = latest is not None and _is_positive_sin_sic(int(latest["sic"]))
    accepted = pd.Timestamp(latest["accepted_at"]) if latest is not None else pd.NaT
    sic = int(latest["sic"]) if latest is not None else None
    return {
        "security_id": str(identity.security_id),
        "ticker": str(identity.symbol),
        "cik": f"{cik:010d}",
        "signal": "sinAlgo",
        "formation_at": formation.isoformat(),
        "period_end": "" if pd.isna(accepted) else accepted.isoformat(),
        "filed_at": "" if pd.isna(accepted) else accepted.isoformat(),
        "available_at": "" if pd.isna(accepted) else accepted.isoformat(),
        "retrieved_at": retrieved.isoformat(),
        "value": 1.0 if positive else float("nan"),
        "fidelity_class": "reconstructed" if positive else "unavailable",
        "current_usable": positive,
        "source_id": "sec_edgar",
        "source_url": f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
        "formula_id": "openap_sinalgo_positive_current_sec_sic",
        "formula_sha256": SINALGO_FORMULA_SHA256,
        "observation_count": 1 if latest is not None else 0,
        "reason_if_missing": "" if positive else "no_positive_current_sec_sic_proof",
        "caveat": (
            f"Current SEC SIC={sic if sic is not None else 'missing'} proves only "
            "positive tobacco/beer classifications; NAICS gaming, Compustat "
            "segments, historical backfill, CRSP share codes and comparable-stock "
            "zeros are not reconstructed, and current CIK/ticker is not PERMNO"
        ),
    }


def calculate_sec_sinalgo_current(
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Emit current positive sin-stock SIC classifications and no inferred zeros."""

    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("sinAlgo formation_at or retrieved_at is invalid")
    identity = build_companyfacts_identity(status)
    latest = _latest_sic(submissions, cutoff=min(formation, retrieved))
    by_cik = {
        int(row.cik): pd.Series(row._asdict())
        for row in latest.itertuples(index=False)
    }
    rows = [
        _row(
            identity=current,
            latest=by_cik.get(int(current.cik)),
            formation=formation,
            retrieved=retrieved,
        )
        for current in identity.itertuples(index=False)
    ]
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


__all__ = [
    "SINALGO_FORMULA_SHA256",
    "SINALGO_FORMULA_URL",
    "calculate_sec_sinalgo_current",
]
