"""Feature store with provenance.

On-disk cache for computed indicators (RSI, MA, vol, returns, etc.) keyed by
(symbol, indicator, params, source_data_hash, code_hash).

Auto-invalidates on:
- Source data change (source_hash mismatch)
- Indicator code change (function source code hash differs)
- Params change

File layout:
    {root}/{symbol}/{indicator}_{combined_key_hash[:16]}.parquet
    {root}/{symbol}/{indicator}_{combined_key_hash[:16]}.parquet.meta.json
"""
from __future__ import annotations
import hashlib
import inspect
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd


def _hash_bytes(*chunks: bytes) -> str:
    h = hashlib.sha256()
    for c in chunks:
        h.update(c)
    return h.hexdigest()


def _source_hash(prices: pd.Series) -> str:
    """Hash of price values + index. Stable across runs."""
    vals = np.asarray(prices.values, dtype=np.float64).tobytes()
    idx = np.asarray(prices.index.values).tobytes()
    return _hash_bytes(vals, idx)


def _code_hash(fn: Callable) -> str:
    """Hash of function source code via inspect.getsource.

    Falls back to qualname+module hash for builtins / lambdas where source
    cannot be retrieved.
    """
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        src = f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', repr(fn))}"
    return _hash_bytes(src.encode("utf-8"))


def _params_repr(params: dict) -> str:
    """Deterministic repr for params dict."""
    items = sorted(params.items(), key=lambda kv: kv[0])
    return json.dumps(items, sort_keys=True, default=str)


def _combined_hash(symbol: str, indicator: str, params: dict,
                   source_hash: str, code_hash: str) -> str:
    payload = f"{symbol}|{indicator}|{_params_repr(params)}|{source_hash}|{code_hash}"
    return _hash_bytes(payload.encode("utf-8"))


@dataclass
class FeatureKey:
    symbol: str
    indicator: str
    params: dict
    source_hash: str
    code_hash: str = ""

    @property
    def combined_hash(self) -> str:
        return _combined_hash(self.symbol, self.indicator, self.params,
                              self.source_hash, self.code_hash)

    def cache_path(self, store_root) -> str:
        """Deterministic file path from key."""
        root = Path(store_root)
        sym_dir = root / self.symbol
        fname = f"{self.indicator}_{self.combined_hash[:16]}.parquet"
        return str(sym_dir / fname)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "indicator": self.indicator,
            "params": self.params,
            "source_hash": self.source_hash,
            "code_hash": self.code_hash,
            "combined_hash": self.combined_hash,
        }


