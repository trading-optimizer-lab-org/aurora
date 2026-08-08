"""Audit Aurora proxy signals against official OpenAP stock-level signals.

This module deliberately refuses to correlate ticker rows with PERMNO rows
without an explicit identifier bridge.  A high correlation obtained after an
incorrect join would be worse than no result.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence
import zipfile

import numpy as np
import pandas as pd


EXPECTED_OPENAP_SIGNALS = 212
DEFAULT_PROXY_COUNT_EXPECTED = 44
CANONICAL_PROXY_SIGNALS = (
    "AOP", "AgeIPO", "AnalystRevision", "CPVolSpread", "ChForecastAccrual",
    "ChangeInRecommendation", "CredRatDG", "DelBreadth", "DivInit", "DivOmit",
    "DivSeason", "DownRecomm", "EarningsForecastDisparity", "ExclExp", "FEPS",
    "ForecastDispersion", "IO_ShortInterest", "IndIPO", "NOA", "OptionVolume1",
    "OptionVolume2", "RDIPO", "RDcap", "REV6", "RIO_Disp", "RIO_MB",
    "RIO_Turnover", "RIO_Volatility", "RIVolSpread", "Recomm_ShortInterest",
    "ShareVol", "SmileSlope", "Spinoff", "TrendFactor", "UpRecomm", "VolSD",
    "VolumeTrend", "dCPVolSpread", "dNoa", "dVolCall", "fgr5yrLag", "sfe",
    "skew1", "std_turn",
)


class ProxyCorrelationError(RuntimeError):
    """Raised when an input violates the proxy-real audit contract."""


@dataclass(frozen=True)
class PanelSchema:
    entity_column: str
    month_column: str
    signal_column: str | None
    value_column: str | None


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _find_column(columns: Iterable[object], candidates: Sequence[str]) -> str | None:
    normalized = {str(column).strip().lower(): str(column) for column in columns}
    for candidate in candidates:
        if candidate.lower() in normalized:
            return normalized[candidate.lower()]
    return None


def detect_panel_schema(frame: pd.DataFrame) -> PanelSchema:
    entity = _find_column(
        frame.columns,
        ("entity_id", "instrument_id", "permno", "gvkey", "cusip", "ticker", "symbol"),
    )
    month = _find_column(frame.columns, ("yyyymm", "yearmonth", "month", "date", "as_of"))
    signal = _find_column(frame.columns, ("signalname", "signal", "predictor", "metric"))
    value = _find_column(frame.columns, ("value", "raw_value", "signal_value", "proxy_value", "official_value"))
    if entity is None or month is None:
        raise ProxyCorrelationError(
            "Panel sin identificador de empresa y mes; no se puede alinear de forma segura."
        )
    if signal is not None and value is None:
        raise ProxyCorrelationError("Panel largo con signalname pero sin columna de valor")
    return PanelSchema(entity, month, signal, value)


def _canonical_month(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    compact = text.str.fullmatch(r"\d{6}")
    parsed = pd.to_datetime(text, errors="coerce")
    parsed.loc[compact] = pd.to_datetime(text.loc[compact] + "01", format="%Y%m%d", errors="coerce")
    return parsed.dt.to_period("M").astype("string")


def _canonical_entity(series: pd.Series, *, namespace: str) -> pd.Series:
    return namespace + ":" + series.astype(str).str.strip().str.upper()


def _read_csv_or_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ProxyCorrelationError(f"No existe el panel requerido: {path}")
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() in {".csv", ".txt"}:
        return pd.read_csv(path, low_memory=False)
    raise ProxyCorrelationError(f"Formato de panel no soportado: {path}")


def _normalise_panel_frame(
    frame: pd.DataFrame,
    *,
    namespace: str,
    signals: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Normalise wide or long data without silently changing identifiers."""

    schema = detect_panel_schema(frame)
    if schema.signal_column is not None:
        rename_map = {
            schema.entity_column: "entity_id",
            schema.month_column: "month",
            schema.signal_column: "signalname",
        }
        if schema.value_column is not None:
            rename_map[schema.value_column] = "value"
        result = frame.rename(columns=rename_map)[["entity_id", "month", "signalname", "value"]].copy()
    else:
        excluded = {schema.entity_column, schema.month_column}
        selected = [str(column) for column in frame.columns if str(column) not in excluded]
        if signals is not None:
            wanted = set(signals)
            selected = [column for column in selected if column in wanted]
        if not selected:
            raise ProxyCorrelationError("Panel ancho no contiene señales solicitadas")
        result = frame.rename(columns={schema.entity_column: "entity_id", schema.month_column: "month"})
        result = result[["entity_id", "month", *selected]].melt(
            id_vars=["entity_id", "month"], var_name="signalname", value_name="value"
        )
    result["entity_id"] = _canonical_entity(result["entity_id"], namespace=namespace)
    result["month"] = _canonical_month(result["month"])
    result["signalname"] = result["signalname"].astype(str)
    result["value"] = pd.to_numeric(result["value"], errors="coerce")
    return result.dropna(subset=["entity_id", "month", "signalname", "value"]).drop_duplicates(
        ["entity_id", "month", "signalname"]
    )


