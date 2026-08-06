"""Causal earnings-event normalization shared by current OpenAP proxies."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import numpy as np
import pandas as pd


EARNINGS_EVENT_COLUMNS = (
    "symbol",
    "period_end",
    "event_at",
    "reported_eps",
    "consensus_eps",
    "prior_close",
    "source_id",
    "source_priority",
    "source_ref",
    "retrieved_at",
)

SOURCE_PRIORITY = {
    "sec_8k_item_202": 0,
    "yahoo_earnings_actual": 1,
    "periodic_filing_date": 2,
}


@dataclass(frozen=True)
class AnnouncementReturnResult:
    value: float | None
    sessions: int
    window_start: pd.Timestamp | None
    window_end: pd.Timestamp | None
    event_session: pd.Timestamp | None


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=list(EARNINGS_EVENT_COLUMNS))


def _finite(value: Any) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) and np.isfinite(float(numeric)) else None


def _timestamp(value: Any) -> pd.Timestamp | pd.NaT:
    result = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(result):
        return pd.NaT
    return pd.Timestamp(result)


def _period_end_from_event(event_at: pd.Timestamp) -> pd.Timestamp:
    naive = event_at.tz_convert(None) if event_at.tzinfo is not None else event_at
    return (naive.to_period("Q") - 1).end_time.normalize()


def _event_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return _empty_events()
    frame = pd.DataFrame(rows)
    for column in EARNINGS_EVENT_COLUMNS:
        if column not in frame:
            frame[column] = None
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    frame["event_at"] = pd.to_datetime(frame["event_at"], errors="coerce", utc=True)
    frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], errors="coerce", utc=True)
    for column in ("reported_eps", "consensus_eps", "prior_close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["source_priority"] = pd.to_numeric(
        frame["source_priority"], errors="coerce"
    ).astype("Int64")
    return frame[list(EARNINGS_EVENT_COLUMNS)]


def normalize_sec_item_202_events(
    submissions: pd.DataFrame,
    security_master: pd.DataFrame,
) -> pd.DataFrame:
    if submissions.empty or "items" not in submissions:
        return _empty_events()
    master = security_master[["symbol", "cik"]].drop_duplicates("cik").copy()
    master["cik"] = pd.to_numeric(master["cik"], errors="coerce")
    frame = submissions.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["form"] = frame["form"].astype(str)
    item_202 = frame["items"].astype("string").fillna("").str.contains(
        r"(?:^|[,;\s])2\.02(?:$|[,;\s])", regex=True
    )
    frame = frame.loc[frame["form"].str.startswith("8-K") & item_202].merge(
        master, on="cik", how="inner", validate="many_to_one"
    )
    rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        event_at = _timestamp(getattr(row, "accepted_at", None))
        if pd.isna(event_at):
            continue
        period_end = pd.to_datetime(getattr(row, "report_date", None), errors="coerce")
        if pd.isna(period_end):
            period_end = _period_end_from_event(event_at)
        rows.append(
            {
                "symbol": str(row.symbol),
                "period_end": period_end,
                "event_at": event_at,
                "reported_eps": None,
                "consensus_eps": None,
                "prior_close": None,
                "source_id": "sec_8k_item_202",
                "source_priority": SOURCE_PRIORITY["sec_8k_item_202"],
                "source_ref": str(getattr(row, "accession_number", "")),
                "retrieved_at": event_at,
            }
        )
    return _event_frame(rows)


def normalize_periodic_filing_events(
    submissions: pd.DataFrame,
    security_master: pd.DataFrame,
) -> pd.DataFrame:
    if submissions.empty:
        return _empty_events()
    master = security_master[["symbol", "cik"]].drop_duplicates("cik").copy()
    master["cik"] = pd.to_numeric(master["cik"], errors="coerce")
    frame = submissions.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame = frame.loc[frame["form"].astype(str).isin(["10-Q", "10-K"])].merge(
        master, on="cik", how="inner", validate="many_to_one"
    )
    rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        event_at = _timestamp(getattr(row, "accepted_at", None))
        if pd.isna(event_at):
            continue
        rows.append(
            {
                "symbol": str(row.symbol),
                "period_end": pd.to_datetime(
                    getattr(row, "report_date", None), errors="coerce"
                ),
                "event_at": event_at,
                "reported_eps": None,
                "consensus_eps": None,
                "prior_close": None,
                "source_id": "periodic_filing_date",
                "source_priority": SOURCE_PRIORITY["periodic_filing_date"],
                "source_ref": str(getattr(row, "accession_number", "")),
                "retrieved_at": event_at,
            }
        )
    return _event_frame(rows)


def _payload_records(value: Any) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [dict(item) for item in decoded if isinstance(item, dict)]


def _first(record: dict[str, Any], names: tuple[str, ...]) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in record.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def normalize_yahoo_earnings_events(analyst_rows: pd.DataFrame) -> pd.DataFrame:
    if analyst_rows.empty:
        return _empty_events()
    frame = analyst_rows.loc[analyst_rows["dataset"].eq("earnings_dates")].copy()
    rows: list[dict[str, Any]] = []
    for snapshot in frame.itertuples(index=False):
        retrieved_at = _timestamp(getattr(snapshot, "retrieved_at", None))
        for record in _payload_records(snapshot.payload_json):
            event_at = _timestamp(
                _first(record, ("Earnings Date", "earningsDate", "date", "index"))
            )
            reported = _finite(
                _first(record, ("Reported EPS", "reportedEPS", "epsActual"))
            )
            consensus = _finite(
                _first(record, ("EPS Estimate", "epsEstimate", "epsDifference"))
            )
            if pd.isna(event_at) or reported is None or consensus is None:
                continue
            rows.append(
                {
                    "symbol": str(snapshot.symbol),
                    "period_end": _period_end_from_event(event_at),
                    "event_at": event_at,
                    "reported_eps": reported,
                    "consensus_eps": consensus,
                    "prior_close": None,
                    "source_id": "yahoo_earnings_actual",
                    "source_priority": SOURCE_PRIORITY["yahoo_earnings_actual"],
                    "source_ref": "yfinance:get_earnings_dates",
                    "retrieved_at": retrieved_at,
                }
            )
    return _event_frame(rows)


def choose_earnings_event(events: pd.DataFrame) -> pd.Series:
    if events.empty:
        raise ValueError("no earnings events supplied")
    frame = events.copy()
    frame["event_at"] = pd.to_datetime(frame["event_at"], errors="coerce", utc=True)
    frame["source_priority"] = frame["source_id"].map(SOURCE_PRIORITY).fillna(99)
    frame = frame.dropna(subset=["event_at"]).sort_values(
        ["source_priority", "event_at"], ascending=[True, True]
    )
    if frame.empty:
        raise ValueError("no dated earnings event supplied")
    return frame.iloc[0]


def _event_session(dates: pd.Series, event_at: Any) -> pd.Timestamp | None:
    event = _timestamp(event_at)
    if pd.isna(event):
        return None
    event_ny = event.tz_convert("America/New_York")
    date = event_ny.tz_localize(None).normalize()
    valid = pd.to_datetime(dates, errors="coerce").dropna().sort_values().drop_duplicates()
    valid = valid.loc[valid.gt(date) if event_ny.hour >= 16 else valid.ge(date)]
    return pd.Timestamp(valid.iloc[0]) if len(valid) else None


def announcement_return(
    prices: pd.DataFrame,
    ff3_daily: pd.DataFrame,
    *,
    event_at: Any,
) -> AnnouncementReturnResult:
    if prices.empty or ff3_daily.empty:
        return AnnouncementReturnResult(None, 0, None, None, None)
    stock = prices.copy()
    stock["date"] = pd.to_datetime(stock["date"], errors="coerce")
    if "stock_return" in stock:
        stock["stock_return"] = pd.to_numeric(stock["stock_return"], errors="coerce")
    else:
        price_column = "adj_close" if "adj_close" in stock else "close"
        stock["stock_return"] = pd.to_numeric(stock[price_column], errors="coerce").pct_change()
    factors = ff3_daily.copy()
    factors["date"] = pd.to_datetime(factors["date"], errors="coerce")
    for column in ("mktrf", "rf"):
        factors[column] = pd.to_numeric(factors[column], errors="coerce")
    merged = stock[["date", "stock_return"]].merge(
        factors[["date", "mktrf", "rf"]], on="date", how="inner", validate="one_to_one"
    ).dropna()
    merged = merged.sort_values("date").reset_index(drop=True)
    event_session = _event_session(merged["date"], event_at)
    if event_session is None:
        return AnnouncementReturnResult(None, 0, None, None, None)
    indexes = merged.index[merged["date"].eq(event_session)].tolist()
    if not indexes:
        return AnnouncementReturnResult(None, 0, None, None, event_session)
    event_index = indexes[0]
    if event_index < 2 or event_index + 1 >= len(merged):
        return AnnouncementReturnResult(None, 0, None, None, event_session)
    window = merged.iloc[event_index - 2 : event_index + 2]
    abnormal = window["stock_return"] - window["mktrf"] - window["rf"]
    return AnnouncementReturnResult(
        value=float(abnormal.sum()),
        sessions=int(len(window)),
        window_start=pd.Timestamp(window["date"].iloc[0]),
        window_end=pd.Timestamp(window["date"].iloc[-1]),
        event_session=event_session,
    )


def earnings_streak_value(
    events: pd.DataFrame,
    *,
    formation_at: Any,
) -> float | None:
    if events.empty:
        return None
    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is None:
        formation = formation.tz_localize("UTC")
    else:
        formation = formation.tz_convert("UTC")
    frame = events.copy()
    frame["event_at"] = pd.to_datetime(frame["event_at"], errors="coerce", utc=True)
    for column in ("reported_eps", "consensus_eps", "prior_close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.loc[
        frame["event_at"].le(formation)
        & frame["reported_eps"].notna()
        & frame["consensus_eps"].notna()
        & frame["prior_close"].gt(0)
    ].sort_values("event_at")
    if len(frame) < 2:
        return None
    latest = frame.iloc[-1]
    if latest["event_at"] < formation - pd.DateOffset(months=6):
        return None
    latest_two = frame.tail(2).copy()
    latest_two["scaled_surprise"] = (
        latest_two["reported_eps"] - latest_two["consensus_eps"]
    ) / latest_two["prior_close"]
    values = latest_two["scaled_surprise"].to_numpy(dtype=float)
    if np.any(values == 0.0) or np.sign(values[0]) != np.sign(values[1]):
        return None
    return float(values[-1])


def attach_prior_closes(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    result = events.copy()
    if "prior_close" not in result:
        result["prior_close"] = np.nan
    result["event_at"] = pd.to_datetime(result["event_at"], errors="coerce", utc=True)
    price_frame = prices.copy()
    price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce")
    price_column = "close" if "close" in price_frame else "adj_close"
    price_frame[price_column] = pd.to_numeric(price_frame[price_column], errors="coerce")
    for index, event in result.loc[result["prior_close"].isna()].iterrows():
        event_date = pd.Timestamp(event["event_at"]).tz_convert(None).normalize()
        history = price_frame.loc[
            price_frame["symbol"].eq(event["symbol"])
            & price_frame["date"].lt(event_date)
            & price_frame[price_column].notna()
        ].sort_values("date")
        if not history.empty:
            result.at[index, "prior_close"] = float(history[price_column].iloc[-1])
    return result


def build_earnings_events(
    security_master: pd.DataFrame,
    submissions: pd.DataFrame,
    analyst_rows: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    frames = [
        normalize_sec_item_202_events(submissions, security_master),
        normalize_yahoo_earnings_events(analyst_rows),
        normalize_periodic_filing_events(submissions, security_master),
    ]
    populated = [frame for frame in frames if not frame.empty]
    if not populated:
        return _empty_events()
    return attach_prior_closes(pd.concat(populated, ignore_index=True), prices)
