"""v43 data: the base book's trades and their one-minute bars (the minute replay of v39's best book).

  trades   every trade of DS1 20% RU 70% NS 40% at the five levels and four costs, with the facts the minute replay
           needs (entry price and leg, the shield's stop, the daily exit), and the symbol-days they are open
  minutes  Alpaca SIP one-minute bars, 04:00-19:59 ET, raw prices, of those symbol-days; a coverage report
Only the trades and the bars are kept (in the Actions cache); the coverage report holds counts only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


R40 = _script("run_v40")
R36, R35, R33, R29, R14 = R40.R36, R40.R35, R40.R33, R40.R29, R40.R14
sh = R33.sh
D14 = _script("run_v14_data")
LEVELS = R35.LEVELS
TASKS = R40.TASKS
META: dict = {}
_DAILY = R33.daily_path


def _daily_path(D, s, table, spread, fee_mult, gross, w_max):
    """R33's shield path; records each trade's entry, stop and daily exit for the minute replay."""
    p = _DAILY(D, s, table, spread, fee_mult, gross, w_max)
    if p is not None:
        P = sh.PARAMS
        e, _ = R33.ENTRIES[-1]
        own_lvl = e * (1 + s.stop) if np.isfinite(s.stop) else np.inf
        stop = sh.stop_level(P["stop"], e, own_lvl, s.t, s.j, 1.0)
        if not np.isfinite(stop) or stop <= e:
            stop = np.inf if P["stop"] == "own" else e * 1.20
        cat = R33.VARIANT["cat"]
        META[(int(s.t), int(s.j), float(s.prio))] = {
            "kind": s.kind, "stop": float(stop), "hold": P["hold"], "scale": P["scale"],
            "cat": float(cat) if cat is not None else np.nan, "target": P.get("target", "none"),
            "limit": e != float(D["O"][s.t, s.j]) if s.kind == "open" else False,
            "exit_row": int(sh.EXIT.get("row", -1)), "exit_kind": str(sh.EXIT.get("kind", "")),
            "exit_minute": int(sh.EXIT.get("minute", -1))}
    return p


R33.daily_path = _daily_path
sh.daily_path = _daily_path


def cmd_trades(args) -> int:
    R29.load(args.inputs, args.report)
    R29.set_plan("FREE")
    rows = R35._rows(args)
    D = R14._G["D"]
    dates, cols = D["dates"], D["cols"]
    out = []
    for task in TASKS:
        for level in LEVELS:
            META.clear()
            its = R40.book_its(rows, float(level), **R33.TASKS[task])
            for k, it in enumerate(its):
                m = META.get((int(it["t"]), int(it["j"]), float(it["prio"])), {})
                out.append({"task": task, "level": float(level), "k": k, "member": it["member"],
                            "sym": str(cols[it["j"]]), "j": int(it["j"]), "t": int(it["t"]), "i0": int(it["i0"]),
                            "date": str(dates[it["t"]].date()), "entry": float(it["entry"]),
                            "raw0": float(it["raw0"]), "r": [float(x) for x in it["r"]], "w": float(it["w"]),
                            "loc": float(it.get("loc", 0.0)), "tier": int(it.get("tier", 0)),
                            "prio": float(it["prio"]), "price": float(it["price"]), **m})
            print(task, level, len(its), "trades", sum(1 for x in out[-len(its):] if "kind" in x), "with meta",
                  flush=True)
    df = pd.DataFrame(out)
    args.out.mkdir(parents=True, exist_ok=True)
    df.to_pickle(args.out / "trades.pkl")
    need: dict[str, set] = {}
    for t, i0, n, sym in zip(df["t"], df["i0"], df["r"].map(len), df["sym"]):
        for u in range(min(t, i0), min(i0 + n + 1, len(dates))):  # the entry day to the day after the exit
            need.setdefault(str(dates[u].date()), set()).add(sym)
    (args.out / "need.json").write_text(json.dumps({d: sorted(s) for d, s in sorted(need.items())}),
                                        encoding="utf-8")
    print(json.dumps({"trades": len(df), "unique": int(df.drop_duplicates(["member", "t", "j"]).shape[0]),
                      "days": len(need), "symbol_days": sum(len(s) for s in need.values())}), flush=True)
    return 0


def _minute_day(day: pd.Timestamp, symbols: list[str], folder: Path, headers: dict, limiter) -> None:
    path = folder / f"{day.date()}.parquet"
    if path.exists():
        return
    rows = []
    for k in range(0, len(symbols), 50):
        rows += D14._bars(symbols[k:k + 50], "1Min", D14._ny(day, 4, 0), D14._ny(day, 19, 59), "raw", headers,
                          limiter)
    df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
    start = D14._ny(day, 4, 0)
    df["minute"] = ((pd.to_datetime(df.pop("t"), utc=True) - start).dt.total_seconds() // 60).astype(np.int16)
    df = df[(df["minute"] >= 0) & (df["minute"] < 960)][D14.MINUTE_COLS]
    for col in ("o", "h", "l", "c", "vw", "v"):
        df[col] = df[col].astype(np.float32)
    D14._write(df.sort_values(["symbol", "minute"]), path)


def cmd_minutes(args) -> int:
    headers = D14._alpaca_headers()
    need = json.loads((args.out / "need.json").read_text(encoding="utf-8"))
    folder = args.out / "minutes"
    folder.mkdir(parents=True, exist_ok=True)
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    todo = [(pd.Timestamp(d), s) for d, s in need.items() if not (folder / f"{d}.parquet").exists()]
    print(f"minute days to fetch: {len(todo)} of {len(need)}", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(_minute_day, d, s, folder, headers, limiter) for d, s in todo]
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 100 == 0:
                print(f"{n}/{len(todo)} days, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    have = 0
    rth_full = 0
    total = 0
    for d, syms in need.items():
        p = folder / f"{d}.parquet"
        x = pd.read_parquet(p, columns=["symbol", "minute"]) if p.exists() else pd.DataFrame(columns=["symbol",
                                                                                                    "minute"])
        rth = x[(x["minute"] >= 330) & (x["minute"] < 720)].groupby("symbol").size()
        for s in syms:
            total += 1
            have += int(s in set(x["symbol"]))
            rth_full += int(rth.get(s, 0) >= 300)
    cov = {"symbol_days": total, "with_bars": have, "with_300_rth_minutes": rth_full}
    (args.out / "coverage.json").write_text(json.dumps(cov, indent=1), encoding="utf-8")
    print(json.dumps(cov), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trades")
    t.add_argument("--choice", type=Path, required=True)
    t.add_argument("--inputs", type=Path, default=Path("outputs/v18"))
    t.add_argument("--report", type=Path, default=Path("outputs/v28w/report"))
    sub.add_parser("minutes")
    for p in sub.choices.values():
        p.add_argument("--out", type=Path, default=Path("outputs/v43"))
    args = ap.parse_args()
    return {"trades": cmd_trades, "minutes": cmd_minutes}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v43_data"
    raise SystemExit(main())
