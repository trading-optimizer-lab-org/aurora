"""Streamlit live dashboard for QuantForge trade journal.

Reads the SQLite trade journal written by ``quantforge.registry.journal`` and
renders an auto-refreshing dashboard with PnL, open positions, per-strategy
panels, and a recent-trade ticker.

Streamlit is an optional dependency. The pure helpers
``fetch_dashboard_data`` and ``compute_dashboard_metrics`` use only pandas /
sqlite3 / numpy and are testable without Streamlit. ``run_dashboard`` lazy
imports streamlit and raises a clear ``RuntimeError`` if missing.

Journal schema (see ``quantforge/registry/journal.py``):
    id, timestamp, strategy_name, strategy_version, symbol, side,
    quantity, fill_price, notional, commission, slippage_bps,
    signal_value, status, order_id, note

PnL convention (matches ``TradeJournal.daily_pnl``): cash flow per trade is
``-notional - commission`` (BUY notional is +qty*price, SELL is -qty*price,
so SELL produces positive realized cash flow).
"""
from __future__ import annotations

import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Optional streamlit
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised by environment
    import streamlit as _st  # noqa: F401
    STREAMLIT_AVAILABLE = True
except Exception:  # pragma: no cover - exercised by environment
    STREAMLIT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class DashboardConfig:
    """Configuration for the Streamlit dashboard."""
    journal_path: str = "quantforge.db"
    refresh_seconds: int = 30
    show_alerts: bool = True
    show_per_strategy: bool = True
    metrics: tuple = field(default_factory=lambda: (
        "total_pnl", "sharpe", "max_dd", "n_trades", "win_rate",
    ))


# ---------------------------------------------------------------------------
# Pure helpers (no streamlit)
# ---------------------------------------------------------------------------


_TRADE_COLS = (
    "id", "timestamp", "strategy_name", "strategy_version", "symbol", "side",
    "quantity", "fill_price", "notional", "commission", "slippage_bps",
    "signal_value", "status", "order_id", "note",
)


def _empty_trades_df() -> pd.DataFrame:
    df = pd.DataFrame(columns=list(_TRADE_COLS))
    # Numeric columns get float dtype so downstream math is well-defined.
    for c in ("quantity", "fill_price", "notional", "commission",
              "slippage_bps", "signal_value"):
        df[c] = df[c].astype(float)
    return df


def _trade_pnl(df: pd.DataFrame) -> pd.Series:
    """Per-trade realized cash flow: -notional - commission. FILLED only."""
    if df.empty:
        return pd.Series([], dtype=float)
    notional = pd.to_numeric(df["notional"], errors="coerce").fillna(0.0)
    commission = pd.to_numeric(df["commission"], errors="coerce").fillna(0.0)
    return (-notional - commission).astype(float)


def compute_dashboard_metrics(trades_df: pd.DataFrame) -> dict:
    """Compute headline metrics from a trades DataFrame.

    Expected columns include: ``timestamp``, ``status``, ``notional``,
    ``commission``. Only ``status == 'FILLED'`` rows count toward PnL.

    Returns dict with keys:
        total_pnl  -- sum of per-trade cash flows (float)
        sharpe     -- annualized PnL-Sharpe of the *cash* daily-PnL series
                      (mean / stdev of daily cash PnL, scaled by sqrt(252)).
                      NOT a returns-Sharpe: it is computed on absolute cash
                      flow rather than ``daily_pnl / starting_equity``, so
                      the magnitude is sensitive to position sizing and
                      should not be compared to a returns-Sharpe across
                      strategies. NaN if < 2 days of data.
        max_dd     -- maximum drawdown of the cumulative PnL curve (<= 0)
        n_trades   -- count of FILLED trades
        win_rate   -- fraction of FILLED trades with positive cash flow
    """
    if trades_df is None or len(trades_df) == 0:
        return {
            "total_pnl": 0.0,
            "sharpe": float("nan"),
            "max_dd": 0.0,
            "n_trades": 0,
            "win_rate": float("nan"),
        }

    df = trades_df
    if "status" in df.columns:
        df = df[df["status"].astype(str).str.upper() == "FILLED"]

    if len(df) == 0:
        return {
            "total_pnl": 0.0,
            "sharpe": float("nan"),
            "max_dd": 0.0,
            "n_trades": 0,
            "win_rate": float("nan"),
        }

    pnl = _trade_pnl(df)
    total_pnl = float(pnl.sum())
    n_trades = int(len(df))
    wins = int((pnl > 0).sum())
    win_rate = float(wins / n_trades) if n_trades > 0 else float("nan")

    # Daily-aggregated PnL for Sharpe and DD.
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce")
        daily = pnl.groupby(ts.dt.date).sum().sort_index()
    else:
        daily = pnl.copy()

    # PnL-Sharpe (cash). See docstring: ``daily`` is in absolute currency
    # units, not returns, so this is not directly comparable to a
    # returns-Sharpe. Renaming the key would break dashboard consumers,
    # but the docstring documents the semantics so callers cannot mistake
    # this for a returns-Sharpe.
    if len(daily) >= 2 and float(daily.std(ddof=1)) > 0.0:
        sharpe = float(daily.mean() / daily.std(ddof=1) * math.sqrt(252.0))
    else:
        sharpe = float("nan")

    equity = daily.cumsum()
    if len(equity) == 0:
        max_dd = 0.0
    else:
        running_max = equity.cummax()
        dd = equity - running_max
        max_dd = float(dd.min()) if len(dd) > 0 else 0.0

    return {
        "total_pnl": total_pnl,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "n_trades": n_trades,
        "win_rate": win_rate,
    }


