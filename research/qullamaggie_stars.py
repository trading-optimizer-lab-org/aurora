"""Qullamaggie phase 3: score every breakout candidate with his measurable
"5-star" criteria (or a logistic model trained on 1995-2010) and trade only the
best one or three of the day. Pre-registered in
docs/research/QULLAMAGGIE_STARS_PREREGISTRATION.md (24 trials).
"""
from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_wind as qw
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7
from aurora.research import stock_trades as st

FEATURES = ["steady", "tight", "dryup", "near10", "mkt1m", "gap", "indrs", "rs", "m1", "adr"]
STAR_RULES = {"steady": (">=", 0.8), "tight": ("<=", 2.0), "dryup": ("<=", 0.7), "near10": ("<=", 0.02),
              "mkt1m": ("<", 0.05), "gap": ("<", 0.02), "indrs": (">=", 0.80), "rs": (">=", 0.90),
              "m1": (">=", 0.25)}
SCORERS, NS, EXPOSURES = ("STARS", "MODEL"), (1, 3), ("E0", "E3_C10")
SETUPS = ("D_BO", "I_BO", "I_MIX")
TOP_RETURN, L2, CLIP = 0.90, 1.0, 5.0


@dataclass(frozen=True)
class Trial:
    name: str
    setup: str
    scorer: str
    n: int
    policy: str


def trials() -> list[Trial]:
    return [Trial(f"{s}_{c}_N{n}_{e}", s, c, n, e) for s in SETUPS for c in SCORERS for n in NS for e in EXPOSURES]


def features(panel: dict, ind: dict, nasdaq: pd.Series) -> dict[str, pd.DataFrame]:
    """Candidate features as of the prior close (the gap as of the open)."""
    O, H, L, C, V = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    n = 63
    x = np.log(C)
    t = pd.Series(np.arange(len(C), dtype=float), index=C.index)
    mx, mt = x.rolling(n, min_periods=n).mean(), t.rolling(n, min_periods=n).mean()
    cov = x.mul(t, axis=0).rolling(n, min_periods=n).mean() - mx.mul(mt, axis=0)
    var_x = (x * x).rolling(n, min_periods=n).mean() - mx * mx
    r2 = cov * cov / var_x.mul((n * n - 1) / 12.0, axis=0)
    adr = ind["adr"]
    mkt = nasdaq.reindex(C.index).ffill().pct_change(21, fill_method=None)
    raw = {
        "steady": r2.where(var_x > 0),
        "tight": (H.rolling(10, min_periods=10).max() - L.rolling(10, min_periods=10).min()) / C / adr,
        "dryup": V.rolling(5, min_periods=5).mean() / V.rolling(50, min_periods=50).mean(),
        "near10": (C / ind["sma10"] - 1).abs(),
        "mkt1m": pd.DataFrame(np.broadcast_to(mkt.to_numpy()[:, None], C.shape), index=C.index, columns=C.columns),
        "indrs": ind["ind_rs"] / 100,
        "rs": (C / C.shift(63) - 1).rank(axis=1, pct=True),
        "m1": C / C.shift(21) - 1,
        "adr": adr,
    }
    out = {k: v.shift(1) for k, v in raw.items()}
    out["gap"] = O / C.shift(1) - 1
    return {k: out[k].astype(np.float32) for k in FEATURES}


def stars(feats: dict[str, pd.DataFrame]) -> pd.DataFrame:
    total = None
    for name, (op, level) in STAR_RULES.items():
        f = feats[name]
        hit = {">=": f >= level, "<=": f <= level, "<": f < level}[op]
        total = hit.astype(np.float32) if total is None else total + hit.astype(np.float32)
    assert total is not None
    return total


