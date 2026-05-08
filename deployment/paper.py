"""Paper trading wrapper via Lumibot. Strategy must pass validation pipeline first.

Round X parity with QFLiveStrategy
----------------------------------
The paper wrapper now mirrors the live wrapper's hardening surface:

- ``bind()`` validates risk parameters (``risk_per_trade``,
  ``daily_loss_limit``, ``lookback_days``) via the same ``_validate_bind_args``
  shape as ``QFLiveStrategy``.
- Per-instance state lives on ``self`` so two QFPaperStrategy instances never
  share a halt flag or session NAV through class-level attributes.
- Daily-loss halt: when NAV drops past ``daily_loss_limit`` since session
  start, new orders are skipped for the remainder of the UTC date.
- NAV-validity guard: ``get_portfolio_value()`` returning ``None``/``<= 0`` is
  treated as a transient broker outage and skips the iteration cleanly.
- ``lookback_days`` is exposed as a ``bind()`` argument with the same default
  (300) as the live wrapper.
"""
from __future__ import annotations

from datetime import datetime as _dt
from datetime import timezone

try:
    from lumibot.strategies.strategy import Strategy as LumibotStrategy
    HAS_LUMIBOT = True
except ImportError:
    HAS_LUMIBOT = False
    LumibotStrategy = object


