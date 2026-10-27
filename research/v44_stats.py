"""v44 statistics on one session's one-minute bars (V44_PREREGISTRATION.md): bulk volume classification, Bayesian
online change points, variance ratios, permutation entropy, a steady-state Kalman (alpha-beta) trend, log-periodic
power law fits, z-scores to VWAP and volume bars. Every value at bar k uses bars up to k only."""
from __future__ import annotations

import numpy as np
from scipy.special import ndtr

from aurora.research import v24_fast as fast


def _expanding_std(x: np.ndarray, min_n: int = 5) -> np.ndarray:
    ok = np.isfinite(x)
    z = np.where(ok, x, 0.0)
    n = np.cumsum(ok)
    s1, s2 = np.cumsum(z), np.cumsum(z * z)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = (s2 - s1 * s1 / n) / np.maximum(n - 1, 1)
    return np.where(n >= min_n, np.sqrt(np.maximum(var, 0.0)), np.nan)


def bvc_imbalance(o: np.ndarray, c: np.ndarray, v: np.ndarray, w: int) -> np.ndarray:
    """Easley et al.'s bulk volume classification: a bar's buy share is Phi(its price change / the session's standard
    deviation of price changes so far); the imbalance over the last w bars is sum v (2 buy - 1) / sum v."""
    dp = np.diff(c, prepend=o[0])
    sd = _expanding_std(dp)
    with np.errstate(invalid="ignore", divide="ignore"):
        buy = np.where(np.isfinite(sd) & (sd > 0), ndtr(dp / sd), 0.5)
    num, den = fast.rsum(v * (2 * buy - 1), w), fast.rsum(v, w)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, 0.0)


def variance_ratio(c: np.ndarray, q: int, w: int) -> np.ndarray:
    """VR(q) over the last w bars: the variance of overlapping q-bar log returns over q times that of 1-bar ones."""
    lc = np.log(np.maximum(c, 1e-9))
    r1 = np.diff(lc, prepend=lc[0])
    rq = lc - np.r_[np.full(q, lc[0]), lc[:-q]]  # the first q are placeholders outside every window kept below
    v1, vq = fast.rstd(r1, w) ** 2, fast.rstd(rq, w - q + 1) ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        out = vq / (q * v1)
    out[: w] = np.nan
    return out


def perm_entropy(c: np.ndarray, w: int = 60) -> np.ndarray:
    """Normalized permutation entropy of order 3 over the ordinal patterns of the last w bars."""
    n = len(c)
    out = np.full(n, np.nan)
    if n < 3:
        return out
    x = np.stack([c[:-2], c[1:-1], c[2:]], axis=1)
    pat = np.argsort(x, axis=1, kind="stable")
    code = pat[:, 0] * 9 + pat[:, 1] * 3 + pat[:, 2]
    counts = np.stack([fast.rsum((code == k).astype(float), w) for k in np.unique(code)], axis=1)
    tot = counts.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        p = counts / tot
        h = -np.nansum(np.where(p > 0, p * np.log(p), 0.0), axis=1) / np.log(6)
    h[np.arange(len(h)) < w - 1] = np.nan
    out[2:] = h
    return out


def alpha_beta(c: np.ndarray, lam: float) -> np.ndarray:
    """Velocity (log price per bar) of the steady-state Kalman filter of a local linear trend with tracking index
    lam = q / r (Kalata's alpha and beta)."""
    r = (4 + lam - np.sqrt(8 * lam + lam * lam)) / 4
    a = 1 - r * r
    b = 2 * (2 - a) - 4 * np.sqrt(1 - a)
    z = np.log(np.maximum(c, 1e-9))
    x, vel = float(z[0]), 0.0
    out = np.zeros(len(z))
    for k in range(1, len(z)):
        pred = x + vel
        e = float(z[k]) - pred
        x = pred + a * e
        vel = vel + b * e
        out[k] = vel
    return out


