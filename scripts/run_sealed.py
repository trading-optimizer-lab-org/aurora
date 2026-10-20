"""The sealed test of the v16 finalists. Protocol: docs/research/SEALED_TEST_PROTOCOL.md.

  freeze  design data only: choose each family's configuration, the COMBO16 members and weights -> frozen.json
  open    rebuild the inputs through 2026-10-16 (the unlock must be set), run only the frozen configurations and
          report 2023-07-01 to 2026-10-16
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import v11
from aurora.research import v14_core as core


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R16 = _script("run_v16")
R15, R14 = R16.R15, R16.R14
EXCLUDE = {"B8", "B8R2"}
ALONE = ("S1", "B8R1")
SEALED_FROM = "2023-07-01"


def _calendar(s: pd.Series, cal: pd.DatetimeIndex) -> pd.Series:
    s = s.dropna()
    return (v11.to_trading(s, cal) if R14._is_calendar(s.index) else s.reindex(cal)).fillna(0.0)


def cmd_freeze(args) -> int:
    reg = R16.combined()
    real = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.rglob("real.parquet"))], axis=1)
    plac = pd.concat([pd.read_parquet(p) for p in sorted(args.parts.rglob("placebo.parquet"))], axis=1)
    D = R14.PREP.load(args.inputs / "daily.pkl")
    cal, cash = D["dates"], D["cash"]
    end = core.DESIGN_END
    cash_m = core.monthly(cash.loc[core.DESIGN_START:end].to_frame("c"))["c"]
    fams: dict[str, list[str]] = {}
    for key, (_, cfgs) in reg.items():
        fams.setdefault(R14.family_of(key), []).extend(f"{key}|{i}" for i in range(len(cfgs)))
    out: dict = {"families": {}}
    chosen = {}
    for fam, names in fams.items():
        cols = [n for n in names if f"{n}|mid" in real]
        if not cols:
            continue
        R = pd.DataFrame({n: _calendar(real[f"{n}|mid"], cal) for n in cols}).loc[core.DESIGN_START:end]
        cfg = [{"rule": n.split("|")[0], **reg[n.split("|")[0]][1][int(n.split("|")[1])]} for n in cols]
        nb = core.neighbours(cfg)
        Mo = core.monthly(R)
        s = core.plateau(core.score(Mo.to_numpy(), cash_m.reindex(Mo.index).fillna(0.0).to_numpy()), nb)
        if not np.isfinite(s).any():
            continue
        i = int(np.nanargmax(s))
        name = cols[i]
        pl = plac[[c for c in plac.columns if c.startswith(name + "|")]].copy()
        pl.index = pd.PeriodIndex(pl.index, freq="M")
        p = R14._p_value(Mo[name], pl, cash_m, None)
        member = fam not in EXCLUDE and s[i] >= 1.0 and np.isfinite(p) and p <= 0.05
        out["families"][fam] = {"name": name, "config": cfg[i], "plateau": float(s[i]), "p": float(p),
                                "member": bool(member)}
        if member:
            chosen[fam] = R[name]
    w = R14._ivol(pd.DataFrame(chosen).tail(252)) if chosen else pd.Series(dtype=float)
    out["weights"] = {k: float(v) for k, v in w.items() if v > 0}
    out["alone"] = {f: out["families"][f]["name"] for f in ALONE if f in out["families"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"members": out["weights"], "alone": out["alone"]}, indent=1), flush=True)
    return 0


def _series(name: str) -> dict[str, pd.Series]:
    key, ci = name.split("|")
    if key in R16.registry():
        fn = R16.real_and_placebo
    elif key in R15.registry():
        fn = R15.real_and_placebo
    else:
        fn = R14.real_and_placebo
    real, _, _ = fn(key, int(ci), 0)
    return real


def cmd_open(args) -> int:
    if core.last_day() != core.SEALED_END:
        raise SystemExit(f"the unlock is not set ({core.UNLOCK_ENV})")
    frozen = json.loads(args.frozen.read_text(encoding="utf-8"))
    R14.BLOCK = 0  # no placebo runs, only the frozen configurations' own returns
    R15.load(args.v14_inputs, args.v15_inputs)
    R16.load(args.v14_inputs, args.v15_inputs, args.v16_inputs)
    D = R14._G["D"]
    cal, cash = D["dates"], D["cash"]
    names = sorted(set(frozen["alone"].values()) | {frozen["families"][f]["name"] for f in frozen["weights"]})
    streams = {}
    for n in names:
        real = _series(n)
        for sc in ("mid", "high"):
            streams[f"{n}|{sc}"] = _calendar(real[sc], cal)
        print(f"ran {n}", flush=True)
    S = pd.DataFrame(streams)
    w = frozen["weights"]
    for sc in ("mid", "high"):
        S[f"COMBO16|{sc}"] = sum(S[f"{frozen['families'][f]['name']}|{sc}"] * x for f, x in w.items())
    end = str(core.SEALED_END.date())
    rows, verdict = [], {}
    targets = [("COMBO16", "COMBO16")] + [(f, frozen["alone"][f]) for f in ALONE if f in frozen["alone"]]
    for label, col in targets:
        for sc in ("mid", "high"):
            x = S[f"{col}|{sc}"]
            st = R14._stats(x, cash, SEALED_FROM, end)
            design = R14._stats(x, cash, "2018-01-01", str(core.DESIGN_END.date()))
            yr = {int(y): float(v) for y, v in ((1 + x.loc[SEALED_FROM:end]).groupby(
                x.loc[SEALED_FROM:end].index.year).prod() - 1).items()}
            rows.append({"strategy": label, "costs": sc, "sealed": st, "design": design, "yearly": yr})
            if sc == "mid":
                s = st.get("sortino", np.nan)
                verdict[label] = "success" if s >= 4 else ("promising" if s >= 3 else "failure")
    lines = ["# The sealed test, 2023-07-01 to 2026-10-16", "",
             "Frozen on design data only (docs/research/data/sealed_frozen.json); protocol in "
             "docs/research/SEALED_TEST_PROTOCOL.md.", "",
             "| strategy | costs | Sortino sealed | CAGR | max DD | total | design Sortino (2018-2023H1) | by year |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        st, de = r["sealed"], r["design"]
        yrs = ", ".join(f"{y} {v:+.1%}" for y, v in r["yearly"].items())
        lines.append(f"| {r['strategy']} | {r['costs']} | {st.get('sortino', np.nan):.2f} | {st.get('cagr', np.nan):.1%} | "
                     f"{st.get('dd', np.nan):.1%} | {st.get('total', np.nan):+.0%} | {de.get('sortino', np.nan):.2f} | "
                     f"{yrs} |")
    lines += ["", "Verdict (middle costs): " + ", ".join(f"{k}: {v}" for k, v in verdict.items()),
              "", "COMBO16 weights: " + ", ".join(f"{k} {v:.0%}" for k, v in w.items())]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.out / "sealed.json").write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=1, default=float),
                                          encoding="utf-8")
    S.astype(np.float32).to_parquet(args.out / "streams.parquet")
    print("\n".join(lines), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--inputs", type=Path, default=Path("outputs/v14/inputs"))
    f.add_argument("--parts", type=Path, required=True)
    f.add_argument("--out", type=Path, default=Path("outputs/sealed/sealed_frozen.json"))
    o = sub.add_parser("open")
    o.add_argument("--frozen", type=Path, default=Path("docs/research/data/sealed_frozen.json"))
    for a in ("v14", "v15", "v16"):
        o.add_argument(f"--{a}-inputs", type=Path, default=Path(f"outputs/sealed/{a}"))
    o.add_argument("--out", type=Path, default=Path("outputs/sealed/report"))
    args = ap.parse_args()
    if args.cmd == "open" and os.environ.get(core.UNLOCK_ENV) != "yes-the-owner-asked":
        raise SystemExit("the sealed window is opened only with the owner's unlock")
    return {"freeze": cmd_freeze, "open": cmd_open}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