class QFPaperStrategy(LumibotStrategy):
    """Generic paper trading wrapper. Bind to any QF Strategy.

    Usage:
        from quantforge.strategies.library import MACross
        s = MACross(fast=20, slow=100)
        QFPaperStrategy.bind(s, symbol="SPY")
        # then deploy via Lumibot Trader
    """

    # Pending bind() configuration. ``bind()`` no longer mutates class
    # attributes that act as live state — it only stores the configuration
    # to be applied per-instance inside ``initialize()``.
    _qf_pending_config: dict | None = None

    _qf_strategy = None
    _qf_symbol = "SPY"
    _qf_lookback_days = 300
    _qf_risk_per_trade = 0.01
    _qf_daily_loss_limit = 0.05
    _qf_bypass_validation_check = False
    _qf_project_dir = "."

    @classmethod
    def _validate_bind_args(cls, *, risk_per_trade: float,
                            daily_loss_limit: float,
                            lookback_days: int) -> None:
        """Reject obviously dangerous paper-trading parameters at bind time."""
        if not (0.0 <= float(risk_per_trade) <= 0.1):
            raise ValueError(
                f"risk_per_trade must be in [0.0, 0.1], got {risk_per_trade}"
            )
        if not (0.0 < float(daily_loss_limit) <= 1.0):
            raise ValueError(
                f"daily_loss_limit must be in (0.0, 1.0], got {daily_loss_limit}"
            )
        if int(lookback_days) < 1:
            raise ValueError(
                f"lookback_days must be >= 1, got {lookback_days}"
            )

    @classmethod
    def bind(cls, qf_strategy, symbol: str = "SPY",
             risk_per_trade: float = 0.01,
             daily_loss_limit: float = 0.05,
             lookback_days: int = 300,
             bypass_validation_check: bool = False,
             project_dir: str = "."):
        """Bind a QF strategy. Returns a fresh subclass per call.

        Mirrors ``QFLiveStrategy.bind`` so two paper sessions never share
        mutable class-level state.
        """
        cls._validate_bind_args(
            risk_per_trade=risk_per_trade,
            daily_loss_limit=daily_loss_limit,
            lookback_days=lookback_days,
        )
        pending_config = {
            "qf_strategy": qf_strategy,
            "symbol": symbol,
            "lookback_days": int(lookback_days),
            "risk_per_trade": float(risk_per_trade),
            "daily_loss_limit": float(daily_loss_limit),
            "bypass_validation_check": bool(bypass_validation_check),
            "project_dir": str(project_dir),
        }
        new_cls = type(
            cls.__name__,
            (cls,),
            {
                "_qf_pending_config": pending_config,
                "_qf_strategy": qf_strategy,
                "_qf_symbol": symbol,
                "_qf_lookback_days": int(lookback_days),
                "_qf_risk_per_trade": float(risk_per_trade),
                "_qf_daily_loss_limit": float(daily_loss_limit),
                "_qf_bypass_validation_check": bool(bypass_validation_check),
                "_qf_project_dir": str(project_dir),
            },
        )
        return new_cls

    def initialize(self, parameters=None):
        self.set_market("NYSE")
        self.sleeptime = "1D"
        # Materialize bound configuration as PER-INSTANCE state.
        pending = type(self)._qf_pending_config or {}
        self.qf_strategy = pending.get("qf_strategy", type(self)._qf_strategy)
        self.qf_symbol = pending.get("symbol", type(self)._qf_symbol)
        self.qf_lookback_days = int(pending.get("lookback_days",
                                                type(self)._qf_lookback_days))
        self.qf_risk_per_trade = float(pending.get(
            "risk_per_trade", type(self)._qf_risk_per_trade))
        self.qf_daily_loss_limit = float(pending.get(
            "daily_loss_limit", type(self)._qf_daily_loss_limit))
        self.qf_bypass_validation_check = bool(pending.get(
            "bypass_validation_check",
            type(self)._qf_bypass_validation_check))
        self.qf_project_dir = str(pending.get(
            "project_dir", type(self)._qf_project_dir))
        self.qf_halted = False
        self.qf_session_date = _dt.now(timezone.utc).date()
        try:
            nav = self.get_portfolio_value()
            self.qf_session_start_nav = (float(nav)
                                         if nav is not None and nav > 0
                                         else None)
        except Exception:
            self.qf_session_start_nav = None
        # P1.1: Round-4 audit -- enforce validation marker at session start.
        self._enforce_validation_marker()

    def _enforce_validation_marker(self) -> None:
        """P1.1 -- ensure the bound QF strategy has a fresh validation marker.

        Mirrors ``QFLiveStrategy._enforce_validation_marker``. On FAIL we
        set ``self.qf_halted = True`` permanently for this session and log
        an ERROR. The ``bypass_validation_check`` flag explicitly opts out
        (with a WARNING) for tests / emergency operator overrides.
        """
        import logging
        log = logging.getLogger("quantforge.deployment.paper")
        if getattr(self, "qf_bypass_validation_check", False):
            log.warning(
                "validation_marker_bypassed: bypass_validation_check=True; "
                "operator override -- USE AT OWN RISK"
            )
            return
        qf_strategy = getattr(self, "qf_strategy", None)
        if qf_strategy is None:
            return
        strategy_name = type(qf_strategy).__name__
        try:
            from quantforge.deployment.preflight import check_validation_marker
            check = check_validation_marker(
                strategy_name,
                project_dir=getattr(self, "qf_project_dir", "."),
            )
        except Exception as e:
            log.error(
                "validation_marker_check_error: strategy=%s err=%s",
                strategy_name, e,
            )
            self.qf_halted = True
            return
        if not check.passed:
            log.error(
                "validation_marker_fail: strategy=%s detail=%s",
                strategy_name, check.detail,
            )
            self.qf_halted = True
            return
        log.info(
            "validation_marker_ok: strategy=%s detail=%s",
            strategy_name, check.detail,
        )

    def _maybe_roll_session(self) -> None:
        """Reset halt flag and session NAV when the UTC date rolls."""
        today = _dt.now(timezone.utc).date()
        prev = getattr(self, "qf_session_date", None)
        if prev is not None and today == prev:
            return
        self.qf_session_date = today
        self.qf_halted = False
        try:
            nav = self.get_portfolio_value()
            self.qf_session_start_nav = (float(nav)
                                         if nav is not None and nav > 0
                                         else None)
        except Exception:
            self.qf_session_start_nav = None

    def on_trading_iteration(self):
        self._maybe_roll_session()

        if getattr(self, "qf_halted", False):
            self.log_message("HALTED (daily loss limit hit). Skipping.")
            return
        if self._qf_strategy is None and getattr(self, "qf_strategy", None) is None:
            self.log_message("No QF strategy bound. Aborting.")
            return

        # NAV<=0 guard: a None/<=0 portfolio value typically signals a
        # transient broker outage. Skip the iteration cleanly.
        nav = self.get_portfolio_value()
        if nav is None or nav <= 0:
            self.log_message(f"Portfolio value invalid: {nav}. Skipping.")
            return
        nav = float(nav)

        # Daily-loss halt: sticky for the remainder of the UTC session.
        nav_start = getattr(self, "qf_session_start_nav", None)
        loss_limit = getattr(self, "qf_daily_loss_limit",
                             type(self)._qf_daily_loss_limit)
        if nav_start is not None and nav_start > 0:
            draw = (nav_start - nav) / nav_start
            if draw >= float(loss_limit):
                self.log_message(
                    f"Daily loss {draw:.4f} exceeds limit {loss_limit:.4f}. "
                    "Halting for the rest of the session."
                )
                self.qf_halted = True
                return

        symbol = getattr(self, "qf_symbol", type(self)._qf_symbol)
        lookback = getattr(self, "qf_lookback_days",
                           type(self)._qf_lookback_days)
        bars = self.get_historical_prices(symbol, length=lookback,
                                          timestep="day")
        if bars is None:
            self.log_message("Missing data, skipping.")
            return
        prices = bars.df["close"]
        qf_strategy = getattr(self, "qf_strategy", None) or self._qf_strategy
        weights = qf_strategy.signals(prices)
        target_w = float(weights[-1])
        target_w = max(-1.0, min(1.0, target_w))

        target_dollars = target_w * nav

        price = self.get_last_price(symbol)
        if price is None or price <= 0:
            return
        target_qty = int(target_dollars / price)
        cur = self.get_position(symbol)
        cur_qty = cur.quantity if cur else 0
        delta = target_qty - cur_qty
        if delta == 0:
            return
        side = "buy" if delta > 0 else "sell"
        order = self.create_order(symbol, abs(delta), side)
        self.submit_order(order)
        self.log_message(
            f"{side.upper()} {abs(delta)} {symbol} "
            f"(weight {target_w:+.3f}, NAV ${nav:.2f})"
        )
