"""Position sizing module.

Three sizing methods:
- fixed_risk_size: risk-per-trade based on stop distance
- vol_target_size: scale notional by realized vol vs target
- kelly_size: fractional Kelly criterion

Plus RiskBudget utility to track aggregate portfolio risk.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field


def fixed_risk_size(nav: float, entry_price: float, stop_price: float,
                    risk_pct: float = 0.01) -> int:
    """Risk-per-trade sizing.

    risk = abs(entry - stop) per share
    position_size = (nav * risk_pct) / risk_per_share
    Returns integer share count, capped by NAV (no leverage).

    Args:
        nav: portfolio value (USD)
        entry_price: planned entry
        stop_price: planned stop
        risk_pct: max % NAV to risk on this trade (default 1%)
    """
    if nav <= 0 or entry_price <= 0 or risk_pct <= 0:
        return 0
    risk_per_share = abs(entry_price - stop_price)
    if risk_per_share <= 0:
        return 0
    dollar_risk = nav * risk_pct
    shares = int(dollar_risk // risk_per_share)
    # Hard NAV cap: a wide stop combined with risk_pct can imply more
    # notional than the account can support. Never return more shares than
    # the unlevered cash floor allows.
    max_shares = int(nav // entry_price)
    return min(max(0, shares), max_shares)


def vol_target_size(nav: float, asset_price: float, asset_vol_annual: float,
                    target_vol: float = 0.15, max_w: float = 1.0,
                    lookback: int = 21) -> int:
    """Vol-target sizing.

    weight = min(target_vol / asset_vol, max_w)
    notional = weight * nav
    shares = notional // asset_price

    Args:
        nav: portfolio value (USD).
        asset_price: current price per share.
        asset_vol_annual: annualized realized volatility of the asset, computed
            by the caller from a return window of length ``lookback``. The
            function does not recompute this from price history; ``lookback``
            is documented here so all sizing paths share a single window
            convention.
        target_vol: target portfolio volatility (default 15%).
        max_w: maximum weight cap (default 1.0).
        lookback: number of bars used by the caller to estimate
            ``asset_vol_annual``. Default 21 (≈1 trading month). The default
            preserves prior behavior when callers were already using a 21-bar
            window. Validated to be >= 2; the value is informational here and
            does not change the sizing arithmetic.

    Returns:
        Integer share count (floored).
    """
    if lookback < 2:
        raise ValueError(f"lookback must be >= 2, got {lookback}")
    if nav <= 0 or asset_price <= 0 or target_vol <= 0:
        return 0
    if asset_vol_annual <= 0:
        weight = max_w
    else:
        weight = min(target_vol / asset_vol_annual, max_w)
    weight = max(0.0, weight)
    notional = weight * nav
    shares = int(notional // asset_price)
    return max(0, shares)


def kelly_size(nav: float, asset_price: float, win_rate: float,
               avg_win: float, avg_loss: float, fraction: float = 0.25) -> int:
    """Fractional Kelly criterion (Thorp form).

    Kelly formula (per-trade), Thorp form:
        f* = (p / L) - (q / W)
    where p = win_rate, q = 1 - p, W = avg_win magnitude, L = avg_loss
    magnitude. This is algebraically equivalent to the textbook
    ``(p*W - q*L) / (W*L)`` form but is preferred at this call site for
    readability and to match the form used in standard references
    (Thorp, "The Kelly Criterion in Blackjack, Sports Betting, and the
    Stock Market"). Quick sanity check: for ``p=0.6, W=L=1`` we get
    ``0.6/1 - 0.4/1 = 0.2``.

    Use fractional (default 25%) for safety. Negative edge -> 0 size.

    Args:
        nav: portfolio value (USD)
        asset_price: current price per share
        win_rate: probability of win in [0, 1]
        avg_win: average win magnitude (positive)
        avg_loss: average loss magnitude (positive)
        fraction: Kelly fraction multiplier (default 0.25)
    """
    if nav <= 0 or asset_price <= 0 or fraction <= 0:
        return 0
    if win_rate <= 0 or win_rate >= 1:
        return 0
    if avg_win <= 0 or avg_loss <= 0:
        return 0
    # Tiny-magnitude floor: when avg_win or avg_loss is below 1e-6, the
    # divisions p/L and q/W blow up f_star to absurd sizes (1/eps levels)
    # that swamp the fraction multiplier and the asset_price floor. Treat
    # those cases as no-edge and return 0 instead of staking the book.
    if avg_loss < 1e-6 or avg_win < 1e-6:
        return 0
    p = win_rate
    q = 1.0 - p
    W = avg_win
    L = avg_loss
    f_star = (p / L) - (q / W)
    if f_star <= 0:
        return 0
    f_use = f_star * fraction
    f_use = min(f_use, 1.0)
    notional = f_use * nav
    shares = int(notional // asset_price)
    return max(0, shares)


@dataclass
class RiskInfo:
    """Per-position risk record."""
    entry: float
    stop: float
    size_shares: int

    @property
    def risk_dollars(self) -> float:
        return abs(self.entry - self.stop) * self.size_shares


@dataclass
class RiskBudget:
    """Tracks aggregate risk across multiple positions.

    Thread-safe: ``can_open``, ``open``, ``close``, ``total_risk_pct``, and
    the atomic ``try_open`` are guarded by an internal ``threading.Lock``
    so two threads cannot race past the budget gate. Use ``try_open`` for
    a single atomic check+register; the legacy ``can_open``/``open`` pair
    is kept for callers that need to size before registering.
    """
    max_portfolio_risk: float = 0.05    # 5% NAV at risk total
    max_single_position_risk: float = 0.01  # 1% per trade

    open_positions: dict = field(default_factory=dict)  # symbol -> RiskInfo
    nav: float = 100_000.0
    _lock: threading.Lock = field(default_factory=threading.Lock,
                                  repr=False, compare=False)

    def _total_risk_pct_locked(self) -> float:
        if self.nav <= 0:
            return 0.0
        total = sum(p.risk_dollars for p in self.open_positions.values())
        return total / self.nav

    def total_risk_pct(self) -> float:
        with self._lock:
            return self._total_risk_pct_locked()

    def _can_open_locked(self, symbol, risk_amt) -> tuple[bool, str]:
        if symbol in self.open_positions:
            return False, f"already open: {symbol}"
        if risk_amt <= 0:
            return False, "risk_amt must be > 0"
        if risk_amt > self.max_single_position_risk:
            return False, (f"single-position risk {risk_amt:.4f} exceeds cap "
                           f"{self.max_single_position_risk:.4f}")
        new_total = self._total_risk_pct_locked() + risk_amt
        if new_total > self.max_portfolio_risk:
            return False, (f"portfolio risk would be {new_total:.4f}, exceeds "
                           f"cap {self.max_portfolio_risk:.4f}")
        return True, "ok"

    def can_open(self, symbol, risk_amt) -> tuple[bool, str]:
        """Check if new position fits within budget. Returns (ok, reason).

        Args:
            symbol: position identifier
            risk_amt: requested risk as fraction of NAV (e.g. 0.01 = 1%)
        """
        with self._lock:
            return self._can_open_locked(symbol, risk_amt)

    def open(self, symbol, entry, stop, size_shares):
        """Register position."""
        with self._lock:
            self.open_positions[symbol] = RiskInfo(
                entry=float(entry), stop=float(stop),
                size_shares=int(size_shares),
            )

    def close(self, symbol):
        """Remove position from tracking. No-op if missing."""
        with self._lock:
            self.open_positions.pop(symbol, None)

    def try_open(self, symbol, entry, stop, size_shares,
                 risk_amt) -> tuple[bool, str]:
        """Atomic check-and-register. Returns (ok, reason).

        Holding the lock for the full check+register prevents a TOCTOU
        race where two threads each pass ``can_open`` and then both
        register, breaching the portfolio risk cap.
        """
        with self._lock:
            ok, reason = self._can_open_locked(symbol, risk_amt)
            if not ok:
                return False, reason
            self.open_positions[symbol] = RiskInfo(
                entry=float(entry), stop=float(stop),
                size_shares=int(size_shares),
            )
            return True, "ok"
