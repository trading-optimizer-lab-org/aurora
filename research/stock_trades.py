"""Trade-level view of the stock catalog: every signal traded on its own
(Amendment 1 of docs/research/STOCK_CATALOG_PREREGISTRATION.md).

No capital limit and no ranking; a new signal in a stock with an open trade
from the same rule is skipped. Entry, stop, exit rules and costs are the same
as in ``stock_catalog.simulate``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc

MAX_HOLD = 250


def _net(entry: float, exit_px: float) -> float:
    return exit_px * (1 - sc.COST) / (entry * (1 + sc.COST)) - 1


def trade_list(panel: dict[str, pd.DataFrame], ind: dict, entries: pd.DataFrame, stops: pd.DataFrame | None,
               exit_rule: str, start: pd.Timestamp = sc.TRAIN_START, limits: pd.DataFrame | None = None,
               rsi: pd.DataFrame | None = None) -> pd.DataFrame:
    dates = panel["close"].index
    f32 = np.float32
    O, H, L, C = (panel[k].to_numpy(dtype=f32) for k in ("open", "high", "low", "close"))
    S10, S20 = ind["sma10"].to_numpy(dtype=f32), ind["sma20"].to_numpy(dtype=f32)
    ST = stops.to_numpy(dtype=f32) if stops is not None else None
    LIM = limits.to_numpy(dtype=f32) if limits is not None else None
    R2 = rsi.to_numpy(dtype=f32) if rsi is not None else None
    first, last = int(dates.searchsorted(start)), len(dates) - 1
    rows, cols = np.nonzero(entries.to_numpy()[first:])
    rows = rows + first
    order = np.lexsort((rows, cols))
    busy_until: dict[int, int] = {}
    out: list[tuple] = []
    exit_t: int | None
    exit_px: float | None
    for k in order:
        t, i = int(rows[k]), int(cols[k])
        if t <= busy_until.get(i, -1) or t >= last:
            continue
        if exit_rule == "BNF":
            assert LIM is not None and R2 is not None
            u, lim = t + 1, LIM[t, i]
            if not (np.isfinite(lim) and np.isfinite(L[u, i]) and L[u, i] <= lim):
                continue
            entry = float(min(O[u, i], lim)) if np.isfinite(O[u, i]) else float(lim)
            exit_t, exit_px = last, None
            for v in range(u + 1, min(u + MAX_HOLD, last) + 1):
                c = C[v, i]
                if not np.isfinite(c):
                    continue
                if R2[v, i] >= 85 or (v - u >= 3 and c < entry) or v - u >= 5:
                    exit_t, exit_px = v, float(c)
                    break
            if exit_px is None:
                exit_px = float(pd.Series(C[u:last + 1, i]).ffill().iloc[-1])
            busy_until[i] = exit_t
            out.append((i, dates[u], dates[exit_t], entry, exit_px, np.nan, exit_t - u, _net(entry, exit_px)))
            continue
        assert ST is not None
        entry, stop = float(C[t, i]), float(ST[t, i])
        if not (np.isfinite(entry) and np.isfinite(stop)) or stop >= entry:
            continue
        risk = (entry - stop) / entry
        half_ret: float | None = None
        exit_t, exit_px = None, None
        for u in range(t + 1, min(t + MAX_HOLD, last) + 1):
            lo, c = L[u, i], C[u, i]
            if np.isfinite(lo) and lo <= stop:
                exit_t, exit_px = u, float(min(O[u, i], stop)) if np.isfinite(O[u, i]) else stop
                break
            if not np.isfinite(c):
                continue
            days = u - t
            if exit_rule == "X5" and days >= 5:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XS10" and c < S10[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XS20" and c < S20[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XH3":
                if days == 3 and half_ret is None:
                    half_ret, stop = _net(entry, float(c)), entry
                if c < S10[u, i]:
                    exit_t, exit_px = u, float(c)
            elif exit_rule == "XF" and ((days == 3 and c <= entry) or c < S10[u, i]):
                exit_t, exit_px = u, float(c)
            if exit_t is not None:
                break
        if exit_t is None:
            exit_t = min(t + MAX_HOLD, last)
            exit_px = float(pd.Series(C[t:exit_t + 1, i]).ffill().iloc[-1])
        assert exit_px is not None
        ret = _net(entry, exit_px)
        if half_ret is not None:
            ret = 0.5 * half_ret + 0.5 * ret
        busy_until[i] = exit_t
        out.append((i, dates[t], dates[exit_t], entry, exit_px, risk, exit_t - t, ret))
    df = pd.DataFrame(out, columns=["col", "entry_date", "exit_date", "entry", "exit", "risk", "days", "return"])
    df["symbol"] = panel["close"].columns[df["col"].to_numpy()] if len(df) else []
    df["R"] = df["return"] / df["risk"]
    return df.drop(columns="col")


def trade_stats(t: pd.DataFrame) -> dict[str, float | int]:
    if t.empty:
        return {"trades": 0}
    r = t["return"]
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    total = float(r.sum())
    top = r.sort_values(ascending=False).head(max(1, int(np.ceil(len(r) * 0.05)))).sum()
    return {
        "trades": int(len(r)), "win_rate": float((r > 0).mean()),
        "avg_return": float(r.mean()), "median_return": float(r.median()),
        "avg_R": float(t["R"].mean()) if t["R"].notna().any() else float("nan"),
        "profit_factor": float(gains / losses) if losses > 0 else float("inf"),
        "total_return": total, "total_R": float(t["R"].sum()) if t["R"].notna().any() else float("nan"),
        "avg_days": float(t["days"].mean()),
        "top5pct_share": float(top / total) if total > 0 else float("nan"),
    }


def summarize(t: pd.DataFrame) -> dict:
    out: dict = {}
    for p, (a, b) in sc.PERIODS.items():
        out[p] = trade_stats(t[(t["entry_date"] >= a) & (t["entry_date"] <= b)])
    out["annual"] = {str(y): {k: v for k, v in trade_stats(g).items()
                              if k in ("trades", "avg_return", "profit_factor", "total_return")}
                     for y, g in t.groupby(t["entry_date"].dt.year)} if len(t) else {}
    return out