class FeatureStore:
    """On-disk feature cache with provenance.

    Stores parquet files keyed by content hash. Auto-invalidates on source
    data, indicator code, or params change.
    """

    def __init__(self, root: str | None = None):
        # Default to the runtime cache dir (honours $QF_CACHE_DIR /
        # $QF_DATA_DIR; falls back to platformdirs). Never lands inside
        # the in-repo `quantforge/data_cache_qf/` ghost directory.
        if root is None:
            from aurora.core.runtime_paths import cache_dir as _cache_dir
            self.root = Path(_cache_dir()) / "features"
        else:
            self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _make_key(self, symbol: str, indicator: str, prices: pd.Series,
                  compute_fn: Callable, params: dict) -> FeatureKey:
        return FeatureKey(
            symbol=symbol,
            indicator=indicator,
            params=dict(params),
            source_hash=_source_hash(prices),
            code_hash=_code_hash(compute_fn),
        )

    def get_or_compute(self, symbol: str, indicator: str, prices: pd.Series,
                       compute_fn: Callable, **params) -> np.ndarray:
        """Look up; compute and cache on miss.

        Args:
            symbol: e.g. 'SPY'
            indicator: name e.g. 'rsi'
            prices: pd.Series of source data
            compute_fn: callable(prices_array, **params) -> np.ndarray
            **params: indicator-specific params

        Returns:
            np.ndarray (cached or freshly computed)
        """
        key = self._make_key(symbol, indicator, prices, compute_fn, params)
        path = Path(key.cache_path(self.root))
        meta_path = Path(str(path) + ".meta.json")

        if path.exists() and meta_path.exists():
            try:
                df = pd.read_parquet(path)
                return df["value"].to_numpy()
            except Exception:
                # corrupt cache file, fall through to recompute
                try: path.unlink()
                except OSError: pass
                try: meta_path.unlink()
                except OSError: pass

        # MISS: compute, persist, return.
        # Atomic write: write parquet to ``.tmp`` first, then write the meta
        # sidecar, then atomically replace the parquet via os.replace. This
        # avoids the half-written-cache hazard where a parquet exists on disk
        # but its meta sidecar is missing (or vice versa) after an interrupted
        # write. Readers checking both files see a fully written pair or no
        # pair, never a torn one.
        result = compute_fn(prices.values if isinstance(prices, pd.Series) else prices,
                            **params)
        result = np.asarray(result)
        path.parent.mkdir(parents=True, exist_ok=True)
        # parquet needs a DataFrame
        out_df = pd.DataFrame({"value": result})
        tmp_path = Path(str(path) + ".tmp")
        out_df.to_parquet(tmp_path)

        meta = key.to_dict()
        meta["created_at"] = time.time()
        meta["n_rows"] = int(len(result))
        meta["dtype"] = str(result.dtype)
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2, default=str)

        # Atomic rename — final visible state is fully written parquet + meta.
        os.replace(str(tmp_path), str(path))

        return result

    def invalidate(self, symbol: Optional[str] = None,
                   indicator: Optional[str] = None) -> int:
        """Delete cache entries matching filter. Returns n deleted."""
        n = 0
        if symbol is not None:
            sym_dirs = [self.root / symbol] if (self.root / symbol).exists() else []
        else:
            sym_dirs = [d for d in self.root.iterdir() if d.is_dir()]

        for sd in sym_dirs:
            for pq in sd.glob("*.parquet"):
                if indicator is not None:
                    # filename: {indicator}_{hash}.parquet
                    if not pq.name.startswith(f"{indicator}_"):
                        continue
                meta = Path(str(pq) + ".meta.json")
                try: pq.unlink(); n += 1
                except OSError: pass
                if meta.exists():
                    try: meta.unlink()
                    except OSError: pass
            # cleanup empty symbol dirs
            try:
                if sd.exists() and not any(sd.iterdir()):
                    sd.rmdir()
            except OSError:
                pass
        return n

    def list_entries(self) -> list[FeatureKey]:
        """List all cached features by reading meta sidecars."""
        entries: list[FeatureKey] = []
        if not self.root.exists():
            return entries
        for sd in self.root.iterdir():
            if not sd.is_dir():
                continue
            for meta_path in sd.glob("*.meta.json"):
                try:
                    with open(meta_path, "r") as f:
                        m = json.load(f)
                    entries.append(FeatureKey(
                        symbol=m.get("symbol", sd.name),
                        indicator=m.get("indicator", ""),
                        params=m.get("params", {}),
                        source_hash=m.get("source_hash", ""),
                        code_hash=m.get("code_hash", ""),
                    ))
                except (OSError, json.JSONDecodeError):
                    continue
        return entries

    def stats(self) -> dict:
        """Return cache stats: n_entries, total_size_mb."""
        n = 0
        total = 0
        if self.root.exists():
            for sd in self.root.iterdir():
                if not sd.is_dir():
                    continue
                for pq in sd.glob("*.parquet"):
                    n += 1
                    try: total += pq.stat().st_size
                    except OSError: pass
                    meta = Path(str(pq) + ".meta.json")
                    if meta.exists():
                        try: total += meta.stat().st_size
                        except OSError: pass
        return {"n_entries": n, "total_size_mb": total / (1024.0 * 1024.0)}


# ---------------------------------------------------------------------------
# Pre-built convenience compute functions and wrappers
# ---------------------------------------------------------------------------

