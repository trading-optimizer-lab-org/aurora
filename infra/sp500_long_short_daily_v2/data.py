"""Bounded V2 OHLCV and fixed-ETF panel layered on the audited V1 ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from aurora.infra.sp500_long_short_daily.contracts import CampaignPackage as V1Package
from aurora.infra.sp500_long_short_daily.data import (
    DownloadReceipt,
    PreparedMarketData,
    download_yahoo_history,
    load_market_snapshot as load_v1_snapshot,
    prepare_market_snapshot as prepare_v1_snapshot,
)
from aurora.infra.sp500_long_short_daily_v2.contracts import (
    CampaignPackage,
    LockedBoundaryError,
    assert_frame_before_locked,
    canonical_json_hash,
    sha256_file,
)

FIXED_SYMBOLS = (
    "SPY", "DIA", "QQQ", "IWM", "IEF", "TLT", "RSP",
    "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY",
)
SECTOR_SYMBOLS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY")
RISK_SYMBOLS = ("DIA", "QQQ", "IWM", "IEF", "TLT", "SPY")


class V2DataGateError(RuntimeError):
    """A V2 predictor source failed its frozen contract."""


def _repo_root() -> Path:
    for root in (Path.cwd(), Path(__file__).resolve().parents[2]):
        if (root / "campaigns" / "sp500_long_short_daily_v2").is_dir():
            return root.resolve()
    raise V2DataGateError("V2_CAMPAIGN_ROOT_NOT_FOUND")


def _v1_package() -> V1Package:
    root = _repo_root() / "campaigns" / "sp500_long_short_daily"
    return V1Package.load(
        root / "research_input",
        root / "input_package" / "SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_FINAL.zip",
    )


def split_normalize_ohlcv(
    prices: pd.DataFrame,
    splits: pd.DataFrame,
    *,
    source_already_split_normalized: bool,
) -> pd.DataFrame:
    """Return price-only OHLCV on one split basis, never dividend adjusted."""

    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.sort_values("date", kind="mergesort").drop_duplicates("date", keep="last")
    numeric = ["open", "high", "low", "close", "volume"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="raise")
    if source_already_split_normalized:
        factor = pd.Series(1.0, index=frame.index)
    else:
        events = splits.copy()
        events["date"] = pd.to_datetime(events["date"]).dt.normalize()
        by_date = events.groupby("date", sort=True)["split_ratio"].prod()
        ratios = frame["date"].map(by_date).fillna(1.0).astype(float)
        # A split effective on d changes the basis of all observations before d.
        factor = ratios.iloc[::-1].cumprod().iloc[::-1] / ratios
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column] / factor.to_numpy(dtype=float)
    frame["volume"] = frame["volume"] * factor.to_numpy(dtype=float)
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise V2DataGateError("NON_POSITIVE_OHLC")
    if not ((frame["high"] >= frame[["open", "close", "low"]].max(axis=1)).all()
            and (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)).all()):
        raise V2DataGateError("OHLC_INEQUALITY_FAILURE")
    if (frame["volume"] < 0).any():
        raise V2DataGateError("NEGATIVE_VOLUME")
    return frame[["date", "open", "high", "low", "close", "volume"]]


def _identity_table() -> pd.DataFrame:
    path = (
        _repo_root()
        / "campaigns"
        / "sp500_long_short_daily_v2"
        / "official_inputs"
        / "etf_identity_inception.csv"
    )
    frame = pd.read_csv(path)
    frame["official_inception"] = pd.to_datetime(frame["official_inception"])
    if set(frame["symbol"]) != set(FIXED_SYMBOLS):
        raise V2DataGateError("ETF_IDENTITY_SET_MISMATCH")
    return frame.set_index("symbol")


def _download_panel(
    root: Path,
    *,
    start: str,
    end: str,
    split: str,
) -> tuple[pd.DataFrame, tuple[DownloadReceipt, ...], Mapping[str, Any]]:
    raw = root / "raw_v2"
    raw.mkdir(parents=True, exist_ok=True)
    identity = _identity_table()
    client = requests.Session()
    frames: list[pd.DataFrame] = []
    receipts: list[DownloadReceipt] = []
    audit: dict[str, Any] = {}
    for symbol in FIXED_SYMBOLS:
        prices, _dividends, splits, downloaded = download_yahoo_history(
            symbol, start, end, split=split, session=client, raw_dir=raw
        )
        normalized = split_normalize_ohlcv(
            prices,
            splits,
            # Yahoo chart OHLCV is historically represented on a split-consistent basis.
            source_already_split_normalized=True,
        )
        if normalized.empty:
            raise V2DataGateError(f"EMPTY_PANEL_SYMBOL:{symbol}")
        first = pd.Timestamp(normalized["date"].min())
        if first < identity.loc[symbol, "official_inception"]:
            raise V2DataGateError(f"PRE_INCEPTION_OBSERVATION:{symbol}")
        normalized.insert(0, "symbol", symbol)
        frames.append(normalized)
        receipts.extend(
            DownloadReceipt(
                dataset_id=f"YAHOO_{symbol}_BOUNDED_CHART",
                url_template=row.url_template,
                sha256=row.sha256,
                byte_count=row.byte_count,
                minimum_date=row.minimum_date,
                maximum_date=row.maximum_date,
                status=row.status,
                reason=row.reason,
            )
            for row in downloaded
        )
        audit[symbol] = {
            "official_inception": identity.loc[symbol, "official_inception"].date().isoformat(),
            "first_raw_bar": first.date().isoformat(),
            "last_raw_bar": pd.Timestamp(normalized["date"].max()).date().isoformat(),
            "rows": len(normalized),
            "split_events": len(splits),
            "dividends_excluded_from_predictor": True,
        }
    panel = pd.concat(frames, ignore_index=True)
    assert_frame_before_locked(panel, label="v2_fixed_etf_panel")
    return panel, tuple(receipts), audit


def prepare_market_snapshot(
    root: Path,
    package: CampaignPackage,
    *,
    start: str,
    end: str,
    split: str,
) -> Mapping[str, Any]:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    v1_manifest = prepare_v1_snapshot(
        root,
        _v1_package(),
        start=start,
        end=end,
        split=split,
    )
    panel, receipts, audit = _download_panel(root, start=start, end=end, split=split)
    pq.write_table(
        pa.Table.from_pandas(panel, preserve_index=False),
        root / "v2_fixed_etf_ohlcv.parquet",
    )
    with (root / "raw_manifest.jsonl").open("a", encoding="utf-8") as handle:
        for receipt in receipts:
            handle.write(json.dumps(receipt.__dict__, sort_keys=True, separators=(",", ":")) + "\n")
    manifest = {
        **v1_manifest,
        "campaign_id": "sp500_long_short_daily_zero_cost_v2_new_strategies",
        "v2_candidate_pack_sha256": canonical_json_hash(list(package.candidates)),
        "v2_panel_sha256": sha256_file(root / "v2_fixed_etf_ohlcv.parquet"),
        "v2_panel_identity_audit": audit,
        "available_dataset_ids": [f"V2DS{i:03d}" for i in range(1, 10)],
        "rejected_datasets": {"V2DS010": "SECONDARY_ONLY_NOT_EXECUTION_GRADE"},
        "locked_opened": False,
    }
    manifest["snapshot_sha256"] = canonical_json_hash(manifest)
    (root / "market_data_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_market_snapshot(root: Path) -> PreparedMarketData:
    root = Path(root).resolve()
    manifest = json.loads((root / "market_data_manifest.json").read_text("utf-8"))
    if manifest.get("locked_opened") is not False:
        raise LockedBoundaryError("TECHNICAL_FAILURE_LOCKED_BREACH:snapshot_manifest")
    base = load_v1_snapshot(root)
    panel = pq.read_table(root / "v2_fixed_etf_ohlcv.parquet").to_pandas()
    panel["date"] = pd.to_datetime(panel["date"])
    assert_frame_before_locked(panel, label="loaded_v2_fixed_etf_panel")
    series = dict(base.series)
    calendar = base.ledger.index
    for symbol, group in panel.groupby("symbol", sort=True):
        indexed = group.set_index("date").sort_index(kind="mergesort")
        for column in ("open", "high", "low", "close", "volume"):
            series[f"{symbol}::{column}"] = indexed[column].astype(float).reindex(calendar)
    return PreparedMarketData(
        ledger=base.ledger,
        series=series,
        available_dataset_ids=frozenset(manifest["available_dataset_ids"]),
        rejected_datasets=manifest["rejected_datasets"],
        receipts=base.receipts,
        split=str(manifest["split"]),
    )
