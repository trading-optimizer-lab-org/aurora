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


def _net(entry: float, exit_px: float, side: int = 1) -> float:
    if side > 0:
        return exit_px * (1 - sc.COST) / (entry * (1 + sc.COST)) - 1
    x = exit_px / entry  # short held as collateral, as in stock_catalog.simulate
    return (2 - x - x * sc.COST) / (1 + sc.COST) - 1


def trade_list(panel: dict[str, pd.DataFrame], ind: dict, entries: pd.DataFrame, stops: pd.DataFrame | None,
               exit_rule: str, start: pd.Timestamp = sc.TRAIN_START, limits: pd.DataFrame | None = None,
               rsi: pd.DataFrame | None = None, side: int = 1) -> pd.DataFrame:
    dates = panel["close"].index
    f32 = np.float32
    O, H, L, C = (panel[k].to_numpy(dtype=f32) for k in ("open", "high", "low", "close"))
    S10, S20 = ind["sma10"].to_numpy(dtype=f32), ind["sma20"].to_numpy(dtype=f32)
    S50 = ind["sma50"].to_numpy(dtype=f32) if "sma50" in ind else None
    S5 = ind["sma5"].to_numpy(dtype=f32) if "sma5" in ind else None
    AD = ind["adr"].to_numpy(dtype=f32)
    E21 = ind["ema21"].to_numpy(dtype=f32) if "ema21" in ind else None
    LO10 = ind["low10"].to_numpy(dtype=f32) if "low10" in ind else None
    LO20 = ind["low20"].to_numpy(dtype=f32) if "low20" in ind else None
    R14 = ind["rsi14"].to_numpy(dtype=f32) if "rsi14" in ind else None
    WK = ind["week_end"].to_numpy() if "week_end" in ind else None
    XC = ind[exit_rule].to_numpy() if exit_rule.startswith("XC_") else None
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
            pstop = float(ST[t, i]) if ST is not None and np.isfinite(ST[t, i]) else None
            exit_t, exit_px = last, None
            for v in range(u + 1, min(u + MAX_HOLD, last) + 1):
                if pstop is not None and np.isfinite(L[v, i]) and L[v, i] <= pstop:
                    exit_t, exit_px = v, float(min(O[v, i], pstop)) if np.isfinite(O[v, i]) else pstop
                    break
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
        if not (np.isfinite(entry) and np.isfinite(stop)) or side * (entry - stop) <= 0:
            continue
        risk = abs(entry - stop) / entry
        adr_e = float(AD[t, i]) if np.isfinite(AD[t, i]) else 0.0
        hc = entry
        half_ret: float | None = None
        exit_t, exit_px = None, None
        for u in range(t + 1, min(t + MAX_HOLD, last) + 1):
            lo, hi, c = L[u, i], H[u, i], C[u, i]
            if side > 0 and np.isfinite(lo) and lo <= stop:
                exit_t, exit_px = u, float(min(O[u, i], stop)) if np.isfinite(O[u, i]) else stop
                break
            if side < 0 and np.isfinite(hi) and hi >= stop:
                exit_t, exit_px = u, float(max(O[u, i], stop)) if np.isfinite(O[u, i]) else stop
                break
            if exit_rule == "XR3" and np.isfinite(hi) and hi >= entry * (1 + 3 * risk):
                tgt = entry * (1 + 3 * risk)
                exit_t, exit_px = u, float(max(O[u, i], tgt)) if np.isfinite(O[u, i]) else tgt
                break
            if exit_rule == "XO25" and half_ret is None and np.isfinite(hi) and hi >= entry * 1.25:
                half_ret = _net(entry, float(max(O[u, i], entry * 1.25)) if np.isfinite(O[u, i]) else entry * 1.25)
            if not np.isfinite(c):
                continue
            days = u - t
            if exit_rule == "X5" and days >= 5:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XS10" and c < S10[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XS20" and c < S20[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XS50" and S50 is not None and c < S50[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XPS" and (c <= S10[u, i] or days >= 10):
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XC20" and c > S20[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XRSI" and S5 is not None and c > S5[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule in ("XT2", "XT3", "XT5", "XT8"):
                hc = max(hc, float(c))
                stop = max(stop, hc * (1 - int(exit_rule[2:]) * adr_e))
            elif exit_rule == "XBE":
                if c >= entry * (1 + risk):
                    stop = max(stop, entry)
                if c < S20[u, i]:
                    exit_t, exit_px = u, float(c)
            elif exit_rule == "XR3" and days >= 60:
                exit_t, exit_px = u, float(c)
            elif exit_rule in ("XTIME20", "XTIME60") and days >= int(exit_rule[5:]):
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XLOW10" and LO10 is not None and c < LO10[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XLOW20" and LO20 is not None and c < LO20[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XRSI80" and R14 is not None and R14[u, i] > 80:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XEXT" and S50 is not None and (c >= 1.25 * S50[u, i] or c < S50[u, i]):
                exit_t, exit_px = u, float(c)
            elif XC is not None and XC[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XWK" and S50 is not None and WK is not None and WK[u] and c < S50[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XE21" and E21 is not None and c < E21[u, i]:
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XS50T60" and S50 is not None and (c < S50[u, i] or days >= 60):
                exit_t, exit_px = u, float(c)
            elif exit_rule == "XO25" and S50 is not None and c < S50[u, i]:
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
        ret = _net(entry, exit_px, side)
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
