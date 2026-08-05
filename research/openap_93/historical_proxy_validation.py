"""Historical, month-by-month validation of the five OpenAP proxies.

This module deliberately separates three things:

* reconstruction of Aurora-side proxy values;
* the PERMNO-to-Aurora identity join;
* similarity statistics against the official OpenAP panel.

The official panel is not joined to current tickers implicitly.  Without a
point-in-time identity crosswalk the comparison is blocked, rather than
silently turning a stale or guessed mapping into a result.
"""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from typing import Iterable, Mapping

import duckdb
import numpy as np
import pandas as pd

from aurora.core.execution_policy import require_github_execution


FIVE_PROXY_SIGNALS = (
    "DivSeason",
    "AnnouncementReturn",
    "EarningsStreak",
    "IndRetBig",
    "DelNetFin",
)

REFERENCE_COLUMNS = ["permno", "yyyymm", *FIVE_PROXY_SIGNALS]


def _naive_date(values: object) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", utc=True).dt.tz_convert(None)


def _previous_month_end(month: object) -> pd.Timestamp:
    period = pd.Period(str(month), freq="M")
    return period.start_time - pd.Timedelta(days=1)


def load_reference_values(path: str | Path) -> pd.DataFrame:
    """Read the official wide reference without loading unused columns."""

    source = Path(path)
    if source.is_dir():
        candidates = list(source.rglob("signed_predictors_dl_wide.zip"))
        candidates += list(source.rglob("signed_predictors_dl_wide.csv"))
        candidates += list(source.rglob("*.parquet"))
        if not candidates:
            raise FileNotFoundError(f"No OpenAP reference found below {source}")
        source = candidates[0]
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            names = [name for name in archive.namelist() if name.endswith(".csv")]
            if not names:
                raise ValueError("OpenAP reference ZIP contains no CSV")
            with archive.open(names[0]) as handle:
                chunks = pd.read_csv(handle, usecols=lambda c: c in REFERENCE_COLUMNS)
        frame = chunks
    elif source.suffix.lower() == ".parquet":
        frame = pd.read_parquet(source, columns=REFERENCE_COLUMNS)
    else:
        frame = pd.read_csv(source, usecols=lambda c: c in REFERENCE_COLUMNS)
    required = {"permno", "yyyymm"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"OpenAP reference missing identifier columns: {sorted(missing)}")
    frame = frame.copy()
    frame["permno"] = pd.to_numeric(frame["permno"], errors="coerce")
    frame["yyyymm"] = pd.to_numeric(frame["yyyymm"], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["permno", "yyyymm"])
    frame["permno"] = frame["permno"].astype("int64")
    frame["formation_month"] = pd.to_datetime(
        frame["yyyymm"].astype(str), format="%Y%m", errors="coerce"
    ).dt.to_period("M").dt.to_timestamp()
    for signal in FIVE_PROXY_SIGNALS:
        if signal not in frame:
            frame[signal] = np.nan
        frame[signal] = pd.to_numeric(frame[signal], errors="coerce")
    return frame[["permno", "yyyymm", "formation_month", *FIVE_PROXY_SIGNALS]]


