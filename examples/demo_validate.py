"""Demo: validate built-in strategies on SPY with full pipeline.

Requires an editable install with the GA + ML extras:
    pip install -e ".[ga,ml]"

Run:
    python quantforge/examples/demo_validate.py
"""
from __future__ import annotations

from quantforge.core.seed import set_global_seed
from quantforge.core.data_layer import load_asset, split_is_oos
from quantforge.core.costs import IBKR_costs, ZERO_costs
from quantforge.core.engine import run_backtest
from quantforge.strategies.library import MACross, RSIMeanRev, TSMomentum, DonchianBreakout
from quantforge.validation.pipeline import validate_pipeline


def main():
    set_global_seed(42)
    print("Loading SPY...")
    prices = load_asset("SPY", include_oos=True)
    print(f"  {len(prices)} bars from {prices.index[0].date()} to {prices.index[-1].date()}")

    strategies = [
        ("MACross_20_100", MACross, dict(fast=20, slow=100, allow_short=True)),
        ("RSIMR_2_10_90",   RSIMeanRev, dict(period=2, oversold=10, overbought=90)),
        ("TSMom_252",        TSMomentum, dict(lookback=252, allow_short=True)),
        ("Donchian_55_20",   DonchianBreakout, dict(channel=55, exit_channel=20)),
    ]

    for name, cls, params in strategies:
        print(f"\n>>> Validating {name}")

        def factory(_p=params, _c=cls):
            return _c(**_p)

        def factory_w(_c=cls, _p=params, **kw):
            merged = dict(_p)
            merged.update(kw)
            return _c(**merged)

        rep = validate_pipeline(
            strategy_factory=factory,
            prices=prices,
            name=name,
            n_trials_optimization=1,
            costs=IBKR_costs,
            spp_param_ranges=cls.spec().param_ranges,
            spp_strategy_factory=factory_w,
            mc_n_paths=200,  # quick demo
        )
        print(rep.report())


if __name__ == "__main__":
    main()