def read_panel(
    path: str | Path,
    *,
    namespace: str,
    signals: Sequence[str] | None = None,
    require_permno: bool = False,
) -> pd.DataFrame:
    """Read a long or wide panel into entity_id, month, signalname, value."""

    source = Path(path)
    frame = _read_csv_or_parquet(source)
    schema = detect_panel_schema(frame)
    if require_permno and schema.entity_column.lower() != "permno":
        raise ProxyCorrelationError(
            f"Panel debe venir identificado por PERMNO; se encontró {schema.entity_column!r}."
        )
    return _normalise_panel_frame(frame, namespace=namespace, signals=signals)


def read_zip_panel(path: str | Path, *, namespace: str, signals: Sequence[str]) -> pd.DataFrame:
    """Read only requested signal columns from an official OpenAP zip CSV."""

    archive = Path(path)
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if name.lower().endswith((".csv", ".txt"))]
        if not members:
            raise ProxyCorrelationError("El ZIP oficial no contiene CSV/TXT")
        member = max(members, key=lambda name: bundle.getinfo(name).file_size)
        with bundle.open(member) as handle:
            header = pd.read_csv(handle, nrows=0)
        schema = detect_panel_schema(header)
        if schema.signal_column is not None:
            if schema.value_column is None:
                raise ProxyCorrelationError("Panel largo oficial sin columna de valor")
            usecols = [schema.entity_column, schema.month_column, schema.signal_column, schema.value_column]
        else:
            selected = [name for name in signals if name in header.columns]
            if not selected:
                raise ProxyCorrelationError("El ZIP oficial no contiene ninguna proxy solicitada")
            usecols = [schema.entity_column, schema.month_column, *selected]
        with bundle.open(member) as handle:
            frame = pd.read_csv(handle, usecols=list(dict.fromkeys(usecols)), low_memory=False)
    return read_panel_from_frame(frame, namespace=namespace, signals=signals, require_permno=True)


def read_panel_from_frame(
    frame: pd.DataFrame,
    *,
    namespace: str,
    signals: Sequence[str] | None = None,
    require_permno: bool = False,
) -> pd.DataFrame:
    schema = detect_panel_schema(frame)
    if require_permno and schema.entity_column.lower() != "permno":
        raise ProxyCorrelationError(
            f"Panel debe venir identificado por PERMNO; se encontró {schema.entity_column!r}."
        )
    return _normalise_panel_frame(frame, namespace=namespace, signals=signals)