def fit_logit(X: np.ndarray, y: np.ndarray, l2: float = L2, iters: int = 100) -> np.ndarray:
    """L2-penalised logistic regression by Newton steps; the intercept is not penalised."""
    Xb = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(Xb.shape[1])
    pen = np.r_[0.0, np.full(X.shape[1], l2)]
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xb @ w))
        grad = Xb.T @ (p - y) + pen * w
        hess = (Xb.T * (p * (1 - p))) @ Xb + np.diag(pen)
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return w


def _matrix(feats: dict[str, pd.DataFrame], rows: pd.DataFrame) -> np.ndarray:
    """Feature values for trade rows (entry date, symbol)."""
    cols = []
    for name in FEATURES:
        f = feats[name]
        r = f.index.get_indexer(rows["entry_date"])
        c = f.columns.get_indexer(rows["symbol"])
        cols.append(f.to_numpy()[r, c])
    return np.column_stack(cols).astype(float)


def train_model(feats: dict[str, pd.DataFrame], trades: pd.DataFrame) -> dict:
    tr = trades[(trades["entry_date"] >= sc.TRAIN_START) & (trades["entry_date"] <= sc.TRAIN_END)]
    X = _matrix(feats, tr)
    y = (tr["return"] >= tr["return"].quantile(TOP_RETURN)).to_numpy(float)
    mu, sd = np.nanmean(X, axis=0), np.nanstd(X, axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = np.nan_to_num(np.clip((X - mu) / sd, -CLIP, CLIP))
    return {"w": fit_logit(Z, y), "mu": mu, "sd": sd, "rows": int(len(tr)), "positives": int(y.sum())}


def model_score(feats: dict[str, pd.DataFrame], model: dict) -> pd.DataFrame:
    like = feats[FEATURES[0]]
    z = np.full(like.shape, model["w"][0], dtype=np.float64)
    for j, name in enumerate(FEATURES):
        zj = np.nan_to_num(np.clip((feats[name].to_numpy(np.float64) - model["mu"][j]) / model["sd"][j], -CLIP, CLIP))
        z += model["w"][j + 1] * zj
    return pd.DataFrame((1 / (1 + np.exp(-z))).astype(np.float32), index=like.index, columns=like.columns)


def top_n(score: pd.DataFrame, candidates: pd.DataFrame, tiebreak: pd.DataFrame, n: int) -> pd.DataFrame:
    """The n best candidates of each day by score (ties: higher tiebreak)."""
    s = score.where(candidates.fillna(False).astype(bool)) + 1e-6 * tiebreak.fillna(0.0)
    return s.rank(axis=1, ascending=False, method="first") <= n


def auc(score: np.ndarray, y: np.ndarray) -> float:
    ok = np.isfinite(score)
    score, y = score[ok], y[ok].astype(bool)
    if y.all() or not y.any():
        return np.nan
    ranks = pd.Series(score).rank().to_numpy()
    pos = y.sum()
    return float((ranks[y].sum() - pos * (pos + 1) / 2) / (pos * (len(y) - pos)))


def diagnostics(feats: dict, model: dict, stream: pd.DataFrame) -> dict:
    out: dict = {"coefficients": dict(zip(["intercept"] + FEATURES, np.round(model["w"], 4).tolist())),
                 "train_rows": model["rows"], "train_positives": model["positives"]}
    cut = stream.loc[(stream["entry_date"] >= sc.TRAIN_START) & (stream["entry_date"] <= sc.TRAIN_END), "return"]
    top = cut.quantile(TOP_RETURN)
    star_df = stars(feats)
    model_df = model_score(feats, model)
    for p, (a, b) in v7.PERIODS.items():
        rows = stream[(stream["entry_date"] >= a) & (stream["entry_date"] <= b)]
        if rows.empty:
            continue
        y = (rows["return"] >= top).to_numpy()
        r, c = star_df.index.get_indexer(rows["entry_date"]), star_df.columns.get_indexer(rows["symbol"])
        sv, mv = star_df.to_numpy()[r, c], model_df.to_numpy()[r, c]
        out[f"{p}_auc_stars"], out[f"{p}_auc_model"] = auc(sv, y), auc(mv, y)
        by = pd.DataFrame({"stars": sv, "ret": rows["return"].to_numpy()}).groupby("stars")["ret"]
        out[f"{p}_return_by_stars"] = {int(k): [round(float(by.mean()[k]), 4), int(by.size()[k])]
                                       for k in by.size().index}
    return out


_G: dict = {}


def _run_trial(t: Trial) -> dict:
    g = _G[(t.setup, t.scorer, t.n)]
    e, s, px, sd = g["signals"]
    scale, gross, cap = qw.policy(t.policy, _G["wind"])
    allowed = e.mul((scale > 0).reindex(e.index).fillna(True), axis=0).astype(bool)
    trades: list[dict] = []
    d = sc.simulate(g["panel"], g["ind"], e, s, qw.EXIT, g["cash"], g["rank"], start=g["start"], entry_px=px,
                    same_day_px=sd, risk_scale=scale, max_gross=gross, cap=cap, trades=trades)
    tl = st.trade_list(g["panel"], g["ind"], allowed, s, qw.EXIT, start=g["start"], entry_px=px, same_day_px=sd)
    row = qw._row(qw.Trial(t.name, t.setup, t.policy), d["return"], tl, g["cash"], g["periods"],
                  qw._captured(g["all_trades"], trades, g["panel"]["close"].columns), _G["wind"]["state"])
    row.update(scorer=t.scorer, n=t.n)
    return row


def run(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series, nasdaq: pd.Series,
        cash_index: pd.Series, industry: pd.Series, load_minutes: Callable[[pd.Timestamp], pd.DataFrame],
        alp_daily: dict[str, pd.DataFrame], workers: int = 4) -> tuple[list[dict], dict]:
    if panel["close"].index.max() >= sc.LOCKED_START or nasdaq.index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the Qullamaggie stars study")
    f32 = np.float32
    ind = sc.indicators(panel, index_close, industry)
    ctx = q.context(panel, ind, nasdaq)
    wind_df = qw.wind(panel, ind, ctx)
    feats = features(panel, ind, nasdaq)
    e35, s35, px35 = q.breakout(panel, ind, ctx, "STOP", *q.BO_SELECTIONS["SCAN35"])
    stream = st.trade_list(panel, ind, e35.fillna(False).astype(bool), s35.astype(f32), qw.EXIT,
                           entry_px=px35.astype(f32))
    model = train_model(feats, stream)
    info = {"diagnostics": diagnostics(feats, model, stream)}
    setup5, _ = q.breakout_setup(panel, ind, ctx, *q.BO_SELECTIONS["SCAN5"])
    tiebreak = (panel["close"] / panel["close"].shift(63) - 1).rank(axis=1, pct=True).shift(1)
    scores = {"STARS": stars(feats), "MODEL": model_score(feats, model)}
    kept = {(c, n): top_n(scores[c], setup5, tiebreak, n) for c in SCORERS for n in NS}
    del feats, scores, tiebreak
    e5, s5, px5 = q.breakout(panel, ind, ctx, "STOP", *q.BO_SELECTIONS["SCAN5"])
    e5, s5, px5 = e5.fillna(False).astype(bool), s5.astype(f32), px5.astype(f32)
    prep = qi.prepare(panel, ind, ctx, cash_index, load_minutes, alp_daily)
    del ctx
    args = (prep["table"], prep["cands"], prep["m1"], prep["adr_prior"], prep["like"])
    ie = qi.trial_inputs(qw.I_EP, *args)[:4]
    ib0 = qi.trial_inputs(qw.I_BO, *args)[:4]

    def mix(b: tuple) -> tuple:
        return (b[0] | ie[0], b[1].where(b[0], ie[1]), b[2].where(b[0], ie[2]), b[3].where(b[0], ie[3]))

    cash = cash_index.reindex(panel["close"].index).ffill().pct_change(fill_method=None).fillna(0.0)
    rank = (panel["close"] / panel["close"].shift(63) - 1).rank(axis=1, pct=True).fillna(0.0).astype(f32)
    daily_base = {"panel": panel, "ind": ind, "cash": cash, "rank": rank, "start": sc.TRAIN_START,
                  "periods": v7.PERIODS, "all_trades": st.trade_list(panel, ind, e5, s5, qw.EXIT, entry_px=px5)}
    intra_base = {"panel": prep["panel"], "ind": prep["ind"], "cash": prep["cash"], "rank": prep["rank"],
                  "start": qi.START, "periods": qi.PERIODS}
    all_ib = st.trade_list(prep["panel"], prep["ind"], ib0[0], ib0[1], qw.EXIT, start=qi.START, entry_px=ib0[2],
                           same_day_px=ib0[3])
    m0 = mix(ib0)
    all_mix = st.trade_list(prep["panel"], prep["ind"], m0[0], m0[1], qw.EXIT, start=qi.START, entry_px=m0[2],
                            same_day_px=m0[3])
    groups: dict = {}
    for (c, n), k in kept.items():
        groups[("D_BO", c, n)] = {**daily_base, "signals": (e5 & k, s5, px5, None)}
        cands = dict(prep["cands"])
        cands["IBO_SCAN5"] = cands["IBO_SCAN5"] & k.reindex_like(cands["IBO_SCAN5"]).fillna(False).astype(bool)
        ib = qi.trial_inputs(qw.I_BO, prep["table"], cands, prep["m1"], prep["adr_prior"], prep["like"])[:4]
        groups[("I_BO", c, n)] = {**intra_base, "signals": ib, "all_trades": all_ib}
        groups[("I_MIX", c, n)] = {**intra_base, "signals": mix(ib), "all_trades": all_mix}
    del kept
    _G.update(groups, wind=wind_df)
    todo = trials()
    if workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(workers) as pool:
            rows = list(pool.imap_unordered(_run_trial, todo))
    else:
        rows = [_run_trial(t) for t in todo]
    _G.clear()
    spy = spy_close.reindex(panel["close"].index).ffill().pct_change(fill_method=None).fillna(0.0)
    spy_row: dict = {"name": "spy"}
    for p, (a, b) in {**v7.PERIODS, **qi.PERIODS}.items():
        m = sc.metrics(spy.loc[a:b], cash)
        spy_row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
    info["intraday"] = prep["info"]
    return rows + [spy_row], info


def aggregate(rows: pd.DataFrame, prior_sharpes: list[float]) -> dict:
    spy = rows[rows["name"] == "spy"].iloc[0].to_dict()
    df = rows[rows["name"] != "spy"].set_index("name")
    df = df.loc[[t.name for t in trials() if t.name in df.index]].copy()
    daily = df["setup"].str.startswith("D_").to_numpy()
    pick = {k: np.where(daily, df[f"validation_{k}"], df[f"all_{k}"]) for k in ("sharpe", "days", "skew", "kurtosis")}
    pool = np.concatenate([pick["sharpe"].astype(float), np.asarray(prior_sharpes, dtype=float)])
    df["deflated_sharpe"] = v7.deflated_sharpe(pick["sharpe"], pool, pick["days"], pick["skew"], pick["kurtosis"])
    passed = []
    for _, r in df.iterrows():
        p = "validation" if str(r["setup"]).startswith("D_") else "all"
        v = {"sortino_monthly": r[f"{p}_sortino_monthly"], "cagr": r[f"{p}_cagr"], "max_drawdown": r[f"{p}_max_drawdown"]}
        passed.append(all(sc.criteria(v, {"cagr": spy[f"{p}_cagr"]}).values()))
    df["passed"] = passed
    return {"df": df, "spy": spy, "passed": list(df.index[df["passed"]]), "n_trials": int(np.isfinite(pool).sum()),
            "expected": len(trials())}
