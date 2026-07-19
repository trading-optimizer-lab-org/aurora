"""Download one manifest-bound post-2020 symbol shard from Yahoo in GitHub."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

import pandas as pd
import yfinance as yf

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.stock_protocol.exact_oos import (
    load_frozen_manifest_authorization,
)
from aurora.research.stock_protocol.locked_access import activate_locked_data_access


YAHOO_SUFFIXES = {
    "A", "AX", "BA", "BE", "BK", "BO", "BR", "CA", "CO", "DE", "DU",
    "F", "HE", "HK", "HM", "IC", "IR", "IS", "JK", "JO", "KQ", "KS",
    "L", "LS", "MC", "ME", "MI", "MU", "MX", "NE", "NS", "NZ", "OL",
    "PA", "PR", "QA", "RG", "SA", "SG", "SI", "SN", "SR", "SS", "ST",
    "SW", "SZ", "T", "TA", "TL", "TO", "TW", "TWO", "V", "VI", "WA",
}
OUTPUT_COLUMNS = (
    "date",
    "symbol",
    "provider_symbol",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "dividends",
    "stock_splits",
    "source",
    "retrieved_at",
)


def canonical_to_yahoo(symbol: str) -> str:
    value = str(symbol).strip().upper()
    if "-" not in value:
        return value
    stem, suffix = value.rsplit("-", 1)
    if suffix in YAHOO_SUFFIXES and stem:
        return f"{stem}.{suffix}"
    return value


def _ticker_frame(raw: pd.DataFrame, provider_symbol: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        level_zero = {str(value) for value in raw.columns.get_level_values(0)}
        level_one = {str(value) for value in raw.columns.get_level_values(1)}
        if provider_symbol in level_zero:
            return raw[provider_symbol].copy()
        if provider_symbol in level_one:
            return raw.xs(provider_symbol, axis=1, level=1).copy()
        return pd.DataFrame()
    return raw.copy()


def _normalise(
    raw: pd.DataFrame,
    *,
    canonical_symbol: str,
    provider_symbol: str,
    locked_end: pd.Timestamp,
    retrieved_at: str,
) -> pd.DataFrame:
    frame = raw.copy()
    if frame.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    frame.columns = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]
    frame = frame.rename(columns={"adjclose": "adj_close"})
    frame["date"] = pd.to_datetime(frame.index, errors="coerce", utc=True).tz_convert(None).normalize()
    for column in ("open", "high", "low", "close", "adj_close", "volume"):
        if column not in frame:
            return pd.DataFrame(columns=OUTPUT_COLUMNS)
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("dividends", "stock_splits"):
        if column not in frame:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    valid = frame["date"].notna() & frame["date"].le(locked_end)
    valid &= frame[["open", "high", "low", "close", "adj_close"]].gt(0).all(axis=1)
    frame = frame.loc[valid].copy()
    frame["symbol"] = canonical_symbol
    frame["provider_symbol"] = provider_symbol
    frame["source"] = "yfinance"
    frame["retrieved_at"] = retrieved_at
    return frame[list(OUTPUT_COLUMNS)].sort_values("date").reset_index(drop=True)


def _download_batch(providers: list[str], start: str, end_exclusive: str) -> pd.DataFrame:
    return yf.download(
        tickers=providers,
        start=start,
        end=end_exclusive,
        auto_adjust=False,
        actions=True,
        group_by="ticker",
        threads=True,
        progress=False,
        timeout=45,
    )


def download_shard(
    *,
    symbols_path: Path,
    manifest_path: Path,
    manifest_sha256: str,
    implementation_commit: str,
    shard_index: int,
    shard_count: int,
    locked_end: str,
    output_root: Path,
) -> dict[str, object]:
    require_github_actions_or_explicit_local_permission("exact locked data download")
    authorization = load_frozen_manifest_authorization(
        manifest_path,
        expected_manifest_sha256=manifest_sha256,
        expected_implementation_commit=implementation_commit,
    )
    activate_locked_data_access(authorization, end=pd.Timestamp(locked_end))
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid locked shard coordinates")
    payload = json.loads(symbols_path.read_text(encoding="utf-8"))
    if int(payload["shard_count"]) != shard_count:
        raise ValueError("symbol manifest shard count mismatch")
    symbols = [
        str(item)
        for item in payload["shards"][str(shard_index)]["symbols"]
    ]
    if not symbols:
        raise ValueError("locked shard has no symbols")
    end = pd.Timestamp(locked_end).normalize()
    end_exclusive = (end + timedelta(days=1)).date().isoformat()
    retrieved_at = datetime.now(timezone.utc).isoformat()
    mapping = {symbol: canonical_to_yahoo(symbol) for symbol in symbols}
    parts: list[pd.DataFrame] = []
    status: list[dict[str, object]] = []
    batch_size = 15
    for offset in range(0, len(symbols), batch_size):
        batch_symbols = symbols[offset : offset + batch_size]
        providers = [mapping[symbol] for symbol in batch_symbols]
        raw = pd.DataFrame()
        error = ""
        for attempt in range(3):
            try:
                raw = _download_batch(providers, "2020-01-01", end_exclusive)
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                time.sleep(2 ** attempt)
        for symbol in batch_symbols:
            provider = mapping[symbol]
            frame = _normalise(
                _ticker_frame(raw, provider),
                canonical_symbol=symbol,
                provider_symbol=provider,
                locked_end=end,
                retrieved_at=retrieved_at,
            )
            if frame.empty:
                try:
                    single = _download_batch([provider], "2020-01-01", end_exclusive)
                    frame = _normalise(
                        _ticker_frame(single, provider),
                        canonical_symbol=symbol,
                        provider_symbol=provider,
                        locked_end=end,
                        retrieved_at=retrieved_at,
                    )
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            if not frame.empty:
                parts.append(frame)
            status.append(
                {
                    "symbol": symbol,
                    "provider_symbol": provider,
                    "status": "downloaded" if not frame.empty else "missing_or_failed",
                    "rows": int(len(frame)),
                    "first_date": None if frame.empty else frame["date"].min().date().isoformat(),
                    "last_date": None if frame.empty else frame["date"].max().date().isoformat(),
                    "error": "" if not frame.empty else error,
                }
            )
    output_root.mkdir(parents=True, exist_ok=True)
    prices = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(columns=OUTPUT_COLUMNS)
    )
    prices = prices.drop_duplicates(["date", "symbol"], keep="last").sort_values(
        ["symbol", "date"]
    )
    price_path = output_root / "locked_prices.parquet"
    prices.to_parquet(price_path, index=False, compression="zstd")
    status_frame = pd.DataFrame(status).sort_values("symbol")
    status_frame.to_csv(output_root / "locked_download_status.csv", index=False)
    digest = hashlib.sha256(price_path.read_bytes()).hexdigest()
    audit = {
        "shard_index": shard_index,
        "shard_count": shard_count,
        "symbols_expected": len(symbols),
        "symbols_downloaded": int(status_frame["status"].eq("downloaded").sum()),
        "symbols_missing": int(status_frame["status"].ne("downloaded").sum()),
        "rows": int(len(prices)),
        "locked_start": "2021-01-01",
        "locked_end": locked_end,
        "partial_session_included": False,
        "locked_opened": True,
        "locked_opened_at": retrieved_at,
        "manifest_sha256": manifest_sha256,
        "implementation_commit": implementation_commit,
        "sha256": digest,
    }
    (output_root / "locked_download_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, sort_keys=True))
    return audit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", dest="symbols_path", type=Path, required=True)
    parser.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--locked-end", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    download_shard(**vars(_parser().parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
