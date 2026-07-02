# Validation Checklist for Codex

1. Confirm 72,000 strategies loaded.
2. Confirm 360 shards with 200 strategies each.
3. Confirm locked remains closed from 2021-01-01.
4. Confirm no validation data after 2020-12-31.
5. Confirm no heavy local backtest.
6. Confirm smoke uses GitHub Actions.
7. Confirm `optimized_evaluation_mode=optimized_evaluation_v5_event_first`.
8. Confirm holding diagnostics exist.
9. Confirm `leaderboard rows == total_strategies_evaluated`.
10. Confirm no full run before user approval.
