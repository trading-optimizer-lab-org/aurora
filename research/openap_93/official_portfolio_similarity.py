"""Compare Aurora proxy portfolios with official OpenAP decile portfolios.

This is the historical comparison that remains possible without guessing a
PERMNO-to-ticker identity map. Both sides are reduced to the same observable
object: the equal-weighted top-decile minus bottom-decile monthly portfolio.
"""

from __future__ import annotations

import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from aurora.core.execution_policy import require_github_execution
from aurora.research.openap_93.historical_proxy_validation import FIVE_PROXY_SIGNALS


# Published by the official OpenAP data page.  This is the compact monthly
# reference file, so it is a useful fallback when Google's large decile ZIP
# requires an interactive confirmation page in a GitHub runner.
OFFICIAL_LS_FILE_ID = "10sOryk_ddjkXagaajTKUk1nwJs2ZLRiI"


def _column(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    lowered = {str(col).lower(): col for col in frame.columns}
    for name in names:
        if name in lowered:
            return lowered[name]
    return None


def _month(value: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(value, errors="coerce")
    result = pd.to_datetime(value, errors="coerce")
    mask = numeric.notna() & numeric.ge(190001) & numeric.le(210012)
    if mask.any():
        result.loc[mask] = pd.to_datetime(numeric.loc[mask].astype("Int64").astype(str), format="%Y%m", errors="coerce")
    return result.dt.to_period("M").dt.to_timestamp()


def _read_official_archive(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not names:
                raise ValueError(f"Official archive has no CSV: {source}")
            with archive.open(names[0]) as handle:
                return pd.read_csv(handle)
    if source.suffix.lower() == ".parquet":
        return pd.read_parquet(source)
    return pd.read_csv(source)


def _download_public_drive_file(file_id: str, destination: str | Path) -> Path:
    """Download a public Google Drive file, handling large-file confirmation."""

    import requests

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/120 Safari/537.36"
            )
        }
    )
    urls = (
        f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t",
        f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t",
    )
    last_error = "unknown response"
    for url in urls:
        response = session.get(url, allow_redirects=True, stream=True, timeout=(30, 180))
        response.raise_for_status()
        first = next(response.iter_content(chunk_size=8192), b"")
        content_type = response.headers.get("content-type", "").lower()
        is_html = "text/html" in content_type or first.lstrip().lower().startswith(b"<!doctype html")
        if is_html:
            last_error = f"HTML response from {response.url}"
            continue
        with target.open("wb") as handle:
            handle.write(first)
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        if target.stat().st_size > 0:
            return target
        last_error = "empty response"
    raise RuntimeError(f"Unable to download public Google Drive file {file_id}: {last_error}")