def _read_trades_table(conn: sqlite3.Connection) -> pd.DataFrame:
    """Read the journal table into a DataFrame; tolerate missing table."""
    try:
        df = pd.read_sql_query("SELECT * FROM journal ORDER BY timestamp ASC",
                               conn)
    except Exception:
        return _empty_trades_df()
    if df.empty:
        return _empty_trades_df()
    # Coerce types we rely on.
    for c in ("quantity", "fill_price", "notional", "commission",
              "slippage_bps", "signal_value"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _equity_curve(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Cumulative PnL over time. Columns: timestamp, pnl, equity."""
    if trades_df is None or trades_df.empty:
        return pd.DataFrame(columns=["timestamp", "pnl", "equity"])
    df = trades_df
    if "status" in df.columns:
        df = df[df["status"].astype(str).str.upper() == "FILLED"]
    if df.empty:
        return pd.DataFrame(columns=["timestamp", "pnl", "equity"])
    pnl = _trade_pnl(df)
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    daily = pnl.groupby(ts.dt.date).sum().sort_index()
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(daily.index),
        "pnl": daily.values,
    })
    out["equity"] = out["pnl"].cumsum()
    return out.reset_index(drop=True)


def _open_positions(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct net position per (strategy, symbol) from BUY/SELL log.

    Only FILLED rows count. BUY adds quantity, SELL subtracts. Returns rows
    with non-zero net position.
    """
    cols = ["strategy_name", "symbol", "position", "last_fill_price",
            "last_timestamp"]
    if trades_df is None or trades_df.empty:
        return pd.DataFrame(columns=cols)
    df = trades_df
    if "status" in df.columns:
        df = df[df["status"].astype(str).str.upper() == "FILLED"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    df = df.copy()
    df["signed_qty"] = np.where(
        df["side"].astype(str).str.upper() == "BUY",
        df["quantity"].astype(float),
        -df["quantity"].astype(float),
    )
    grouped = df.groupby(["strategy_name", "symbol"], dropna=False)
    pos = grouped["signed_qty"].sum().rename("position")
    last_price = grouped["fill_price"].last().rename("last_fill_price")
    last_ts = grouped["timestamp"].last().rename("last_timestamp")
    out = pd.concat([pos, last_price, last_ts], axis=1).reset_index()
    out = out[out["position"].abs() > 1e-12].reset_index(drop=True)
    return out


def _per_strategy_stats(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Headline metrics per strategy_name.

    Columns: strategy_name, total_pnl, sharpe, max_dd, n_trades, win_rate.
    """
    cols = ["strategy_name", "total_pnl", "sharpe", "max_dd",
            "n_trades", "win_rate"]
    if trades_df is None or trades_df.empty:
        return pd.DataFrame(columns=cols)
    df = trades_df
    if "status" in df.columns:
        df = df[df["status"].astype(str).str.upper() == "FILLED"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for name, sub in df.groupby("strategy_name", dropna=False):
        m = compute_dashboard_metrics(sub)
        rows.append({"strategy_name": name, **m})
    return pd.DataFrame(rows, columns=cols)


# Module-level memoization cache for ``fetch_dashboard_data`` to keep the
# Streamlit dashboard cheap. Keyed on (path, ttl_bucket) so callers can opt
# in to a coarser refresh granularity. The cache is intentionally bounded —
# in practice only a handful of journals + refresh intervals exist per
# session, but ``_CACHE_MAX`` guards against accidental unbounded growth.
_CACHE_MAX = 8
_FETCH_CACHE: dict = {}


def _cached_fetch(path: str, ttl_bucket: int) -> dict:
    """Return the dashboard data for ``path`` cached within ``ttl_bucket``.

    The cache is keyed on ``(path, ttl_bucket)`` where the caller chooses
    ``ttl_bucket`` so that the cache invalidates every ``ttl`` seconds
    (typical: ``ttl_bucket = int(time.time() / refresh_seconds)``).

    Empty results (journal not yet written, or zero rows) are deliberately
    *not* cached: caching them would persist a "dashboard is empty" view
    for the whole TTL bucket even if the journal becomes populated mid-
    bucket, which is the most common cold-start case for live deployment.
    """
    key = (path, int(ttl_bucket))
    cached = _FETCH_CACHE.get(key)
    if cached is not None:
        return cached
    data = fetch_dashboard_data(path)
    # Skip caching empty results so the next call retries the read.
    if _is_empty_dashboard(data):
        return data
    if len(_FETCH_CACHE) >= _CACHE_MAX:
        _FETCH_CACHE.clear()
    _FETCH_CACHE[key] = data
    return data


def _is_empty_dashboard(data: dict) -> bool:
    """True if the dashboard payload has no journal rows worth caching."""
    if not isinstance(data, dict):
        return False
    trades = data.get("trades")
    if trades is None:
        return True
    try:
        return len(trades) == 0
    except TypeError:
        return False


def fetch_dashboard_data(journal_path: str) -> dict:
    """Read the journal SQLite file and return all data the UI needs.

    Returns dict with keys:
        trades         : DataFrame of all journal rows (sorted ASC)
        recent_trades  : DataFrame of the last 100 rows (DESC)
        equity_curve   : DataFrame[timestamp, pnl, equity] from FILLED rows
        open_positions : DataFrame of net positions with non-zero size
        per_strategy   : DataFrame of headline metrics per strategy
        metrics        : dict of overall headline metrics

    If ``journal_path`` does not exist, returns an empty dict (graceful).
    """
    if not journal_path or not os.path.exists(journal_path):
        return {}

    # Open the journal read-only. The dashboard never writes; using
    # ``mode=ro`` prevents accidental schema drift, removes journaling
    # overhead, and lets multiple readers operate concurrently without
    # contending with the live trader's writer connection.
    try:
        ro_uri = f"file:{os.path.abspath(journal_path)}?mode=ro"
        conn = sqlite3.connect(ro_uri, uri=True)
    except Exception:
        return {}
    try:
        trades = _read_trades_table(conn)
    finally:
        conn.close()

    recent = trades.sort_values("timestamp", ascending=False).head(100) \
        .reset_index(drop=True) if not trades.empty else _empty_trades_df()
    equity = _equity_curve(trades)
    positions = _open_positions(trades)
    per_strat = _per_strategy_stats(trades)
    metrics = compute_dashboard_metrics(trades)

    return {
        "trades": trades,
        "recent_trades": recent,
        "equity_curve": equity,
        "open_positions": positions,
        "per_strategy": per_strat,
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Streamlit UI (lazy)
# ---------------------------------------------------------------------------


def _format_metric(name: str, value) -> str:
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except Exception:
        return str(value)
    if math.isnan(v):
        return "n/a"
    if name == "n_trades":
        return f"{int(v)}"
    if name in ("win_rate",):
        return f"{v * 100:.1f}%"
    if name in ("total_pnl", "max_dd"):
        return f"{v:,.2f}"
    if name == "sharpe":
        return f"{v:.2f}"
    return f"{v:.4f}"


def run_dashboard(config: Optional[DashboardConfig] = None):
    """Launch the Streamlit dashboard.

    Reads ``config.journal_path``, displays PnL chart, open positions,
    per-strategy panels, and recent-trade alert log. Auto-refreshes every
    ``config.refresh_seconds``.

    Requires Streamlit to be installed. Raises RuntimeError otherwise.
    """
    if not STREAMLIT_AVAILABLE:
        raise RuntimeError(
            "streamlit is not installed. Install it with "
            "'pip install streamlit' or run via "
            "'forge dashboard --journal <path>'."
        )

    cfg = config or DashboardConfig()

    import streamlit as st

    st.set_page_config(
        page_title="QuantForge Live Dashboard",
        layout="wide",
    )

    # --- sidebar --------------------------------------------------------
    st.sidebar.title("QuantForge")
    st.sidebar.caption("Live trade journal monitor")

    journal_path = st.sidebar.text_input(
        "Journal path", value=str(cfg.journal_path),
        help="SQLite database written by quantforge.registry.journal",
    )
    refresh = st.sidebar.number_input(
        "Refresh seconds", min_value=1, max_value=3600,
        value=int(cfg.refresh_seconds), step=1,
    )
    show_alerts = st.sidebar.checkbox("Show alert ticker",
                                      value=bool(cfg.show_alerts))
    show_per_strat = st.sidebar.checkbox("Show per-strategy panels",
                                         value=bool(cfg.show_per_strategy))

    # Cached fetch — uses module-scope ``_cached_fetch`` keyed on
    # (path, ttl_bucket) so the cache survives Streamlit reruns and so
    # changing the refresh interval immediately picks the new bucket.
    refresh_int = max(int(refresh), 1)
    ttl_bucket = int(time.time() / refresh_int)
    data = _cached_fetch(journal_path, ttl_bucket)

    if not data:
        st.warning(
            f"No journal found at '{journal_path}'. "
            "The dashboard will refresh every "
            f"{int(refresh)}s and pick it up when it appears."
        )
        # Trigger a rerun via whichever streamlit API is available — modern
        # streamlit exposes ``st.rerun``; older releases used
        # ``st.experimental_rerun``. We probe for either, only invoking the
        # callable that actually exists.
        rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
        if callable(rerun):
            try:
                rerun()
            except Exception:
                pass
        st.stop()
        return None

    # --- optional symbol filter ----------------------------------------
    trades = data.get("trades", _empty_trades_df())
    symbols = sorted(s for s in trades["symbol"].dropna().unique()) \
        if not trades.empty else []
    selected_symbols = st.sidebar.multiselect(
        "Symbols", options=symbols, default=symbols,
        help="Filter dashboard to a subset of symbols",
    )
    if selected_symbols and not trades.empty:
        trades_view = trades[trades["symbol"].isin(selected_symbols)].copy()
    else:
        trades_view = trades.copy()

    metrics = compute_dashboard_metrics(trades_view)

    # --- header metrics -------------------------------------------------
    st.title("Live PnL")
    st.caption(f"Source: `{journal_path}`")

    metric_cols = st.columns(len(cfg.metrics))
    labels = {
        "total_pnl": "Total PnL",
        "sharpe": "Sharpe",
        "max_dd": "Max DD",
        "n_trades": "Trades",
        "win_rate": "Win rate",
    }
    for col, key in zip(metric_cols, cfg.metrics):
        col.metric(labels.get(key, key), _format_metric(key, metrics.get(key)))

    # --- PnL chart ------------------------------------------------------
    eq = _equity_curve(trades_view)
    st.subheader("Cumulative PnL")
    if eq.empty:
        st.info("No FILLED trades to plot yet.")
    else:
        chart_df = eq.set_index("timestamp")[["equity"]]
        st.line_chart(chart_df, use_container_width=True)

    # --- positions table ------------------------------------------------
    st.subheader("Open positions")
    pos = _open_positions(trades_view)
    if pos.empty:
        st.info("No open positions.")
    else:
        st.dataframe(pos, use_container_width=True, hide_index=True)

    # --- per-strategy panels --------------------------------------------
    if show_per_strat:
        st.subheader("Per-strategy")
        per_strat = _per_strategy_stats(trades_view)
        if per_strat.empty:
            st.info("No strategy data yet.")
        else:
            for _, row in per_strat.iterrows():
                with st.expander(str(row["strategy_name"])):
                    inner = st.columns(len(cfg.metrics))
                    for col, key in zip(inner, cfg.metrics):
                        col.metric(
                            labels.get(key, key),
                            _format_metric(key, row.get(key)),
                        )

    # --- alert ticker / recent trades -----------------------------------
    if show_alerts:
        st.subheader("Recent trades")
        recent = data.get("recent_trades", _empty_trades_df())
        if not selected_symbols or recent.empty:
            recent_view = recent
        else:
            recent_view = recent[recent["symbol"].isin(selected_symbols)]
        if recent_view.empty:
            st.info("No recent trades.")
        else:
            cols = [c for c in ("timestamp", "strategy_name", "symbol",
                                "side", "quantity", "fill_price", "status",
                                "note")
                    if c in recent_view.columns]
            st.dataframe(recent_view[cols].head(50),
                         use_container_width=True, hide_index=True)

    # --- auto refresh ---------------------------------------------------
    # Streamlit recommended pattern: use st.autorefresh if available, else
    # fall back to a meta refresh tag. Keeps the dashboard cheap.
    autorefresh = getattr(st, "autorefresh", None)
    if callable(autorefresh):
        try:
            autorefresh(interval=int(refresh) * 1000, key="qf_dashboard_tick")
        except Exception:
            pass
    else:
        st.markdown(
            f"<meta http-equiv='refresh' content='{int(refresh)}'>",
            unsafe_allow_html=True,
        )

    return None


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------


def _streamlit_entrypoint() -> int:
    """Module-mode entry: ``python -m quantforge.monitoring.dashboard``.

    When invoked under ``streamlit run``, Streamlit imports this module as a
    script, so calling ``run_dashboard()`` here renders the page.
    """
    cfg = DashboardConfig(
        journal_path=os.environ.get("QF_JOURNAL", "quantforge.db"),
        refresh_seconds=int(os.environ.get("QF_REFRESH", "30")),
    )
    run_dashboard(cfg)
    return 0


if __name__ == "__main__":  # pragma: no cover - executed by streamlit run
    _streamlit_entrypoint()