def bocpd(c: np.ndarray, hazard: float, rmax: int = 120, recent: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """Adams and MacKay's online change point on one-minute log returns (Gaussian, the session's variance so far,
    a normal prior on the mean): (probability that the run started within the last ``recent`` bars, the posterior
    mean of those recent runs)."""
    lc = np.log(np.maximum(c, 1e-9))
    x = np.diff(lc, prepend=lc[0])
    sd = _expanding_std(x, 10)
    n = len(x)
    cp, mean = np.zeros(n), np.zeros(n)
    p = np.array([1.0])
    s1 = np.array([0.0])
    cnt = np.array([0.0])
    for t in range(1, n):
        s2 = float(sd[t]) ** 2 if np.isfinite(sd[t]) and sd[t] > 0 else np.nan
        if not np.isfinite(s2):
            continue
        tau0 = 1.0 / (4 * s2)  # prior on the mean: N(0, (2 sd)^2)
        prec = tau0 + cnt / s2
        mu = (s1 / s2) / prec
        pred_var = s2 + 1.0 / prec
        like = np.exp(-0.5 * (x[t] - mu) ** 2 / pred_var) / np.sqrt(2 * np.pi * pred_var)
        grow = p * like * (1 - hazard)
        new = float((p * like * hazard).sum())
        p = np.r_[new, grow][: rmax + 1]
        s1 = np.r_[0.0, s1 + x[t]][: rmax + 1]
        cnt = np.r_[0.0, cnt + 1][: rmax + 1]
        tot = p.sum()
        if not tot > 0:
            p, s1, cnt = np.array([1.0]), np.array([0.0]), np.array([0.0])
            continue
        p = p / tot
        k = min(recent, len(p))
        cp[t] = float(p[:k].sum())
        prec_k = tau0 + cnt[:k] / s2
        mu_k = (s1[:k] / s2) / prec_k
        mean[t] = float((p[:k] * mu_k).sum() / max(cp[t], 1e-12))
    return cp, mean


LPPL_M, LPPL_W, LPPL_TC = (0.3, 0.5, 0.7), (6.0, 9.0, 12.0), (5, 10, 15, 20, 30, 45, 60)


def lppl(m: np.ndarray, c: np.ndarray, k: int, window: int | None) -> tuple[float, float]:
    """The best log-periodic power law fit of log price over the bars up to k (the last ``window`` bars, or all):
    a grid of exponent, angular frequency and critical time (minutes after bar k), linear least squares for the
    rest. (best R-squared among fits with B < 0, its critical time in minutes after bar k); (nan, nan) if none."""
    lo = 0 if window is None else max(0, k + 1 - window)
    tm, y = m[lo:k + 1].astype(float), np.log(np.maximum(c[lo:k + 1], 1e-9))
    if len(y) < 20:
        return np.nan, np.nan
    sst = float(((y - y.mean()) ** 2).sum())
    if sst <= 0:
        return np.nan, np.nan
    best = (np.nan, np.nan)
    for dtc in LPPL_TC:
        dt = tm[-1] + dtc - tm
        ldt = np.log(dt)
        for mm in LPPL_M:
            f = dt ** mm
            for om in LPPL_W:
                X = np.stack([np.ones_like(f), f, f * np.cos(om * ldt), f * np.sin(om * ldt)], axis=1)
                coef, *_ = np.linalg.lstsq(X, y, rcond=None)
                if coef[1] >= 0:
                    continue
                r2 = 1 - float(((y - X @ coef) ** 2).sum()) / sst
                if not np.isfinite(best[0]) or r2 > best[0]:
                    best = (r2, float(dtc))
    return best


def zscore(c: np.ndarray, line: np.ndarray, how: str) -> np.ndarray:
    """log(close / VWAP) over its standard deviation since the open ('sess') or over the last 60 bars ('roll60')."""
    with np.errstate(invalid="ignore", divide="ignore"):
        x = np.log(c / line)
    sd = _expanding_std(x) if how == "sess" else fast.rstd(x, 60)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(np.isfinite(sd) & (sd > 0), x / sd, 0.0)


def volume_bars(b: tuple, size: float) -> np.ndarray:
    """The index of the last minute bar of each volume bar of ``size`` shares (a volume bar closes on the minute its
    cumulative volume crosses the next multiple of size, so it is known at that minute's close)."""
    v = np.asarray(b[5], float)
    if not size > 0 or not len(v):
        return np.zeros(0, int)
    bucket = np.floor(np.cumsum(v) / size)
    return np.flatnonzero(np.diff(bucket, prepend=0.0) > 0)


def halts(m: np.ndarray, c: np.ndarray, move: float) -> list[tuple[int, int]]:
    """Inferred halts: bar k followed by no bar for five or more minutes, after a move of at least ``move`` over
    the five bars to k: (k, +1 up / -1 down)."""
    out = []
    gaps = np.flatnonzero(np.diff(m) >= 6)
    for k in gaps:
        if k < 5:
            continue
        r = c[k] / c[k - 5] - 1
        if abs(r) >= move:
            out.append((int(k), 1 if r > 0 else -1))
    return out
