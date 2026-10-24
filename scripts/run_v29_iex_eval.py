"""v29 section 6: do COMBO28's intraday members still work when their signals come from IEX's free real-time feed?

The three minute stores (the v18 event store, the v23 liquid store, the v24 mover store) are rebuilt with IEX's bars
for the same candidates: each day's regular-session bars, open, gap and premarket facts (pmv, pmh, pml, pml30, rv5)
from IEX; the prior days' facts kept; a candidate with no IEX bar that session is dropped. Each intraday member's
entries are captured on those stores, then filled on SIP's bars of the same symbol-day at the first bar at least one
minute after the IEX signal bar, at its open, with the captured stop distance, and walked by the member's shield as
in v28. Compared on the same years with the SIP entries (v28's) and, for reference, SIP entries one minute late.
Costs: v28's R4, middle. The criterion (pre-registered): over the intraday members pooled (trade-weighted), IEX keeps
at least 80% of the mean net return a trade and 70% of the trades.

  family  one shard of the B families: SIP, SIP+1 and IEX trades of each year's pick
  final   V29_IEX.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v14_intraday as vi
from aurora.research import v19_grid as v19
from aurora.research import v24_long1m as v24
from aurora.research import v25_short1m as v25
from aurora.research import v26_shield as sh


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


A = _script("run_v28_after")
R28, R26, R22, R14, R16 = A.R28, A.R26, A.R22, A.R14, A.R16
IEX = Path("outputs/v29/iex/minutes")
KEEP, ENOUGH = 0.80, 0.70


# ---------------------------------------------------------------- IEX stores

def _facts(pre: pd.DataFrame, reg: pd.DataFrame, cd: dict, dv1: float) -> dict:
    op = float(reg["o"].iloc[0])
    pc = float(cd["pc"])
    pv = np.where(np.isfinite(pre["vw"]), pre["vw"], pre["c"])
    last30 = pre[pre["minute"] >= 300]
    first5 = float(reg.loc[reg["minute"] < 335, "v"].sum())
    return {"open": op, "gap": op / pc - 1 if pc > 0 else np.nan, "pmv": float((pv * pre["v"]).sum()),
            "pmh": float(pre["h"].max()) if len(pre) else np.nan, "pml": float(pre["l"].min()) if len(pre) else np.nan,
            "pml30": float(last30["l"].min()) if len(last30) else np.nan,
            "rv5": first5 / max(dv1 / pc / 78, 1.0) if np.isfinite(dv1) and pc > 0 else 0.0}


def iex_stores(stores: dict[str, vi.Store], D: dict, folder: Path = IEX) -> tuple[dict[str, vi.Store], dict]:
    """The stores rebuilt on IEX's bars (same candidates; a candidate without an IEX bar that day is dropped)."""
    rows = {nm: [] for nm in stores}
    arrays = {nm: {k: [] for k in vi.FIELDS} for nm in stores}
    off = dict.fromkeys(stores, 0)
    by_day = {nm: st.cands.groupby("date").indices for nm, st in stores.items()}
    days = sorted(set().union(*[set(d) for d in by_day.values()]))
    DV1 = np.asarray(D["DV1"], float)
    seen = {"cands": 0, "kept": 0}
    for day in days:
        path = folder / f"{pd.Timestamp(day).date()}.parquet"
        bars = pd.read_parquet(path) if path.exists() else None
        groups = dict(tuple(bars.groupby("symbol", sort=False))) if bars is not None and len(bars) else {}
        for nm, st in stores.items():
            for i in by_day[nm].get(day, []):
                seen["cands"] += 1
                cd = st.cands.iloc[i].to_dict()
                b = groups.get(str(cd["symbol"]))
                if b is None:
                    continue
                mm = b["minute"].to_numpy()
                pre, reg = b[mm < 330], b[(mm >= 330) & (mm < 720)]
                if not len(reg):
                    continue
                new = {**cd, **{k: v for k, v in _facts(pre, reg, cd, DV1[int(cd["t"]), int(cd["j"])]).items()
                                if k in st.cands.columns}, "off": off[nm], "n": len(reg)}
                rows[nm].append(new)
                arrays[nm]["m"].append((reg["minute"].to_numpy() - 330).astype(np.int16))
                for k in ("o", "h", "l", "c", "v", "vw"):
                    arrays[nm][k].append(reg[k].to_numpy(np.float32))
                off[nm] += len(reg)
                seen["kept"] += 1
    out = {}
    for nm, st in stores.items():
        cands = pd.DataFrame(rows[nm], columns=st.cands.columns).astype(st.cands.dtypes.to_dict(), errors="ignore")
        out[nm] = vi.Store(cands.reset_index(drop=True),
                           {k: np.concatenate(v) if v else np.zeros(0, st.arrays[k].dtype)
                            for k, v in arrays[nm].items()})
    return out, seen


class Swap:
    """R14's stores and the capture caches replaced by the IEX ones inside the block."""

    def __init__(self, ev: vi.Store, lq: vi.Store, mv: vi.Store) -> None:
        D = R14._G["D"]
        st25 = {"event": vi.Store(ev.cands.copy(), ev.arrays), "liquid": vi.Store(lq.cands.copy(), lq.arrays),
                "mover": mv}
        v25.prepare(st25, D)
        self.new = {"store": ev, "liquid": lq, "v25": st25}
        self.E: dict = {}

    def __enter__(self):
        self.old = {k: R14._G[k] for k in self.new}
        self.oldE, self.oldIDX = dict(R26._E), dict(v24._IDX)
        R14._G.update(self.new)
        R26._E.clear()
        R26._E.update(self.E)
        v24._IDX.clear()
        return self

    def __exit__(self, *exc):
        self.E = dict(R26._E)
        R14._G.update(self.old)
        R26._E.clear()
        R26._E.update(self.oldE)
        v24._IDX.clear()
        v24._IDX.update(self.oldIDX)
        return False


# ---------------------------------------------------------------- trades

def _bars(st: vi.Store, i: int) -> tuple:
    off, n = int(st.cands["off"].iat[i]), int(st.cands["n"].iat[i])
    return tuple(st.arrays[f][off:off + n] for f in vi.FIELDS)


def sip_index(stores: list[vi.Store]) -> dict[tuple[int, int], tuple[int, vi.Store]]:
    """(row, column) -> (position, store) of the SIP candidate, from the first store that has it."""
    out: dict = {}
    for st in stores:
        for i, key in enumerate(zip(st.cands["t"].to_numpy(int), st.cands["j"].to_numpy(int))):
            out.setdefault((int(key[0]), int(key[1])), (i, st))
    return out


def on_sip(a: tuple, idx: dict, lag: int = 1) -> tuple | None:
    """An IEX entry filled on SIP's bars at the first bar ``lag`` minutes or more after the IEX signal bar."""
    cd, b, _line, j, e, stop, prio = a
    hit = idx.get((int(cd["t"]), int(cd["j"])))
    if hit is None:
        return None
    i, st = hit
    sb = _bars(st, i)
    k = int(np.searchsorted(sb[0], int(b[0][j]) + lag))
    if k >= len(sb[0]):
        return None
    e2 = float(sb[1][k])
    if not (np.isfinite(e2) and e2 > 0):
        return None
    return st.cands.iloc[i].to_dict(), sb, vi.vwap(sb[4], sb[5], sb[6]), k, e2, e2 * stop / e, prio


def _cfg(nm: str) -> tuple[str, dict]:
    k, ci = nm.rsplit("|", 1)
    return k[2:], R28.registry()[k][1][int(ci)]


def _rows(data: list, cfg: dict, year: int) -> pd.DataFrame:
    D = R14._G["D"]
    R28._TARGET["v"] = cfg.get("target", "none")
    sh.set_params({k: cfg[k] for k in ("hold", "stop", "ext", "rally", "scale")})
    try:
        keep = [a for a in data if a is not None and pd.Timestamp(a[0]["date"]).year == year]
        tr = pd.DataFrame([sh.intra_row(D, *a) for a in keep], columns=v19.COLS)
        return R26._keep_rows(tr, cfg["filt"])
    finally:
        sh.set_params(None)
        R28._TARGET["v"] = "none"


def stats(parts: list[pd.DataFrame], fam: str) -> dict:
    D, table = R14._G["D"], R16._W["table"]
    t = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=v19.COLS)
    items = A._rows_items(t, table, 0.01, 0.20, 100_000.0, 1.0, 1.0, fam)
    net = np.array([float(np.sum(it["r"])) for it in items])
    s = v19.intra_book(t, D["dates"], table, 1.0)[0] if len(t) else pd.Series(0.0, index=D["dates"])
    a, b, _ = A._window(D)
    st = R14._stats(s, D["cash"], str(a.date()), str(b.date())) or {}
    return {"trades": int(len(net)), "mean_net": float(net.mean()) if len(net) else np.nan,
            "sum_net": float(net.sum()), "sortino": st.get("sortino", np.nan), "cagr": st.get("cagr", np.nan)}


def cmd_family(args) -> int:
    A.ARGS = argparse.Namespace(report=str(args.report))
    fams = sorted({f for _, f, _, _ in A.members("A28") if f.startswith("B:")})
    mine = fams[args.shard::args.shards]
    R22.R19.load(args.inputs)
    v19.set_costs("r4", R22.SLIP, R22.R4)
    D = R14._G["D"]
    picks = [(y, f, nm) for y, f, nm, _ in A.members("A28") if f in mine]
    intra = []
    for y, f, nm in picks:
        key, cfg = _cfg(nm)
        if R26.entries(key, cfg["entry"])[0] == "intra":
            intra.append((y, f, nm))
    out: dict = {"coverage": None, "families": {}}
    if intra:
        ev, lq, mv = R14._G["store"], R14._G["liquid"], R14._G["v25"]["mover"]
        new, seen = iex_stores({"event": ev, "liquid": lq, "mover": mv}, D, args.iex)
        out["coverage"] = seen
        print(f"IEX stores: {seen}", flush=True)
        swap = Swap(new["event"], new["liquid"], new["mover"])
        idx = sip_index([ev, lq, mv])
        res: dict = {}
        for y, f, nm in intra:
            key, cfg = _cfg(nm)
            sip = R26.entries(key, cfg["entry"])[2]
            late = [R26._delayed(a, 1) for a in sip]
            with swap:
                cap = R26.entries(key, cfg["entry"])[2]
            iex = [on_sip(a, idx) for a in cap]
            for lab, data in (("sip", sip), ("sip1", late), ("iex", iex)):
                res.setdefault(f, {}).setdefault(lab, []).append(_rows(data, cfg, y))
            print(f"{f} {y}: sip {len(sip)} captured, iex {len(cap)} captured, {sum(a is not None for a in iex)} "
                  f"filled", flush=True)
        for f, labs in res.items():
            out["families"][f] = {lab: stats(parts, f) for lab, parts in labs.items()}
            print(f, {lab: (v["trades"], round(v["mean_net"], 4)) for lab, v in out["families"][f].items()},
                  flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"iex_{args.shard:02d}.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


def verdict(fams: dict) -> dict:
    tot = {lab: sum(v[lab]["trades"] for v in fams.values()) for lab in ("sip", "sip1", "iex")}
    net = {lab: sum(v[lab]["sum_net"] for v in fams.values()) for lab in ("sip", "sip1", "iex")}
    mean = {lab: net[lab] / tot[lab] if tot[lab] else np.nan for lab in tot}
    keep = mean["iex"] / mean["sip"] if mean["sip"] and np.isfinite(mean["sip"]) and mean["sip"] > 0 else np.nan
    share = tot["iex"] / tot["sip"] if tot["sip"] else np.nan
    return {"trades": tot, "mean_net": mean, "keep": keep, "share": share,
            "met": bool(np.isfinite(keep) and keep >= KEEP and share >= ENOUGH)}


def cmd_final(args) -> int:
    fams, cov = {}, []
    for p in sorted(args.parts.rglob("iex_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        fams.update(d["families"])
        if d["coverage"]:
            cov.append(d["coverage"])
    v = verdict(fams) if fams else None
    L = ["# v29 section 6: the intraday members on IEX's free real-time feed", "",
         "Signals on IEX's one-minute bars, fills on SIP's one minute later; v28's R4 middle costs; the same picks and "
         "years. Criterion: IEX keeps 80% of the mean net return a trade and 70% of the trades (pooled).", ""]
    if cov:
        L.append(f"IEX coverage: {cov[0]['kept']} of {cov[0]['cands']} candidate symbol-days had IEX bars.")
        L.append("")
    L += ["| family | trades SIP | SIP+1m | IEX | mean net SIP | SIP+1m | IEX | Sortino SIP | SIP+1m | IEX |",
          "|" + "---|" * 10]

    def f(x, pct=False):
        return "-" if not isinstance(x, (int, float)) or not np.isfinite(x) else (f"{x:.2%}" if pct else f"{x:.2f}")
    for fam, r in sorted(fams.items()):
        L.append(f"| {fam} | {r['sip']['trades']} | {r['sip1']['trades']} | {r['iex']['trades']} | "
                 f"{f(r['sip']['mean_net'], True)} | {f(r['sip1']['mean_net'], True)} | {f(r['iex']['mean_net'], True)} "
                 f"| {f(r['sip']['sortino'])} | {f(r['sip1']['sortino'])} | {f(r['iex']['sortino'])} |")
    if v:
        L += ["", f"Pooled: trades SIP {v['trades']['sip']}, SIP+1m {v['trades']['sip1']}, IEX {v['trades']['iex']} "
              f"({f(v['share'], True)} of SIP's); mean net a trade SIP {f(v['mean_net']['sip'], True)}, SIP+1m "
              f"{f(v['mean_net']['sip1'], True)}, IEX {f(v['mean_net']['iex'], True)} ({f(v['keep'], True)} of SIP's). "
              f"**Criterion {'met' if v['met'] else 'not met'}.**"]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "V29_IEX.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / "v29_iex_summary.json").write_text(json.dumps({"families": fams, "verdict": v, "coverage": cov},
                                                              indent=1, default=float), encoding="utf-8")
    print("\n".join(L), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("family")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, required=True)
    s.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    s.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    s.add_argument("--iex", type=Path, default=IEX)
    fi = sub.add_parser("final")
    fi.add_argument("--parts", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"family": cmd_family, "final": cmd_final}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v29_iex_eval"
    raise SystemExit(main())
