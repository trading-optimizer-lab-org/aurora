"""Tax-aware backtest with capital gains tracking.

Tracks per-lot basis and holding period. Applies short-term and long-term
capital gains rates. Implements US wash-sale rule: if a position is sold at a
loss and the same asset is repurchased within 30 days, the loss is disallowed
(added to the basis of the replacement lot in the IRS treatment; here we
report it as `wash_sale_disallowed_loss` and exclude from the realized loss).

A "trade" in this module is a (timestamp, symbol, qty, price) execution. We
derive trades from a weight series + prices by treating each weight change as
a buy or sell at the bar price.

CRITICAL:
- weight at bar i applies on bar i (entry/exit at close of bar i)
- holding_days from lot.entry_date to sell_date in calendar days
- accounting methods: FIFO (oldest first), LIFO (newest first),
  HIFO (highest basis first, minimizes realized gain)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class TaxConfig:
    """Tax configuration. Defaults model the US individual tax regime.

    long_term_threshold_days documents jurisdictional differences:
      - US (default 365): holding > 1 year qualifies for long-term capital
        gains rates (IRC §1222).
      - UK: no fixed holding-period split; CGT rates differ by income bracket
        rather than holding period. Use a very large value (e.g. 10**9) to
        force all gains to short-term, or set to 0 to force all long-term.
      - Germany: pre-2009 pre-acquired equities had a 365-day Spekulationsfrist;
        post-2009 reform removed the holding-period split for most assets.
        Crypto retains a 365-day rule.
      - Australia: 365 days for the 50% CGT discount eligibility.
    Project default = US (365). Override per-call via TaxConfig.
    """
    short_term_rate: float = 0.37        # US short-term cap gains (ordinary income)
    long_term_rate: float = 0.20         # US long-term cap gains
    long_term_threshold_days: int = 365  # holding period for long-term (US default)
    wash_sale_window_days: int = 30      # disallow loss recognition within window
    enable_wash_sale: bool = True
    accounting_method: str = "FIFO"      # FIFO | LIFO | HIFO


@dataclass
class TaxLot:
    entry_date: str
    quantity: float
    basis_per_share: float


@dataclass
class RealizedGain:
    sell_date: str
    quantity: float
    basis: float
    proceeds: float
    pnl: float
    holding_days: int
    is_long_term: bool
    is_wash_sale: bool
    tax: float


@dataclass
class TaxResult:
    realized_gains: list[RealizedGain]
    total_short_term_pnl: float
    total_long_term_pnl: float
    total_short_term_tax: float
    total_long_term_tax: float
    total_tax: float
    after_tax_pnl: float
    wash_sale_disallowed_loss: float
    pre_tax_return: float
    after_tax_return: float
    final_nav_pre_tax: float = 0.0
    final_nav_after_tax: float = 0.0


@dataclass
class _Trade:
    """Internal trade record (one per execution)."""
    bar: int
    date: str
    symbol: str
    qty: float                # +buy, -sell (in shares)
    price: float
    pnl: float = 0.0          # realized for sells (signed)
    is_loss: bool = False


def _to_date_str(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _holding_days(entry_date: str, sell_date: str) -> int:
    return int((pd.Timestamp(sell_date) - pd.Timestamp(entry_date)).days)


class TaxAwareSimulator:
    """Simulator with tax lot tracking.

    Tracks per-lot basis, holding period, applies short/long-term rates.
    Implements wash sale rule (disallows losses if buy within 30 days).
    """

    def __init__(self, config: Optional[TaxConfig] = None,
                 accounting_method: Optional[str] = None):
        self.config = config or TaxConfig()
        if accounting_method is not None:
            # explicit kwarg overrides config
            self.config = TaxConfig(
                short_term_rate=self.config.short_term_rate,
                long_term_rate=self.config.long_term_rate,
                long_term_threshold_days=self.config.long_term_threshold_days,
                wash_sale_window_days=self.config.wash_sale_window_days,
                enable_wash_sale=self.config.enable_wash_sale,
                accounting_method=accounting_method,
            )
        if self.config.accounting_method not in ("FIFO", "LIFO", "HIFO"):
            raise ValueError(f"unknown accounting_method: {self.config.accounting_method}")

    # ------- lot pickers -------
    def _pick_lots(self, lots: list[TaxLot], qty: float) -> list[tuple[int, float]]:
        """Return list of (lot_index, qty_used) for the chosen accounting method."""
        method = self.config.accounting_method
        if method == "FIFO":
            order = list(range(len(lots)))
        elif method == "LIFO":
            order = list(range(len(lots) - 1, -1, -1))
        elif method == "HIFO":
            order = sorted(range(len(lots)), key=lambda i: -lots[i].basis_per_share)
        else:
            raise ValueError(method)

        remaining = qty
        picks: list[tuple[int, float]] = []
        for i in order:
            if remaining <= 1e-12:
                break
            avail = lots[i].quantity
            if avail <= 0:
                continue
            used = min(avail, remaining)
            picks.append((i, used))
            remaining -= used
        if remaining > 1e-9:
            raise ValueError(f"insufficient lot quantity: short {remaining} shares")
        return picks

    # ------- core sim -------
    def simulate(self, weights: np.ndarray, prices: np.ndarray,
                 timestamps: np.ndarray,
                 initial_capital: float = 100_000.0) -> TaxResult:
        """Run tax-aware sim. Compute realized gains + after-tax returns.

        Single-asset case: weights[i] in [-1, 1] is the target equity fraction.
        For tax purposes, we only track long lots (weight >= 0). Short positions
        do not accrue capital gains under standard treatment until covered.
        We treat short flips by closing the long lots first (selling all
        existing long lots) and then ignoring short notional for tax.
        """
        weights = np.asarray(weights, dtype=float)
        prices = np.asarray(prices, dtype=float)
        timestamps = np.asarray(timestamps)
        T = len(prices)
        if len(weights) != T or len(timestamps) != T:
            raise ValueError("weights, prices, timestamps must have same length")
        if T == 0:
            return self._empty_result(initial_capital)

        # 1) build trade list from weight changes.
        trades: list[_Trade] = []
        # track desired share count via target value / price (long-only for taxes).
        # nav_pre compounds per bar: base cash + (current shares * current price)
        # so position sizing reflects realized + mark-to-market PnL through time
        # rather than a fixed fraction of initial_capital.
        nav_pre = float(initial_capital)
        prev_shares = 0.0
        # track lot holdings per (single) symbol
        lots: list[TaxLot] = []
        realized: list[RealizedGain] = []
        wash_disallowed = 0.0

        symbol = "ASSET"

        for i in range(T):
            p = float(prices[i])
            if p <= 0 or not np.isfinite(p):
                continue
            # Mark-to-market NAV: previous-bar cash + current-price * carried shares.
            # We approximate cash as initial_capital - sum(realized_proceeds_consumed)
            # by tracking it through the loop. This gives a compound NAV path so
            # weight * nav_pre sizes against current portfolio value, not the
            # static initial capital.
            nav_pre_bar = float(initial_capital)
            # realized PnL contributes to cash; carried position contributes MTM.
            for r_done in realized:
                if not (r_done.is_wash_sale and r_done.pnl < 0):
                    nav_pre_bar += r_done.pnl
            for lot in lots:
                nav_pre_bar += lot.quantity * (p - lot.basis_per_share)
            nav_pre = nav_pre_bar
            target_w = max(0.0, float(weights[i]))   # long-only for tax tracking
            target_value = target_w * nav_pre
            target_shares = target_value / p
            delta = target_shares - prev_shares

            date = _to_date_str(timestamps[i])

            if abs(delta) > 1e-12:
                if delta > 0:
                    # BUY
                    lots.append(TaxLot(entry_date=date,
                                       quantity=float(delta),
                                       basis_per_share=p))
                    trades.append(_Trade(bar=i, date=date, symbol=symbol,
                                         qty=float(delta), price=p))
                else:
                    # SELL — cap sell_qty at available lot quantity. Anything
                    # beyond the existing long position is a fresh short and
                    # has no tax consequence under standard treatment (we track
                    # only long lots; shorts accrue when covered, not when
                    # opened). See module docstring.
                    sell_qty_requested = -float(delta)
                    available = sum(lot.quantity for lot in lots)
                    sell_qty = min(sell_qty_requested, available)
                    trade_pnl = 0.0
                    if sell_qty > 1e-12:
                        picks = self._pick_lots(lots, sell_qty)
                        for idx, used in picks:
                            lot = lots[idx]
                            basis = used * lot.basis_per_share
                            proceeds = used * p
                            lot_pnl = proceeds - basis
                            trade_pnl += lot_pnl
                            holding = _holding_days(lot.entry_date, date)
                            is_long_term = holding >= self.config.long_term_threshold_days
                            realized.append(RealizedGain(
                                sell_date=date,
                                quantity=used,
                                basis=basis,
                                proceeds=proceeds,
                                pnl=lot_pnl,
                                holding_days=holding,
                                is_long_term=is_long_term,
                                is_wash_sale=False,  # set after wash-sale pass
                                tax=0.0,
                            ))
                            lot.quantity -= used
                        # purge fully consumed lots
                        lots = [lo for lo in lots if lo.quantity > 1e-12]

                    trades.append(_Trade(bar=i, date=date, symbol=symbol,
                                         qty=float(delta), price=p,
                                         pnl=trade_pnl,
                                         is_loss=trade_pnl < 0))

            prev_shares = target_shares

        # 2) wash-sale pass: for each loss-sell trade, check if any buy of the
        # same symbol falls within window_days AFTER the sell date.
        if self.config.enable_wash_sale:
            # Build per-sell groups by walking trades and realized in order.
            # realized list order mirrors the order of sells we appended, so we
            # can group realized rows by walking sells sequentially and
            # consuming realized entries until each sell's qty is matched.
            realized_by_sell: list[list[int]] = []
            r_pos = 0
            for t in trades:
                if t.qty >= 0:
                    continue
                qty_left = -t.qty
                grp: list[int] = []
                while r_pos < len(realized) and qty_left > 1e-9:
                    grp.append(r_pos)
                    qty_left -= realized[r_pos].quantity
                    r_pos += 1
                realized_by_sell.append(grp)

            # iterate sells; if loss, look for any later buy within window.
            sell_index_in_trades = [k for k, t in enumerate(trades) if t.qty < 0]
            for grp_pos, k_sell in enumerate(sell_index_in_trades):
                t_sell = trades[k_sell]
                if not t_sell.is_loss:
                    continue
                sell_dt = pd.Timestamp(t_sell.date)
                window = self.config.wash_sale_window_days
                # rebuy within (sell_dt, sell_dt + window]
                tagged = False
                for k_buy in range(k_sell + 1, len(trades)):
                    t_buy = trades[k_buy]
                    if t_buy.qty <= 0:
                        continue
                    buy_dt = pd.Timestamp(t_buy.date)
                    days = (buy_dt - sell_dt).days
                    if 0 < days <= window:
                        tagged = True
                        break
                    if days > window:
                        break
                if tagged:
                    for ridx in realized_by_sell[grp_pos]:
                        if realized[ridx].pnl < 0:
                            realized[ridx].is_wash_sale = True
                            wash_disallowed += -realized[ridx].pnl

        # 3) compute taxes per realized row. Wash-sale loss rows: pnl excluded
        # from taxable; their loss is disallowed (we record it but tax=0).
        total_st_pnl = 0.0
        total_lt_pnl = 0.0
        for r in realized:
            if r.is_wash_sale and r.pnl < 0:
                # disallowed loss: not deductible this year
                r.tax = 0.0
                continue
            if r.is_long_term:
                total_lt_pnl += r.pnl
            else:
                total_st_pnl += r.pnl

        # tax only on positive net category pnl
        st_tax = max(0.0, total_st_pnl) * self.config.short_term_rate
        lt_tax = max(0.0, total_lt_pnl) * self.config.long_term_rate
        # Apportion category tax across positive-pnl rows only, weighted by
        # row pnl. Net category losses cancel against gains before tax, so
        # the per-row tax allocation must scale by (net_taxable / sum_pos)
        # rather than per-row pnl directly. This keeps sum(r.tax) == st_tax.
        if total_st_pnl > 0:
            pos_st = [r for r in realized
                      if (not r.is_long_term) and (not r.is_wash_sale) and r.pnl > 0]
            sum_pos_st = sum(r.pnl for r in pos_st)
            if sum_pos_st > 0:
                scale = total_st_pnl / sum_pos_st
                for r in pos_st:
                    r.tax = r.pnl * scale * self.config.short_term_rate
        if total_lt_pnl > 0:
            pos_lt = [r for r in realized
                      if r.is_long_term and (not r.is_wash_sale) and r.pnl > 0]
            sum_pos_lt = sum(r.pnl for r in pos_lt)
            if sum_pos_lt > 0:
                scale = total_lt_pnl / sum_pos_lt
                for r in pos_lt:
                    r.tax = r.pnl * scale * self.config.long_term_rate

        total_tax = st_tax + lt_tax
        # close out unrealized at last bar so pre-tax return matches MTM PnL.
        final_price = float(prices[-1]) if T > 0 else 0.0
        unrealized = sum(lot.quantity * (final_price - lot.basis_per_share)
                         for lot in lots)
        realized_pnl = sum(r.pnl for r in realized
                           if not (r.is_wash_sale and r.pnl < 0))
        # include disallowed losses as zero (not in pnl)
        total_pnl_pre_tax = realized_pnl + unrealized
        # After-tax: tax on realized only (unrealized untaxed).
        after_tax_pnl = total_pnl_pre_tax - total_tax

        nav_final_pre = float(initial_capital + total_pnl_pre_tax)
        nav_final_after = float(initial_capital + after_tax_pnl)
        pre_tax_ret = total_pnl_pre_tax / initial_capital if initial_capital > 0 else 0.0
        after_tax_ret = after_tax_pnl / initial_capital if initial_capital > 0 else 0.0

        return TaxResult(
            realized_gains=realized,
            total_short_term_pnl=float(total_st_pnl),
            total_long_term_pnl=float(total_lt_pnl),
            total_short_term_tax=float(st_tax),
            total_long_term_tax=float(lt_tax),
            total_tax=float(total_tax),
            after_tax_pnl=float(after_tax_pnl),
            wash_sale_disallowed_loss=float(wash_disallowed),
            pre_tax_return=float(pre_tax_ret),
            after_tax_return=float(after_tax_ret),
            final_nav_pre_tax=nav_final_pre,
            final_nav_after_tax=nav_final_after,
        )

    @staticmethod
    def _empty_result(cap: float) -> TaxResult:
        return TaxResult(
            realized_gains=[], total_short_term_pnl=0.0, total_long_term_pnl=0.0,
            total_short_term_tax=0.0, total_long_term_tax=0.0, total_tax=0.0,
            after_tax_pnl=0.0, wash_sale_disallowed_loss=0.0,
            pre_tax_return=0.0, after_tax_return=0.0,
            final_nav_pre_tax=cap, final_nav_after_tax=cap,
        )


def prev_shares_prev_p_value(prev_shares, prices, i):
    """Helper used in MTM placeholder; kept for clarity. Not used in final NAV."""
    if i == 0:
        return 0.0
    return prev_shares * float(prices[i - 1])


def after_tax_metrics(weights: np.ndarray, prices: np.ndarray,
                      timestamps: np.ndarray,
                      config: Optional[TaxConfig] = None,
                      initial_capital: float = 100_000.0,
                      ppy: int = 252,
                      long_term_threshold_days: int = 365) -> dict:
    """Convenience: compute after-tax CAGR / Sharpe / final NAV.

    long_term_threshold_days overrides the threshold even when a `config` is
    supplied (to make the jurisdiction explicit at the call site). Default
    365 = US long-term cap-gains qualifying period. Pass a UK / Germany /
    Australia value if you need a different jurisdiction.
    """
    base_cfg = config or TaxConfig()
    cfg = TaxConfig(
        short_term_rate=base_cfg.short_term_rate,
        long_term_rate=base_cfg.long_term_rate,
        long_term_threshold_days=long_term_threshold_days,
        wash_sale_window_days=base_cfg.wash_sale_window_days,
        enable_wash_sale=base_cfg.enable_wash_sale,
        accounting_method=base_cfg.accounting_method,
    )
    sim = TaxAwareSimulator(config=cfg)
    res = sim.simulate(weights, prices, timestamps, initial_capital=initial_capital)
    T = len(prices)
    years = max(T / ppy, 1e-9)
    pre_cagr = (res.final_nav_pre_tax / initial_capital) ** (1 / years) - 1.0 \
        if res.final_nav_pre_tax > 0 else -1.0
    after_cagr = (res.final_nav_after_tax / initial_capital) ** (1 / years) - 1.0 \
        if res.final_nav_after_tax > 0 else -1.0

    # daily returns approximation for sharpe: derive from price * weight - cost-free
    p = np.asarray(prices, dtype=float)
    w = np.asarray(weights, dtype=float)
    rets = np.zeros(len(p))
    rets[1:] = w[:-1] * (p[1:] / p[:-1] - 1.0)
    if len(rets) > 1 and rets.std() > 0:
        sharpe = float(np.sqrt(ppy) * rets.mean() / rets.std())
    else:
        sharpe = 0.0

    return {
        "pre_tax_cagr": float(pre_cagr),
        "after_tax_cagr": float(after_cagr),
        "pre_tax_sharpe": sharpe,
        "final_nav_pre_tax": float(res.final_nav_pre_tax),
        "final_nav_after_tax": float(res.final_nav_after_tax),
        "total_tax": float(res.total_tax),
        "wash_sale_disallowed_loss": float(res.wash_sale_disallowed_loss),
        "pre_tax_return": float(res.pre_tax_return),
        "after_tax_return": float(res.after_tax_return),
    }


# Default substantially-identical security map for cross-symbol wash-sale
# detection. Groups securities that the IRS would (or many practitioners
# treat as) "substantially identical" — primarily S&P 500 ETFs that all
# track the same underlying index. The map is symbol -> canonical group id.
# Users can override via the `equiv_map` arg of detect_wash_sales.
DEFAULT_EQUIV_MAP: dict[str, str] = {
    # S&P 500 trackers
    "SPY": "SP500", "IVV": "SP500", "VOO": "SP500", "SPLG": "SP500",
    # Total US market
    "VTI": "US_TOTAL", "ITOT": "US_TOTAL", "SCHB": "US_TOTAL",
    # Nasdaq-100
    "QQQ": "NDX100", "QQQM": "NDX100",
    # Long-bond US Treasury
    "TLT": "LT_TSY", "VGLT": "LT_TSY",
}


def detect_wash_sales(trades: list,
                      window_days: int = 30,
                      cross_symbol: bool = False,
                      equiv_map: Optional[dict[str, str]] = None) -> list[int]:
    """Identify trade indices that fall within wash-sale window after a loss.

    Args:
        trades: list of dict-like or _Trade objects with attributes/keys
                'date' (str), 'qty' (signed), 'is_loss' (bool, optional),
                'symbol' (str, optional — required if cross_symbol=True).
                If 'is_loss' missing, derived from 'pnl' < 0.
        window_days: replacement window. Default 30 (US IRS rule).
        cross_symbol: when True, two trades match if their symbols map to the
            same equivalence group in `equiv_map` (e.g. SPY ~ IVV ~ VOO).
            When False (default), only exact-same-symbol replacements count
            (preserves prior behavior).
        equiv_map: optional override for the substantially-identical security
            mapping. Defaults to :data:`DEFAULT_EQUIV_MAP` (S&P 500 ETFs,
            total-market ETFs, Nasdaq-100, long Treasury). Symbols not in the
            map fall back to themselves (so an unmapped symbol only matches
            itself even when cross_symbol=True).

    Returns:
        List of buy-trade indices that are wash-sale replacements for a prior
        loss sale within the window.
    """
    def _get(t, key, default=None):
        if isinstance(t, dict):
            return t.get(key, default)
        return getattr(t, key, default)

    eq = equiv_map if equiv_map is not None else DEFAULT_EQUIV_MAP

    def _key(symbol):
        if symbol is None:
            return None
        if cross_symbol:
            return eq.get(symbol, symbol)
        return symbol

    n = len(trades)
    flagged: list[int] = []
    for i, t in enumerate(trades):
        qty = _get(t, "qty", 0.0)
        if qty is None or qty >= 0:
            continue
        is_loss = _get(t, "is_loss", None)
        if is_loss is None:
            pnl = _get(t, "pnl", 0.0) or 0.0
            is_loss = pnl < 0
        if not is_loss:
            continue
        sell_dt = pd.Timestamp(_get(t, "date"))
        sell_key = _key(_get(t, "symbol", None))
        for j in range(i + 1, n):
            t2 = trades[j]
            q2 = _get(t2, "qty", 0.0)
            if q2 is None or q2 <= 0:
                continue
            buy_key = _key(_get(t2, "symbol", None))
            # If both have symbols, they must match by equivalence key.
            # If either lacks a symbol, fall back to the legacy "ignore
            # symbol" behavior (single-asset trade lists).
            if sell_key is not None and buy_key is not None:
                if sell_key != buy_key:
                    continue
            buy_dt = pd.Timestamp(_get(t2, "date"))
            days = (buy_dt - sell_dt).days
            if 0 < days <= window_days:
                flagged.append(j)
            elif days > window_days:
                break
    return sorted(set(flagged))
