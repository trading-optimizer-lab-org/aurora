from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ForwardProxyGate:
    minimum_pearson: float = 0.80
    minimum_spearman: float = 0.80
    minimum_sign_agreement: float = 0.75
    minimum_common_months: int = 60
    gate_version: str = "openap-forward-proxy-v1"


@dataclass(frozen=True)
class SelectedForwardProxyVariant:
    signal: str
    variant_id: str
    train_end: str
    common_months: int
    pearson: float
    spearman: float
    sign_agreement: float
    tracking_error: float


@dataclass(frozen=True)
class ForwardProxyCertificate:
    signal: str
    variant_id: str
    formula_sha256: str
    source_manifest_sha256: str
    train_end: str
    validation_start: str
    validation_end: str
    common_months: int
    pearson: float
    spearman: float
    sign_agreement: float
    tracking_error: float
    passed: bool
    locked_opened: bool
    validation_used_for_selection: bool
    backtest_enabled: bool
    gate_version: str


@dataclass(frozen=True)
class _Similarity:
    common_months: int
    pearson: float
    spearman: float
    sign_agreement: float
    tracking_error: float


def _coerce_month(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["month"] = pd.to_datetime(result["month"], errors="raise").dt.to_period("M").dt.to_timestamp()
    return result


def _validate_unique(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    duplicated = frame.duplicated(columns, keep=False)
    if duplicated.any():
        raise ValueError(f"{label} contains duplicate rows for {columns}")


def _aligned_values(
    candidates: pd.DataFrame,
    official: pd.DataFrame,
    *,
    signal: str,
    variant_id: str,
    start: str | None,
    end: str,
) -> tuple[np.ndarray, np.ndarray]:
    candidate_required = {"signal", "variant_id", "month", "proxy_return"}
    official_required = {"signal", "month", "official_return"}
    if missing := candidate_required.difference(candidates.columns):
        raise ValueError(f"candidate columns missing: {sorted(missing)}")
    if missing := official_required.difference(official.columns):
        raise ValueError(f"official columns missing: {sorted(missing)}")

    candidate_rows = _coerce_month(
        candidates.loc[
            (candidates["signal"] == signal) & (candidates["variant_id"] == variant_id)
        ]
    )
    official_rows = _coerce_month(official.loc[official["signal"] == signal])
    _validate_unique(candidate_rows, ["signal", "variant_id", "month"], "candidates")
    _validate_unique(official_rows, ["signal", "month"], "official")

    start_ts = pd.Timestamp(start) if start is not None else None
    end_ts = pd.Timestamp(end)
    candidate_mask = candidate_rows["month"].le(end_ts)
    official_mask = official_rows["month"].le(end_ts)
    if start_ts is not None:
        candidate_mask &= candidate_rows["month"].ge(start_ts)
        official_mask &= official_rows["month"].ge(start_ts)

    aligned = candidate_rows.loc[candidate_mask, ["month", "proxy_return"]].merge(
        official_rows.loc[official_mask, ["month", "official_return"]],
        on="month",
        how="inner",
        validate="one_to_one",
    )
    aligned["proxy_return"] = pd.to_numeric(aligned["proxy_return"], errors="coerce")
    aligned["official_return"] = pd.to_numeric(aligned["official_return"], errors="coerce")
    aligned = aligned.replace([np.inf, -np.inf], np.nan).dropna()
    return (
        aligned["proxy_return"].to_numpy(dtype=float),
        aligned["official_return"].to_numpy(dtype=float),
    )


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2:
        return float("nan")
    if np.array_equal(left, right):
        return 1.0
    if np.std(left) == 0.0 or np.std(right) == 0.0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])


def _similarity(left: np.ndarray, right: np.ndarray) -> _Similarity:
    left_rank = pd.Series(left).rank(method="average").to_numpy(dtype=float)
    right_rank = pd.Series(right).rank(method="average").to_numpy(dtype=float)
    return _Similarity(
        common_months=int(len(left)),
        pearson=_correlation(left, right),
        spearman=_correlation(left_rank, right_rank),
        sign_agreement=float(np.mean(np.sign(left) == np.sign(right))) if len(left) else float("nan"),
        tracking_error=float(np.sqrt(np.mean(np.square(left - right)))) if len(left) else float("nan"),
    )


def select_train_variant(
    candidates: pd.DataFrame,
    official: pd.DataFrame,
    *,
    signal: str,
    train_end: str,
) -> SelectedForwardProxyVariant:
    variants = sorted(
        str(value)
        for value in candidates.loc[candidates["signal"] == signal, "variant_id"].dropna().unique()
    )
    if not variants:
        raise ValueError(f"no candidate variants for {signal}")

    ranked: list[tuple[tuple[float, float, float, float, str], SelectedForwardProxyVariant]] = []
    for variant_id in variants:
        proxy_values, official_values = _aligned_values(
            candidates,
            official,
            signal=signal,
            variant_id=variant_id,
            start=None,
            end=train_end,
        )
        metrics = _similarity(proxy_values, official_values)
        finite_floor = min(metrics.pearson, metrics.spearman)
        if not np.isfinite(finite_floor):
            finite_floor = float("-inf")
        selected = SelectedForwardProxyVariant(
            signal=signal,
            variant_id=variant_id,
            train_end=str(pd.Timestamp(train_end).date()),
            **asdict(metrics),
        )
        rank_key = (
            finite_floor,
            metrics.sign_agreement if np.isfinite(metrics.sign_agreement) else float("-inf"),
            -metrics.tracking_error if np.isfinite(metrics.tracking_error) else float("-inf"),
            float(metrics.common_months),
            variant_id,
        )
        ranked.append((rank_key, selected))
    return max(ranked, key=lambda item: item[0])[1]


