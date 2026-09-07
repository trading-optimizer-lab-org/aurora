# Checkpoint performance during R1

The first operational release (R1) may retain declared transport overhead;
performance qualification belongs to R2. This does not waive scientific
equivalence, exact coverage, durable recovery, or integrity checks.

`recovery_execution.checkpoint_overhead_gate` is an approved policy field:

- `required` (default): reject checkpoint plans exceeding the 5% projected
  overhead target or the 600-second projected loss window.
- `report_only_r1`: report overhead without using that performance target as
  an admission veto. Keep the loss-window check and the same recovery rules.

The sealed checkpoint policy records the selected mode, upload estimate and
projected overhead for each worker. These are projections, not benchmark
results. In particular, feature-count scheduling weights and a single upload
probe cannot establish measured p99 computation or p95 upload-and-verification
latency. Do not report R2 performance qualification from these fields.

The normal chat request cannot select or change this mode. Its source is the
protected campaign policy, bound to preparation and the sealed execution plan.
Changing policy invalidates incompatible preparation; it never authorizes a
manual run or edits to installed receipts.

Both registered campaigns initially select `report_only_r1`. Restoring
`required` for R2 requires representative timing evidence and acceptance of
the resulting prepared execution plan. R1 itself still requires the full
protected-entry and scientific acceptance sequence; passing preparation alone
does not establish readiness.
