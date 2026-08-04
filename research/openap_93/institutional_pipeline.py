"""Current institutional-ownership signals from SEC Form 13F public data.

The SEC files are official but are not a drop-in replacement for the historical
Thomson/CRSP panel used by OpenAP.  The implementation therefore preserves the
published formulas while classifying the result as reconstructed and failing
closed whenever a CUSIP mapping, amendment, denominator or causal date is not
usable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from io import TextIOWrapper
from pathlib import Path
from typing import Any
from zipfile import ZipFile
import json
import time

import numpy as np
import pandas as pd
import requests

from .analyst_pipeline import _latest_payloads, _period
from .registry import FidelityClass


INSTITUTIONAL_IMPLEMENTED_SIGNALS = frozenset(
    {"DelBreadth", "RIO_Disp", "RIO_MB", "RIO_Turnover", "RIO_Volatility"}
)

OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
# The current unauthenticated OpenFIGI v3 contract allows ten mapping jobs per
# request and twenty-five requests per minute.
OPENFIGI_BATCH_SIZE = 10
OPENFIGI_REQUESTS_PER_MINUTE = 25


def _archive_table(archive: ZipFile, stem: str) -> pd.DataFrame:
    candidates = [
        name
        for name in archive.namelist()
        if Path(name).stem.upper() == stem.upper()
        and Path(name).suffix.lower() in {".tsv", ".txt"}
    ]
    if len(candidates) != 1:
        raise ValueError(f"Expected one {stem} table, found {candidates}")
    with archive.open(candidates[0]) as raw:
        with TextIOWrapper(raw, encoding="utf-8-sig", errors="replace") as handle:
            frame = pd.read_csv(handle, sep="\t", dtype=str, low_memory=False)
    frame.columns = [str(column).strip().upper() for column in frame.columns]
    return frame


def parse_13f_archives(
    archive_paths: Iterable[str | Path],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Parse quarterly SEC 13F archives into filings, holdings and exclusions.

    Amendment handling is deliberately conservative.  A complete restatement
    replaces the original filing.  Groups containing an amendment that merely
    adds holdings, or whose type is unclear, are excluded because treating that
    amendment as a full replacement or blindly concatenating it can both create
    incorrect institutional ownership.
    """

    submissions: list[pd.DataFrame] = []
    covers: list[pd.DataFrame] = []
    infotables: list[pd.DataFrame] = []
    for archive_path in archive_paths:
        with ZipFile(archive_path) as archive:
            submissions.append(_archive_table(archive, "SUBMISSION"))
            covers.append(_archive_table(archive, "COVERPAGE"))
            infotables.append(_archive_table(archive, "INFOTABLE"))

    submission = pd.concat(submissions, ignore_index=True)
    cover = pd.concat(covers, ignore_index=True)
    info = pd.concat(infotables, ignore_index=True)
    for frame in (submission, cover, info):
        if "ACCESSION_NUMBER" not in frame:
            raise ValueError("SEC 13F table is missing ACCESSION_NUMBER")
        frame["ACCESSION_NUMBER"] = frame["ACCESSION_NUMBER"].astype(str).str.strip()

    required_submission = {
        "ACCESSION_NUMBER",
        "FILING_DATE",
        "SUBMISSIONTYPE",
        "CIK",
        "PERIODOFREPORT",
    }
    required_info = {
        "ACCESSION_NUMBER",
        "NAMEOFISSUER",
        "TITLEOFCLASS",
        "CUSIP",
        "VALUE",
        "SSHPRNAMT",
        "SSHPRNAMTTYPE",
        "PUTCALL",
        "INVESTMENTDISCRETION",
    }
    if not required_submission <= set(submission):
        raise ValueError(
            "SEC 13F submission schema missing: "
            + ", ".join(sorted(required_submission - set(submission)))
        )
    if not required_info <= set(info):
        raise ValueError(
            "SEC 13F infotable schema missing: "
            + ", ".join(sorted(required_info - set(info)))
        )

    submission = submission.loc[
        submission["SUBMISSIONTYPE"].isin({"13F-HR", "13F-HR/A"})
    ].copy()
    submission["filing_date"] = pd.to_datetime(
        submission["FILING_DATE"], errors="coerce"
    )
    submission["report_period"] = pd.to_datetime(
        submission["PERIODOFREPORT"], errors="coerce"
    )
    submission["manager_cik"] = (
        submission["CIK"].astype(str).str.replace(r"\D", "", regex=True).str.lstrip("0")
    )
    submission = submission.dropna(subset=["filing_date", "report_period"])
    submission = submission.loc[submission["manager_cik"].ne("")].copy()

    cover_columns = [
        column
        for column in ("ACCESSION_NUMBER", "ISAMENDMENT", "AMENDMENTNO", "AMENDMENTTYPE")
        if column in cover
    ]
    submission = submission.merge(
        cover[cover_columns].drop_duplicates("ACCESSION_NUMBER", keep="last"),
        on="ACCESSION_NUMBER",
        how="left",
        validate="many_to_one",
    )

    selected_rows: list[pd.Series] = []
    exclusion_rows: list[dict[str, Any]] = []
    for (manager_cik, report_period), group in submission.groupby(
        ["manager_cik", "report_period"], sort=True
    ):
        ordered = group.sort_values(["filing_date", "ACCESSION_NUMBER"])
        amendments = ordered.loc[ordered["SUBMISSIONTYPE"].eq("13F-HR/A")]
        if amendments.empty:
            initials = ordered.loc[ordered["SUBMISSIONTYPE"].eq("13F-HR")]
            if initials.empty:
                continue
            selected_rows.append(initials.iloc[-1])
            continue
        latest_amendment = amendments.iloc[-1]
        amendment_type = str(latest_amendment.get("AMENDMENTTYPE") or "").upper()
        if "RESTATEMENT" in amendment_type:
            selected_rows.append(latest_amendment)
        else:
            exclusion_rows.append(
                {
                    "manager_cik": manager_cik,
                    "report_period": report_period,
                    "accession_number": latest_amendment["ACCESSION_NUMBER"],
                    "reason": "non_restatement_or_ambiguous_amendment",
                    "amendment_type": amendment_type,
                }
            )

    if not selected_rows:
        raise RuntimeError("SEC 13F archives yielded no unambiguous holdings filings")
    selected = pd.DataFrame(selected_rows).rename(
        columns={"ACCESSION_NUMBER": "accession_number"}
    )
    filings = selected[
        ["accession_number", "manager_cik", "filing_date", "report_period"]
    ].drop_duplicates()

    info = info.rename(columns={"ACCESSION_NUMBER": "accession_number"})
    holdings = info.merge(
        filings,
        on="accession_number",
        how="inner",
        validate="many_to_one",
    )
    holdings["cusip"] = (
        holdings["CUSIP"].astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    )
    holdings["shares_held"] = pd.to_numeric(holdings["SSHPRNAMT"], errors="coerce")
    holdings["market_value_thousands"] = pd.to_numeric(
        holdings["VALUE"], errors="coerce"
    )
    put_call = holdings["PUTCALL"].fillna("").astype(str).str.strip().str.upper()
    share_type = holdings["SSHPRNAMTTYPE"].fillna("").astype(str).str.strip().str.upper()
    holdings = holdings.loc[
        holdings["cusip"].str.fullmatch(r"[A-Z0-9]{9}")
        & share_type.eq("SH")
        & put_call.eq("")
        & holdings["shares_held"].gt(0)
    ].copy()
    holdings = (
        holdings.groupby(
            [
                "accession_number",
                "manager_cik",
                "filing_date",
                "report_period",
                "cusip",
                "NAMEOFISSUER",
                "TITLEOFCLASS",
            ],
            as_index=False,
            dropna=False,
        )
        .agg(
            shares_held=("shares_held", "sum"),
            market_value_thousands=("market_value_thousands", "sum"),
        )
        .rename(
            columns={"NAMEOFISSUER": "issuer_name", "TITLEOFCLASS": "title_of_class"}
        )
    )
    exclusions = pd.DataFrame(
        exclusion_rows,
        columns=[
            "manager_cik",
            "report_period",
            "accession_number",
            "reason",
            "amendment_type",
        ],
    )
    return filings.reset_index(drop=True), holdings.reset_index(drop=True), exclusions