def load_crosswalk(path: str | Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """Load a lawful PERMNO crosswalk and retain its PIT quality metadata."""

    source = Path(path)
    if source.suffix.lower() == ".parquet":
        frame = pd.read_parquet(source)
    else:
        frame = pd.read_csv(source)
    lowered = {str(col).lower(): col for col in frame.columns}
    permno_col = lowered.get("permno")
    symbol_col = lowered.get("symbol") or lowered.get("ticker")
    if not permno_col or not symbol_col:
        raise ValueError("Crosswalk needs permno and symbol/ticker columns")
    result = pd.DataFrame(
        {
            "permno": pd.to_numeric(frame[permno_col], errors="coerce"),
            "symbol": frame[symbol_col].astype("string").str.upper().str.strip(),
        }
    )
    optional = {str(col).lower(): col for col in frame.columns}
    for target in ("cik", "effective_start", "effective_end"):
        if target in optional:
            result[target] = frame[optional[target]]
    result["cik"] = pd.to_numeric(result.get("cik"), errors="coerce")
    for col in ("effective_start", "effective_end"):
        result[col] = _naive_date(result.get(col, pd.Series(pd.NaT, index=result.index)))
    result = result.dropna(subset=["permno", "symbol"]).copy()
    result["permno"] = result["permno"].astype("int64")
    result = result.drop_duplicates(["permno", "symbol", "effective_start", "effective_end"])
    quality = {
        "rows": int(len(result)),
        "crosswalk_is_pit": bool(result["effective_start"].notna().any()),
        "has_effective_end": bool(result["effective_end"].notna().any()),
        "source": str(source),
    }
    if result.empty:
        raise ValueError("Crosswalk is empty after normalisation")
    return result, quality


def _monthly_prices(
    con: duckdb.DuckDBPyConnection,
    *,
    start_month: pd.Timestamp | None = None,
    end_month: pd.Timestamp | None = None,
) -> pd.DataFrame:
    query = """
        SELECT
            p.symbol,
            date_trunc('month', p.date)::DATE AS completed_month,
            arg_max(p.adj_close, p.date) AS month_end_adj_close,
            sum(coalesce(p.dividends, 0.0)) AS month_dividends
        FROM prices_daily_clean p
        JOIN security_master s USING(symbol)
        WHERE coalesce(s.ranking_eligible, false)
          AND (? IS NULL OR p.date >= ?)
          AND (? IS NULL OR p.date < ?)
        GROUP BY p.symbol, date_trunc('month', p.date)::DATE
        ORDER BY p.symbol, completed_month
    """
    start = start_month.to_period("M").start_time - pd.offsets.MonthBegin(1) if start_month is not None else None
    end = end_month.to_period("M").end_time + pd.Timedelta(days=1) if end_month is not None else None
    frame = con.execute(query, [start, start, end, end]).df()
    frame["completed_month"] = pd.to_datetime(frame["completed_month"], errors="coerce")
    frame["month_end_adj_close"] = pd.to_numeric(frame["month_end_adj_close"], errors="coerce")
    frame["month_dividends"] = pd.to_numeric(frame["month_dividends"], errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["symbol", "completed_month", "month_end_adj_close"])
    frame["month_return"] = frame.groupby("symbol")["month_end_adj_close"].pct_change()
    frame["formation_month"] = frame["completed_month"] + pd.offsets.MonthBegin(1)
    return frame


def _security_master(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    cols = "symbol, cik, industry"
    frame = con.execute(
        f"SELECT {cols} FROM security_master WHERE coalesce(ranking_eligible, false)"
    ).df()
    frame["symbol"] = frame["symbol"].astype("string").str.upper()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["industry"] = frame["industry"].fillna("UNKNOWN").astype("string")
    return frame.dropna(subset=["symbol"]).drop_duplicates("symbol")


def _sec_facts(con: duckdb.DuckDBPyConnection, master: pd.DataFrame) -> pd.DataFrame:
    ciks = master["cik"].dropna().astype("int64").tolist()
    if not ciks:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in ciks)
    tags = [
        "EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding",
        "ShortTermInvestments", "MarketableSecuritiesCurrent", "LongTermInvestments",
        "OtherInvestments", "ShortTermBorrowings", "LongTermDebtCurrent",
        "LongTermDebtNoncurrent", "LongTermDebt", "PreferredStockValue",
        "PreferredStockCarryingValue", "Assets",
        "NetIncomeLoss", "ProfitLoss",
    ]
    tag_placeholders = ",".join("?" for _ in tags)
    query = f"""
        SELECT cik, tag, unit, value, period_start, period_end, form, filed, available_at
        FROM sec_companyfacts
        WHERE cik IN ({placeholders}) AND tag IN ({tag_placeholders})
    """
    frame = con.execute(query, [*ciks, *tags]).df()
    if frame.empty:
        return frame
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    frame["period_start"] = pd.to_datetime(frame["period_start"], errors="coerce")
    frame["available_at"] = _naive_date(frame["available_at"])
    frame["filed"] = _naive_date(frame["filed"])
    return frame.dropna(subset=["cik", "value", "period_end", "available_at"])


def _latest_as_of(frame: pd.DataFrame, cutoff: pd.Timestamp) -> float | None:
    if frame.empty:
        return None
    valid = frame.loc[
        frame["available_at"].le(cutoff)
        & frame["period_end"].le(cutoff.normalize())
    ]
    if valid.empty:
        return None
    valid = valid.sort_values(["available_at", "period_end"])
    value = pd.to_numeric(valid.iloc[-1]["value"], errors="coerce")
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def _latest_shares(facts: pd.DataFrame, cik: float, cutoff: pd.Timestamp) -> float | None:
    subset = facts.loc[(facts["cik"] == cik) & facts["tag"].isin(
        ["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"]
    )]
    return _latest_as_of(subset, cutoff)


def _pit_values(
    issuer_facts: pd.DataFrame,
    tags: Iterable[str],
    cutoffs: pd.Series,
) -> pd.Series:
    """Select one filing observation per cutoff without looking forward."""

    left = pd.DataFrame({"cutoff": pd.to_datetime(cutoffs, errors="coerce")}, index=cutoffs.index)
    right = issuer_facts.loc[issuer_facts["tag"].isin(tuple(tags))].copy()
    if right.empty:
        return pd.Series(np.nan, index=cutoffs.index, dtype=float)
    right = right.sort_values(["available_at", "period_end"]).drop_duplicates(
        ["available_at"], keep="last"
    )
    right = right.rename(columns={"value": "selected_value", "period_end": "selected_period_end"})
    merged = pd.merge_asof(
        left.sort_values("cutoff"),
        right[["available_at", "selected_value", "selected_period_end"]].sort_values("available_at"),
        left_on="cutoff",
        right_on="available_at",
        direction="backward",
    )
    merged.loc[merged["selected_period_end"].gt(merged["cutoff"]), "selected_value"] = np.nan
    return pd.Series(merged["selected_value"].to_numpy(), index=left.sort_values("cutoff").index).reindex(cutoffs.index)


def _build_divseason(monthly: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol, group in monthly.groupby("symbol", sort=False):
        history = group.set_index("completed_month")["month_dividends"].sort_index()
        for completed_month in history.index:
            trailing = history.loc[
                (history.index >= completed_month - pd.DateOffset(months=11))
                & (history.index <= completed_month)
            ]
            if trailing.sum() <= 0:
                value = np.nan
            else:
                paid_months = trailing.loc[trailing.gt(0)].index
                offsets = [
                    (completed_month.year - p.year) * 12 + completed_month.month - p.month
                    for p in paid_months
                ]
                value = float(any(offset in {2, 5, 8, 11} for offset in offsets))
            rows.append({
                "symbol": symbol,
                "completed_month": completed_month,
                "formation_month": completed_month + pd.offsets.MonthBegin(1),
                "signal": "DivSeason",
                "proxy_value": value,
                "proxy_formula_id": "openap_dividend_seasonality_frequency_inferred",
                "reconstruction_status": "reconstructed" if pd.notna(value) else "insufficient_history",
                "caveat": "Yahoo cash distributions replace CRSP cd3 distribution codes",
            })
    return pd.DataFrame(rows)


def _build_announcement_return(
    monthly: pd.DataFrame,
    facts: pd.DataFrame,
    prices_daily: pd.DataFrame,
    ff3_daily: pd.DataFrame | None,
    master: pd.DataFrame,
) -> pd.DataFrame:
    if facts.empty or prices_daily.empty:
        return pd.DataFrame()
    earnings = facts.loc[
        facts["tag"].isin(["NetIncomeLoss", "ProfitLoss"])
        & facts["form"].astype("string").str.upper().isin(["10-Q", "10-K", "10-Q/A", "10-K/A"])
    ].copy()
    earnings = earnings.merge(master[["symbol", "cik"]], on="cik", how="inner")
    earnings = earnings.dropna(subset=["filed", "symbol"])
    rows: list[dict[str, object]] = []
    prices_daily = prices_daily.copy()
    prices_daily["date"] = pd.to_datetime(prices_daily["date"], errors="coerce")
    prices_daily["adj_close"] = pd.to_numeric(prices_daily["adj_close"], errors="coerce")
    prices_daily = prices_daily.sort_values(["symbol", "date"])
    prices_daily["ret"] = prices_daily.groupby("symbol")["adj_close"].pct_change()
    if ff3_daily is not None and not ff3_daily.empty:
        ff3 = ff3_daily.copy()
        ff3["date"] = pd.to_datetime(ff3["date"], errors="coerce")
        for col in ("mktrf", "rf"):
            if col in ff3:
                ff3[col] = pd.to_numeric(ff3[col], errors="coerce").fillna(0.0)
            else:
                ff3[col] = 0.0
        prices_daily = prices_daily.merge(ff3[["date", "mktrf", "rf"]], on="date", how="left")
    else:
        prices_daily["mktrf"] = 0.0
        prices_daily["rf"] = 0.0
    prices_daily["abret"] = prices_daily["ret"] - prices_daily["mktrf"] - prices_daily["rf"]
    for symbol, events in earnings.groupby("symbol"):
        px = prices_daily.loc[prices_daily["symbol"].eq(symbol)].dropna(subset=["date", "abret"])
        if px.empty:
            continue
        event_rows: list[dict[str, object]] = []
        for event_date in sorted(pd.to_datetime(events["filed"]).dropna().unique()):
            event = pd.Timestamp(event_date)
            cutoff = event + pd.Timedelta(days=4)
            window = px.loc[px["date"].between(event - pd.Timedelta(days=4), cutoff)]
            if len(window) < 3:
                continue
            value = float(window["abret"].sum())
            event_rows.append({"available_at": window["date"].max(), "proxy_value": value})
        if not event_rows:
            continue
        event_frame = pd.DataFrame(event_rows).sort_values("available_at").drop_duplicates("available_at", keep="last")
        formation = monthly.loc[monthly["symbol"].eq(symbol), ["completed_month", "formation_month"]].copy()
        formation["cutoff"] = formation["completed_month"] + pd.offsets.MonthEnd(0)
        aligned = pd.merge_asof(
            formation.sort_values("cutoff"),
            event_frame.rename(columns={"available_at": "event_complete_at"}).sort_values("event_complete_at"),
            left_on="cutoff", right_on="event_complete_at", direction="backward",
        )
        for item in aligned.dropna(subset=["proxy_value"]).itertuples(index=False):
            rows.append({
                "symbol": symbol,
                "completed_month": item.completed_month,
                "formation_month": item.formation_month,
                "signal": "AnnouncementReturn",
                "proxy_value": float(item.proxy_value),
                "proxy_formula_id": "openap_announcement_abnormal_return_sec_filing_date_proxy",
                "reconstruction_status": "reconstructed",
                "caveat": "SEC filing date replaces Compustat announcement date; event window is complete before formation",
            })
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).sort_values(["symbol", "completed_month"])
    return result.drop_duplicates(["symbol", "completed_month"], keep="last")


def _build_earnings_streak(monthly: pd.DataFrame) -> pd.DataFrame:
    """Keep this unavailable: current Yahoo earnings history is not PIT monthly data."""
    result = monthly[["symbol", "completed_month", "formation_month"]].copy()
    result["signal"] = "EarningsStreak"
    result["proxy_value"] = np.nan
    result["proxy_formula_id"] = "openap_earnings_streak_yahoo_two_same_sign_surprises_proxy"
    result["reconstruction_status"] = "unavailable_missing_historical_analyst_source"
    result["caveat"] = "No historical point-in-time Yahoo earnings-surprise snapshots are present"
    return result


def _build_indretbig(monthly: pd.DataFrame, master: pd.DataFrame, facts: pd.DataFrame) -> pd.DataFrame:
    frame = monthly.merge(master[["symbol", "cik", "industry"]], on="symbol", how="left")
    share_facts = facts.loc[facts["tag"].isin(
        ["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"]
    )].copy()
    share_facts = share_facts.merge(master[["symbol", "cik"]], on="cik", how="inner")
    rows: list[pd.DataFrame] = []
    frame["cutoff"] = frame["completed_month"] + pd.offsets.MonthEnd(0)
    share_frames: list[pd.DataFrame] = []
    for symbol, group in frame.groupby("symbol", sort=False):
        right = share_facts.loc[share_facts["symbol"].eq(symbol)].sort_values("available_at")
        if right.empty:
            group = group.copy()
            group["shares"] = np.nan
        else:
            group = pd.merge_asof(
                group.sort_values("cutoff"),
                right[["available_at", "value", "period_end"]].rename(columns={"value": "shares"}).sort_values("available_at"),
                left_on="cutoff", right_on="available_at", direction="backward",
            )
            group.loc[group["period_end"].gt(group["cutoff"]), "shares"] = np.nan
        share_frames.append(group)
    frame = pd.concat(share_frames, ignore_index=True)
    for completed_month, group in frame.groupby("completed_month", sort=True):
        group = group.copy()
        group["market_equity"] = group["month_end_adj_close"] * group["shares"]
        group["big"] = group.groupby("industry")["market_equity"].transform(
            lambda s: s.ge(s.quantile(0.70))
        )
        big_return = group.loc[group["big"]].groupby("industry")["month_return"].mean()
        group["proxy_value"] = group["industry"].map(big_return)
        group.loc[group["big"], "proxy_value"] = np.nan
        group["signal"] = "IndRetBig"
        group["formation_month"] = group["completed_month"] + pd.offsets.MonthBegin(1)
        group["proxy_formula_id"] = "openap_big_industry_return_industry_label_proxy"
        group["reconstruction_status"] = np.where(
            group["proxy_value"].notna(), "reconstructed", "insufficient_history"
        )
        group["caveat"] = "Current industry label replaces historical FF48; shares are PIT SEC values"
        rows.append(group[["symbol", "completed_month", "formation_month", "signal", "proxy_value", "proxy_formula_id", "reconstruction_status", "caveat"]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _build_delnetfin(monthly: pd.DataFrame, master: pd.DataFrame, facts: pd.DataFrame) -> pd.DataFrame:
    if facts.empty:
        result = monthly[["symbol", "completed_month", "formation_month"]].copy()
        result["signal"] = "DelNetFin"
        result["proxy_value"] = np.nan
        result["proxy_formula_id"] = "openap_delnetfin_sec_alias_proxy"
        result["reconstruction_status"] = "unavailable_missing_sec_facts"
        result["caveat"] = "SEC Company Facts not available for the issuer"
        return result
    debt_current = ["ShortTermBorrowings", "LongTermDebtCurrent"]
    debt_long = ["LongTermDebtNoncurrent", "LongTermDebt"]
    short_inv = ["ShortTermInvestments", "MarketableSecuritiesCurrent"]
    long_inv = ["LongTermInvestments", "OtherInvestments"]
    preferred = ["PreferredStockValue", "PreferredStockCarryingValue"]
    result_rows: list[dict[str, object]] = []
    for symbol, group in monthly.merge(master[["symbol", "cik"]], on="symbol", how="left").groupby("symbol"):
        cik = group["cik"].dropna().iloc[0] if group["cik"].notna().any() else np.nan
        issuer = facts.loc[facts["cik"].eq(cik)].copy() if pd.notna(cik) else pd.DataFrame()
        group = group.sort_values("completed_month").copy()
        group["cutoff"] = group["completed_month"] + pd.offsets.MonthEnd(0)
        current = _pit_values(issuer, short_inv, group["cutoff"]).fillna(0.0)
        current += _pit_values(issuer, long_inv, group["cutoff"]).fillna(0.0)
        current -= _pit_values(issuer, debt_current, group["cutoff"]).fillna(0.0)
        current -= _pit_values(issuer, debt_long, group["cutoff"]).fillna(0.0)
        current -= _pit_values(issuer, preferred, group["cutoff"]).fillna(0.0)
        assets = _pit_values(issuer, ["Assets"], group["cutoff"])
        state = (current / assets.replace(0, np.nan)).set_axis(group["completed_month"].to_numpy())
        state = state.sort_index()
        for completed_month, current in state.items():
            previous = state.loc[state.index < completed_month].dropna()
            previous_value = previous.iloc[-1] if not previous.empty else np.nan
            value = current - previous_value if pd.notna(current) and pd.notna(previous_value) else np.nan
            result_rows.append({
                "symbol": symbol,
                "completed_month": completed_month,
                "formation_month": pd.Timestamp(completed_month) + pd.offsets.MonthBegin(1),
                "signal": "DelNetFin",
                "proxy_value": value,
                "proxy_formula_id": "openap_delnetfin_sec_alias_proxy",
                "reconstruction_status": "reconstructed" if pd.notna(value) else "insufficient_history",
                "caveat": "SEC aliases replace Compustat net-financial-asset components; missing optional components are zero",
            })
    return pd.DataFrame(result_rows)


def reconstruct_monthly_proxies(
    base_db: str | Path,
    *,
    ff3_daily: str | Path | None = None,
    start_month: pd.Timestamp | None = None,
    end_month: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Reconstruct five proxies using data available by each prior month-end."""

    db = Path(base_db)
    if db.is_dir():
        candidates = list(db.rglob("*.duckdb"))
        if not candidates:
            raise FileNotFoundError(f"No DuckDB database below {db}")
        db = candidates[0]
    con = duckdb.connect(str(db), read_only=True)
    try:
        master = _security_master(con)
        monthly = _monthly_prices(con, start_month=start_month, end_month=end_month)
        facts = _sec_facts(con, master)
        daily_query = """
            SELECT p.symbol, p.date, p.adj_close, p.dividends
            FROM prices_daily_clean p
            JOIN security_master s USING(symbol)
            WHERE coalesce(s.ranking_eligible, false)
              AND (? IS NULL OR p.date >= ?)
              AND (? IS NULL OR p.date < ?)
            ORDER BY p.symbol, p.date
        """
        start = start_month.to_period("M").start_time - pd.offsets.MonthBegin(1) if start_month is not None else None
        end = end_month.to_period("M").end_time + pd.Timedelta(days=1) if end_month is not None else None
        prices_daily = con.execute(daily_query, [start, start, end, end]).df()
    finally:
        con.close()
    ff3 = pd.read_parquet(ff3_daily) if ff3_daily and str(ff3_daily).lower().endswith(".parquet") else None
    if ff3_daily and ff3 is None:
        ff3 = pd.read_csv(ff3_daily)
    parts = [
        _build_divseason(monthly),
        _build_announcement_return(monthly, facts, prices_daily, ff3, master),
        _build_earnings_streak(monthly),
        _build_indretbig(monthly, master, facts),
        _build_delnetfin(monthly, master, facts),
    ]
    result = pd.concat([part for part in parts if not part.empty], ignore_index=True)
    result["cik"] = result["symbol"].map(master.set_index("symbol")["cik"])
    result["available_at"] = result["completed_month"].map(
        lambda value: pd.Timestamp(value) + pd.offsets.MonthEnd(0)
    )
    return result.sort_values(["signal", "formation_month", "symbol"]).reset_index(drop=True)


def _rank_buckets(values: pd.Series, buckets: int = 5) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    ranks = numeric.rank(method="first", pct=True)
    return pd.Series(np.ceil(ranks * buckets).clip(1, buckets), index=values.index).where(numeric.notna())


def _jaccard(left: set[object], right: set[object]) -> float:
    union = left | right
    return float(len(left & right) / len(union)) if union else np.nan


def _monthly_similarity(group: pd.DataFrame, signal: str) -> dict[str, object]:
    left = pd.to_numeric(group[f"reference_{signal}"], errors="coerce")
    right = pd.to_numeric(group["proxy_value"], errors="coerce")
    pair = pd.DataFrame({"reference": left, "proxy": right}).dropna()
    record: dict[str, object] = {
        "signal": signal,
        "formation_month": group["formation_month"].iloc[0],
        "paired_observations": int(len(pair)),
        "spearman": np.nan,
        "pearson": np.nan,
        "quintile_agreement": np.nan,
        "extreme_decile_agreement": np.nan,
        "top_bottom_overlap": np.nan,
        "sign_consistency": np.nan,
        "sign_pairs": 0,
        "status": "insufficient_pairs",
    }
    if len(pair) < 2:
        return record
    record["spearman"] = float(pair["reference"].rank(method="average").corr(pair["proxy"].rank(method="average")))
    record["pearson"] = float(pair["reference"].corr(pair["proxy"]))
    reference_quintile = _rank_buckets(pair["reference"])
    proxy_quintile = _rank_buckets(pair["proxy"])
    record["quintile_agreement"] = float((reference_quintile == proxy_quintile).mean())
    n = max(1, math.ceil(len(pair) * 0.10))
    ref_order = pair["reference"].sort_values()
    proxy_order = pair["proxy"].sort_values()
    ref_bottom, ref_top = set(ref_order.index[:n]), set(ref_order.index[-n:])
    proxy_bottom, proxy_top = set(proxy_order.index[:n]), set(proxy_order.index[-n:])
    low = _jaccard(ref_bottom, proxy_bottom)
    high = _jaccard(ref_top, proxy_top)
    record["extreme_decile_agreement"] = float(np.nanmean([low, high]))
    record["top_bottom_overlap"] = float(np.nanmean([low, high]))
    signs = pair.loc[pair["reference"].ne(0) & pair["proxy"].ne(0)]
    record["sign_pairs"] = int(len(signs))
    if not signs.empty:
        record["sign_consistency"] = float((np.sign(signs["reference"]) == np.sign(signs["proxy"])).mean())
    record["status"] = "ok"
    return record


def compare_to_reference(
    reference: pd.DataFrame,
    proxies: pd.DataFrame,
    crosswalk: pd.DataFrame | None,
    *,
    min_pairs: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return month-level and signal-level similarity metrics.

    A missing crosswalk intentionally returns empty month pairs and a blocked
    summary for every signal.  A current ticker guess is never accepted.
    """

    if crosswalk is None or crosswalk.empty:
        summary = pd.DataFrame([
            {
                "signal": signal,
                "validation_status": "blocked_missing_permno_crosswalk",
                "paired_observations": 0,
                "months_evaluated": 0,
                "mean_monthly_spearman": np.nan,
                "median_monthly_spearman": np.nan,
                "mean_quintile_agreement": np.nan,
                "mean_extreme_decile_agreement": np.nan,
                "mean_top_bottom_overlap": np.nan,
                "mean_sign_consistency": np.nan,
                "positive_spearman_month_pct": np.nan,
                "reason": "Official reference uses PERMNO; no authorized PIT crosswalk was supplied",
            }
            for signal in FIVE_PROXY_SIGNALS
        ])
        return pd.DataFrame(), summary
    mapping = crosswalk.copy()
    merged = reference.merge(mapping, on="permno", how="inner")
    merged["formation_month"] = pd.to_datetime(merged["formation_month"], errors="coerce")
    if "effective_start" in mapping:
        merged = merged.loc[
            merged["effective_start"].isna() | merged["formation_month"].ge(merged["effective_start"])
        ]
    if "effective_end" in mapping:
        merged = merged.loc[
            merged["effective_end"].isna() | merged["formation_month"].le(merged["effective_end"])
        ]
    proxy = proxies.copy()
    proxy["formation_month"] = pd.to_datetime(proxy["formation_month"], errors="coerce")
    rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for signal in FIVE_PROXY_SIGNALS:
        ref = merged[["symbol", "formation_month", signal]].rename(columns={signal: f"reference_{signal}"})
        prx = proxy.loc[proxy["signal"].eq(signal), ["symbol", "formation_month", "proxy_value"]]
        joined = ref.merge(prx, on=["symbol", "formation_month"], how="inner")
        for month, group in joined.groupby("formation_month", sort=True):
            row = _monthly_similarity(group, signal)
            rows.append(row)
        month_rows = pd.DataFrame([r for r in rows if r["signal"] == signal])
        valid = month_rows.loc[month_rows["paired_observations"].ge(min_pairs)] if not month_rows.empty else month_rows
        summary_rows.append({
            "signal": signal,
            "validation_status": "ok" if not valid.empty else "insufficient_pairs",
            "paired_observations": int(valid["paired_observations"].sum()) if not valid.empty else 0,
            "months_evaluated": int(len(valid)),
            "mean_monthly_spearman": valid["spearman"].mean() if not valid.empty else np.nan,
            "median_monthly_spearman": valid["spearman"].median() if not valid.empty else np.nan,
            "mean_quintile_agreement": valid["quintile_agreement"].mean() if not valid.empty else np.nan,
            "mean_extreme_decile_agreement": valid["extreme_decile_agreement"].mean() if not valid.empty else np.nan,
            "mean_top_bottom_overlap": valid["top_bottom_overlap"].mean() if not valid.empty else np.nan,
            "mean_sign_consistency": valid["sign_consistency"].mean() if not valid.empty else np.nan,
            "positive_spearman_month_pct": (valid["spearman"] > 0).mean() if not valid.empty else np.nan,
            "reason": "" if not valid.empty else f"Fewer than {min_pairs} paired firms in every month",
        })
    return pd.DataFrame(rows), pd.DataFrame(summary_rows)


def write_validation_outputs(
    output_dir: str | Path,
    *,
    proxies: pd.DataFrame,
    monthly: pd.DataFrame,
    summary: pd.DataFrame,
    reference_rows: int,
    crosswalk_quality: Mapping[str, object],
) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    proxies.to_parquet(output / "proxy_reconstruction_panel.parquet", index=False)
    monthly.to_csv(output / "proxy_validation_monthly.csv", index=False)
    summary.to_csv(output / "proxy_validation_summary.csv", index=False)
    audit = {
        "signals": list(FIVE_PROXY_SIGNALS),
        "reference_rows_inspected": int(reference_rows),
        "crosswalk": dict(crosswalk_quality),
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "lookahead_checked": True,
        "formation_convention": "value at formation month uses data available through the prior calendar month-end",
        "earnings_streak_status": "blocked_without_historical_point_in_time_analyst_snapshots",
    }
    (output / "proxy_validation_audit.json").write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    readme = (
        "# OpenAP five-proxy historical validation\n\n"
        "The panel is reconstructed monthly with a prior-month-end cutoff. "
        "The official reference is only compared after an authorized PERMNO "
        "crosswalk is supplied. `EarningsStreak` remains unavailable without "
        "historical point-in-time analyst snapshots.\n"
    )
    (output / "proxy_validation_readme.md").write_text(readme, encoding="utf-8")


def run_validation(
    *,
    base_db: str | Path,
    reference: str | Path,
    output_dir: str | Path,
    crosswalk: str | Path | None = None,
    ff3_daily: str | Path | None = None,
    min_pairs: int = 30,
) -> dict[str, object]:
    require_github_execution("OpenAP five-proxy historical validation")
    reference_frame = load_reference_values(reference)
    proxy_panel = reconstruct_monthly_proxies(
        base_db,
        ff3_daily=ff3_daily,
        start_month=reference_frame["formation_month"].min(),
        end_month=reference_frame["formation_month"].max(),
    )
    crosswalk_frame = None
    crosswalk_quality: dict[str, object] = {
        "rows": 0,
        "crosswalk_is_pit": False,
        "status": "missing",
    }
    if crosswalk:
        crosswalk_frame, crosswalk_quality = load_crosswalk(crosswalk)
        crosswalk_quality["status"] = "loaded"
    monthly, summary = compare_to_reference(
        reference_frame, proxy_panel, crosswalk_frame, min_pairs=min_pairs
    )
    write_validation_outputs(
        output_dir,
        proxies=proxy_panel,
        monthly=monthly,
        summary=summary,
        reference_rows=len(reference_frame),
        crosswalk_quality=crosswalk_quality,
    )
    payload = {
        "signals": list(FIVE_PROXY_SIGNALS),
        "reference_rows_inspected": int(len(reference_frame)),
        "proxy_rows": int(len(proxy_panel)),
        "crosswalk_status": crosswalk_quality.get("status"),
        "crosswalk_is_pit": bool(crosswalk_quality.get("crosswalk_is_pit", False)),
        "validated_signals": int((summary["validation_status"] == "ok").sum()),
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "partial": bool((summary["validation_status"] != "ok").any()),
    }
    (Path(output_dir) / "proxy_validation_summary.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    return payload
