"""v44 checks: the data helpers (session mapping, tick aggregation), the statistics, the new families' signals and
counts, part M's triggers and filters, part C's sleeve."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def DV():
    from test_v24 import _script
    return _script("run_v44_data", "run_v44_data_under_test")


def test_session_events(DV) -> None:
    D = {"dates": pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"]), "cols": pd.Index(["AAA", "BBB"])}
    when = pd.Series(pd.to_datetime(["2024-01-02 08:00", "2024-01-02 10:15", "2024-01-02 17:30",
                                     "2024-01-03 09:29", "2024-01-06 11:00"]))
    ev = DV.session_events(D, pd.Series(["AAA", "BBB", "AAA", "ZZZ", "BBB"]), when)
    assert list(ev.index) == [0, 1, 2]  # ZZZ has no column; Saturday falls past the last session
    assert ev["t"].tolist() == [0, 0, 1] and ev["minute"].tolist() == [-1, 45, -1] and ev["j"].tolist() == [0, 1, 0]


def test_aggregate_ticks(DV) -> None:
    start = pd.Timestamp("2024-01-02 14:00", tz="UTC")
    t = start + pd.to_timedelta([10, 20, 30, 70, 80], unit="s")
    trades = pd.DataFrame({"t": t, "p": [10.0, 10.1, 10.1, 10.0, 10.2], "s": [100, 50, 20000, 300, 100],
                           "c": [[], ["F"], [], [], ["I"]]})
    quotes = pd.DataFrame({"t": [start + pd.Timedelta(seconds=65)], "bp": [10.0], "ap": [10.4], "bs": [3], "as": [1]})
    out = DV.aggregate_ticks(trades, quotes, start).set_index("minute")
    # minute 0: tick rule (no quote yet): +1 for 10.1, carried for the second 10.1; the first trade has no sign
    assert out.loc[0, "vb"] == 20050 and out.loc[0, "vs"] == 0 and out.loc[0, "viso"] == 50
    assert out.loc[0, "vodd"] == 50 and out.loc[0, "vblk"] == 20000 and out.loc[0, "n"] == 3
    # minute 1: mid 10.2: 10.0 is a sell, 10.2 at the mid falls back to the tick rule (up)
    assert out.loc[1, "vs"] == 300 and out.loc[1, "vb"] == 100
    assert out.loc[1, "spread"] == pytest.approx(0.4 / 10.2) and out.loc[1, "dimb"] == pytest.approx(0.5)


# ---------------------------------------------------------------- part N: counts, statistics, signals, trades

from aurora.research import v14_core as core  # noqa: E402
from aurora.research import v14_intraday as vi  # noqa: E402
from aurora.research import v19_grid as v19  # noqa: E402
from aurora.research import v24_long1m as v24  # noqa: E402
from aurora.research import v44_new1m as v44  # noqa: E402
from aurora.research import v44_stats as st  # noqa: E402

N_COUNTS = {"NW_NEWS": 74844, "ED_EDGAR": 88452, "BC_BTC": 64800, "SY_SYMPATHY": 10800, "LV_LEVETF": 11520,
            "ZV_ZSCORE": 129600, "CP_BOCPD": 43200, "HU_FRACTAL": 64800, "KF_KALMAN": 77760, "LP_LPPL": 21600,
            "SS_SSR": 14400, "RO_ROTATION": 54000, "FB_FLOWBAR": 64800, "SQ_SQUEEZE": 48600, "HN_HALTNEWS": 3456}


def test_counts_match_the_preregistration() -> None:
    assert v44.counts() == N_COUNTS and sum(N_COUNTS.values()) == 772632
    for fam, n in N_COUNTS.items():
        assert len(core.grid(v44.INTRA_DIMS[fam])) == n
        assert list(v44.INTRA_DIMS[fam])[0] == "scope"


@pytest.mark.parametrize("family", sorted(N_COUNTS))
def test_feature_keys_partition_the_signal_keys(family: str) -> None:
    cfgs = core.grid(v44.INTRA_DIMS[family])
    keys = {v44.sig_key(family, g) for g in cfgs}
    fks = {v44.feat_key(family, g) for g in cfgs}
    seen: list = []
    for fk in fks:
        seen += v44.sig_keys(family, fk)
    assert len(seen) == len(set(seen)) == len(keys) and set(seen) == keys
    for g in cfgs[:: max(1, len(cfgs) // 500)]:
        assert v44.sig_key(family, g) in v44.sig_keys(family, v44.feat_key(family, g))


def _causal(f, x: np.ndarray, k: int, rng: np.random.Generator):
    y = np.array(x, copy=True)
    y[k + 1:] *= rng.uniform(0.5, 2.0, len(y) - k - 1)
    a, b = f(x), f(y)
    for u, w in zip(a if isinstance(a, tuple) else (a,), b if isinstance(b, tuple) else (b,)):
        assert np.allclose(np.asarray(u)[: k + 1], np.asarray(w)[: k + 1], equal_nan=True)


def test_statistics_use_bars_up_to_k_only() -> None:
    rng = np.random.default_rng(7)
    c = 5 * np.exp(np.cumsum(rng.normal(0, 0.005, 300)))
    o, v = np.r_[c[0], c[:-1]], rng.lognormal(8, 1, 300)
    for k in (40, 150, 260):
        _causal(lambda x: st.bvc_imbalance(o, x, v, 15), c, k, rng)
        _causal(lambda x: st.variance_ratio(x, 5, 30), c, k, rng)
        _causal(lambda x: st.perm_entropy(x, 60), c, k, rng)
        _causal(lambda x: st.alpha_beta(x, 0.01), c, k, rng)
        _causal(lambda x: st.bocpd(x, 1 / 30), c, k, rng)
        _causal(lambda x: st.zscore(x, np.cumsum(x) / np.arange(1, 301), "sess"), c, k, rng)
        _causal(lambda x: st.zscore(x, np.cumsum(x) / np.arange(1, 301), "roll60"), c, k, rng)
        m = np.arange(300)
        y = np.array(c, copy=True)
        y[k + 1:] *= 1.7
        assert st.lppl(m, c, k, 60) == st.lppl(m, y, k, 60)


def test_statistics_on_known_series() -> None:
    rng = np.random.default_rng(8)
    up = np.linspace(5, 6, 200)
    assert np.nanmax(st.perm_entropy(up, 60)) == pytest.approx(0.0)
    assert np.nanmean(st.perm_entropy(5 + rng.normal(0, 0.01, 2000).cumsum(), 60)) > 0.9
    rw = 5 * np.exp(np.cumsum(rng.normal(0, 0.003, 3000)))
    alt = 5 * np.exp(np.cumsum(np.where(np.arange(3000) % 2, 0.003, -0.003) + rng.normal(0, 0.0005, 3000)))
    assert 0.8 < np.nanmedian(st.variance_ratio(rw, 5, 60)) < 1.2
    assert np.nanmedian(st.variance_ratio(alt, 5, 60)) < 0.3
    trend = 5 * np.exp(0.002 * np.arange(300))
    assert st.alpha_beta(trend, 0.01)[-1] == pytest.approx(0.002, rel=1e-3)
    o = np.r_[5.0, trend[:-1]]
    assert st.bvc_imbalance(o, trend, np.ones(300), 15)[-1] > 0.3
    x = np.r_[np.zeros(150), np.full(150, 0.004)] + rng.normal(0, 0.001, 300)
    cp, mean = st.bocpd(5 * np.exp(np.cumsum(x)), 1 / 60)
    assert cp[151:158].max() > 0.5 and mean[170] > 0 and cp[60:140].max() < 0.5
    m = np.arange(200)
    tc = 215
    y = np.exp(1.5 - 0.12 * (tc - m) ** 0.5 + 0.01 * (tc - m) ** 0.5 * np.cos(9 * np.log(tc - m)))
    r2, dtc = st.lppl(m, y, 199, None)
    assert r2 > 0.99 and dtc == 15
    b = (np.arange(6), None, None, None, None, np.array([4.0, 4, 4, 10, 1, 1]))
    assert st.volume_bars(b, 10).tolist() == [2, 3]
    mm = np.r_[np.arange(10), np.arange(16, 20)]
    cc = np.r_[np.full(5, 10.0), 10.5, 11, 11.5, 12, 12.5, np.full(4, 12.0)]
    assert st.halts(mm, cc, 0.10) == [(9, 1)] and st.halts(mm, cc, 0.3) == []


def _x_extras(rng: np.random.Generator, T: int = 12) -> dict:
    """The v44 extras for one candidate (t 10, column 0) on synthetic data."""
    btc = 30000 * np.exp(np.cumsum(rng.normal(0, 0.001, (T, 390)) + rng.choice([0, 0.004, -0.004], (T, 390),
                                                                                 p=[0.97, 0.015, 0.015]), axis=1))
    iwm = 100 * np.exp(np.cumsum(rng.normal(0.00004, 0.0004, (T, 390)), axis=1))
    news = {(10, 0): (np.array([-1, 40, 120]), np.array([0, 3, len(v44.NEWS_CLASSES)])),
            (9, 0): (np.array([300]), np.array([1]))}
    edgar = {(10, 0): (np.array([-1, -1, 75]), np.array([0, 4, 8]))}
    L = np.full((T, 1), 4.0)
    L[9, 0] = 3.0
    return {"D": {"L": L, "C": np.full((T, 1), 5.0)}, "hot": np.array([0, 1, -1] * 4)[:T], "news": news,
            "edgar": edgar, "btc_min": btc.astype(np.float32), "btc_sig": np.full((T, 3), 0.001),
            "corr_btc": np.full((T, 1), 0.6, np.float32), "beta_btc": np.ones((T, 1), np.float32),
            "iwm_min": iwm.astype(np.float32), "iwm_pc": np.full(T, 99.0), "beta_iwm": np.full((T, 1), 1.2),
            "si_so": np.full((T, 1), 0.35), "dtc": np.full((T, 1), 4.0), "upos": np.array([0])}


def _signal(family: str, g: dict, cd: dict, b: tuple) -> tuple:
    if family in ("NW_NEWS", "ED_EDGAR"):
        return v44._events_signal(g, cd, b, "news" if family == "NW_NEWS" else "edgar")
    F = v44.FEATURES[family](v44.feat_key(family, g), cd, b) if family in v44.FEATURES else {}
    return v44.SIGNALS[family](g, cd, b, F)


def _from(b: tuple, k: int, rng: np.random.Generator, keep_open: bool) -> tuple:
    """Bars k on changed (bar k's open kept with ``keep_open``; bar k kept whole without)."""
    m, o, h, lo, c, v, vw = (np.array(x, copy=True) for x in b)
    s = np.arange(len(c)) >= (k if keep_open else k + 1)
    f = rng.uniform(0.6, 1.5, s.sum())
    o0 = o[k]
    o[s], c[s] = o[s] * f, c[s] * f[::-1]
    if keep_open:
        o[k] = o0
    h[s], lo[s] = np.maximum(o[s], c[s]) * 1.02, np.minimum(o[s], c[s]) * 0.98
    v[s] = v[s] * rng.uniform(0.1, 10, s.sum())
    vw[s] = (h[s] + lo[s] + c[s]) / 3
    return m, o, h, lo, c, v, vw


def _lppl_day(rng: np.random.Generator) -> tuple:
    m = np.arange(390)
    c = 4.0 * (1 + 1.4 * (m / 390) ** 2.5) * np.exp(rng.normal(0, 0.002, 390))
    o = np.r_[4.0, c[:-1]]
    h, lo = np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998
    return m.astype(np.int16), o, h, lo, c, rng.lognormal(8, 1, 390), (h + lo + c) / 3


@pytest.mark.parametrize("family", sorted(set(N_COUNTS) - {"SY_SYMPATHY"}))
def test_signals_do_not_look_ahead(family: str) -> None:
    from test_v24 import _cd, _day
    rng = np.random.default_rng(abs(hash(family)) % 2 ** 32)
    v44.X.clear()
    v44.X.update(_x_extras(rng))
    dims = {k: v for k, v in v44.INTRA_DIMS[family].items() if k not in v44.CONFIG_DIMS}
    sks = core.grid(dims)
    found = 0
    for ci in rng.choice(len(sks), size=min(30, len(sks)), replace=False):
        g = dict(sks[int(ci)], stop="pct10", exit="close", ctx="none", band="3-8")
        for _ in range(6):
            b = _lppl_day(rng) if family == "LP_LPPL" else _day(rng, halt=family == "HN_HALTNEWS")
            cd = dict(_cd(b, rng), adv=2e6, so=1.5e6)
            k, e, _, side = _signal(family, g, cd, b)
            if k < 0:
                continue
            found += 1
            intrabar = family == "SS_SSR" and g["setup"] == "lowbrk"
            b2 = _from(b, k, rng, keep_open=not intrabar)
            keep = {n: v44.X[n].copy() for n in ("btc_min", "iwm_min")}
            for n in keep:
                v44.X[n][10, int(b[0][k]):] *= 1.03
            try:
                k2, e2, _, side2 = _signal(family, g, cd, b2)
            finally:
                v44.X.update(keep)
            assert (k2, side2) == (k, side) and e2 == pytest.approx(e), (family, g)
            for rule in ("pct5", "ext", "vwap"):
                assert np.isclose(v44.stop_of(rule, b2, k, e, side), v44.stop_of(rule, b, k, e, side),
                                  equal_nan=True)
    assert found > 0, family


def _store_of(D: dict, rows: list[tuple[int, int]], days: list[tuple]) -> vi.Store:
    cands, arrays, off = [], {f: [] for f in vi.FIELDS}, 0
    for (t, j), b in zip(rows, days):
        pc = float(D["C"][t - 1, j])
        cands.append({"date": D["dates"][t], "symbol": str(D["cols"][j]), "t": t, "j": j, "off": off, "n": len(b[0]),
                      "open": float(b[1][0]), "pc": pc, "gap": float(b[1][0]) / pc - 1, "pmv": 1e6,
                      "pmh": float(b[1][0]) * 1.02, "pml30": float(b[1][0]) * 0.98, "pml": float(b[1][0]) * 0.98,
                      "so": 1.5e6, "s_gap_up": True, "s_runner": True, "s_gap_down": False, "s_day2": True})
        for f, x in zip(vi.FIELDS, b):
            arrays[f].append(x)
        off += len(b[0])
    st_ = vi.Store(pd.DataFrame(cands), {f: np.concatenate(x) for f, x in arrays.items()})
    st_.cols = {k: st_.cands[k].to_numpy() for k in st_.cands}
    return st_


def test_sympathy_events_use_minutes_up_to_the_event() -> None:
    from test_v24 import _daily, _day
    D = _daily()
    rng = np.random.default_rng(11)
    rows = [(260, 0), (260, 1), (260, 2), (261, 0), (261, 1)]
    days = [_day(rng, start=float(D["O"][t, j])) for t, j in rows]
    v44.X.clear()
    v44.X["sic"] = np.array(["2834", "2836", "7372"])
    v44._IDX.clear()
    ev = v44.sympathy_events({"event": _store_of(D, rows, days)}, 3)
    assert ev and all(nm == "event" and i in (0, 1, 3, 4) for nm, i in ev)  # 7372 has no peer
    cut = 200
    days2 = []
    for b in days:
        b2 = [np.array(x, copy=True) for x in b]
        late = b2[0] > cut
        for f in (1, 2, 3, 4, 6):
            b2[f][late] *= rng.uniform(0.5, 2.0, late.sum())
        days2.append(tuple(b2))
    v44._IDX.clear()
    ev2 = v44.sympathy_events({"event": _store_of(D, rows, days2)}, 3)
    for key in set(ev) | set(ev2):
        assert [x for x in ev.get(key, []) if x[0] <= cut] == [x for x in ev2.get(key, []) if x[0] <= cut]
    v44._IDX.clear()


def test_trades_and_placebos_on_a_synthetic_store() -> None:
    from test_v24 import _daily, _day
    D = _daily()
    T, N = len(D["dates"]), 3
    D["P1"], D["valid1"] = D["C"], np.ones((T, N), bool)
    rng = np.random.default_rng(12)
    rows = [(t, j) for t in range(250, 290) for j in range(N)]

    def make(rr: list) -> vi.Store:
        return _store_of(D, rr, [_day(rng, start=float(D["O"][t, j]), halt=rng.random() < 0.3) for t, j in rr])

    stores = {"event": make(rows), "liquid": make(rows[::2]), "mover": make(rows[1::2]), "filing": make(rows[::3])}
    for nm in ("liquid", "mover", "filing"):
        c = stores[nm].cands
        c["pdh"], c["pdl"], c["h5"], c["l5"] = np.nan, np.nan, np.nan, np.nan
    ex = _x_extras(rng, T)
    ex["news"] = {(t, j): (np.array([-1, 30]), np.array([0, 4])) for t, j in rows[::4]}
    ex["edgar"] = {(t, j): (np.array([-1]), np.array([0])) for t, j in rows[1::4]}
    ex["si_so"], ex["dtc"] = np.full((T, N), 0.35), np.full((T, N), 4.0)
    ex["sic"] = np.array(["2834", "2836", "2835"])
    ex["btc_day"], ex["iwm_day"] = rng.normal(0, 0.03, T), rng.normal(0, 0.01, T)
    ex["D"] = D
    for k in ("corr_btc", "beta_btc", "beta_iwm", "upos"):
        ex.pop(k)
    v44._IDX.clear()
    v44._BATCH.clear()
    v44.prepare(stores, D, ex)
    assert X_SHAPES(v44.X)
    v44.X["corr_btc"][:] = 0.6  # synthetic returns carry no BTC link
    v19.set_costs("r4", 0.25, None)
    n_tr = 0
    for fam in sorted(N_COUNTS):
        cfgs = core.grid(v44.INTRA_DIMS[fam])
        for g in [cfgs[int(i)] for i in np.random.default_rng(1).choice(len(cfgs), 6, replace=False)]:
            g = dict(g, band="3-8")
            tr = v44.trades(stores, D, fam, g)
            assert list(tr.columns) == v19.COLS
            if not len(tr):
                continue
            n_tr += len(tr)
            assert tr["side"].isin([1, -1]).all() and tr.groupby("date").size().max() <= 5
            assert ((tr["stop"] - tr["entry"]) * tr["side"] < 0).all()
            pl = v44.placebo(stores, v44.pool_by_day(stores, g), D, fam, g, tr, np.random.default_rng(0))
            assert len(pl) <= len(tr) and list(pl.columns) == v19.COLS
    assert n_tr > 0
    v44._IDX.clear()
    v44._BATCH.clear()


def X_SHAPES(X: dict) -> bool:
    used = len(X["used"])
    return X["corr_btc"].shape[1] == used and X["beta_iwm"].shape[1] == used and len(X["hot"]) == 300


def test_runner_deals_every_configuration_once() -> None:
    from test_v24 import _script
    R = _script("run_v44n", "run_v44n_under_test")
    cfgs = R.configs()
    assert len(cfgs) == len(set(cfgs)) == 772632
    assert R.SCEN[-1][0] == "strict" and R.R22.COMBO == "COMBO44"