def _requests_post(
    session: requests.Session,
) -> Callable[[str, Sequence[Mapping[str, Any]], Mapping[str, str]], Sequence[Mapping[str, Any]]]:
    def post(
        url: str,
        payload: Sequence[Mapping[str, Any]],
        headers: Mapping[str, str],
    ) -> Sequence[Mapping[str, Any]]:
        response = session.post(url, json=list(payload), headers=dict(headers), timeout=90)
        response.raise_for_status()
        decoded = response.json()
        if not isinstance(decoded, list):
            raise TypeError("OpenFIGI mapping response is not a list")
        return decoded

    return post


def map_cusips_openfigi(
    cusips: Iterable[str],
    *,
    output_checkpoint: str | Path | None = None,
    http_post: Callable[
        [str, Sequence[Mapping[str, Any]], Mapping[str, str]],
        Sequence[Mapping[str, Any]],
    ]
    | None = None,
    sleep: Callable[[float], None] = time.sleep,
    batch_size: int = OPENFIGI_BATCH_SIZE,
) -> pd.DataFrame:
    """Map 13F CUSIPs with the free unauthenticated OpenFIGI endpoint.

    Every candidate is retained in ``candidates_json``.  A CUSIP becomes usable
    only when exactly one US common-stock ticker remains after filtering.
    Checkpoint rows are append-only and make an interrupted mapping resumable.
    """

    clean = sorted(
        {
            str(value).upper().strip()
            for value in cusips
            if str(value).upper().strip()
            and len(str(value).upper().strip()) == 9
        }
    )
    checkpoint = Path(output_checkpoint) if output_checkpoint else None
    existing_rows: list[dict[str, Any]] = []
    completed: set[str] = set()
    if checkpoint is not None and checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            existing_rows.append(row)
            if str(row.get("mapping_status", "")) != "request_failed":
                completed.add(str(row["cusip"]))
    pending = [cusip for cusip in clean if cusip not in completed]

    owned_session: requests.Session | None = None
    if http_post is None:
        owned_session = requests.Session()
        http_post = _requests_post(owned_session)

    rows = list(existing_rows)
    interval = 60.0 / OPENFIGI_REQUESTS_PER_MINUTE + 0.05
    try:
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset : offset + batch_size]
            jobs = [
                {
                    "idType": "ID_CUSIP",
                    "idValue": cusip,
                    "marketSecDes": "Equity",
                }
                for cusip in batch
            ]
            response: Sequence[Mapping[str, Any]] | None = None
            last_error = ""
            for attempt in range(5):
                try:
                    response = http_post(
                        OPENFIGI_MAPPING_URL,
                        jobs,
                        {
                            "Content-Type": "application/json",
                            "User-Agent": (
                                "Aurora-OpenAP-Research/1.0 "
                                "https://github.com/trading-optimizer-lab-org/aurora"
                            ),
                        },
                    )
                    if len(response) != len(batch):
                        raise ValueError(
                            f"OpenFIGI returned {len(response)} rows for {len(batch)} jobs"
                        )
                    break
                except Exception as exc:  # network failures need bounded retries
                    last_error = f"{type(exc).__name__}: {exc}"
                    if attempt == 4:
                        response = None
                        break
                    sleep(min(60.0, 2.0 ** attempt))
            request_failed = response is None
            if request_failed:
                response = [{"error": last_error}] * len(batch)

            batch_rows: list[dict[str, Any]] = []
            for cusip, item in zip(batch, response, strict=True):
                raw_candidates = item.get("data", []) if isinstance(item, Mapping) else []
                candidates = [
                    candidate
                    for candidate in raw_candidates
                    if isinstance(candidate, Mapping)
                    and str(candidate.get("marketSector", "")).lower() == "equity"
                    and (
                        "common stock" in str(candidate.get("securityType2", "")).lower()
                        or "common stock" in str(candidate.get("securityType", "")).lower()
                    )
                ]
                us_candidates = [
                    candidate
                    for candidate in candidates
                    if str(candidate.get("exchCode", "")).upper() == "US"
                ]
                if us_candidates:
                    candidates = us_candidates
                tickers = sorted(
                    {
                        str(candidate.get("ticker", "")).upper().strip()
                        for candidate in candidates
                        if str(candidate.get("ticker", "")).strip()
                    }
                )
                if request_failed:
                    status = "request_failed"
                elif len(tickers) == 1:
                    status = "mapped_unique"
                elif len(tickers) > 1:
                    status = "ambiguous"
                else:
                    status = "no_common_stock_match"
                row = {
                    "cusip": cusip,
                    "ticker": tickers[0] if len(tickers) == 1 else None,
                    "mapping_status": status,
                    "candidate_count": len(candidates),
                    "candidates_json": json.dumps(candidates, sort_keys=True),
                    "warning": str(item.get("warning") or item.get("error") or ""),
                    "source_id": "openfigi_public",
                }
                batch_rows.append(row)
            rows.extend(batch_rows)
            if checkpoint is not None:
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                with checkpoint.open("a", encoding="utf-8") as handle:
                    for row in batch_rows:
                        handle.write(json.dumps(row, sort_keys=True) + "\n")
            if offset + batch_size < len(pending):
                sleep(interval)
    finally:
        if owned_session is not None:
            owned_session.close()

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(
            columns=[
                "cusip",
                "ticker",
                "mapping_status",
                "candidate_count",
                "candidates_json",
                "warning",
                "source_id",
            ]
        )
    return (
        result.drop_duplicates("cusip", keep="last")
        .sort_values("cusip")
        .reset_index(drop=True)
    )


def _quintile(values: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    available = pd.to_numeric(values, errors="coerce").dropna()
    if len(available) < 5 or available.nunique() < 2:
        return result
    result.loc[available.index] = np.ceil(
        available.rank(method="average", pct=True) * 5.0
    ).clip(1, 5)
    return result


def _latest_concept(concepts: pd.DataFrame, concept: str) -> pd.DataFrame:
    frame = concepts.loc[concepts["concept"].eq(concept)].copy()
    if "concept_lag" in frame:
        frame = frame.loc[pd.to_numeric(frame["concept_lag"], errors="coerce").eq(0)]
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                concept,
                f"{concept}_period_end",
                f"{concept}_available_at",
            ]
        )
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce")
    if "period_end" in frame:
        frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    else:
        frame["period_end"] = pd.NaT
    frame = frame.sort_values(["symbol", "available_at"]).drop_duplicates(
        "symbol", keep="last"
    )
    return frame[["symbol", "value", "period_end", "available_at"]].rename(
        columns={
            "value": concept,
            "period_end": f"{concept}_period_end",
            "available_at": f"{concept}_available_at",
        }
    )


def _max_timestamp(*values: object) -> pd.Timestamp | None:
    candidates: list[pd.Timestamp] = []
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            continue
        if pd.isna(timestamp):
            continue
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(None)
        candidates.append(timestamp)
    return max(candidates) if candidates else None


def _is_true(value: object) -> bool:
    """Accept only actual booleans; NaN must never pass a size gate."""

    return isinstance(value, (bool, np.bool_)) and bool(value)


def _historical_shares(
    companyfacts: pd.DataFrame,
    *,
    report_period: pd.Timestamp,
    available_cutoff: pd.Timestamp,
) -> pd.DataFrame:
    frame = companyfacts.loc[
        companyfacts["tag"].isin(
            {"EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"}
        )
    ].copy()
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce")
    frame["shares_outstanding"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.loc[
        frame["period_end"].le(report_period)
        & frame["available_at"].le(available_cutoff)
        & frame["shares_outstanding"].gt(0)
    ].copy()
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "shares_outstanding", "shares_available_at"])
    frame["tag_priority"] = frame["tag"].eq(
        "EntityCommonStockSharesOutstanding"
    ).astype(int)
    frame = frame.sort_values(
        ["symbol", "period_end", "available_at", "tag_priority"]
    ).drop_duplicates("symbol", keep="last")
    return frame[["symbol", "shares_outstanding", "available_at"]].rename(
        columns={"available_at": "shares_available_at"}
    )


def _latest_price_at(prices: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adj_close"] = pd.to_numeric(frame["adj_close"], errors="coerce")
    frame = frame.loc[frame["date"].le(date) & frame["adj_close"].gt(0)]
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "price_at_report", "price_date"])
    frame = frame.sort_values(["symbol", "date"]).drop_duplicates("symbol", keep="last")
    return frame[["symbol", "adj_close", "date"]].rename(
        columns={"adj_close": "price_at_report", "date": "price_date"}
    )


