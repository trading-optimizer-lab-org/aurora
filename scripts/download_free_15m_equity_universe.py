from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Mapping

import pandas as pd
import yfinance as yf

_AURORA_POLICY_ROOT = Path(__file__).resolve().parents[1]
if str(_AURORA_POLICY_ROOT) not in sys.path:
    sys.path.insert(0, str(_AURORA_POLICY_ROOT))

try:
    from core.execution_policy import require_github_actions_or_explicit_local_permission
except ModuleNotFoundError:

    def require_github_actions_or_explicit_local_permission(run_kind: str = "research run") -> None:
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            return
        if os.environ.get("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT") == "USER_REQUESTED_LOCAL_RUN_THIS_TURN":
            return
        raise RuntimeError(
            "Run local bloqueado por politica Aurora. "
            f"Lanzalo en GitHub Actions o pide explicitamente ejecucion local. Tipo: {run_kind}."
        )


CAMPAIGN_ID = "free_15m_equity_universe_yfinance"
DEFAULT_PERIOD = "60d"
DEFAULT_INTERVAL = "15m"
DEFAULT_SYMBOLS = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "AVGO",
    "LLY",
    "JPM",
    "TSLA",
    "V",
    "UNH",
    "XOM",
    "MA",
    "COST",
    "NFLX",
    "WMT",
    "PG",
    "HD",
    "KO",
)
PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def main() -> None:
    require_github_actions_or_explicit_local_permission("free 15m equity universe download")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--period", default=DEFAULT_PERIOD)
    parser.add_argument("--interval", choices=[DEFAULT_INTERVAL], default=DEFAULT_INTERVAL)
    parser.add_argument("--min-symbols", type=int, default=20)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    if len(symbols) < args.min_symbols:
        raise ValueError(f"Se pidieron {len(symbols)} simbolos, menos que min-symbols={args.min_symbols}")

    frames: dict[str, pd.DataFrame] = {}
    failures: list[dict[str, str]] = []
    for symbol in symbols:
        try:
            frames[symbol] = fetch_yfinance_15m(
                symbol,
                period=args.period,
                interval=args.interval,
                retries=args.retries,
            )
        except Exception as exc:
            failures.append({"symbol": symbol, "error": str(exc)})

    if len(frames) < args.min_symbols:
        raise RuntimeError(
            f"Solo se descargaron {len(frames)} simbolos, minimo requerido {args.min_symbols}. "
            f"Fallos: {failures}"
        )

    result = write_aligned_universe(
        frames,
        output_dir=Path(args.output_dir),
        requested_symbols=symbols,
        requested_period=args.period,
        interval=args.interval,
        source="yfinance_free_no_api_key",
        failures=failures,
        min_symbols=args.min_symbols,
    )
    print(json.dumps(result, indent=2))


def parse_symbols(raw: str) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for part in raw.replace("\n", ",").split(","):
        symbol = part.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def fetch_yfinance_15m(
    symbol: str,
    *,
    period: str,
    interval: str,
    retries: int,
) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            raw = yf.download(
                symbol,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                prepost=False,
                threads=False,
                timeout=60,
            )
            bars = normalise_yfinance_ohlcv(raw, symbol=symbol)
            if len(bars) < 300:
                raise RuntimeError(f"muy pocas barras: {len(bars)}")
            return bars
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2.0 * attempt)
    raise RuntimeError(f"No se pudo descargar {symbol}: {last_error}")


def normalise_yfinance_ohlcv(raw: pd.DataFrame, *, symbol: str = "") -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance devolvio datos vacios para {symbol}".strip())
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        if symbol and symbol in frame.columns.get_level_values(-1):
            frame = frame.xs(symbol, axis=1, level=-1, drop_level=True)
        else:
            frame.columns = frame.columns.get_level_values(0)
    rename = {column: str(column).title() for column in frame.columns}
    frame = frame.rename(columns=rename)
    missing = [column for column in PRICE_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"faltan columnas {missing} para {symbol}".strip())
    frame = frame.loc[:, list(PRICE_COLUMNS)].copy()
    frame.index = pd.to_datetime(frame.index)
    if getattr(frame.index, "tz", None) is not None:
        frame.index = frame.index.tz_convert("America/New_York").tz_localize(None)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
    frame = frame[frame["Volume"].fillna(0) >= 0]
    return filter_regular_session(frame)


def filter_regular_session(bars: pd.DataFrame) -> pd.DataFrame:
    idx = pd.to_datetime(bars.index)
    mask = (
        (idx.dayofweek < 5)
        & (
            ((idx.hour > 9) | ((idx.hour == 9) & (idx.minute >= 30)))
            & (idx.hour < 16)
        )
    )
    return bars.loc[mask].copy()


