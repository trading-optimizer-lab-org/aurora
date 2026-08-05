# SP500 Long/Short Daily V2 Campaign Mapping

## Frozen boundaries

- Instrument: SPY only.
- Position: exactly `+1` or `-1`; never cash or leverage.
- Decision: after regular close `t`; execution at next tradable SPY open.
- Train ends `2010-12-31`.
- Validation is `2011-01-01..2020-12-31`, opened once after a verified freeze.
- Every market observation dated `2021-01-01` or later is forbidden.

## Repository mapping

| Responsibility | Implementation |
| --- | --- |
| Exact package, V1 hashes, cardinality and boundaries | `infra/sp500_long_short_daily_v2/contracts.py` |
| Audited V1 ledger plus bounded fixed-ETF panel | `infra/sp500_long_short_daily_v2/data.py` |
| Frozen 24-family signal state machines | `infra/sp500_long_short_daily_v2/signals.py` |
| Cumulative V1+V2 WRC, SPA, PBO, DSR and FDR | `infra/sp500_long_short_daily_v2/statistics.py` |
| GitHub train, merge, ranking and immutable freeze | `infra/sp500_long_short_daily_v2/workload.py` |
| One-shot validation guard and evaluation | `infra/sp500_long_short_daily_v2/validation.py` |
| GitHub orchestration | `.github/workflows/sp500-long-short-daily-v2-campaign.yml` |
| Package, causal, numerical and boundary tests | `tests/test_sp500_long_short_daily_v2_campaign.py` |

The authoritative package and both exact V1 artifacts are preserved byte-for-byte under
`campaigns/sp500_long_short_daily_v2/`. V2 never resets the V1 multiplicity history.