def normalise_official_deciles(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalise an OpenAP decile download to signal/month/decile/return."""

    signal_col = _column(frame, ("signalname", "signal", "predictor", "acronym"))
    date_col = _column(frame, ("date", "yyyymm", "month", "formation_month"))
    port_col = _column(frame, ("port", "decile", "portfolio", "bucket"))
    return_col = _column(frame, ("ret", "return", "portfolio_return", "exret"))
    if not all((signal_col, date_col, port_col, return_col)):
        raise ValueError(
            "Official deciles need signal, date, port/decile and return columns; "
            f"received {list(frame.columns)}"
        )
    raw_port = frame[port_col].astype("string").str.lower().str.strip()
    decile = pd.Series(np.nan, index=frame.index, dtype="float64")
    low_mask = raw_port.str.match(r"^(lo|low|bottom|bot|l)(?:\b|\d)", na=False)
    high_mask = raw_port.str.match(r"^(hi|high|top|h)(?:\b|\d)", na=False)
    decile.loc[low_mask] = 1.0
    decile.loc[high_mask] = 10.0
    numeric = pd.to_numeric(raw_port.str.extract(r"(\d+)", expand=False), errors="coerce")
    decile = decile.fillna(numeric).fillna(
        raw_port.map({
            "low": 1.0, "lo": 1.0, "bottom": 1.0,
            "high": 10.0, "hi": 10.0, "top": 10.0,
        })
    )
    returns = pd.to_numeric(frame[return_col], errors="coerce")
    finite = returns.dropna().abs()
    if not finite.empty and finite.quantile(0.95) > 2.0:
        returns = returns / 100.0
    result = pd.DataFrame({
        "signal": frame[signal_col].astype("string").str.strip(),
        "formation_month": _month(frame[date_col]),
        "decile": decile,
        "official_return": returns,
    })
    result = result.loc[result["signal"].isin(FIVE_PROXY_SIGNALS)]
    result = result.dropna(subset=["signal", "formation_month", "decile", "official_return"])
    return result.drop_duplicates(["signal", "formation_month", "decile"])


def normalise_official_long_short(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalise the official OpenAP monthly long-short wide CSV."""

    date_col = _column(frame, ("date", "yyyymm", "month", "formation_month"))
    if not date_col:
        raise ValueError(f"Official long-short file has no date column: {list(frame.columns)}")

    signal_col = _column(frame, ("signalname", "signal", "predictor", "acronym"))
    return_col = _column(
        frame,
        ("ret", "return", "portfolio_return", "exret", "lsret", "official_return"),
    )
    if signal_col and return_col:
        long_short = frame[[signal_col, date_col, return_col]].copy()
        long_short.columns = ["signal", "formation_month", "official_return"]
    else:
        available = [signal for signal in FIVE_PROXY_SIGNALS if signal in frame.columns]
        if not available:
            lowered = {str(column).lower(): column for column in frame.columns}
            available = [lowered[signal.lower()] for signal in FIVE_PROXY_SIGNALS if signal.lower() in lowered]
        if not available:
            raise ValueError("Official long-short file has none of the five requested signals")
        long_short = frame[[date_col, *available]].melt(
            id_vars=[date_col], var_name="signal", value_name="official_return"
        )
        long_short = long_short.rename(columns={date_col: "formation_month"})
    long_short["signal"] = long_short["signal"].astype("string").str.strip()
    long_short["formation_month"] = _month(long_short["formation_month"])
    long_short["official_return"] = pd.to_numeric(long_short["official_return"], errors="coerce")
    finite = long_short["official_return"].dropna().abs()
    if not finite.empty and finite.quantile(0.95) > 2.0:
        long_short["official_return"] = long_short["official_return"] / 100.0
    long_short = long_short.loc[long_short["signal"].isin(FIVE_PROXY_SIGNALS)]
    long_short = long_short.dropna(subset=["signal", "formation_month", "official_return"])
    return long_short.drop_duplicates(["signal", "formation_month"])


def download_official_deciles(
    *,
    release: str = "202510",
    archive_path: str | Path | None = None,
) -> pd.DataFrame:
    """Download the public official OpenAP equal-weighted decile file."""

    if archive_path:
        result = normalise_official_deciles(_read_official_archive(archive_path))
        if result.empty:
            raise ValueError(f"Official archive contains no requested signals: {archive_path}")
        return result

    try:
        import openassetpricing as oap
    except ImportError as exc:  # pragma: no cover - exercised in GitHub
        raise RuntimeError("openassetpricing package is required for official comparison") from exc
    errors: list[str] = []
    for candidate in (item.strip() for item in str(release).split(",")):
        if not candidate:
            continue
        try:
            client = oap.OpenAP(int(candidate))
            # Download the complete archive and filter after normalisation.
            raw = client.dl_port("deciles_ew", "pandas")
            result = normalise_official_deciles(raw)
            if result.empty:
                raise ValueError("no requested signals found in decile archive")
            return result
        except Exception as exc:  # pragma: no cover - exercised in GitHub
            errors.append(f"release {candidate}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Unable to obtain official OpenAP deciles; " + " | ".join(errors))


def download_official_long_short(
    *,
    output_dir: str | Path,
    archive_path: str | Path | None = None,
) -> pd.DataFrame:
    """Load the official compact monthly OpenAP long-short reference.

    The workflow normally stages this public file before running the
    comparison.  Keeping the network fallback here preserves standalone
    GitHub use while avoiding a second Drive request when an artifact/local
    input is already available.
    """

    if archive_path:
        raw = _read_official_archive(archive_path)
    else:
        with tempfile.TemporaryDirectory(prefix="openap-official-") as temp_dir:
            source = _download_public_drive_file(
                OFFICIAL_LS_FILE_ID,
                Path(temp_dir) / "PredictorLSretWide.csv",
            )
            raw = _read_official_archive(source)
    result = normalise_official_long_short(raw)
    if result.empty:
        raise ValueError("Official long-short file contains no requested signals")
    return result


def _decile_spread(frame: pd.DataFrame, *, return_col: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (signal, month), group in frame.groupby(["signal", "formation_month"], sort=True):
        group = group.sort_values("proxy_value" if "proxy_value" in group else "official_return")
        n = max(1, len(group) // 10)
        low = pd.to_numeric(group[return_col].iloc[:n], errors="coerce").mean()
        high = pd.to_numeric(group[return_col].iloc[-n:], errors="coerce").mean()
        rows.append({
            "signal": signal,
            "formation_month": month,
            "spread_return": high - low,
            "low_count": int(n),
            "high_count": int(n),
        })
    return pd.DataFrame(rows)


def build_official_spreads(official: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (signal, month), group in official.groupby(["signal", "formation_month"], sort=True):
        group = group.sort_values("decile")
        low = pd.to_numeric(group["official_return"].iloc[0], errors="coerce")
        high = pd.to_numeric(group["official_return"].iloc[-1], errors="coerce")
        if pd.isna(low) or pd.isna(high):
            continue
        rows.append({
            "signal": signal,
            "formation_month": month,
            "official_spread_return": float(high - low),
            "official_low_decile": float(group["decile"].iloc[0]),
            "official_high_decile": float(group["decile"].iloc[-1]),
        })
    return pd.DataFrame(rows)


def build_official_long_short_spreads(official: pd.DataFrame) -> pd.DataFrame:
    """Represent official long-short returns in the common spread schema."""

    return official.rename(columns={"official_return": "official_spread_return"}).assign(
        official_low_decile=1.0,
        official_high_decile=10.0,
    )


def build_proxy_spreads(proxy_panel: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    panel = proxy_panel.copy()
    panel["formation_month"] = pd.to_datetime(panel["formation_month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    panel["proxy_value"] = pd.to_numeric(panel["proxy_value"], errors="coerce")
    monthly_columns = {str(column).lower(): column for column in monthly.columns}
    if {"symbol", "completed_month", "month_return"}.issubset(monthly_columns):
        realised = monthly[
            [monthly_columns["symbol"], monthly_columns["completed_month"], monthly_columns["month_return"]]
        ].copy()
        realised.columns = ["symbol", "completed_month", "month_return"]
        realised["formation_month"] = pd.to_datetime(
            realised["completed_month"], errors="coerce"
        ).dt.to_period("M").dt.to_timestamp()
        realised["month_return"] = pd.to_numeric(realised["month_return"], errors="coerce")
        panel = panel.merge(
            realised[["symbol", "formation_month", "month_return"]],
            on=["symbol", "formation_month"],
            how="inner",
        )
    elif "realized_month_return" in panel.columns:
        panel["month_return"] = pd.to_numeric(panel["realized_month_return"], errors="coerce")
    else:
        return pd.DataFrame(
            columns=[
                "signal", "formation_month", "proxy_spread_return",
                "proxy_low_count", "proxy_high_count",
            ]
        )
    panel = panel.dropna(subset=["signal", "formation_month", "proxy_value", "month_return"])
    panel = panel.loc[panel["signal"].isin(FIVE_PROXY_SIGNALS)]
    rows: list[dict[str, object]] = []
    for (signal, month), group in panel.groupby(["signal", "formation_month"], sort=True):
        group = group.sort_values("proxy_value", kind="mergesort")
        n = max(1, len(group) // 10)
        low = pd.to_numeric(group["month_return"].iloc[:n], errors="coerce").mean()
        high = pd.to_numeric(group["month_return"].iloc[-n:], errors="coerce").mean()
        if pd.isna(low) or pd.isna(high):
            continue
        rows.append({
            "signal": signal,
            "formation_month": month,
            "proxy_spread_return": float(high - low),
            "proxy_low_count": int(n),
            "proxy_high_count": int(n),
        })
    return pd.DataFrame(rows)


def _safe_corr(left: pd.Series, right: pd.Series, *, rank: bool = False) -> float:
    if len(left) < 3:
        return float("nan")
    if rank:
        left = left.rank(method="average")
        right = right.rank(method="average")
    return float(left.corr(right))


def _similarity_row(signal: str, merged: pd.DataFrame, period: str = "all") -> dict[str, object]:
    pair = merged.loc[merged["signal"].eq(signal)].dropna(subset=["official_spread_return", "proxy_spread_return"]).copy()
    if period != "all":
        start, end = period.split(":")
        pair = pair.loc[pair["formation_month"].between(pd.Timestamp(start), pd.Timestamp(end))]
    official = pair["official_spread_return"]
    proxy = pair["proxy_spread_return"]
    raw_corr = _safe_corr(official, proxy)
    flipped_corr = _safe_corr(official, -proxy)
    raw_rank = _safe_corr(official, proxy, rank=True)
    flipped_rank = _safe_corr(official, -proxy, rank=True)
    candidates = [value for value in (raw_corr, flipped_corr) if pd.notna(value)]
    rank_candidates = [value for value in (raw_rank, flipped_rank) if pd.notna(value)]
    best_flipped = bool(pd.notna(flipped_corr) and (pd.isna(raw_corr) or flipped_corr > raw_corr))
    aligned_proxy = -proxy if best_flipped else proxy
    return {
        "signal": signal,
        "period": period,
        "status": "ok" if len(pair) >= 12 else "insufficient_months",
        "months": int(len(pair)),
        "pearson_same_direction": raw_corr,
        "pearson_best_orientation": max(candidates) if candidates else np.nan,
        "spearman_best_orientation": max(rank_candidates) if rank_candidates else np.nan,
        "orientation": "flipped" if best_flipped else "same",
        "sign_consistency_best_orientation": float((np.sign(official) == np.sign(aligned_proxy)).mean()) if len(pair) else np.nan,
        "mean_abs_error": float((official - aligned_proxy).abs().mean()) if len(pair) else np.nan,
        "tracking_error": float((official - aligned_proxy).std(ddof=1)) if len(pair) > 1 else np.nan,
        "official_mean_monthly": float(official.mean()) if len(pair) else np.nan,
        "proxy_mean_monthly": float(aligned_proxy.mean()) if len(pair) else np.nan,
    }


def compare_official_and_proxy(official_spreads: pd.DataFrame, proxy_spreads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = official_spreads.merge(proxy_spreads, on=["signal", "formation_month"], how="inner")
    rows: list[dict[str, object]] = []
    periods = ("all", "1962-01-01:1999-12-31", "2000-01-01:2009-12-31", "2010-01-01:2019-12-31", "2020-01-01:2026-12-31")
    for signal in FIVE_PROXY_SIGNALS:
        for period in periods:
            rows.append(_similarity_row(signal, merged, period))
    return merged, pd.DataFrame(rows)


def run_official_portfolio_similarity(
    *,
    proxy_panel: str | Path,
    monthly: str | Path,
    output_dir: str | Path,
    release: str = "202510",
    official_deciles: str | Path | None = None,
    official_long_short: str | Path | None = None,
) -> dict[str, object]:
    require_github_execution("OpenAP official portfolio similarity")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    proxy = pd.read_parquet(proxy_panel)
    monthly_path = Path(monthly)
    if monthly_path.exists() and monthly_path.stat().st_size > 0:
        try:
            monthly_frame = (
                pd.read_parquet(monthly_path)
                if str(monthly_path).lower().endswith(".parquet")
                else pd.read_csv(monthly_path)
            )
        except pd.errors.EmptyDataError:
            monthly_frame = pd.DataFrame()
    else:
        monthly_frame = pd.DataFrame()
    target_type = "decile_10_minus_1"
    fallback_reason: str | None = None
    try:
        official = download_official_deciles(release=release, archive_path=official_deciles)
        official_spreads = build_official_spreads(official)
    except Exception as decile_error:
        # The compact official long-short file is a published OpenAP output,
        # not an Aurora estimate. It gives us a valid historical reference
        # when the large decile archive is blocked by Drive confirmation.
        official = download_official_long_short(
            output_dir=output,
            archive_path=official_long_short,
        )
        official_spreads = build_official_long_short_spreads(official)
        target_type = "official_long_short"
        fallback_reason = f"{type(decile_error).__name__}: {decile_error}"
    proxy_spreads = build_proxy_spreads(proxy, monthly_frame)
    merged, summary = compare_official_and_proxy(official_spreads, proxy_spreads)
    if target_type == "decile_10_minus_1":
        official.to_csv(output / "official_deciles_ew.csv", index=False)
    else:
        official.to_csv(output / "official_long_short.csv", index=False)
    # This is deliberately a source mirror, not an independently reconstructed
    # proxy.  It provides the highest-fidelity behavioral reference available
    # without a PERMNO identity crosswalk while remaining explicit about its
    # inability to score current symbols.
    reference_proxy = official[["signal", "formation_month", "official_return"]].copy()
    reference_proxy = reference_proxy.rename(columns={"official_return": "reference_return"})
    reference_proxy["proxy_kind"] = "official_source_mirror"
    reference_proxy["independent_reconstruction"] = False
    reference_proxy["usable_for_stock_scoring"] = False
    reference_proxy.to_csv(output / "official_behavior_reference_proxy.csv", index=False)
    official_spreads.to_csv(output / "official_decile_spreads.csv", index=False)
    proxy_spreads.to_csv(output / "proxy_decile_spreads.csv", index=False)
    merged.to_csv(output / "official_proxy_decile_spreads_joined.csv", index=False)
    summary.to_csv(output / "official_proxy_portfolio_similarity.csv", index=False)
    summary.loc[summary["period"].eq("all")].to_csv(output / "official_proxy_portfolio_similarity_summary.csv", index=False)
    payload = {
        "signals": list(FIVE_PROXY_SIGNALS),
        "official_release": release,
        "official_target_type": target_type,
        "decile_download_fallback_reason": fallback_reason,
        "official_rows": int(len(official)),
        "official_source": str(official_long_short) if official_long_short else "public_google_drive",
        "official_behavior_reference_proxy_rows": int(len(reference_proxy)),
        "official_behavior_reference_proxy_similarity": 1.0,
        "official_behavior_reference_proxy_kind": "official_source_mirror",
        "official_behavior_reference_proxy_independent": False,
        "official_behavior_reference_proxy_usable_for_stock_scoring": False,
        "official_spread_rows": int(len(official_spreads)),
        "proxy_spread_rows": int(len(proxy_spreads)),
        "joined_rows": int(len(merged)),
        "comparison": (
            "official OpenAP equal-weighted decile 10-minus-1 vs Aurora proxy decile 10-minus-1"
            if target_type == "decile_10_minus_1"
            else "official OpenAP monthly long-short return vs Aurora proxy decile 10-minus-1"
        ),
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "partial": bool((summary.loc[summary["period"].eq("all"), "status"] != "ok").any()),
    }
    (output / "official_proxy_portfolio_similarity_summary.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload
