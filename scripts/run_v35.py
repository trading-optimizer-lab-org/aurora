"""v35: growing the limit book (V35_PREREGISTRATION.md). Phase 0 is a diagnostic of v34's limit members at 30%
a position (v33 run 40192951586's choice), base costs: what each member earns, the signals the account's caps leave
out, how full the account is, and the trades and sessions behind the tail. Nothing is chosen in phase 0.

  diag   V35_DIAG.md and v35_diag.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


R33 = _script("run_v33")
R29, R31, A, R14 = R33.R29, R33.R31, R33.A, R33.R14
SIZE = 0.30
DIAG_LEVELS = (5_000.0, 25_000.0)
CAPS: dict[str, tuple[float, int, int]] = {"base": (2.0, 20, 3), "gross3": (3.0, 20, 3), "new5": (2.0, 20, 5),
                                           "open40": (2.0, 40, 3), "free": (99.0, 999, 99)}


def pf(net: np.ndarray) -> float:
    """Profit factor: the sum of the winning trades' returns over the sum of the losing trades' losses."""
    win, loss = net[net > 0].sum(), -net[net < 0].sum()
    return float(win / loss) if loss > 0 else float("inf")


def daily_book(taken: list[dict], T: int) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Gross weight and open positions per session, and each member's contribution per session (before the
    broker's liquidation)."""
    gross, n_open = np.zeros(T), np.zeros(T)
    by: dict[str, np.ndarray] = {}
    for it in taken:
        r, w, i0 = np.asarray(it["r"], float), float(it["w"]), int(it["i0"])
        n = min(len(r), T - i0)
        if n <= 0:
            continue
        gross[i0:i0 + n] += w
        n_open[i0:i0 + n] += 1
        by.setdefault(it["member"], np.zeros(T))[i0:i0 + n] += w * r[:n]
    return gross, n_open, by


def members_table(taken: list[dict]) -> dict[str, dict]:
    out = {}
    for m in sorted({it["member"] for it in taken}):
        x = [it for it in taken if it["member"] == m]
        net = np.array([it["net"] for it in x])
        out[m] = {"n": len(x), "win": float((net > 0).mean()), "pf": pf(net), "mean_net": float(net.mean()),
                  "worst_net": float(net.min()), "contrib": float(sum(it["contrib"] for it in x)),
                  "w_mean": float(np.mean([it["w"] for it in x]))}
    return out


def _key(it: dict) -> tuple:
    return int(it["i0"]), int(it["j"]), it["member"]


def summary(s: pd.Series, taken: list[dict], gross_cap: float) -> dict:
    T = len(s)
    gross, n_open, _ = daily_book(taken, T)
    net = np.array([it["net"] for it in taken]) if taken else np.zeros(0)
    years = s.groupby(s.index.year).apply(lambda x: float(np.prod(1 + x.to_numpy()) - 1))
    return {"n": len(taken), "pf": pf(net) if len(net) else None, "contrib": float(sum(it["contrib"] for it in taken)),
            "gross_mean": float(gross.mean()), "gross_full": float((gross >= 0.9 * gross_cap).mean()),
            "open_mean": float(n_open.mean()), "days_in": float((n_open > 0).mean()),
            "years": {str(k): v for k, v in years.items()}, "members": members_table(taken)}


def cmd_diag(args) -> int:
    ch = json.loads((args.choice / "arms.json").read_text(encoding="utf-8"))
    rows = ch["arms"]["limit"]
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    D = R14._G["D"]
    dates = D["dates"]
    R33.RISK, R33.CAP = SIZE / 10, SIZE
    out: dict = {"size": SIZE, "levels": {}}
    for level in DIAG_LEVELS:
        its = []
        for r in rows:
            its += [{**it, "member": r["fam"]} for it in R33.member_items(r["name"], {int(r["year"])}, level,
                                                                         tuple(r["var"]))]
        runs = {}
        for name, (g, mo, mn) in CAPS.items():
            s, taken = A.joint(its, dates, g, mo, mn, "move", "none", "tzi", 0.0, 0.0, None, None)
            runs[name] = (s, taken)
        lv: dict = {"offered": len(its), "caps": {n: summary(s, tk, CAPS[n][0]) for n, (s, tk) in runs.items()}}
        base_keys = {_key(it) for it in runs["base"][1]}
        left = [it for it in runs["free"][1] if _key(it) not in base_keys]
        lnet = np.array([it["net"] for it in left]) if left else np.zeros(0)
        lv["left_out"] = {"n": len(left), "mean_net": float(lnet.mean()) if len(lnet) else None,
                          "pf": pf(lnet) if len(lnet) else None,
                          "by_member": {m: sum(1 for it in left if it["member"] == m)
                                        for m in sorted({it["member"] for it in left})}}
        s, taken = runs["base"]
        worst = sorted(taken, key=lambda it: it["contrib"])[:15]
        lv["worst_trades"] = [{"date": it["date"], "member": it["member"], "entry": float(it["entry"]),
                               "w": float(it["w"]), "net": float(it["net"]), "contrib": float(it["contrib"]),
                               "sessions": len(it["r"]), "tier": int(it.get("tier", -1))} for it in worst]
        liq, _ = R33.account(rows, level)
        _, _, by = daily_book(taken, len(s))
        order = np.argsort(liq)[:10]
        lv["worst_days"] = [{"date": str(dates[d].date()), "liquidated": float(liq[d]), "before": float(s.iloc[d]),
                             "by_member": {m: float(v[d]) for m, v in by.items() if abs(v[d]) > 1e-6}}
                            for d in order]
        out["levels"][f"{level:.0f}"] = lv
        print(level, lv["offered"], {n: c["n"] for n, c in lv["caps"].items()}, flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "v35_diag.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    (args.out / "V35_DIAG.md").write_text(report(out), encoding="utf-8")
    print(report(out), flush=True)
    return 0


def _p(x) -> str:
    return "-" if x is None else f"{x:.1%}"


def report(out: dict) -> str:
    L = ["# v35 phase 0: diagnostic of the limit book at 30%", "",
         "v33's limit members (run 40192951586), size 30% a position, base costs, before the broker's liquidation "
         "unless stated. Nothing is chosen here.", ""]
    for level, lv in out["levels"].items():
        L += [f"## Equity level ${int(level):,}", "", f"Trades offered by the members: {lv['offered']}.", "",
              "| caps (gross, open, new) | trades | PF | sum of contributions | mean gross | sessions >= 90% gross | "
              "mean open | sessions in |", "|---|---|---|---|---|---|---|---|"]
        for n, c in lv["caps"].items():
            g, mo, mn = CAPS[n]
            L.append(f"| {n} ({g:g}, {mo}, {mn}) | {c['n']} | {c['pf']:.2f} | {c['contrib']:.2f} | "
                     f"{c['gross_mean']:.2f} | {_p(c['gross_full'])} | {c['open_mean']:.1f} | {_p(c['days_in'])} |")
        lo = lv["left_out"]
        L += ["", f"Left out by the base caps but taken without caps: {lo['n']} trades, mean net "
                  f"{_p(lo['mean_net'])}, PF {lo['pf'] if lo['pf'] is None else round(lo['pf'], 2)}, "
                  f"by member {lo['by_member']}.", "", "| member | trades | win | PF | mean net | worst | sum of "
                  "contributions | mean weight |", "|---|---|---|---|---|---|---|---|"]
        for m, x in lv["caps"]["base"]["members"].items():
            L.append(f"| {m} | {x['n']} | {_p(x['win'])} | {x['pf']:.2f} | {_p(x['mean_net'])} | "
                     f"{_p(x['worst_net'])} | {x['contrib']:.2f} | {x['w_mean']:.2f} |")
        L += ["", "Year by year (base caps, compounded at this level): " + ", ".join(
            f"{y} {_p(v)}" for y, v in lv["caps"]["base"]["years"].items()), "",
            "| worst trades: date | member | weight | net | contribution | sessions | tier |",
            "|---|---|---|---|---|---|---|"]
        for t in lv["worst_trades"]:
            L.append(f"| {t['date']} | {t['member']} | {t['w']:.2f} | {_p(t['net'])} | {_p(t['contrib'])} | "
                     f"{t['sessions']} | {t['tier']} |")
        L += ["", "| worst sessions: date | with liquidation | before | by member |", "|---|---|---|---|"]
        for d in lv["worst_days"]:
            L.append(f"| {d['date']} | {_p(d['liquidated'])} | {_p(d['before'])} | " + ", ".join(
                f"{m} {_p(v)}" for m, v in d["by_member"].items()) + " |")
        L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diag")
    d.add_argument("--choice", type=Path, required=True)
    for p in sub.choices.values():
        p.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
        p.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"diag": cmd_diag}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v35"
    raise SystemExit(main())