def _turnover_and_volatility(
    prices: pd.DataFrame,
    master: pd.DataFrame,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adj_close"] = pd.to_numeric(frame["adj_close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    completed_month = formation.to_period("M") - 1
    frame = frame.loc[frame["date"].dt.to_period("M").le(completed_month)].copy()
    frame["month"] = frame["date"].dt.to_period("M")
    monthly = frame.groupby(["symbol", "month"], as_index=False).agg(
        first_price=("adj_close", "first"),
        last_price=("adj_close", "last"),
        monthly_volume=("volume", "sum"),
        period_end=("date", "max"),
    )
    monthly["monthly_return"] = monthly["last_price"] / monthly["first_price"] - 1.0
    recent = monthly.loc[monthly["month"].eq(completed_month)].copy()
    shares = master[["symbol", "sharesOutstanding"]].copy()
    shares["sharesOutstanding"] = pd.to_numeric(shares["sharesOutstanding"], errors="coerce")
    recent = recent.merge(shares, on="symbol", how="left", validate="one_to_one")
    recent["turnover"] = recent["monthly_volume"] / recent["sharesOutstanding"]
    ordered = monthly.sort_values(["symbol", "month"])
    recent_twelve = ordered.groupby("symbol", group_keys=False).tail(12)
    volatility = recent_twelve.groupby("symbol", as_index=False).agg(
        volatility=("monthly_return", "std"),
        volatility_months=("monthly_return", "count"),
        volatility_period_end=("period_end", "max"),
    )
    volatility.loc[volatility["volatility_months"].lt(6), "volatility"] = np.nan
    recent = recent.rename(columns={"period_end": "turnover_period_end"})
    recent["turnover_available_at"] = recent["turnover_period_end"]
    volatility["volatility_available_at"] = volatility["volatility_period_end"]
    return recent[
        ["symbol", "turnover", "turnover_period_end", "turnover_available_at"]
    ].merge(
        volatility, on="symbol", how="outer"
    )


def _forecast_dispersion(
    analyst_rows: pd.DataFrame, symbols: Sequence[str], formation: pd.Timestamp
) -> pd.DataFrame:
    payloads = _latest_payloads(analyst_rows, formation)
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        payload, available_at = payloads.get((symbol, "earnings_estimate"), ([], None))
        item = _period(payload, "0y")
        if not item:
            item = _period(payload, "+1y")
        low = pd.to_numeric(pd.Series([item.get("low")]), errors="coerce").iloc[0]
        high = pd.to_numeric(pd.Series([item.get("high")]), errors="coerce").iloc[0]
        average = pd.to_numeric(pd.Series([item.get("avg")]), errors="coerce").iloc[0]
        value = (
            float(high - low) / max(abs(float(average)), 1e-9)
            if pd.notna(low) and pd.notna(high) and pd.notna(average) and high >= low
            else np.nan
        )
        rows.append(
            {
                "symbol": symbol,
                "dispersion_proxy": value,
                "dispersion_available_at": available_at,
            }
        )
    return pd.DataFrame(rows)


def _current_size_filters(master: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the current-month NYSE size filters used by OpenAP."""

    frame = master[["symbol", "exchange_sec", "marketCap"]].copy()
    frame["current_market_cap"] = pd.to_numeric(frame["marketCap"], errors="coerce")
    exchange = frame["exchange_sec"].fillna("").astype(str).str.upper()
    nyse_market_caps = frame.loc[
        exchange.eq("NYSE") & frame["current_market_cap"].gt(0),
        "current_market_cap",
    ]
    nyse_amex_market_caps = frame.loc[
        exchange.isin({"NYSE", "AMEX", "NYSE AMERICAN"})
        & frame["current_market_cap"].gt(0),
        "current_market_cap",
    ]
    del_breadth_cutoff = (
        float(nyse_market_caps.quantile(0.20)) if not nyse_market_caps.empty else np.nan
    )
    rio_cutoff = (
        float(nyse_amex_market_caps.quantile(0.20))
        if not nyse_amex_market_caps.empty
        else np.nan
    )
    frame["del_breadth_size_eligible"] = (
        frame["current_market_cap"].ge(del_breadth_cutoff)
        if np.isfinite(del_breadth_cutoff)
        else False
    )
    frame["rio_current_size_eligible"] = (
        frame["current_market_cap"].gt(rio_cutoff)
        if np.isfinite(rio_cutoff)
        else False
    )
    return frame[
        [
            "symbol",
            "current_market_cap",
            "del_breadth_size_eligible",
            "rio_current_size_eligible",
        ]
    ]


def calculate_institutional_signals(
    security_master: pd.DataFrame,
    prices: pd.DataFrame,
    companyfacts: pd.DataFrame,
    concept_inputs: pd.DataFrame,
    analyst_rows: pd.DataFrame,
    filings: pd.DataFrame,
    holdings: pd.DataFrame,
    cusip_map: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate current institutional breadth and residual-ownership signals."""

    formation = pd.Timestamp(formation_at).tz_localize(None)
    master = security_master.copy().drop_duplicates("symbol")
    symbols = master["symbol"].astype(str).tolist()
    size_filters = _current_size_filters(master)
    mapping = cusip_map.loc[
        cusip_map["mapping_status"].eq("mapped_unique")
        & cusip_map["ticker"].isin(symbols),
        ["cusip", "ticker"],
    ].drop_duplicates("cusip")
    mapped = holdings.merge(mapping, on="cusip", how="inner", validate="many_to_one")
    mapped = mapped.rename(columns={"ticker": "symbol"})
    mapped["report_period"] = pd.to_datetime(mapped["report_period"], errors="coerce")
    mapped["filing_date"] = pd.to_datetime(mapped["filing_date"], errors="coerce")
    mapped = mapped.loc[mapped["filing_date"].le(formation)].copy()
    causal_filings = filings.copy()
    causal_filings["report_period"] = pd.to_datetime(
        causal_filings["report_period"], errors="coerce"
    )
    causal_filings["filing_date"] = pd.to_datetime(
        causal_filings["filing_date"], errors="coerce"
    )
    causal_filings = causal_filings.loc[causal_filings["filing_date"].le(formation)]
    periods = sorted(causal_filings["report_period"].dropna().unique())

    breadth_values = pd.Series(np.nan, index=symbols, dtype=float)
    breadth_period: pd.Timestamp | None = None
    breadth_available: pd.Timestamp | None = None
    if len(periods) >= 2:
        previous_period = pd.Timestamp(periods[-2])
        current_period = pd.Timestamp(periods[-1])
        current_managers = set(
            causal_filings.loc[
                causal_filings["report_period"].eq(current_period), "manager_cik"
            ].astype(str)
        )
        previous_managers = set(
            causal_filings.loc[
                causal_filings["report_period"].eq(previous_period), "manager_cik"
            ].astype(str)
        )
        new_managers = current_managers - previous_managers
        old_managers = previous_managers - current_managers
        current_holders = mapped.loc[mapped["report_period"].eq(current_period)]
        previous_holders = mapped.loc[mapped["report_period"].eq(previous_period)]
        for symbol in symbols:
            owners_current = set(
                current_holders.loc[current_holders["symbol"].eq(symbol), "manager_cik"].astype(str)
            )
            owners_previous = set(
                previous_holders.loc[
                    previous_holders["symbol"].eq(symbol), "manager_cik"
                ].astype(str)
            )
            if previous_managers:
                breadth_values.loc[symbol] = 100.0 * (
                    (len(owners_current) - len(owners_current & new_managers))
                    - (len(owners_previous) - len(owners_previous & old_managers))
                ) / len(previous_managers)
        breadth_period = current_period
        current_dates = causal_filings.loc[
            causal_filings["report_period"].eq(current_period), "filing_date"
        ]
        breadth_available = pd.Timestamp(current_dates.max()) if not current_dates.empty else None

    breadth_size = size_filters.set_index("symbol")["del_breadth_size_eligible"]
    breadth_values = breadth_values.where(breadth_size.reindex(breadth_values.index).fillna(False))

    lag_cutoff = formation - pd.DateOffset(months=6)
    lag_filings = causal_filings.loc[causal_filings["filing_date"].le(lag_cutoff)]
    rio_periods = sorted(lag_filings["report_period"].dropna().unique())
    rio = pd.DataFrame({"symbol": symbols})
    rio_period: pd.Timestamp | None = None
    rio_available: pd.Timestamp | None = None
    if rio_periods:
        rio_period = pd.Timestamp(rio_periods[-1])
        chosen = mapped.loc[
            mapped["report_period"].eq(rio_period)
            & mapped["filing_date"].le(lag_cutoff)
        ]
        institutional = chosen.groupby("symbol", as_index=False).agg(
            institutional_shares=("shares_held", "sum"),
            manager_count=("manager_cik", "nunique"),
            holdings_filed_at=("filing_date", "max"),
        )
        shares = _historical_shares(
            companyfacts,
            report_period=rio_period,
            available_cutoff=lag_cutoff,
        )
        report_prices = _latest_price_at(prices, rio_period)
        rio = rio.merge(institutional, on="symbol", how="left")
        rio = rio.merge(shares, on="symbol", how="left")
        rio = rio.merge(report_prices, on="symbol", how="left")
        rio["institutional_shares"] = pd.to_numeric(
            rio["institutional_shares"], errors="coerce"
        ).fillna(0.0)
        rio["manager_count"] = pd.to_numeric(
            rio["manager_count"], errors="coerce"
        ).fillna(0)
        fraction = rio["institutional_shares"] / rio["shares_outstanding"]
        fraction = fraction.where(fraction.ge(0)).clip(0.0001, 0.9999)
        rio["mve_millions"] = (
            rio["shares_outstanding"] * rio["price_at_report"] / 1_000_000.0
        )
        log_mve = np.log(rio["mve_millions"].where(rio["mve_millions"].gt(0)))
        rio["rio_raw"] = (
            np.log(fraction / (1.0 - fraction))
            + 23.66
            - 2.89 * log_mve
            + 0.08 * log_mve.pow(2)
        )
        exchanges = master[["symbol", "exchange_sec"]].copy()
        rio = rio.merge(exchanges, on="symbol", how="left")
        reference = rio.loc[
            rio["exchange_sec"].astype(str).str.upper().isin({"NYSE", "AMEX"}),
            "mve_millions",
        ].dropna()
        if not reference.empty:
            threshold = float(reference.quantile(0.20))
            rio.loc[rio["mve_millions"].lt(threshold), "rio_raw"] = np.nan
        rio["rio_quintile"] = _quintile(rio["rio_raw"])
        selected_dates = lag_filings.loc[
            lag_filings["report_period"].eq(rio_period), "filing_date"
        ]
        source_available = (
            pd.Timestamp(selected_dates.max()) if not selected_dates.empty else None
        )
        # OpenAP deliberately lags institutional ownership by six months.  The
        # effective signal date is therefore when that lag has elapsed, not the
        # original 13F filing date.  Recording the effective date preserves
        # causality without misclassifying the intended lag as stale data.
        rio_available = (
            source_available + pd.DateOffset(months=6)
            if source_available is not None
            else None
        )

    equity = _latest_concept(concept_inputs, "equity")
    deferred_tax = _latest_concept(concept_inputs, "deferred_tax")
    preferred = _latest_concept(concept_inputs, "preferred_stock")
    characteristic_columns = ["symbol", "marketCap", "sharesOutstanding"]
    market_cap_timestamp_column = next(
        (
            column
            for column in ("retrieved_at_yahoo", "retrieved_at")
            if column in master
        ),
        None,
    )
    if market_cap_timestamp_column is not None:
        characteristic_columns.append(market_cap_timestamp_column)
    characteristics = master[characteristic_columns].copy()
    if market_cap_timestamp_column is not None:
        characteristics["market_cap_available_at"] = pd.to_datetime(
            characteristics[market_cap_timestamp_column], errors="coerce"
        )
    else:
        characteristics["market_cap_available_at"] = pd.NaT
    characteristics = characteristics.merge(equity, on="symbol", how="left")
    characteristics = characteristics.merge(deferred_tax, on="symbol", how="left")
    characteristics = characteristics.merge(preferred, on="symbol", how="left")
    characteristics["book_equity"] = (
        pd.to_numeric(characteristics["equity"], errors="coerce")
        + pd.to_numeric(characteristics["deferred_tax"], errors="coerce").fillna(0.0)
        - pd.to_numeric(characteristics["preferred_stock"], errors="coerce").fillna(0.0)
    )
    characteristics["market_to_book"] = (
        pd.to_numeric(characteristics["marketCap"], errors="coerce")
        / characteristics["book_equity"].where(characteristics["book_equity"].gt(0))
    )
    characteristics["mb_quintile"] = _quintile(characteristics["market_to_book"])
    characteristics = characteristics.merge(
        _turnover_and_volatility(prices, master, formation), on="symbol", how="left"
    )
    characteristics["turnover_quintile"] = _quintile(characteristics["turnover"])
    characteristics["volatility_quintile"] = _quintile(characteristics["volatility"])
    characteristics = characteristics.merge(
        _forecast_dispersion(analyst_rows, symbols, formation), on="symbol", how="left"
    )
    characteristics["dispersion_quintile"] = _quintile(
        characteristics["dispersion_proxy"]
    )
    characteristics = characteristics.merge(size_filters, on="symbol", how="left")
    rio = rio.merge(characteristics, on="symbol", how="left")

    rows: list[dict[str, Any]] = []
    for item in rio.itertuples(index=False):
        symbol = str(item.symbol)
        del_breadth = breadth_values.get(symbol)
        mb_period = _max_timestamp(
            rio_period,
            getattr(item, "equity_period_end", None),
            getattr(item, "deferred_tax_period_end", None),
            getattr(item, "preferred_stock_period_end", None),
        )
        mb_available = _max_timestamp(
            rio_available,
            getattr(item, "market_cap_available_at", None),
            getattr(item, "equity_available_at", None),
            getattr(item, "deferred_tax_available_at", None),
            getattr(item, "preferred_stock_available_at", None),
        )
        turnover_period = _max_timestamp(
            rio_period, getattr(item, "turnover_period_end", None)
        )
        turnover_available = _max_timestamp(
            rio_available, getattr(item, "turnover_available_at", None)
        )
        volatility_period = _max_timestamp(
            rio_period, getattr(item, "volatility_period_end", None)
        )
        volatility_available = _max_timestamp(
            rio_available, getattr(item, "volatility_available_at", None)
        )
        dispersion_available = _max_timestamp(
            rio_available, getattr(item, "dispersion_available_at", None)
        )
        rio_mb = (
            float(item.rio_quintile)
            if pd.notna(getattr(item, "rio_quintile", np.nan))
            and getattr(item, "mb_quintile", np.nan) == 5
            and _is_true(getattr(item, "rio_current_size_eligible", False))
            else np.nan
        )
        rio_turnover = (
            float(item.rio_quintile)
            if pd.notna(getattr(item, "rio_quintile", np.nan))
            and getattr(item, "turnover_quintile", np.nan) == 5
            and _is_true(getattr(item, "rio_current_size_eligible", False))
            else np.nan
        )
        rio_volatility = (
            float(item.rio_quintile)
            if pd.notna(getattr(item, "rio_quintile", np.nan))
            and getattr(item, "volatility_quintile", np.nan) == 5
            and _is_true(getattr(item, "rio_current_size_eligible", False))
            else np.nan
        )
        rio_disp = (
            float(item.rio_quintile)
            if pd.notna(getattr(item, "rio_quintile", np.nan))
            and getattr(item, "dispersion_quintile", np.nan) >= 4
            and _is_true(getattr(item, "rio_current_size_eligible", False))
            else np.nan
        )
        specifications = (
            (
                "DelBreadth",
                del_breadth,
                FidelityClass.RECONSTRUCTED,
                "openap_dbreadth_sec13f_manager_entry_exit_adjusted",
                breadth_period,
                breadth_available,
                "sec_13f|openfigi_public",
                "SEC as-filed 13F replaces the Thomson institutional panel; "
                "ambiguous amendments and CUSIPs are excluded",
            ),
            (
                "RIO_MB",
                rio_mb,
                FidelityClass.RECONSTRUCTED,
                "openap_residual_institutional_ownership_lag6_high_mb",
                mb_period,
                mb_available,
                "sec_13f|openfigi_public|sec_edgar|yahoo_public",
                "SEC 13F, SEC shares/book equity and Yahoo prices reconstruct "
                "the published residual-ownership formula",
            ),
            (
                "RIO_Turnover",
                rio_turnover,
                FidelityClass.RECONSTRUCTED,
                "openap_residual_institutional_ownership_lag6_high_turnover",
                turnover_period,
                turnover_available,
                "sec_13f|openfigi_public|sec_edgar|yahoo_public",
                "SEC 13F and current monthly Yahoo turnover replace Thomson/CRSP inputs",
            ),
            (
                "RIO_Volatility",
                rio_volatility,
                FidelityClass.RECONSTRUCTED,
                "openap_residual_institutional_ownership_lag6_high_volatility",
                volatility_period,
                volatility_available,
                "sec_13f|openfigi_public|sec_edgar|yahoo_public",
                "SEC 13F and 12-month Yahoo return volatility replace Thomson/CRSP inputs",
            ),
            (
                "RIO_Disp",
                rio_disp,
                FidelityClass.UNVALIDATED_PROXY,
                "openap_residual_institutional_ownership_lag6_high_forecast_range_proxy",
                rio_period,
                dispersion_available,
                "sec_13f|openfigi_public|sec_edgar|yahoo_public",
                "Yahoo forecast high-low range is not IBES forecast standard "
                "deviation; excluded from strict/current scores",
            ),
        )
        for (
            signal,
            value,
            fidelity,
            formula,
            period_end,
            available_at,
            sources,
            caveat,
        ) in specifications:
            finite = value is not None and np.isfinite(float(value))
            actual_fidelity = fidelity if finite else FidelityClass.UNAVAILABLE
            current_size_eligible = _is_true(
                getattr(item, "rio_current_size_eligible", False)
            )
            rio_base_available = pd.notna(
                getattr(item, "rio_quintile", np.nan)
            )
            if finite:
                missing_reason = ""
            elif signal == "DelBreadth" and not _is_true(
                breadth_size.get(symbol, False)
            ):
                missing_reason = "not_applicable:official_nyse_size_filter"
            elif (
                signal.startswith("RIO_")
                and rio_base_available
                and not current_size_eligible
            ):
                missing_reason = "not_applicable:official_nyse_amex_size_filter"
            elif (
                signal == "RIO_MB"
                and rio_base_available
                and pd.notna(getattr(item, "mb_quintile", np.nan))
                and getattr(item, "mb_quintile", np.nan) != 5
            ):
                missing_reason = "not_applicable:outside_high_mb_quintile"
            elif (
                signal == "RIO_Turnover"
                and rio_base_available
                and pd.notna(getattr(item, "turnover_quintile", np.nan))
                and getattr(item, "turnover_quintile", np.nan) != 5
            ):
                missing_reason = "not_applicable:outside_high_turnover_quintile"
            elif (
                signal == "RIO_Volatility"
                and rio_base_available
                and pd.notna(getattr(item, "volatility_quintile", np.nan))
                and getattr(item, "volatility_quintile", np.nan) != 5
            ):
                missing_reason = "not_applicable:outside_high_volatility_quintile"
            elif (
                signal == "RIO_Disp"
                and rio_base_available
                and pd.notna(getattr(item, "dispersion_quintile", np.nan))
                and getattr(item, "dispersion_quintile", np.nan) < 4
            ):
                missing_reason = "not_applicable:outside_high_dispersion_quintiles"
            else:
                missing_reason = "institutional_inputs_missing"
            rows.append(
                {
                    "symbol": symbol,
                    "formation_at": formation,
                    "period_end": period_end,
                    "available_at": available_at,
                    "staleness_days": (
                        int((formation.normalize() - pd.Timestamp(available_at).normalize()).days)
                        if available_at is not None and not pd.isna(available_at)
                        else np.nan
                    ),
                    "signal": signal,
                    "value": float(value) if finite else None,
                    "fidelity_class": actual_fidelity.value,
                    "current_usable": bool(
                        finite
                        and actual_fidelity
                        in {
                            FidelityClass.EXACT,
                            FidelityClass.RECONSTRUCTED,
                            FidelityClass.VALIDATED_PROXY,
                        }
                    ),
                    "formula_id": formula,
                    "source_ids": sources,
                    "observation_count": int(
                        getattr(item, "manager_count", 0)
                        if pd.notna(getattr(item, "manager_count", np.nan))
                        else 0
                    ),
                    "reason_if_missing": missing_reason,
                    "caveat": caveat,
                }
            )
    return pd.DataFrame(rows)


def implemented_source_pairs() -> frozenset[tuple[str, str]]:
    requirements = {
        "DelBreadth": {"sec_13f", "openfigi_public"},
        "RIO_Disp": {"sec_13f", "openfigi_public", "sec_edgar", "yahoo_public"},
        "RIO_MB": {"sec_13f", "openfigi_public", "sec_edgar", "yahoo_public"},
        "RIO_Turnover": {"sec_13f", "openfigi_public", "sec_edgar", "yahoo_public"},
        "RIO_Volatility": {"sec_13f", "openfigi_public", "sec_edgar", "yahoo_public"},
    }
    return frozenset(
        (signal, source)
        for signal, sources in requirements.items()
        for source in sources
    )


__all__ = [
    "INSTITUTIONAL_IMPLEMENTED_SIGNALS",
    "OPENFIGI_MAPPING_URL",
    "calculate_institutional_signals",
    "implemented_source_pairs",
    "map_cusips_openfigi",
    "parse_13f_archives",
]
