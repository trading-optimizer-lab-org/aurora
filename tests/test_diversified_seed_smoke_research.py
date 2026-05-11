"""R158 smoke research suite -- runs strategies from local data only.

Each test bootstraps a manifest with mocked providers, then loads the
persisted DataFrame from the timeseries store and runs a small piece
of research code against it. None of the tests opens a network socket
because all providers are injected.

Coverage:

* Broad-market smoke from a local SPY snapshot (50/200 MA cross).
* Sector relative strength: XLK vs XLF ratio.
* Risk-on / risk-off classifier across SPY + TLT + DGS10 + VIXCLS.
* Crypto smoke: BTCUSDT realised volatility from local data.
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from aurora.core.data_providers.first_dataset import (
    FirstDatasetManifest,
    FirstDatasetSection,
    bootstrap_first_dataset,
    load_from_first_dataset,
)
from aurora.data_contracts.timeseries_store import TimeSeriesStore


# ---------------------------------------------------------------------------
# Fixtures + helpers.
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_store(tmp_path) -> TimeSeriesStore:
    return TimeSeriesStore(root_dir=tmp_path / "ts_store")


def _trend_csv(start: str, n: int, base: float, drift: float) -> str:
    """OHLCV CSV with monotonic linear drift -- safe under contract."""
    out = ["Date,Open,High,Low,Close,Volume"]
    base_ts = pd.Timestamp(start, tz="UTC")
    for i in range(n):
        d = base_ts + pd.Timedelta(days=i)
        c = base + drift * i + 0.05 * np.sin(i / 5.0)
        o = c - 0.05
        h = c + 0.4
        low = c - 0.4
        out.append(
            f"{d.date().isoformat()},{o:.4f},{h:.4f},{low:.4f},{c:.4f},1000"
        )
    return "\n".join(out) + "\n"


def _binance_kline_zip(symbol: str, n_days: int, base: float, drift: float) -> bytes:
    """Build an in-memory Binance kline ZIP archive with controlled drift."""
    rows = []
    base_ts = pd.Timestamp("2023-01-01", tz="UTC")
    for i in range(n_days):
        open_time_ms = int((base_ts + pd.Timedelta(days=i)).value // 10**6)
        close_time_ms = open_time_ms + 86_400_000 - 1
        c = base + drift * i + 0.5 * np.sin(i / 4.0)
        o = max(c - 0.05, 0.5)
        h = c + 0.5
        low = max(c - 0.5, 0.4)
        rows.append(
            f"{open_time_ms},{o:.6f},{h:.6f},{low:.6f},{c:.6f},10.5,"
            f"{close_time_ms},1050.0,5,5.0,500.0,0"
        )
    csv_bytes = ("\n".join(rows) + "\n").encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{symbol}-1d-2023-01.csv", csv_bytes)
    return buf.getvalue()


def _section(
    name: str, **kw,
) -> FirstDatasetSection:
    defaults = {
        "symbols": ("SPY",),
        "providers": ("stooq",),
        "library": "prices_daily",
        "allow_fallback": False,
        "trust_level": "research_seed",
        "asset_group": None,
        "expected_fields": ("open", "high", "low", "close", "volume"),
        "notes": None,
    }
    defaults.update(kw)
    return FirstDatasetSection(name=name, **defaults)


def _manifest(*sections: FirstDatasetSection) -> FirstDatasetManifest:
    return FirstDatasetManifest(
        name="diversified_seed",
        start="2023-01-01",
        end="2023-12-31",
        sections=tuple(sections),
        frequency="1d",
    )


# ---------------------------------------------------------------------------
# 1. Broad-market smoke (50/200 MA cross on local SPY).
# ---------------------------------------------------------------------------


def test_broad_market_smoke_runs_from_local_spy(tmp_store):
    """Build SPY locally, then run a 50/200-day MA cross -> finite PnL."""
    csv = _trend_csv("2022-01-03", n=260, base=400.0, drift=0.20)
    manifest = _manifest(
        _section(
            "broad_us_etfs",
            symbols=("SPY",),
            providers=("stooq",),
        ),
    )
    bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"stooq": lambda *_: csv},
    )
    df = load_from_first_dataset("SPY", store=tmp_store)
    assert len(df) == 260
    closes = pd.Series(
        df["close"].to_numpy(),
        index=pd.to_datetime(df["timestamp"], utc=True),
    ).sort_index()
    rets = closes.pct_change().fillna(0.0)
    ma_short = closes.rolling(50, min_periods=10).mean()
    ma_long = closes.rolling(200, min_periods=20).mean()
    signal = (ma_short > ma_long).astype(int).shift(1).fillna(0)
    pnl = float((signal * rets).sum())
    assert np.isfinite(pnl)


# ---------------------------------------------------------------------------
# 2. Sector relative strength (XLK vs XLF).
# ---------------------------------------------------------------------------


def test_sector_relative_xlk_vs_xlf(tmp_store):
    """XLK with stronger drift than XLF -> ratio rises monotonically (mostly)."""
    xlk_csv = _trend_csv("2023-01-03", n=120, base=170.0, drift=0.12)
    xlf_csv = _trend_csv("2023-01-03", n=120, base=35.0, drift=0.02)

    captured: list[str] = []

    def stooq(symbol, start, end):
        captured.append(symbol)
        if symbol == "XLK":
            return xlk_csv
        if symbol == "XLF":
            return xlf_csv
        raise RuntimeError(f"no fixture for {symbol}")

    manifest = _manifest(
        _section(
            "us_sector_etfs",
            symbols=("XLK", "XLF"),
            providers=("stooq",),
        ),
    )
    bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"stooq": stooq},
    )
    xlk = load_from_first_dataset("XLK", store=tmp_store)
    xlf = load_from_first_dataset("XLF", store=tmp_store)
    xlk_close = pd.Series(
        xlk["close"].to_numpy(),
        index=pd.to_datetime(xlk["timestamp"], utc=True),
    ).sort_index()
    xlf_close = pd.Series(
        xlf["close"].to_numpy(),
        index=pd.to_datetime(xlf["timestamp"], utc=True),
    ).sort_index()
    common = xlk_close.index.intersection(xlf_close.index)
    ratio = xlk_close.loc[common] / xlf_close.loc[common]
    # Ratio is finite and increases on average since XLK drift > XLF drift.
    assert np.isfinite(ratio).all()
    assert ratio.iloc[-1] > ratio.iloc[0]


# ---------------------------------------------------------------------------
# 3. Risk regime classifier (SPY / TLT / DGS10 / VIXCLS).
# ---------------------------------------------------------------------------


def test_risk_regime_spy_tlt_dgs10_vixcls(tmp_store):
    """Risk-on: SPY/TLT > median, DGS10 trending up, VIX <25 -> deterministic label."""
    n = 60
    spy_csv = _trend_csv("2023-01-03", n=n, base=400.0, drift=0.50)
    tlt_csv = _trend_csv("2023-01-03", n=n, base=100.0, drift=-0.10)

    def stooq(symbol, start, end):
        if symbol == "SPY":
            return spy_csv
        if symbol == "TLT":
            return tlt_csv
        raise RuntimeError(f"no fixture for {symbol}")

    def fred(series_id, kwargs):
        idx = pd.date_range("2023-01-03", periods=n, freq="D")
        if series_id == "DGS10":
            # Rising 10y yield -> growth-friendly.
            return pd.Series(
                np.linspace(3.5, 4.4, n), index=idx, name=series_id,
            )
        if series_id == "VIXCLS":
            # VIX <= 25 (calm).
            return pd.Series(
                np.linspace(14.0, 18.0, n), index=idx, name=series_id,
            )
        raise RuntimeError(f"no fixture for {series_id}")

    manifest = _manifest(
        _section(
            "broad_us_etfs",
            symbols=("SPY",),
            providers=("stooq",),
        ),
        _section(
            "bonds_rates_etfs",
            symbols=("TLT",),
            providers=("stooq",),
            asset_group="rates_fixed_income",
        ),
        _section(
            "macro",
            symbols=("DGS10", "VIXCLS"),
            providers=("fred_macro",),
            library="macro_daily",
            asset_group="macro_indicator",
            expected_fields=("value",),
        ),
    )
    bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={"stooq": stooq, "fred_macro": fred},
    )

    def _close(symbol):
        df = load_from_first_dataset(symbol, store=tmp_store)
        return pd.Series(
            df["close"].to_numpy(),
            index=pd.to_datetime(df["timestamp"], utc=True),
        ).sort_index()

    def _macro(series_id):
        df = load_from_first_dataset(
            series_id, library="macro_daily", store=tmp_store,
        )
        return pd.Series(
            df["value"].to_numpy(),
            index=pd.to_datetime(df["timestamp"], utc=True),
        ).sort_index()

    spy = _close("SPY")
    tlt = _close("TLT")
    dgs10 = _macro("DGS10")
    vix = _macro("VIXCLS")

    common = spy.index.intersection(tlt.index)
    ratio = spy.loc[common] / tlt.loc[common]
    median = float(ratio.median())
    last_ratio = float(ratio.iloc[-1])
    rates_trend_up = bool(dgs10.iloc[-1] > dgs10.iloc[0])
    vix_calm = bool(vix.iloc[-1] < 25.0)

    # Deterministic risk-on classifier.
    if last_ratio > median and rates_trend_up and vix_calm:
        label = "risk_on"
    elif last_ratio < median and not rates_trend_up:
        label = "risk_off"
    else:
        label = "neutral"

    # Constructed fixtures push this regime into risk_on; the label
    # itself is what we assert is deterministic, not the verdict.
    assert label in {"risk_on", "risk_off", "neutral"}
    assert label == "risk_on"


# ---------------------------------------------------------------------------
# 4. Crypto smoke (BTCUSDT realised volatility from local data).
# ---------------------------------------------------------------------------


def test_crypto_smoke_runs_from_local_btcusdt(tmp_store):
    """Load BTCUSDT from local zip, compute realised vol -> finite, positive."""
    zip_bytes = _binance_kline_zip("BTCUSDT", n_days=20, base=20000.0, drift=120.0)
    manifest = _manifest(
        _section(
            "crypto",
            symbols=("BTCUSDT",),
            providers=("binance_public_data",),
            library="crypto_daily",
        ),
    )
    bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={
            "binance_public_data": lambda *args, **kw: (zip_bytes, None),
        },
    )
    df = load_from_first_dataset(
        "BTCUSDT", library="crypto_daily", store=tmp_store,
    )
    closes = pd.Series(
        df["close"].to_numpy(),
        index=pd.to_datetime(df["timestamp"], utc=True),
    ).sort_index()
    rets = closes.pct_change().dropna()
    realised_vol = float(rets.std() * np.sqrt(365))
    assert np.isfinite(realised_vol)
    assert realised_vol > 0.0
