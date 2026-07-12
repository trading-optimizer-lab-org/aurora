"""Clean prices and evaluate GTBI signals in a real capital-constrained portfolio."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd


PRICE_COLUMNS = ("open", "high", "low", "close", "adj_close", "volume")
KNOWN_SPLIT_RATIOS = np.asarray(
    (1.1, 1.2, 1.25, 4.0 / 3.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0, 20.0, 50.0, 100.0),
    dtype=float,
)
MAX_TERMINAL_MARK_DAYS = 7


class UnresolvedPositionError(ValueError):
    """Raised when a position has no honest executable exit price."""


@dataclass(frozen=True)
class DataQualityPolicy:
    max_adjusted_gap_ratio: float = 3.0
    min_segment_rows: int = 260
    min_split_adjustment_ratio: float = 1.1
    max_calendar_gap_days: int = 14

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_adjusted_gap_ratio) or self.max_adjusted_gap_ratio <= 1.0:
            raise ValueError("max_adjusted_gap_ratio must be greater than 1")
        if self.min_segment_rows < 2:
            raise ValueError("min_segment_rows must be at least 2")
        if not math.isfinite(self.min_split_adjustment_ratio) or self.min_split_adjustment_ratio <= 1.0:
            raise ValueError("min_split_adjustment_ratio must be greater than 1")
        if self.max_calendar_gap_days < 1:
            raise ValueError("max_calendar_gap_days must be positive")


@dataclass(frozen=True)
class SanitizedSymbol:
    segments: dict[str, pd.DataFrame]
    diagnostics: dict[str, Any]
    anomalies: pd.DataFrame


@dataclass(frozen=True)
class PortfolioConfig:
    initial_capital: float = 100_000.0
    position_size_pct: float = 0.01
    max_positions: int = 20
    max_gross_exposure: float = 1.0
    transaction_cost_bps_per_side: float = 0.0
    slippage_bps_per_side: float = 0.0
    allow_fractional_shares: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.initial_capital) or self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not math.isfinite(self.position_size_pct) or not 0 < self.position_size_pct <= 1:
            raise ValueError("position_size_pct must be in (0, 1]")
        if self.max_positions < 1:
            raise ValueError("max_positions must be positive")
        if not math.isfinite(self.max_gross_exposure) or not 0 < self.max_gross_exposure <= 1:
            raise ValueError("max_gross_exposure must be in (0, 1]")
        if self.transaction_cost_bps_per_side < 0 or self.slippage_bps_per_side < 0:
            raise ValueError("costs cannot be negative")


@dataclass(frozen=True)
class PortfolioResult:
    daily_equity: pd.DataFrame
    annual_returns: pd.DataFrame
    ledger: pd.DataFrame
    skipped_entries: pd.DataFrame
    summary: dict[str, Any]


@dataclass(frozen=True)
class PreparedSignalPortfolioData:
    frames: dict[str, pd.DataFrame]
    signal_maps: dict[str, pd.Series]
    market_maps: dict[str, pd.Series]
    next_dates: dict[str, dict[pd.Timestamp, pd.Timestamp]]
    exit_mas: dict[str, pd.Series]
    signal_events: dict[pd.Timestamp, tuple[dict[str, Any], ...]]
    calendar: tuple[pd.Timestamp, ...]
    start: pd.Timestamp
    end: pd.Timestamp
    indicator_config: Any


def _normalise_dates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "date" in out.columns:
        dates = pd.to_datetime(out["date"], errors="coerce", utc=True)
    elif isinstance(out.index, pd.DatetimeIndex):
        dates = pd.to_datetime(out.index, errors="coerce", utc=True)
    else:
        raise ValueError("price frame needs a date column or DatetimeIndex")
    out["date"] = (
        dates.dt.tz_convert(None).dt.normalize()
        if isinstance(dates, pd.Series)
        else dates.tz_convert(None).normalize()
    )
    out = out.reset_index(drop=True)
    return out.dropna(subset=["date"]).sort_values("date", kind="mergesort")


def _prepared_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = _normalise_dates(frame)
    for column in PRICE_COLUMNS:
        if column not in out.columns:
            if column == "adj_close" and "close" in out.columns:
                out[column] = out["close"]
            elif column == "volume":
                out[column] = 0.0
            else:
                raise ValueError(f"missing price column: {column}")
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def sanitize_symbol_prices(
    frame: pd.DataFrame,
    *,
    symbol: str,
    locked_start: str | None,
    policy: DataQualityPolicy | None = None,
) -> SanitizedSymbol:
    """Adjust every OHLC field and split remaining unexplained discontinuities."""

    policy = policy or DataQualityPolicy()
    source = _prepared_price_frame(frame)
    original_rows = len(source)
    locked_mask = (
        source["date"] >= pd.Timestamp(locked_start)
        if locked_start is not None
        else pd.Series(False, index=source.index)
    )
    locked_rows_removed = int(locked_mask.sum())
    source = source.loc[~locked_mask].copy()
    duplicate_dates_removed = int(source.duplicated("date", keep="last").sum())
    source = source.drop_duplicates("date", keep="last").reset_index(drop=True)

    finite = np.isfinite(source.loc[:, PRICE_COLUMNS].to_numpy(dtype=float)).all(axis=1)
    positive = (source[["open", "high", "low", "close", "adj_close"]] > 0).all(axis=1)
    ohlc_valid = (source["high"] >= source[["open", "close", "low"]].max(axis=1)) & (
        source["low"] <= source[["open", "close", "high"]].min(axis=1)
    )
    valid = pd.Series(finite, index=source.index) & positive & ohlc_valid & (source["volume"] >= 0)
    invalid_bars_removed = int((~valid).sum())
    source = source.loc[valid].copy().reset_index(drop=True)

    if source.empty:
        diagnostics = {
            "symbol": symbol,
            "original_rows": int(original_rows),
            "usable_rows": 0,
            "adjusted_rows": 0,
            "locked_rows_removed": locked_rows_removed,
            "duplicate_dates_removed": duplicate_dates_removed,
            "invalid_bars_removed": invalid_bars_removed,
            "intraday_anomalies_removed": 0,
            "calendar_breaks": 0,
            "hard_breaks": 0,
            "segments_kept": 0,
            "rows_below_min_segment_removed": 0,
            "excluded": True,
        }
        return SanitizedSymbol({}, diagnostics, pd.DataFrame())

    factor = source["adj_close"] / source["close"]
    factor_valid = np.isfinite(factor) & (factor > 0)
    invalid_factor_rows = int((~factor_valid).sum())
    source = source.loc[factor_valid].copy().reset_index(drop=True)
    factor = factor.loc[factor_valid].reset_index(drop=True)
    adjusted_rows = int((~np.isclose(factor, 1.0, rtol=1e-10, atol=1e-12)).sum())
    for column in ("open", "high", "low", "close"):
        source[column] = source[column].to_numpy(dtype=float) * factor.to_numpy(dtype=float)
    factor_values = factor.to_numpy(dtype=float)
    split_changes = np.ones(len(source), dtype=float)
    if len(source) > 1:
        factor_changes = factor_values[1:] / factor_values[:-1]
        magnitudes = np.maximum(factor_changes, 1.0 / factor_changes)
        resembles_known_split = np.isclose(
            magnitudes[:, None],
            KNOWN_SPLIT_RATIOS[None, :],
            rtol=0.005,
            atol=0.005,
        ).any(axis=1)
        detected = resembles_known_split & (magnitudes >= policy.min_split_adjustment_ratio)
        split_changes[1:] = np.where(detected, factor_changes, 1.0)
    reverse_products = np.cumprod(split_changes[::-1])[::-1]
    volume_adjustment = reverse_products / split_changes
    source["volume"] = source["volume"].to_numpy(dtype=float) * volume_adjustment
    source["adj_close"] = source["close"]

    previous_close = source["close"].shift(1)
    open_ratio = source["open"] / previous_close
    close_ratio = source["close"] / previous_close
    high_ratio = source["high"] / previous_close
    low_ratio = source["low"] / previous_close
    threshold = float(policy.max_adjusted_gap_ratio)
    open_and_close_normal = (
        open_ratio.between(1 / threshold, threshold, inclusive="both")
        & close_ratio.between(1 / threshold, threshold, inclusive="both")
    )
    intraday_bad = (
        open_and_close_normal
        & ((high_ratio > threshold) | (low_ratio < 1 / threshold))
    ).fillna(False)
    anomaly_rows: list[dict[str, Any]] = [
        {
            "symbol": symbol,
            "date": pd.Timestamp(source.loc[index, "date"]).date().isoformat(),
            "reason": "corrupt_intraday_range",
            "adjusted_open_to_previous_close_ratio": float(open_ratio.iloc[index]),
            "adjusted_close_to_previous_close_ratio": float(close_ratio.iloc[index]),
            "adjusted_high_to_previous_close_ratio": float(high_ratio.iloc[index]),
            "adjusted_low_to_previous_close_ratio": float(low_ratio.iloc[index]),
        }
        for index in np.flatnonzero(intraday_bad.to_numpy(dtype=bool))
    ]
    intraday_anomalies_removed = int(intraday_bad.sum())
    source = source.loc[~intraday_bad].copy().reset_index(drop=True)

    previous_close = source["close"].shift(1)
    open_ratio = source["open"] / previous_close
    close_ratio = source["close"] / previous_close
    price_break = (
        (open_ratio > threshold)
        | (open_ratio < 1 / threshold)
        | (close_ratio > threshold)
        | (close_ratio < 1 / threshold)
    ).fillna(False)
    calendar_gap_days = source["date"].diff().dt.days
    calendar_break = calendar_gap_days.gt(policy.max_calendar_gap_days).fillna(False)
    hard_break = price_break | calendar_break
    anomaly_rows.extend(
        [
            {
                "symbol": symbol,
                "date": pd.Timestamp(source.loc[index, "date"]).date().isoformat(),
                "reason": "unexplained_adjusted_price_jump",
                "adjusted_open_to_previous_close_ratio": float(open_ratio.iloc[index]),
                "adjusted_close_to_previous_close_ratio": float(close_ratio.iloc[index]),
            }
            for index in np.flatnonzero(price_break.to_numpy(dtype=bool))
        ]
    )
    anomaly_rows.extend(
        [
            {
                "symbol": symbol,
                "date": pd.Timestamp(source.loc[index, "date"]).date().isoformat(),
                "reason": "missing_price_history_gap",
                "calendar_gap_days": int(calendar_gap_days.iloc[index]),
            }
            for index in np.flatnonzero(calendar_break.to_numpy(dtype=bool))
        ]
    )
    anomalies = pd.DataFrame(anomaly_rows)

    segments: dict[str, pd.DataFrame] = {}
    rows_below_min = 0
    for segment_number, group in source.groupby(hard_break.astype(int).cumsum(), sort=True):
        if len(group) < policy.min_segment_rows:
            rows_below_min += len(group)
            continue
        cleaned = group.copy().set_index("date", drop=False)
        cleaned.index = pd.DatetimeIndex(cleaned.index).tz_localize(None)
        key = f"{symbol}::segment_{int(segment_number):03d}"
        cleaned["original_symbol"] = symbol
        cleaned["data_segment"] = int(segment_number)
        cleaned["symbol"] = key
        segments[key] = cleaned

    diagnostics = {
        "symbol": symbol,
        "original_rows": int(original_rows),
        "usable_rows": int(sum(len(segment) for segment in segments.values())),
        "adjusted_rows": adjusted_rows,
        "locked_rows_removed": locked_rows_removed,
        "duplicate_dates_removed": duplicate_dates_removed,
        "invalid_bars_removed": invalid_bars_removed + invalid_factor_rows,
        "intraday_anomalies_removed": intraday_anomalies_removed,
        "calendar_breaks": int(calendar_break.sum()),
        "hard_breaks": int(hard_break.sum()),
        "segments_kept": len(segments),
        "rows_below_min_segment_removed": int(rows_below_min),
        "excluded": not bool(segments),
    }
    return SanitizedSymbol(segments, diagnostics, anomalies)


def _market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if (
        isinstance(frame.index, pd.DatetimeIndex)
        and frame.index.tz is None
        and frame.index.equals(frame.index.normalize())
        and frame.index.is_monotonic_increasing
        and frame.index.is_unique
        and "date" in frame.columns
        and all(column in frame.columns for column in PRICE_COLUMNS)
        and pd.DatetimeIndex(pd.to_datetime(frame["date"], errors="coerce")).equals(frame.index)
    ):
        return frame
    out = _prepared_price_frame(frame).drop_duplicates("date", keep="last").set_index("date", drop=False)
    out.index = pd.DatetimeIndex(out.index).tz_localize(None)
    return out.sort_index()


def _close_series(frame: pd.DataFrame) -> pd.Series:
    out = _market_frame(frame)
    return pd.to_numeric(out["close"], errors="coerce").sort_index()


def _normalise_series_index(series: pd.Series) -> pd.Series:
    if series.empty:
        return series.copy()
    out = series.copy()
    index = pd.to_datetime(out.index, errors="coerce", utc=True)
    valid = ~pd.isna(index)
    out = out.loc[valid]
    normalized = pd.DatetimeIndex(index[valid]).tz_convert(None).normalize()
    out.index = normalized
    if out.index.has_duplicates:
        out = out.groupby(level=0, sort=True).last()
    return out.sort_index()


def entry_priority_at_signal(
    prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    *,
    entry_date: str | pd.Timestamp,
    lookback: int = 63,
) -> float:
    if lookback < 1:
        raise ValueError("lookback must be positive")
    boundary = pd.Timestamp(entry_date)
    stock = _close_series(prices).loc[lambda value: value.index < boundary]
    benchmark = _close_series(benchmark_prices).loc[lambda value: value.index < boundary]
    if len(stock) <= lookback or len(benchmark) <= lookback:
        return float("-inf")
    return float(stock.iloc[-1] / stock.iloc[-1 - lookback] - benchmark.iloc[-1] / benchmark.iloc[-1 - lookback])


def _annual_returns(daily: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    columns = ["year", "start_equity", "end_equity", "equity_return_pct", "positive_year"]
    if daily.empty:
        return pd.DataFrame(columns=columns)
    previous_end = float(initial_capital)
    rows: list[dict[str, Any]] = []
    for year, group in daily.groupby(daily["date"].dt.year, sort=True):
        end_equity = float(group.iloc[-1]["equity"])
        value = (end_equity / previous_end - 1) * 100
        rows.append(
            {
                "year": int(year),
                "start_equity": previous_end,
                "end_equity": end_equity,
                "equity_return_pct": value,
                "positive_year": bool(value > 0),
            }
        )
        previous_end = end_equity
    return pd.DataFrame(rows, columns=columns)


def _result(
    *,
    daily_rows: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
    skipped_rows: list[dict[str, Any]],
    config: PortfolioConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> PortfolioResult:
    daily = pd.DataFrame(daily_rows)
    annual = _annual_returns(daily, config.initial_capital)
    ending = float(daily.iloc[-1]["equity"]) if not daily.empty else config.initial_capital
    years = max((end - start).days / 365.25, 1 / 365.25)
    cagr = ((ending / config.initial_capital) ** (1 / years) - 1) * 100 if ending > 0 else -100.0
    summary = {
        "initial_capital": config.initial_capital,
        "ending_equity": ending,
        "total_return_pct": (ending / config.initial_capital - 1) * 100,
        "cagr_pct": cagr,
        "max_drawdown_pct": float(daily["drawdown_pct"].min()) if not daily.empty else 0.0,
        "worst_year_pct": float(annual["equity_return_pct"].min()) if not annual.empty else 0.0,
        "positive_years": int(annual["positive_year"].sum()) if not annual.empty else 0,
        "years": len(annual),
        "trades_accepted": len(ledger_rows),
        "entries_skipped": len(skipped_rows),
        "max_open_positions": int(daily["open_positions"].max()) if not daily.empty else 0,
        "max_gross_exposure": float(daily["gross_exposure"].max()) if not daily.empty else 0.0,
        "position_size_pct": config.position_size_pct,
        "max_positions": config.max_positions,
        "transaction_cost_bps_per_side": config.transaction_cost_bps_per_side,
        "slippage_bps_per_side": config.slippage_bps_per_side,
    }
    return PortfolioResult(daily, annual, pd.DataFrame(ledger_rows), pd.DataFrame(skipped_rows), summary)


def _fill_size(
    *,
    cash: float,
    market_value: float,
    equity: float,
    price: float,
    config: PortfolioConfig,
) -> tuple[float, float, float]:
    commission = config.transaction_cost_bps_per_side / 10_000
    target = min(
        config.position_size_pct * equity,
        max(config.max_gross_exposure * equity - market_value, 0.0),
        cash / (1 + commission),
    )
    if target <= max(equity, 1.0) * 1e-12:
        return 0.0, 0.0, 0.0
    shares = target / price
    if not config.allow_fractional_shares:
        shares = math.floor(shares)
    notional = shares * price
    fee = notional * commission
    return float(shares), float(notional), float(fee)


def simulate_portfolio(
    trades: pd.DataFrame,
    price_frames: Mapping[str, pd.DataFrame],
    *,
    start: str,
    end: str,
    config: PortfolioConfig,
) -> PortfolioResult:
    """Compatibility helper for a pre-existing trade ledger."""

    start_date, end_date = pd.Timestamp(start), pd.Timestamp(end)
    required = {"symbol", "entry_date", "exit_date", "entry_price", "exit_price"}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"trades missing columns: {', '.join(sorted(missing))}")
    frames = {str(symbol): _market_frame(frame) for symbol, frame in price_frames.items()}
    candidates = trades.copy()
    candidates["entry_date"] = pd.to_datetime(candidates["entry_date"], errors="coerce").dt.normalize()
    candidates["exit_date"] = pd.to_datetime(candidates["exit_date"], errors="coerce").dt.normalize()
    candidates["entry_priority"] = pd.to_numeric(candidates.get("entry_priority", 0), errors="coerce").fillna(float("-inf"))
    candidates["original_symbol"] = candidates.get("original_symbol", candidates["symbol"])
    candidates = candidates[
        (candidates["entry_date"] >= start_date)
        & (candidates["exit_date"] <= end_date)
        & (candidates["entry_date"] <= candidates["exit_date"])
    ].copy()
    candidates["_id"] = range(len(candidates))
    entries = {
        date: group.sort_values(["entry_priority", "original_symbol"], ascending=[False, True], kind="mergesort")
        for date, group in candidates.groupby("entry_date")
    }
    calendar = set(pd.date_range(start_date, end_date, freq="D"))
    calendar.update(candidates["entry_date"])
    calendar.update(candidates["exit_date"])
    cash = config.initial_capital
    active: dict[int, dict[str, Any]] = {}
    marks: dict[str, float] = {}
    daily_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    peak = config.initial_capital
    commission = config.transaction_cost_bps_per_side / 10_000

    def market_value(date: pd.Timestamp) -> float:
        total = 0.0
        for position in active.values():
            symbol = position["symbol"]
            frame = frames.get(symbol)
            if frame is not None and date in frame.index and math.isfinite(float(frame.at[date, "close"])):
                marks[symbol] = float(frame.at[date, "close"])
            total += position["shares"] * marks.get(symbol, position["entry_price"])
        return total

    for date in sorted(calendar):
        market_value(date)
        for trade_id in sorted([key for key, value in active.items() if value["exit_date"] <= date]):
            position = active.pop(trade_id)
            proceeds = position["shares"] * position["exit_price"]
            exit_fee = proceeds * commission
            cash += proceeds - exit_fee
            pnl = proceeds - exit_fee - position["notional"] - position["entry_fee"]
            ledger_rows.append({**position["trade"], "net_pnl": pnl, "allocated_capital": position["notional"]})
        for _, trade in entries.get(date, pd.DataFrame()).iterrows():
            symbol = str(trade["symbol"])
            if len(active) >= config.max_positions:
                skipped_rows.append({"symbol": symbol, "entry_date": date, "reason": "max_positions"})
                continue
            current_value = market_value(date)
            equity = cash + current_value
            price = float(trade["entry_price"])
            shares, notional, fee = _fill_size(cash=cash, market_value=current_value, equity=equity, price=price, config=config)
            if shares <= 0:
                skipped_rows.append({"symbol": symbol, "entry_date": date, "reason": "insufficient_cash"})
                continue
            cash -= notional + fee
            marks[symbol] = float(frames.get(symbol, pd.DataFrame()).at[date, "close"]) if symbol in frames and date in frames[symbol].index else price
            active[int(trade["_id"])] = {
                "symbol": symbol,
                "shares": shares,
                "notional": notional,
                "entry_fee": fee,
                "entry_price": price,
                "exit_price": float(trade["exit_price"]),
                "exit_date": pd.Timestamp(trade["exit_date"]),
                "trade": {key: value for key, value in trade.items() if not str(key).startswith("_")},
            }
        value = market_value(date)
        equity = cash + value
        peak = max(peak, equity)
        daily_rows.append(
            {
                "date": date,
                "cash": cash,
                "market_value": value,
                "equity": equity,
                "gross_exposure": value / equity if equity > 0 else 0,
                "open_positions": len(active),
                "drawdown_pct": (equity / peak - 1) * 100,
            }
        )
    return _result(daily_rows=daily_rows, ledger_rows=ledger_rows, skipped_rows=skipped_rows, config=config, start=start_date, end=end_date)


def prepare_signal_portfolio_data(
    signals_by_symbol: Mapping[str, pd.Series],
    price_frames: Mapping[str, pd.DataFrame],
    *,
    market_exit_signals: Mapping[str, pd.Series],
    priority_scores: Mapping[str, pd.Series] | None = None,
    start: str,
    end: str,
    indicator_config: Any,
) -> PreparedSignalPortfolioData:
    """Compile immutable market and signal state once for a position-size sweep."""

    start_date, end_date = pd.Timestamp(start), pd.Timestamp(end)
    frames = {str(symbol): _market_frame(frame) for symbol, frame in price_frames.items()}
    calendar = sorted(
        {
            date
            for frame in frames.values()
            for date in frame.index
            if start_date <= date <= end_date
        }
        | {start_date, end_date}
    )
    signal_maps = {
        symbol: _normalise_series_index(signal).reindex(frame.index).fillna(False).astype(bool)
        for symbol, frame in frames.items()
        for signal in [signals_by_symbol.get(symbol, pd.Series(False, index=frame.index))]
    }
    market_maps = {
        symbol: _normalise_series_index(signal).reindex(frame.index).fillna(False).astype(bool)
        for symbol, frame in frames.items()
        for signal in [market_exit_signals.get(symbol, pd.Series(False, index=frame.index))]
    }
    confirmation_days = max(int(getattr(indicator_config, "market_exit_confirmation_days", 1)), 1)
    if confirmation_days > 1:
        market_maps = {
            symbol: signal.astype(int)
            .rolling(confirmation_days, min_periods=confirmation_days)
            .sum()
            .ge(confirmation_days)
            .fillna(False)
            .astype(bool)
            for symbol, signal in market_maps.items()
        }
    next_dates: dict[str, dict[pd.Timestamp, pd.Timestamp]] = {}
    exit_mas: dict[str, pd.Series] = {}
    signal_events_mutable: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    priority_scores = priority_scores or {}
    for symbol, frame in frames.items():
        dates = list(frame.index)
        next_dates[symbol] = {dates[index]: dates[index + 1] for index in range(len(dates) - 1)}
        exit_mas[symbol] = frame["close"].rolling(int(getattr(indicator_config, "exit_ma_days", 20)), min_periods=int(getattr(indicator_config, "exit_ma_days", 20))).mean()
        original = str(frame["original_symbol"].iloc[0]) if "original_symbol" in frame.columns else symbol.split("::segment_", 1)[0]
        signal = signal_maps[symbol]
        priority = _normalise_series_index(
            priority_scores.get(symbol, pd.Series(dtype=float))
        ).reindex(frame.index)
        for signal_date in signal.index[signal.to_numpy(dtype=bool)]:
            signal_date = pd.Timestamp(signal_date)
            next_date = next_dates[symbol].get(signal_date)
            if next_date is None or signal_date < start_date or signal_date >= end_date or next_date > end_date:
                continue
            signal_events_mutable.setdefault(signal_date, []).append(
                {
                    "symbol": symbol,
                    "original_symbol": original,
                    "signal_date": signal_date,
                    "entry_date": next_date,
                    "entry_priority": float(priority.get(signal_date, float("-inf")))
                    if math.isfinite(float(priority.get(signal_date, float("nan"))))
                    else float("-inf"),
                }
            )
    signal_events = {
        date: tuple(
            sorted(
                events,
                key=lambda item: (-item["entry_priority"], item["original_symbol"], item["symbol"]),
            )
        )
        for date, events in signal_events_mutable.items()
    }

    return PreparedSignalPortfolioData(
        frames=frames,
        signal_maps=signal_maps,
        market_maps=market_maps,
        next_dates=next_dates,
        exit_mas=exit_mas,
        signal_events=signal_events,
        calendar=tuple(calendar),
        start=start_date,
        end=end_date,
        indicator_config=indicator_config,
    )


def simulate_signal_portfolio(
    signals_by_symbol: Mapping[str, pd.Series],
    price_frames: Mapping[str, pd.DataFrame],
    *,
    market_exit_signals: Mapping[str, pd.Series],
    priority_scores: Mapping[str, pd.Series] | None = None,
    start: str,
    end: str,
    indicator_config: Any,
    portfolio_config: PortfolioConfig,
) -> PortfolioResult:
    prepared = prepare_signal_portfolio_data(
        signals_by_symbol,
        price_frames,
        market_exit_signals=market_exit_signals,
        priority_scores=priority_scores,
        start=start,
        end=end,
        indicator_config=indicator_config,
    )
    return simulate_prepared_signal_portfolio(prepared, portfolio_config=portfolio_config)


def simulate_prepared_signal_portfolio(
    data: PreparedSignalPortfolioData,
    *,
    portfolio_config: PortfolioConfig,
) -> PortfolioResult:
    """Run one global portfolio using precompiled close-time signals."""

    frames = data.frames
    signal_maps = data.signal_maps
    market_maps = data.market_maps
    next_dates = data.next_dates
    exit_mas = data.exit_mas
    calendar = data.calendar
    start_date = data.start
    end_date = data.end
    indicator_config = data.indicator_config

    pending_entries: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    pending_entry_symbols: set[str] = set()
    pending_exits: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    active: dict[str, dict[str, Any]] = {}
    cash = portfolio_config.initial_capital
    marks: dict[str, float] = {}
    ledger_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    peak = portfolio_config.initial_capital
    commission = portfolio_config.transaction_cost_bps_per_side / 10_000
    slippage = portfolio_config.slippage_bps_per_side / 10_000

    def current_market_value(date: pd.Timestamp, price_field: str) -> float:
        total = 0.0
        for symbol, position in active.items():
            frame = frames[symbol]
            if date in frame.index and math.isfinite(float(frame.at[date, price_field])):
                marks[symbol] = float(frame.at[date, price_field])
            total += position["shares"] * marks.get(symbol, position["entry_price"])
        return total

    def close_position(symbol: str, date: pd.Timestamp, raw_price: float, reason: str) -> None:
        nonlocal cash
        position = active.pop(symbol)
        exit_price = raw_price * (1 - slippage)
        proceeds = position["shares"] * exit_price
        exit_fee = proceeds * commission
        cash += proceeds - exit_fee
        pnl = proceeds - exit_fee - position["notional"] - position["entry_fee"]
        ledger_rows.append(
            {
                "candidate_id": position.get("candidate_id", ""),
                "symbol": symbol,
                "original_symbol": position["original_symbol"],
                "signal_date": position["signal_date"],
                "entry_priority": position["entry_priority"],
                "entry_date": position["entry_date"],
                "exit_date": date,
                "entry_price": position["entry_price"],
                "exit_price": exit_price,
                "holding_days": (date - position["entry_date"]).days,
                "holding_bars": position["holding_bars"],
                "exit_reason": reason,
                "allocated_capital": position["notional"],
                "shares": position["shares"],
                "entry_fee": position["entry_fee"],
                "exit_fee": exit_fee,
                "net_pnl": pnl,
                "portfolio_trade_return_pct": pnl / position["notional"] * 100,
            }
        )

    for date in calendar:
        current_market_value(date, "open")
        for order in sorted(pending_exits.pop(date, []), key=lambda item: item["symbol"]):
            symbol = order["symbol"]
            if symbol not in active:
                continue
            raw_open = float(frames[symbol].at[date, "open"])
            if not math.isfinite(raw_open) or raw_open <= 0:
                later = next_dates[symbol].get(date)
                if later is not None and later <= end_date:
                    pending_exits.setdefault(later, []).append(order)
                continue
            close_position(symbol, date, raw_open, order["reason"])

        entry_orders = sorted(
            pending_entries.pop(date, []),
            key=lambda item: (-item.get("entry_priority", float("-inf")), item["original_symbol"], item["symbol"]),
        )
        for order in entry_orders:
            symbol = order["symbol"]
            pending_entry_symbols.discard(symbol)
            raw_open = float(frames[symbol].at[date, "open"])
            if not math.isfinite(raw_open) or raw_open <= 0:
                skipped_rows.append({**order, "entry_date": date, "reason": "missing_next_open"})
                continue
            if symbol in active:
                skipped_rows.append({**order, "entry_date": date, "reason": "symbol_already_active"})
                continue
            if any(position["original_symbol"] == order["original_symbol"] for position in active.values()):
                skipped_rows.append({**order, "entry_date": date, "reason": "original_symbol_already_active"})
                continue
            if len(active) >= portfolio_config.max_positions:
                skipped_rows.append({**order, "entry_date": date, "reason": "max_positions"})
                continue
            value = current_market_value(date, "open")
            equity = cash + value
            entry_price = raw_open * (1 + slippage)
            shares, notional, fee = _fill_size(cash=cash, market_value=value, equity=equity, price=entry_price, config=portfolio_config)
            if shares <= 0:
                skipped_rows.append({**order, "entry_date": date, "reason": "insufficient_cash"})
                continue
            cash -= notional + fee
            frame = frames[symbol]
            original_symbol = str(frame["original_symbol"].iloc[0]) if "original_symbol" in frame.columns else symbol.split("::segment_", 1)[0]
            marks[symbol] = raw_open
            active[symbol] = {
                "symbol": symbol,
                "original_symbol": original_symbol,
                "signal_date": order["signal_date"],
                "entry_date": date,
                "entry_price": entry_price,
                "shares": shares,
                "notional": notional,
                "entry_fee": fee,
                "high_water": float(frame.at[date, "high"]),
                "holding_bars": 0,
                "exit_pending": False,
                "entry_priority": order.get("entry_priority", float("-inf")),
            }

        for symbol in sorted(active):
            frame = frames[symbol]
            if date not in frame.index:
                continue
            position = active[symbol]
            position["holding_bars"] += 1
            position["high_water"] = max(position["high_water"], float(frame.at[date, "high"]))
            if (
                next_dates[symbol].get(date) is None
                and date < end_date
                and (end_date - date).days > MAX_TERMINAL_MARK_DAYS
            ):
                raise UnresolvedPositionError(
                    f"{symbol} has no executable exit after {date.date()} before {end_date.date()}"
                )
            soft_allowed = position["holding_bars"] >= int(getattr(indicator_config, "minimum_holding_days_before_soft_exit", 0))
            reason = ""
            if float(frame.at[date, "low"]) <= position["entry_price"] * (1 - float(getattr(indicator_config, "stop_loss_pct", 0))):
                reason = "stop_loss"
            elif (
                float(getattr(indicator_config, "take_profit_pct", 0)) > 0
                and position["holding_bars"] >= int(getattr(indicator_config, "take_profit_min_holding_days", 0))
                and float(frame.at[date, "high"]) >= position["entry_price"] * (1 + float(getattr(indicator_config, "take_profit_pct", 0)))
            ):
                reason = "take_profit"
            elif soft_allowed and float(getattr(indicator_config, "trailing_stop_pct", 0)) > 0 and float(frame.at[date, "low"]) <= position["high_water"] * (1 - float(getattr(indicator_config, "trailing_stop_pct", 0))):
                reason = "trailing_stop"
            elif soft_allowed and bool(getattr(indicator_config, "use_exit_ma", False)) and math.isfinite(float(exit_mas[symbol].get(date, np.nan))) and float(frame.at[date, "close"]) < float(exit_mas[symbol].at[date]):
                reason = "exit_ma"
            elif soft_allowed and bool(getattr(indicator_config, "use_market_exit", False)) and bool(market_maps[symbol].get(date, False)):
                reason = "market_exit"
            elif position["holding_bars"] >= int(getattr(indicator_config, "max_holding_days", 1)):
                reason = "max_holding"
            if reason and not position["exit_pending"]:
                next_date = next_dates[symbol].get(date)
                if next_date is not None and next_date <= end_date:
                    pending_exits.setdefault(next_date, []).append({"symbol": symbol, "reason": reason})
                    position["exit_pending"] = True

        if date < end_date:
            for event in data.signal_events.get(date, ()):
                symbol = str(event["symbol"])
                if symbol in active:
                    continue
                if symbol in pending_entry_symbols:
                    continue
                next_date = pd.Timestamp(event["entry_date"])
                pending_entries.setdefault(next_date, []).append(dict(event))
                pending_entry_symbols.add(symbol)

        if date == end_date:
            for symbol in sorted(list(active)):
                close_position(symbol, date, float(frames[symbol].at[date, "close"]) if date in frames[symbol].index else marks[symbol], "period_end")

        value = current_market_value(date, "close")
        equity = cash + value
        peak = max(peak, equity)
        daily_rows.append(
            {
                "date": date,
                "cash": cash,
                "market_value": value,
                "equity": equity,
                "gross_exposure": value / equity if equity > 0 else 0,
                "open_positions": len(active),
                "drawdown_pct": (equity / peak - 1) * 100,
            }
        )
    return _result(daily_rows=daily_rows, ledger_rows=ledger_rows, skipped_rows=skipped_rows, config=portfolio_config, start=start_date, end=end_date)


def choose_risk_compliant_result(sweep: pd.DataFrame, *, risk_limit_pct: float = 25.0) -> pd.Series:
    required = {
        "position_size_pct",
        "max_positions",
        "train_max_drawdown_pct",
        "validation_max_drawdown_pct",
        "train_worst_year_pct",
        "validation_worst_year_pct",
        "validation_cagr_pct",
    }
    missing = required - set(sweep.columns)
    if missing:
        raise ValueError(f"sweep missing columns: {', '.join(sorted(missing))}")
    if not math.isfinite(risk_limit_pct) or risk_limit_pct <= 0:
        raise ValueError("risk_limit_pct must be positive")
    ranked = sweep.copy()
    ranked["risk_limit_pass"] = (
        (ranked["train_max_drawdown_pct"] > -risk_limit_pct)
        & (ranked["validation_max_drawdown_pct"] > -risk_limit_pct)
        & (ranked["train_worst_year_pct"] > -risk_limit_pct)
        & (ranked["validation_worst_year_pct"] > -risk_limit_pct)
    )
    ranked = ranked.loc[ranked["risk_limit_pass"]].copy()
    if ranked.empty:
        raise ValueError("no position size satisfies the risk limit")
    columns = ["validation_cagr_pct"]
    ascending = [False]
    if "train_cagr_pct" in ranked.columns:
        columns.append("train_cagr_pct")
        ascending.append(False)
    columns.extend(["position_size_pct", "max_positions"])
    ascending.extend([False, True])
    return ranked.sort_values(columns, ascending=ascending, kind="mergesort").iloc[0]


def choose_train_selected_result(sweep: pd.DataFrame, *, risk_limit_pct: float = 20.0) -> pd.Series:
    """Choose sizing from train only; validation remains an untouched confirmation."""

    required = {
        "position_size_pct",
        "max_positions",
        "train_max_drawdown_pct",
        "train_worst_year_pct",
        "train_cagr_pct",
    }
    missing = required - set(sweep.columns)
    if missing:
        raise ValueError(f"sweep missing columns: {', '.join(sorted(missing))}")
    if not math.isfinite(risk_limit_pct) or risk_limit_pct <= 0:
        raise ValueError("risk_limit_pct must be positive")
    ranked = sweep.copy()
    ranked["train_risk_limit_pass"] = (
        (pd.to_numeric(ranked["train_max_drawdown_pct"], errors="coerce") > -risk_limit_pct)
        & (pd.to_numeric(ranked["train_worst_year_pct"], errors="coerce") > -risk_limit_pct)
    )
    ranked = ranked.loc[ranked["train_risk_limit_pass"]].copy()
    if ranked.empty:
        raise ValueError("no position size satisfies the train risk limit")
    columns = ["train_cagr_pct"]
    ascending = [False]
    if "train_total_return_pct" in ranked.columns:
        columns.append("train_total_return_pct")
        ascending.append(False)
    columns.extend(["position_size_pct", "max_positions"])
    ascending.extend([False, True])
    return ranked.sort_values(columns, ascending=ascending, kind="mergesort").iloc[0]
