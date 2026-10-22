"""v28 data (V28_PREREGISTRATION.md): the new public inputs of the megarun, all free.

  sec      EDGAR quarterly form indexes (EFFECT, NT 10-K, NT 10-Q, S-4, 424B4), full-text search hits (going-concern
           doubt in 10-K/10-Q, crypto treasury, de-SPAC closings, PDUFA dates, buybacks), the PDUFA target dates read
           from those 8-Ks, XBRL company facts (cash, operating cash flow, net income, assets, equity, revenue), the
           SIC code and former names of each company, and the SEC fails-to-deliver files
  regsho   Nasdaq's daily Reg SHO threshold lists
  finra    FINRA consolidated short interest (twice a month, as far back as the API serves)
  macro    VIX (FRED)
  pm       Alpaca SIP minute bars from 16:00 of the session before a small-cap gap-up to 09:29 of its day, as in v26's
           night store (premarket of the gap day)
  build    everything aligned to v14's daily panel: extras28.pkl (inputs of run_v28.py)
Only derived inputs are kept (in the Actions cache); nothing is published.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from aurora.research import v14_core as core


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


D26 = _script("run_v26_data")
D14, P14 = D26.D14, D26.P14
FORMS28 = {"EFFECT", "NT 10-K", "NT 10-Q", "S-4", "424B4"}
FTS = "https://efts.sec.gov/LATEST/search-index"
PHRASES = {  # name -> (query, forms, first year)
    "gc": ('"substantial doubt"', "10-K,10-Q", 2015),
    "crypto1": ('"treasury reserve asset"', "8-K", 2017),
    "crypto2": ('"digital asset treasury"', "8-K", 2017),
    "crypto3": ('"bitcoin treasury"', "8-K", 2017),
    "crypto4": ('"crypto treasury"', "8-K", 2017),
    "despac": ('"consummated the previously announced business combination"', "8-K", 2017),
    "pdufa": ('"PDUFA"', "8-K", 2015),
    "buyback1": ('"share repurchase program"', "8-K", 2015),
    "buyback2": ('"stock repurchase program"', "8-K", 2015),
}
TAGS = {"cash": ("CashAndCashEquivalentsAtCarryingValue",
                 "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        "ocf": ("NetCashProvidedByUsedInOperatingActivities",),
        "ni": ("NetIncomeLoss",), "assets": ("Assets",), "equity": ("StockholdersEquity",),
        "rev": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")}
WINDOWS = [(d, min(d + pd.Timedelta(days=9), d + pd.offsets.MonthEnd(0)) if d.day < 21 else d + pd.offsets.MonthEnd(0))
           for d in pd.date_range("2015-01-01", D14.LAST, freq="D") if d.day in (1, 11, 21)]  # ten-day windows
LAG_FTD, LAG_SI = 31, 12  # calendar days from a settlement date until the SEC / FINRA file is public
DATE_RE = r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})"


# ---------------------------------------------------------------- SEC

def _sec():
    return D14._Sec()


def form_index(sec, y: int, q: int, cache: Path) -> pd.DataFrame:
    path = cache / "form28" / f"{y}Q{q}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    b = sec.raw(f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.idx")
    rows = []
    for line in (b or b"").decode("latin-1").splitlines():
        form = re.split(r"\s{2,}", line.strip())[0]
        if form in FORMS28:
            m = re.search(r"\s(\d{1,10})\s+(\d{4}-\d{2}-\d{2})\s", line)
            if m:
                rows.append((form, int(m.group(1)), m.group(2)))
    df = pd.DataFrame(rows, columns=["form", "cik", "date"])
    D14._write(df, path)
    return df


def fts_window(sec, name: str, start: pd.Timestamp, end: pd.Timestamp, cache: Path) -> pd.DataFrame:
    """Every full-text hit of a phrase in a window of about ten days: (name, cik, date, form, adsh, file)."""
    path = cache / "fts" / name / f"{start.date()}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    q, forms, _ = PHRASES[name]
    rows, frm = [], 0
    while True:
        url = (f"{FTS}?q={requests.utils.quote(q)}&forms={forms}&dateRange=custom&startdt={start.date()}"
               f"&enddt={end.date()}&from={frm}")
        body = sec.json(url) or {}
        hits = (body.get("hits") or {}).get("hits", [])
        for h in hits:
            s = h.get("_source", {})
            for c in s.get("ciks", [])[:1]:
                rows.append((name, int(c), s.get("file_date"), s.get("form"), s.get("adsh"),
                             str(h.get("_id", ":")).split(":")[-1]))
        frm += len(hits)
        total = ((body.get("hits") or {}).get("total") or {}).get("value", 0)
        if not hits or frm >= min(total, 9900):
            break
    df = pd.DataFrame(rows, columns=["name", "cik", "date", "form", "adsh", "file"])
    D14._write(df, path)
    return df


def pdufa_dates(text: str, filed: pd.Timestamp) -> list[pd.Timestamp]:
    """Target dates near the word PDUFA, 1-500 days after the filing."""
    out = []
    for m in re.finditer(r"PDUFA", text):
        for d in re.findall(DATE_RE, text[max(0, m.start() - 250):m.end() + 250]):
            ts = pd.to_datetime(d, errors="coerce")
            if pd.notna(ts) and 1 <= (ts - filed).days <= 500:
                out.append(ts)
    return sorted(set(out))


def _pdufa_doc(sec, row: tuple) -> list[tuple]:
    cik, date, adsh, file = row
    b = sec.raw(f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{file}")
    if not b:
        return []
    text = re.sub(r"<[^>]+>", " ", b.decode("latin-1"))
    text = re.sub(r"&nbsp;|&#160;|\s+", " ", text)
    return [(cik, date, str(d.date())) for d in pdufa_dates(text, pd.Timestamp(date))]


def _bulk(sec, url: str, path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, headers=sec.headers, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 22):
                    f.write(chunk)
    return path


def company_facts(sec, ciks: set[int], cache: Path) -> pd.DataFrame:
    z = zipfile.ZipFile(_bulk(sec, "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
                              cache / "bulk" / "companyfacts.zip"))
    want = {t: k for k, ts in TAGS.items() for t in ts}
    rows = []
    for n in z.namelist():
        m = re.search(r"CIK(\d+)\.json", n)
        if not m or int(m.group(1)) not in ciks:
            continue
        facts = (json.loads(z.read(n)).get("facts") or {}).get("us-gaap", {})
        for tag, key in want.items():
            for unit, vals in ((facts.get(tag) or {}).get("units") or {}).items():
                if unit != "USD":
                    continue
                for v in vals:
                    if v.get("form") in ("10-K", "10-Q", "10-K/A", "10-Q/A") and v.get("filed"):
                        rows.append((int(m.group(1)), key, tag, v.get("start"), v["end"], float(v["val"]),
                                     v["filed"], v.get("fp")))
    return pd.DataFrame(rows, columns=["cik", "key", "tag", "start", "end", "val", "filed", "fp"])


def submissions_meta(sec, ciks: set[int], cache: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    z = zipfile.ZipFile(_bulk(sec, "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip",
                              cache / "bulk" / "submissions.zip"))
    sic, names = [], []
    for n in z.namelist():
        m = re.fullmatch(r"CIK(\d+)\.json", n.split("/")[-1])
        if not m or int(m.group(1)) not in ciks:
            continue
        j = json.loads(z.read(n))
        c = int(m.group(1))
        sic.append((c, str(j.get("sic") or ""), str(j.get("name") or "")))
        for f in j.get("formerNames") or []:
            names.append((c, f.get("name"), str(f.get("from", ""))[:10], str(f.get("to", ""))[:10]))
    return (pd.DataFrame(sic, columns=["cik", "sic", "name"]),
            pd.DataFrame(names, columns=["cik", "former", "from", "to"]))


def _ftd_file(sec, ym: str, half: str, cache: Path) -> pd.DataFrame | None:
    path = cache / "ftd" / f"{ym}{half}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    b = sec.raw(f"https://www.sec.gov/files/data/fails-deliver-data/cnsfails{ym}{half}.zip")
    if not b:
        return None
    z = zipfile.ZipFile(io.BytesIO(b))
    raw = z.read(z.namelist()[0]).decode("latin-1")
    rows = []
    for line in raw.splitlines()[1:]:
        p = line.split("|")
        if len(p) >= 4 and p[0].isdigit():
            try:
                rows.append((p[0], p[2].strip().upper(), float(p[3])))
            except ValueError:
                continue
    df = pd.DataFrame(rows, columns=["date", "symbol", "qty"])
    D14._write(df, path)
    return df


def cmd_sec(args) -> int:
    sec, cache = _sec(), args.out / "sec"
    hist = P14.ticker_history(args.sec)
    ciks = set(hist["cik"].astype(int))
    forms = pd.concat([form_index(sec, y, q, cache) for y, q in D14.QUARTERS], ignore_index=True)
    D14._write(forms, cache / "forms28.parquet")
    print(json.dumps({"forms28": forms["form"].value_counts().to_dict()}), flush=True)
    hits = []
    for name, (_, _, y0) in PHRASES.items():
        got = [fts_window(sec, name, a, b, cache) for a, b in WINDOWS if a.year >= y0]
        hits.append(pd.concat(got, ignore_index=True))
        print(f"fts {name}: {sum(len(g) for g in got)} hits", flush=True)
    fts = pd.concat(hits, ignore_index=True)
    D14._write(fts, cache / "fts.parquet")
    pd_rows = fts[fts["name"] == "pdufa"].drop_duplicates(["cik", "adsh"])
    pd_rows = pd_rows[pd_rows["cik"].isin(ciks)]
    out = []
    with ThreadPoolExecutor(6) as ex:
        futs = [ex.submit(_pdufa_doc, sec, (int(r.cik), r.date, r.adsh, r.file)) for r in pd_rows.itertuples()]
        for f in as_completed(futs):
            out += f.result()
    D14._write(pd.DataFrame(out, columns=["cik", "filed", "pdufa"]).drop_duplicates(), cache / "pdufa.parquet")
    print(json.dumps({"pdufa_docs": len(pd_rows), "pdufa_dates": len(out)}), flush=True)
    D14._write(company_facts(sec, ciks, cache), cache / "facts.parquet")
    sic, names = submissions_meta(sec, ciks, cache)
    D14._write(sic, cache / "sic.parquet")
    D14._write(names, cache / "former_names.parquet")
    for p in (cache / "bulk").glob("*.zip"):
        p.unlink()
    ftd = [f for ym in pd.period_range("2015-12", D14.LAST.strftime("%Y-%m"), freq="M")
           for h in ("a", "b") if (f := _ftd_file(sec, ym.strftime("%Y%m"), h, cache)) is not None]
    allftd = pd.concat(ftd, ignore_index=True)
    D14._write(allftd, cache / "ftd.parquet")
    print(json.dumps({"ftd_rows": len(allftd), "sic": len(sic), "former_names": len(names),
                      "sec_calls": sec.limiter.calls}), flush=True)
    return 0


# ---------------------------------------------------------------- Nasdaq, FINRA, FRED

def cmd_regsho(args) -> int:
    folder = args.out / "regsho"
    folder.mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range("2016-01-01", D14.LAST)
    sess = requests.Session()

    def one(d: pd.Timestamp) -> list[tuple]:
        r = None
        for attempt in range(5):
            try:
                r = sess.get(f"https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{d:%Y%m%d}.txt",
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
                break
            except requests.RequestException:
                time.sleep(2 ** attempt)
        if r is None or r.status_code != 200:
            return []
        return [(str(d.date()), p.split("|")[0].strip().upper()) for p in r.text.splitlines()[1:]
                if p.count("|") >= 3 and p.split("|")[3].strip() == "Y"]

    rows = []
    with ThreadPoolExecutor(4) as ex:
        for f in as_completed([ex.submit(one, d) for d in days]):
            rows += f.result()
    df = pd.DataFrame(rows, columns=["date", "symbol"])
    D14._write(df, folder / "threshold.parquet")
    print(json.dumps({"threshold_rows": len(df), "days": int(df["date"].nunique())}), flush=True)
    return 0


def _si_date(sess: requests.Session, d: pd.Timestamp) -> list[str]:
    rows, off = [], 0
    while True:
        body = {"limit": 5000, "offset": off, "fields": ["symbolCode", "settlementDate", "currentShortPositionQuantity",
                                                          "averageDailyVolumeQuantity", "daysToCoverQuantity"],
                "compareFilters": [{"compareType": "equal", "fieldName": "settlementDate", "fieldValue": str(d.date())}]}
        r = None
        for attempt in range(6):
            try:
                r = sess.post("https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest", json=body,
                              headers={"Accept": "text/plain"}, timeout=120)
                if r.status_code in (200, 204):
                    break
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)
        if r is None or r.status_code != 200 or not r.text.strip():
            return rows
        lines = r.text.strip().splitlines()[1:]
        rows += lines
        off += len(lines)
        if len(lines) < 5000:
            return rows


def cmd_finra(args) -> int:
    folder = args.out / "finra"
    folder.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    cands = [d for m in pd.period_range("2015-12", D14.LAST.strftime("%Y-%m"), freq="M")
             for d in pd.bdate_range(m.start_time + pd.Timedelta(days=9), m.start_time + pd.Timedelta(days=16))
             .append(pd.bdate_range(m.end_time.normalize() - pd.Timedelta(days=6), m.end_time.normalize()))]
    lines = []
    for d in cands:
        got = _si_date(sess, d)
        if got:
            lines += got
            print(f"short interest {d.date()}: {len(got)}", flush=True)
    rows = []
    for ln in lines:
        p = [x.strip('"') for x in ln.split(",")]
        if len(p) >= 5:
            rows.append(p[:5])
    df = pd.DataFrame(rows, columns=["symbol", "date", "si", "adv", "dtc"])
    for c in ("si", "adv", "dtc"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    D14._write(df, folder / "short_interest.parquet")
    print(json.dumps({"si_rows": len(df), "dates": int(df["date"].nunique()),
                      "first": str(df["date"].min()) if len(df) else None}), flush=True)
    return 0


def cmd_macro(args) -> int:
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS", timeout=120)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "vix"]
    df["vix"] = pd.to_numeric(df["vix"], errors="coerce")
    D14._write(df, args.out / "macro" / "vix.parquet")
    print(json.dumps({"vix_rows": len(df)}), flush=True)
    return 0


# ---------------------------------------------------------------- premarket of the gap days

GAP_TOP = 100


def pm_sets(D: dict) -> dict[int, list[int]]:
    """Night row t - 1 -> the small caps gapping up 15% or more on session t (prior close $1-$20, prior 20-day dollar
    volume >= $500k; at most 100 a session, the largest gaps)."""
    O, C, P1, DV1 = D["O"], D["C"], D["P1"], D["DV1"]
    ok = D["valid"] & D["valid1"]
    start = int(np.searchsorted(D["dates"], core.DESIGN_START))
    out = {}
    for t in range(max(start, 1), len(D["dates"])):
        with np.errstate(invalid="ignore", divide="ignore"):
            gap = O[t] / C[t - 1] - 1
            el = ok[t] & (gap >= 0.15) & (P1[t] >= 1) & (P1[t] <= 20) & np.isfinite(DV1[t]) & (DV1[t] >= 5e5)
        cols = np.flatnonzero(el)
        if len(cols):
            out[t - 1] = cols[np.argsort(-gap[cols], kind="stable")[:GAP_TOP]].tolist()
    return out


def cmd_pm(args) -> int:
    D = P14.load(args.inputs / "daily.pkl")
    sets = pm_sets(D)
    folder = args.out / "pm" / "nights"
    folder.mkdir(parents=True, exist_ok=True)
    headers = D14._alpaca_headers()
    limiter = D14.V9.Limiter(D14.V9.ALPACA_PER_MIN / 60)
    order = np.random.default_rng(28).permutation(sorted(sets))
    t0 = time.time()

    def one(u):
        if time.time() - t0 < args.budget_min * 60:
            D26._night(D, int(u), sets[int(u)], folder, headers, limiter)

    with ThreadPoolExecutor(4) as ex:
        for n, f in enumerate(as_completed([ex.submit(one, u) for u in order])):
            f.result()
            if n % 200 == 0:
                print(f"pm nights: {n}/{len(order)}, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    index, arrays = D26.build_store(D, sets, folder)
    store = args.out / "pmstore"
    store.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(store / "nights.npz", **arrays)
    index.to_parquet(store / "nights.parquet", index=False)
    print(json.dumps({"pm_nights": len(sets), "fetched": int(len(arrays["fetched"])), "symbol_nights": len(index)}),
          flush=True)
    return 0


# ---------------------------------------------------------------- build

def _panel(D: dict, rows: pd.DataFrame, value: str | None = None, fill: float = 0.0) -> np.ndarray:
    """A (session, column) array from rows with t, j (and a value column)."""
    out = np.full(D["C"].shape, fill, np.float32)
    if len(rows):
        out[rows["t"].to_numpy(int), rows["j"].to_numpy(int)] = rows[value].to_numpy(float) if value else 1.0
    return out


def _sym_rows(D: dict, df: pd.DataFrame, lag_days: int = 0) -> pd.DataFrame:
    """(t, j) by ticker: t = the first session after the date plus the publication lag."""
    pos = {str(s): i for i, s in enumerate(D["cols"])}
    d = pd.to_datetime(df["date"], errors="coerce") + pd.Timedelta(days=lag_days)
    df = df[d.notna()]
    t = D["dates"].searchsorted(d[d.notna()].to_numpy(), side="right")
    out = df.assign(t=t, j=df["symbol"].astype(str).map(pos)).dropna(subset=["j"])
    out = out[out["t"] < len(D["dates"])]
    return out.astype({"t": np.int64, "j": np.int64})


def _cik_rows(D: dict, df: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    ev = df.reset_index(drop=True).copy()
    ev["date"] = pd.to_datetime(ev["date"], errors="coerce")
    ev = ev.dropna(subset=["date"])
    ev["symbol"] = P14.map_symbols(ev, hist)
    return P14._rows(ev.dropna(subset=["symbol"]), D)


def _ffill_known(arr: np.ndarray, limit: int) -> np.ndarray:
    return pd.DataFrame(np.where(arr == 0, np.nan, arr)).ffill(limit=limit).fillna(0.0).to_numpy(np.float32)


def facts_panel(D: dict, facts: pd.DataFrame, hist: pd.DataFrame) -> dict[str, np.ndarray]:
    """Latest reported value of each fact known at each session (by filing date): cash, quarterly operating cash
    flow (a 3-month duration), trailing net income over assets, equity."""
    out = {}
    f = facts.copy()
    f["date"] = f["filed"]
    for key in ("cash", "assets", "equity"):
        x = f[f["key"] == key].sort_values("end").drop_duplicates(["cik", "filed"], keep="last")
        r = _cik_rows(D, x, hist)
        out[key] = _ffill_known(_panel(D, r, "val"), 400)
    for key in ("ocf", "ni"):
        x = f[(f["key"] == key) & f["start"].notna()].copy()
        days = (pd.to_datetime(x["end"]) - pd.to_datetime(x["start"])).dt.days
        x = x[(days >= 80) & (days <= 100)].sort_values("end").drop_duplicates(["cik", "filed"], keep="last")
        r = _cik_rows(D, x, hist)
        out[key + "_q"] = _ffill_known(_panel(D, r, "val"), 400)
    return out


def cmd_build(args) -> int:
    D = P14.load(args.inputs / "daily.pkl")
    hist = P14.ticker_history(args.sec)
    base = args.out
    sec = base / "sec"
    X: dict = {}
    # FTD shares over shares outstanding, the largest of the last 10 settlement days known (31-day lag)
    ftd = pd.read_parquet(sec / "ftd.parquet")
    ftd["date"] = pd.to_datetime(ftd["date"], format="%Y%m%d", errors="coerce")
    r = _sym_rows(D, ftd, LAG_FTD)
    q = _panel(D, r.groupby(["t", "j"], as_index=False)["qty"].max(), "qty")
    with np.errstate(invalid="ignore", divide="ignore"):
        X["ftd_so"] = (pd.DataFrame(q).rolling(10, min_periods=1).max().to_numpy() / D["SO"]).astype(np.float32)
    thr = pd.read_parquet(base / "regsho" / "threshold.parquet")
    r = _sym_rows(D, thr.assign(date=pd.to_datetime(thr["date"]) - pd.Timedelta(days=1)))
    X["thr"] = (pd.DataFrame(_panel(D, r.drop_duplicates(["t", "j"]))).rolling(5, min_periods=1).max()
                .to_numpy() > 0)
    si_path = base / "finra" / "short_interest.parquet"
    if si_path.exists():
        si = pd.read_parquet(si_path).dropna(subset=["si"])
        r = _sym_rows(D, si, LAG_SI).drop_duplicates(["t", "j"], keep="last")
        X["si_so"] = np.where(D["SO"] > 0, _ffill_known(_panel(D, r, "si"), 25) / D["SO"], np.nan).astype(np.float32)
        X["dtc"] = _ffill_known(_panel(D, r, "dtc"), 25)
        X["si_known"] = _ffill_known(_panel(D, r), 25) > 0
    fp = facts_panel(D, pd.read_parquet(sec / "facts.parquet"), hist)
    with np.errstate(invalid="ignore", divide="ignore"):
        burn = -np.minimum(fp["ocf_q"], 0.0) / 3.0
        X["runway"] = np.where(burn > 0, fp["cash"] / burn, np.where(fp["cash"] > 0, 999.0, np.nan)).astype(np.float32)
        X["roa"] = np.where(fp["assets"] > 0, 4 * fp["ni_q"] / fp["assets"], np.nan).astype(np.float32)
        X["eq_neg"] = fp["equity"] < 0
        so = pd.DataFrame(D["SO"]).ffill()
        X["so_g250"] = (so / so.shift(250) - 1).to_numpy(np.float32)
    fts = pd.read_parquet(sec / "fts.parquet")
    ev: dict = {}
    for name, sel in (("gc", fts["name"] == "gc"), ("crypto", fts["name"].str.startswith("crypto")),
                      ("despac", fts["name"] == "despac"), ("buyback", fts["name"].str.startswith("buyback"))):
        x = fts[sel].drop_duplicates(["cik", "date"])
        ev[name] = _cik_rows(D, x[["cik", "date"]], hist)[["t", "j"]]
    gcp = _panel(D, ev["gc"].drop_duplicates())
    X["gc"] = pd.DataFrame(gcp).rolling(400, min_periods=1).max().to_numpy() > 0
    prior = pd.DataFrame(gcp).rolling(400, min_periods=1).max().shift(1).fillna(0).to_numpy() > 0
    ev["gc_new"] = ev["gc"][~prior[ev["gc"]["t"].to_numpy(), ev["gc"]["j"].to_numpy()]]
    forms = pd.read_parquet(sec / "forms28.parquet")
    for name, fs in (("effect", ("EFFECT",)), ("nt", ("NT 10-K", "NT 10-Q")), ("s4", ("S-4",)),
                     ("ipo", ("424B4",))):
        x = forms[forms["form"].isin(fs)].drop_duplicates(["cik", "date"])
        ev[name] = _cik_rows(D, x[["cik", "date"]], hist)[["t", "j"]]
    filings = pd.read_parquet(args.sec / "filings.parquet")
    k8 = filings[filings["form"] == "8-K"]
    for name, item in (("pipe", "3.02"), ("earn", "2.02"), ("news", "8.01")):
        x = k8[k8["items"].astype(str).str.contains(item, regex=False)].drop_duplicates(["cik", "date"])
        ev[name] = _cik_rows(D, x[["cik", "date"]], hist)[["t", "j"]]
    pdu = pd.read_parquet(sec / "pdufa.parquet")
    pr = _cik_rows(D, pdu.rename(columns={"filed": "date"}), hist)
    pr["t_target"] = D["dates"].searchsorted(pd.to_datetime(pr["pdufa"]).to_numpy(), side="left")
    ev["pdufa"] = pr[pr["t_target"] < len(D["dates"])][["t", "j", "t_target"]].drop_duplicates(["j", "t_target"])
    names = pd.read_parquet(sec / "former_names.parquet")
    names = names.assign(date=pd.to_datetime(names["to"], errors="coerce") + pd.Timedelta(days=1))
    ev["rename"] = _cik_rows(D, names[["cik", "date"]].dropna(), hist)[["t", "j"]]
    sic = pd.read_parquet(sec / "sic.parquet")
    cur = hist.sort_values("filed").drop_duplicates("symbol", keep="last").merge(sic, on="cik", how="left")
    smap = dict(zip(cur["symbol"], cur["sic"]))
    X["sic"] = np.array([str(smap.get(str(s), "") or "") for s in D["cols"]])
    vix = pd.read_parquet(base / "macro" / "vix.parquet")
    X["vix"] = vix.assign(date=pd.to_datetime(vix["date"])).set_index("date")["vix"].reindex(D["dates"]).ffill() \
        .shift(1).to_numpy(np.float32)
    X["events"] = ev
    out = base / "inputs"
    out.mkdir(parents=True, exist_ok=True)
    P14.dump(X, out / "extras28.pkl")
    print(json.dumps({**{k: int(len(v)) for k, v in ev.items()}, "si": "si_so" in X,
                      "runway_known": float(np.isfinite(X["runway"]).mean())}), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("sec", "regsho", "finra", "macro", "pm", "build"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    ap.add_argument("--sec", type=Path, default=Path("outputs/v14/sec"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v28"))
    ap.add_argument("--budget-min", type=float, default=150.0)
    args = ap.parse_args()
    return {"sec": cmd_sec, "regsho": cmd_regsho, "finra": cmd_finra, "macro": cmd_macro, "pm": cmd_pm,
            "build": cmd_build}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