def _rsi_compute(p: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI via Wilder smoothing. Works on a numpy array of prices."""
    p = np.asarray(p, dtype=float)
    n = int(period)
    rsi = np.full(len(p), np.nan)
    if len(p) < n + 1:
        return rsi
    d = np.diff(p)
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    ag = g[:n].mean()
    al = l[:n].mean()
    for i in range(n, len(p)):
        if i > n:
            ag = (ag * (n - 1) + g[i - 1]) / n
            al = (al * (n - 1) + l[i - 1]) / n
        rsi[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return rsi


def _sma_compute(p: np.ndarray, n: int = 20) -> np.ndarray:
    """Simple moving average via cumsum."""
    p = np.asarray(p, dtype=float)
    L = len(p)
    n = int(n)
    out = np.full(L, np.nan)
    if L < n or n <= 0:
        return out
    cs = np.empty(L + 1)
    cs[0] = 0.0
    np.cumsum(p, out=cs[1:])
    for i in range(n - 1, L):
        out[i] = (cs[i + 1] - cs[i + 1 - n]) / n
    return out


def _ema_compute(p: np.ndarray, n: int = 20) -> np.ndarray:
    """Exponential moving average."""
    p = np.asarray(p, dtype=float)
    L = len(p)
    n = int(n)
    out = np.full(L, np.nan)
    if L == 0 or n <= 0:
        return out
    alpha = 2.0 / (n + 1.0)
    out[0] = p[0]
    for i in range(1, L):
        out[i] = alpha * p[i] + (1.0 - alpha) * out[i - 1]
    return out


def _realized_vol_compute(p: np.ndarray, window: int = 20,
                          ppy: int = 252) -> np.ndarray:
    """Realized vol from log returns, annualized."""
    p = np.asarray(p, dtype=float)
    L = len(p)
    out = np.full(L, np.nan)
    if L < 2 or window <= 1:
        return out
    r = np.diff(np.log(p))
    for i in range(window, L):
        seg = r[i - window:i]
        out[i] = float(np.std(seg, ddof=1)) * np.sqrt(ppy)
    return out


def _returns_compute(p: np.ndarray, kind: str = "log") -> np.ndarray:
    """Daily returns, log or simple. Index 0 = NaN."""
    p = np.asarray(p, dtype=float)
    L = len(p)
    out = np.full(L, np.nan)
    if L < 2:
        return out
    if kind == "log":
        out[1:] = np.diff(np.log(p))
    else:
        out[1:] = np.diff(p) / p[:-1]
    return out


def cached_rsi(store: FeatureStore, symbol: str, prices: pd.Series,
               period: int = 14) -> np.ndarray:
    """Cached RSI. Mirrors quantforge.strategies.library.rsi_meanrev._rsi."""
    return store.get_or_compute(symbol, "rsi", prices, _rsi_compute, period=period)


def cached_sma(store: FeatureStore, symbol: str, prices: pd.Series,
               n: int = 20) -> np.ndarray:
    """Cached simple moving average."""
    return store.get_or_compute(symbol, "sma", prices, _sma_compute, n=n)


def cached_ema(store: FeatureStore, symbol: str, prices: pd.Series,
               n: int = 20) -> np.ndarray:
    """Cached exponential moving average."""
    return store.get_or_compute(symbol, "ema", prices, _ema_compute, n=n)


def cached_realized_vol(store: FeatureStore, symbol: str, prices: pd.Series,
                        window: int = 20, ppy: int = 252) -> np.ndarray:
    """Cached realized (rolling) volatility, annualized."""
    return store.get_or_compute(symbol, "realized_vol", prices,
                                _realized_vol_compute, window=window, ppy=ppy)


def cached_returns(store: FeatureStore, symbol: str, prices: pd.Series,
                   kind: str = "log") -> np.ndarray:
    """Cached daily returns (log or simple)."""
    return store.get_or_compute(symbol, "returns", prices, _returns_compute, kind=kind)


__all__ = [
    "FeatureKey",
    "FeatureStore",
    "cached_rsi",
    "cached_sma",
    "cached_ema",
    "cached_realized_vol",
    "cached_returns",
]
