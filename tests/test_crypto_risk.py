"""Tests for aurora.risk.crypto_risk (R185)."""
from __future__ import annotations

import pytest

from aurora.markets.crypto_derivatives import (
    CryptoInstrument,
    CryptoInstrumentKind,
)
from aurora.risk.crypto_risk import (
    CryptoRiskRefusal,
    FundingDragExceeded,
    LeverageBreached,
    SymbolDelisted,
    assert_funding_drag_below,
    assert_leverage_within_limit,
    assert_symbol_active,
)


# ---------------------------------------------------------------------------
# Leverage refusals
# ---------------------------------------------------------------------------


def test_leverage_within_limit_passes() -> None:
    """A 2x leverage proposal under a 3x cap passes silently."""
    assert_leverage_within_limit(notional=20_000.0, equity=10_000.0, max_leverage=3.0)


def test_leverage_breach_refused() -> None:
    """5x leverage under a 3x cap raises LeverageBreached."""
    with pytest.raises(LeverageBreached, match="exceeds max allowed"):
        assert_leverage_within_limit(
            notional=50_000.0, equity=10_000.0, max_leverage=3.0
        )


def test_leverage_breach_message_is_human_readable() -> None:
    """The refusal carries a plain-English reason."""
    try:
        assert_leverage_within_limit(50_000.0, 10_000.0, 3.0)
    except LeverageBreached as exc:
        msg = str(exc)
        assert "leverage" in msg.lower()
        assert "5.00x" in msg
        assert "3.00x" in msg
    else:
        pytest.fail("expected LeverageBreached")


def test_leverage_short_notional_handled() -> None:
    """Negative (short) notional still computes leverage as |notional|/equity."""
    with pytest.raises(LeverageBreached):
        assert_leverage_within_limit(
            notional=-50_000.0, equity=10_000.0, max_leverage=3.0
        )


def test_leverage_zero_equity_raises_value_error() -> None:
    """Zero or negative equity is a programming error, not a refusal."""
    with pytest.raises(ValueError, match="equity must be > 0"):
        assert_leverage_within_limit(1.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Funding drag refusals
# ---------------------------------------------------------------------------


def test_funding_drag_under_threshold_passes() -> None:
    """10% annualised funding under a 25% threshold (2500 bps) passes."""
    assert_funding_drag_below(annualised_funding=0.10, threshold_bps=2500.0)


def test_funding_drag_over_threshold_refused() -> None:
    """30% annualised funding above 2500 bps threshold is refused."""
    with pytest.raises(FundingDragExceeded, match="exceeds operator threshold"):
        assert_funding_drag_below(annualised_funding=0.30, threshold_bps=2500.0)


def test_funding_drag_negative_rate_uses_abs() -> None:
    """Large negative funding (rebate) also exceeds an absolute-value threshold."""
    with pytest.raises(FundingDragExceeded):
        assert_funding_drag_below(annualised_funding=-0.50, threshold_bps=2500.0)


def test_funding_drag_message_includes_bps() -> None:
    """The refusal message reports both observed and threshold in bps."""
    try:
        assert_funding_drag_below(0.30, 2500.0)
    except FundingDragExceeded as exc:
        msg = str(exc)
        assert "bps" in msg
        assert "3000" in msg or "3000.0" in msg


# ---------------------------------------------------------------------------
# Symbol-active refusals
# ---------------------------------------------------------------------------


class _StubRecord:
    def __init__(self, active: bool = True) -> None:
        self.active = active


class _StubRegistry:
    def __init__(self, records: dict) -> None:
        self._records = records

    def get(self, sym: str):
        return self._records.get(sym)


def _spot_inst(symbol: str) -> CryptoInstrument:
    return CryptoInstrument(
        symbol=symbol,
        kind=CryptoInstrumentKind.SPOT,
        base_currency="BTC",
        quote_currency="USDT",
        exchange="binance_spot",
    )


def test_symbol_active_happy_path() -> None:
    """An active record passes silently."""
    reg = _StubRegistry({"BTCUSDT": _StubRecord(active=True)})
    assert_symbol_active(_spot_inst("BTCUSDT"), reg)


def test_symbol_delisted_refused() -> None:
    """A record marked inactive is refused with a delisting reason."""
    reg = _StubRegistry({"BTCUSDT": _StubRecord(active=False)})
    with pytest.raises(SymbolDelisted, match="inactive"):
        assert_symbol_active(_spot_inst("BTCUSDT"), reg)


def test_symbol_unknown_refused() -> None:
    """A symbol not in the registry is refused."""
    reg = _StubRegistry({})
    with pytest.raises(SymbolDelisted, match="not present"):
        assert_symbol_active(_spot_inst("BTCUSDT"), reg)


def test_symbol_mapping_fallback() -> None:
    """A plain dict with active records is accepted via mapping fallback."""
    reg = {"BTCUSDT": _StubRecord(active=True)}
    assert_symbol_active(_spot_inst("BTCUSDT"), reg)


def test_symbol_mapping_inactive_refused() -> None:
    """A plain dict with an inactive record refuses via the mapping fallback."""
    reg = {"BTCUSDT": _StubRecord(active=False)}
    with pytest.raises(SymbolDelisted):
        assert_symbol_active(_spot_inst("BTCUSDT"), reg)


def test_refusals_inherit_from_base() -> None:
    """Every refusal type inherits from CryptoRiskRefusal."""
    for cls in (LeverageBreached, FundingDragExceeded, SymbolDelisted):
        assert issubclass(cls, CryptoRiskRefusal)
        assert issubclass(cls, ValueError)