def write_aligned_universe(
    frames: Mapping[str, pd.DataFrame],
    *,
    output_dir: Path,
    requested_symbols: list[str],
    requested_period: str,
    interval: str,
    source: str,
    failures: list[dict[str, str]] | None = None,
    min_symbols: int = 20,
) -> dict[str, object]:
    clean_frames = {symbol: frame.copy() for symbol, frame in frames.items() if not frame.empty}
    if len(clean_frames) < min_symbols:
        raise RuntimeError(f"Solo hay {len(clean_frames)} dataframes validos, minimo {min_symbols}")

    common_start = max(frame.index.min() for frame in clean_frames.values())
    common_end = min(frame.index.max() for frame in clean_frames.values())
    if common_start >= common_end:
        raise RuntimeError(f"No hay periodo comun: start={common_start}, end={common_end}")

    common_index: pd.Index | None = None
    for frame in clean_frames.values():
        trimmed_index = frame.loc[(frame.index >= common_start) & (frame.index <= common_end)].index
        common_index = trimmed_index if common_index is None else common_index.intersection(trimmed_index)
    assert common_index is not None
    common_index = pd.DatetimeIndex(common_index).sort_values()
    if len(common_index) < 300:
        raise RuntimeError(f"El indice comun tiene muy pocas barras: {len(common_index)}")

    data_dir = output_dir / "data"
    wide_dir = output_dir / "wide"
    data_dir.mkdir(parents=True, exist_ok=True)
    wide_dir.mkdir(parents=True, exist_ok=True)

    symbol_summaries: list[dict[str, object]] = []
    aligned_frames: dict[str, pd.DataFrame] = {}
    for symbol, frame in clean_frames.items():
        aligned = frame.reindex(common_index).dropna(subset=["Open", "High", "Low", "Close"])
        if len(aligned) != len(common_index):
            raise RuntimeError(
                f"{symbol} no cubre todo el indice comun: {len(aligned)} de {len(common_index)}"
            )
        aligned = aligned.loc[:, list(PRICE_COLUMNS)]
        aligned_frames[symbol] = aligned
        aligned.to_csv(data_dir / f"{symbol}_15m.csv", index_label="timestamp")
        symbol_summaries.append(
            {
                "symbol": symbol,
                "source_rows": int(len(frame)),
                "aligned_rows": int(len(aligned)),
                "dropped_rows_to_align": int(len(frame) - len(aligned)),
                "source_first_timestamp": str(frame.index.min()),
                "source_last_timestamp": str(frame.index.max()),
            }
        )

    for column in PRICE_COLUMNS:
        wide = pd.DataFrame({symbol: frame[column] for symbol, frame in aligned_frames.items()})
        wide.to_csv(wide_dir / f"{column.lower()}.csv", index_label="timestamp")
        wide.to_parquet(wide_dir / f"{column.lower()}.parquet", index=True)

    summary = pd.DataFrame(symbol_summaries).sort_values("symbol")
    summary.to_csv(output_dir / "summary.csv", index=False)

    manifest: dict[str, object] = {
        "campaign_id": CAMPAIGN_ID,
        "source": source,
        "free_policy": "100% gratis, sin API key, descarga por yfinance/Yahoo Finance.",
        "requested_period": requested_period,
        "interval": interval,
        "requested_symbols": requested_symbols,
        "downloaded_symbols": sorted(aligned_frames),
        "symbol_count": int(len(aligned_frames)),
        "min_symbols": int(min_symbols),
        "common_start": str(common_index.min()),
        "common_end": str(common_index.max()),
        "common_rows_per_symbol": int(len(common_index)),
        "common_trading_days": int(pd.Series(common_index.date).nunique()),
        "bar_policy": "US regular cash session only, exact shared timestamp index across every symbol.",
        "symbols": symbol_summaries,
        "failures": failures or [],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_dir / "README.md").write_text(build_readme(manifest), encoding="utf-8")
    return manifest


def build_readme(manifest: Mapping[str, object]) -> str:
    return "\n".join(
        [
            "# Free 15m equity universe",
            "",
            f"Source: {manifest['source']}",
            f"Interval: {manifest['interval']}",
            f"Requested period: {manifest['requested_period']}",
            f"Common period: {manifest['common_start']} to {manifest['common_end']}",
            f"Symbols: {manifest['symbol_count']}",
            f"Rows per symbol: {manifest['common_rows_per_symbol']}",
            f"Trading days: {manifest['common_trading_days']}",
            "",
            "Every per-symbol CSV is aligned to the same timestamp index.",
        ]
    )


if __name__ == "__main__":
    main()