def validate_frozen_variant(
    selected: SelectedForwardProxyVariant,
    candidates: pd.DataFrame,
    official: pd.DataFrame,
    *,
    validation_start: str,
    validation_end: str,
    formula_sha256: str,
    source_manifest_sha256: str,
    gate: ForwardProxyGate,
) -> ForwardProxyCertificate:
    proxy_values, official_values = _aligned_values(
        candidates,
        official,
        signal=selected.signal,
        variant_id=selected.variant_id,
        start=validation_start,
        end=validation_end,
    )
    metrics = _similarity(proxy_values, official_values)
    passed = bool(
        metrics.common_months >= gate.minimum_common_months
        and np.isfinite(metrics.pearson)
        and metrics.pearson >= gate.minimum_pearson
        and np.isfinite(metrics.spearman)
        and metrics.spearman >= gate.minimum_spearman
        and np.isfinite(metrics.sign_agreement)
        and metrics.sign_agreement >= gate.minimum_sign_agreement
    )
    return ForwardProxyCertificate(
        signal=selected.signal,
        variant_id=selected.variant_id,
        formula_sha256=formula_sha256,
        source_manifest_sha256=source_manifest_sha256,
        train_end=selected.train_end,
        validation_start=str(pd.Timestamp(validation_start).date()),
        validation_end=str(pd.Timestamp(validation_end).date()),
        passed=passed,
        locked_opened=False,
        validation_used_for_selection=False,
        backtest_enabled=False,
        gate_version=gate.gate_version,
        **asdict(metrics),
    )


def certify_forward_proxy_candidates(
    candidates: pd.DataFrame,
    official: pd.DataFrame,
    *,
    formula_hashes: dict[tuple[str, str], str],
    source_manifest_hashes: dict[tuple[str, str], str],
    train_end: str,
    validation_start: str,
    validation_end: str,
    gate: ForwardProxyGate | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[ForwardProxyCertificate]]:
    """Select variants on train and certify the frozen formulas on validation."""

    active_gate = gate or ForwardProxyGate()
    signals = sorted(str(value) for value in candidates["signal"].dropna().unique())
    selected_rows: list[dict[str, object]] = []
    validation_rows: list[dict[str, object]] = []
    certificates: list[ForwardProxyCertificate] = []
    for signal in signals:
        selected = select_train_variant(
            candidates,
            official,
            signal=signal,
            train_end=train_end,
        )
        identity = (selected.signal, selected.variant_id)
        if identity not in formula_hashes:
            raise ValueError(f"missing formula hash for {identity}")
        if identity not in source_manifest_hashes:
            raise ValueError(f"missing source manifest hash for {identity}")
        certificate = validate_frozen_variant(
            selected,
            candidates,
            official,
            validation_start=validation_start,
            validation_end=validation_end,
            formula_sha256=formula_hashes[identity],
            source_manifest_sha256=source_manifest_hashes[identity],
            gate=active_gate,
        )
        selected_rows.append(asdict(selected))
        validation_record = asdict(certificate)
        validation_record["certificate_sha256"] = certificate_sha256(certificate)
        validation_rows.append(validation_record)
        certificates.append(certificate)
    return pd.DataFrame(selected_rows), pd.DataFrame(validation_rows), certificates


def certificate_sha256(certificate: ForwardProxyCertificate) -> str:
    payload = json.dumps(
        asdict(certificate),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def apply_certificates(
    current_rows: pd.DataFrame,
    certificates: Iterable[ForwardProxyCertificate],
) -> pd.DataFrame:
    required = {
        "signal",
        "variant_id",
        "formula_sha256",
        "source_manifest_sha256",
        "current_usable",
        "base_score_weight",
    }
    if missing := required.difference(current_rows.columns):
        raise ValueError(f"current columns missing: {sorted(missing)}")

    certificate_map = {
        (
            certificate.signal,
            certificate.variant_id,
            certificate.formula_sha256,
            certificate.source_manifest_sha256,
        ): certificate
        for certificate in certificates
    }
    result = current_rows.copy()
    statuses: list[str] = []
    hashes: list[str | None] = []
    passed_flags: list[bool] = []
    for row in result.itertuples(index=False):
        key = (
            str(row.signal),
            str(row.variant_id),
            str(row.formula_sha256),
            str(row.source_manifest_sha256),
        )
        certificate = certificate_map.get(key)
        if certificate is None:
            same_signal_variant = any(
                candidate.signal == key[0] and candidate.variant_id == key[1]
                for candidate in certificate_map.values()
            )
            statuses.append(
                "certificate_identity_mismatch" if same_signal_variant else "missing_certificate"
            )
            hashes.append(None)
            passed_flags.append(False)
        elif not certificate.passed:
            statuses.append("failed_validation_gate")
            hashes.append(certificate_sha256(certificate))
            passed_flags.append(False)
        else:
            statuses.append("certified")
            hashes.append(certificate_sha256(certificate))
            passed_flags.append(True)

    original_usable = result["current_usable"].fillna(False).astype(bool).to_numpy()
    passed_array = np.asarray(passed_flags, dtype=bool)
    result["certificate_status"] = statuses
    result["certificate_sha256"] = hashes
    result["current_usable"] = original_usable & passed_array
    result["effective_score_weight"] = np.where(
        result["current_usable"],
        pd.to_numeric(result["base_score_weight"], errors="coerce").fillna(0.0),
        0.0,
    )
    return result