def load_proxy_names(
    path: str | Path | None,
    proxy_panel: pd.DataFrame | None = None,
    snapshot: str | Path | None = None,
) -> list[str]:
    if path is not None:
        names = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(names) != len(set(names)):
            raise ProxyCorrelationError("La lista de proxies contiene duplicados")
        return names
    if proxy_panel is None:
        if snapshot is None:
            return []
        snapshot_path = Path(snapshot)
        if not snapshot_path.exists():
            raise ProxyCorrelationError(f"No existe el snapshot de proxies: {snapshot_path}")
        snapshot_frame = _read_csv_or_parquet(snapshot_path)
        if not {"signalname", "status"}.issubset(snapshot_frame.columns):
            raise ProxyCorrelationError("El snapshot necesita signalname y status")
        return sorted(
            snapshot_frame.loc[snapshot_frame["status"].astype(str).str.lower().eq("proxy"), "signalname"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
    return sorted(proxy_panel["signalname"].dropna().astype(str).unique().tolist())


def load_canonical_proxy_names(
    path: str | Path = "config/openap_proxy_44_signals.txt",
) -> list[str]:
    """Load and validate the frozen 44-proxy inventory from the 212 catalogue."""

    names = load_proxy_names(path)
    if tuple(names) != CANONICAL_PROXY_SIGNALS:
        raise ProxyCorrelationError(
            "El registro canónico de proxies no coincide exactamente con las 44 señales congeladas"
        )
    if len(names) != DEFAULT_PROXY_COUNT_EXPECTED:
        raise ProxyCorrelationError(
            f"El registro canónico debe contener {DEFAULT_PROXY_COUNT_EXPECTED} señales; contiene {len(names)}"
        )
    return names


def validate_identity_bridge(path: str | Path) -> dict[str, object]:
    """Validate the bridge contract; never use a current ticker as identity."""

    bridge_path = Path(path)
    if not bridge_path.exists():
        raise ProxyCorrelationError(f"No existe el puente de identificadores: {bridge_path}")
    bridge = _read_csv_or_parquet(bridge_path)
    lower = {str(column).strip().lower() for column in bridge.columns}
    if "permno" not in lower:
        raise ProxyCorrelationError("El puente no contiene PERMNO")
    if not ({"ticker", "symbol"} & lower):
        raise ProxyCorrelationError("El puente no contiene ticker o symbol")
    return {
        "path": str(bridge_path),
        "rows": int(len(bridge)),
        "columns": [str(column) for column in bridge.columns],
        "has_valid_from": bool({"valid_from", "start_date", "from_date"} & lower),
        "has_valid_to": bool({"valid_to", "end_date", "to_date"} & lower),
        "sha256": sha256_file(bridge_path),
    }


def _safe_corr(left: pd.Series, right: pd.Series, method: str) -> float | None:
    if len(left) < 3 or left.nunique() < 2 or right.nunique() < 2:
        return None
    value = left.corr(right, method=method)
    return float(value) if pd.notna(value) else None


def audit_proxy_real(
    official: pd.DataFrame,
    proxy: pd.DataFrame,
    *,
    signal_names: Sequence[str],
    signs: Mapping[str, float] | None = None,
    min_overlap_rows: int = 60,
    min_overlap_months: int = 12,
    correlation_threshold: float = 0.95,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one summary row per requested proxy plus monthly diagnostics."""

    sign_map = {str(key): float(value) for key, value in (signs or {}).items()}
    requested = list(dict.fromkeys(str(name) for name in signal_names))
    if not requested:
        raise ProxyCorrelationError("No hay proxies solicitadas")
    official = official.loc[official["signalname"].isin(requested)].copy()
    proxy = proxy.loc[proxy["signalname"].isin(requested)].copy()
    official = official.rename(columns={"value": "official_value"})
    proxy = proxy.rename(columns={"value": "proxy_value"})
    merged = official.merge(proxy, on=["entity_id", "month", "signalname"], how="inner")
    if not merged.empty:
        merged["proxy_value"] = merged.apply(
            lambda row: row["proxy_value"] * sign_map.get(row["signalname"], 1.0), axis=1
        )
    summary: list[dict[str, object]] = []
    monthly_rows: list[dict[str, object]] = []
    for signal in requested:
        subset = merged.loc[merged["signalname"].eq(signal)].copy()
        if subset.empty:
            summary.append({"signalname": signal, "status": "not_computable", "failure_reason": "no_aligned_rows"})
            continue
        per_month = []
        for month, group in subset.groupby("month", sort=True):
            pearson = _safe_corr(group["official_value"], group["proxy_value"], "pearson")
            spearman = _safe_corr(group["official_value"], group["proxy_value"], "spearman")
            monthly_rows.append(
                {
                    "signalname": signal,
                    "month": str(month),
                    "n_instruments": int(len(group)),
                    "pearson": pearson,
                    "spearman": spearman,
                }
            )
            if spearman is not None:
                per_month.append(spearman)
        pooled_pearson = _safe_corr(subset["official_value"], subset["proxy_value"], "pearson")
        pooled_spearman = _safe_corr(subset["official_value"], subset["proxy_value"], "spearman")
        months = subset["month"].nunique()
        status = "pass" if (
            len(subset) >= min_overlap_rows
            and months >= min_overlap_months
            and pooled_spearman is not None
            and pooled_spearman >= correlation_threshold
        ) else "fail_threshold"
        summary.append(
            {
                "signalname": signal,
                "status": status,
                "failure_reason": "" if status == "pass" else "overlap_or_correlation_below_threshold",
                "n_overlap_rows": int(len(subset)),
                "n_overlap_months": int(months),
                "n_overlap_instruments": int(subset["entity_id"].nunique()),
                "pearson_pooled": pooled_pearson,
                "spearman_pooled": pooled_spearman,
                "spearman_monthly_mean": float(np.mean(per_month)) if per_month else None,
                "spearman_monthly_median": float(np.median(per_month)) if per_month else None,
                "correlation_threshold": float(correlation_threshold),
            }
        )
    return pd.DataFrame(summary), pd.DataFrame(monthly_rows)


def blocked_report(
    signal_names: Sequence[str],
    *,
    reason: str,
    expected_proxy_count: int = DEFAULT_PROXY_COUNT_EXPECTED,
    observed_proxy_count: int | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    rows = [
        {
            "signalname": signal,
            "status": "not_computable",
            "failure_reason": reason,
            "n_overlap_rows": 0,
            "n_overlap_months": 0,
            "n_overlap_instruments": 0,
            "pearson_pooled": None,
            "spearman_pooled": None,
            "spearman_monthly_mean": None,
            "spearman_monthly_median": None,
            "correlation_threshold": None,
        }
        for signal in signal_names
    ]
    summary = {
        "requested_proxy_count": int(expected_proxy_count),
        "observed_proxy_count": observed_proxy_count,
        "proxy_count_mismatch": observed_proxy_count is not None and observed_proxy_count != expected_proxy_count,
        "correlations_computed": 0,
        "status": "blocked",
        "failure_reason": reason,
        "official_openap_signals": EXPECTED_OPENAP_SIGNALS,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    return pd.DataFrame(rows), summary


def write_audit_manifest(output_dir: str | Path, inputs: Mapping[str, object]) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "proxy_real_manifest.json").write_text(
        json.dumps(dict(inputs), indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
