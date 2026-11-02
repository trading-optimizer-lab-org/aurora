# v54s: CRASH-long under strict extended-session fills: pre-registration

Written and committed on 2026-11-02, before any v54s number was computed. v54d found that CRASH-long earns only
through limit orders filled outside regular hours: the premarket sell (d1pm: prior close +3%, else the open) and
the after-hours buy (c_ah0). The engine fills such a limit when any one-minute bar trades 0.1% through it, at the
limit or the bar's open if better, whatever the bar's volume. v54s asks whether the edge survives fill rules that
a thin print cannot satisfy.

## 1. Fill rules (every limit order in the extended sessions and in regular hours alike)

- **asis**: the engine's rule, unchanged (it must reproduce v54d's cells).
- **through1**: a bar must trade 1% through the limit; the fill is at the limit, never better.
- **vol3k1**: through1, and the dollar volume of the bars trading 1% through the limit, summed from the first such
  bar, must reach 3 times the order's value with a $1,000 order; the fill is at the bar where it does.
- **vol3k5**: the same with a $5,000 order.
- Dollar volume is the bar's share volume in the shares of the day times the split-adjusted price, divided by the
  split factor (raw dollars). A limit not filled falls back as in the engine (the d1pm exit sells at the open).

## 2. What is measured

- v54d's setup, data and cells: CRASH-long on v51+v52's minute bars 2016-2026, filter all, entries c_1555 and
  c_ah0, exits d1pm and d1o at no target or stop and at target 25% / stop 100%, net of TZC costs; by year and
  pooled 2021-2026: trades, PF, PF without the top and bottom 1% (trimmed), median trade; and the share of d1pm
  exits that are not the d1o exit (filled by the limit).

## 3. Decision

- **SURVIVES** under a rule if, for at least one entry, d1pm at no target or stop has pooled 2021-2026 trimmed PF at
  least 1.10 and a trimmed PF of at least 1.0 in at least 5 of the 6 years 2021-2026.
- Reading: survives under vol3k1 and vol3k5: the edge does not rest on thin prints. Under vol3k1 only: it exists at
  small size only. Not under vol3k1: CRASH-long is dropped for good, since its edge needs fills the market may not
  give.
- Check: asis must equal v54d's c_1555 d1pm/t0.00/s0.00 2024 cell (1935 trades, PF 1.14, trimmed 1.16).

## 4. Caveats fixed now

- One-minute bars hold no quotes and no trade-by-trade prints: the volume rule is a proxy for queue position, and
  it may still be optimistic (volume through the limit is not volume for us) or pessimistic (an order can fill
  on a bar that trades exactly at the limit).

## 5. Addendum, v54s2 (2026-11-02, after v54s's numbers, before v54s2's)

v54s's strict rules filled at the limit and never better. That also took away a fill a resting order does get:
when the bar that fills it opens beyond the limit (a premarket gap far above close +3%, an after-hours drop below
the close), the order fills near that opening print. v54s therefore mixed two changes, the stricter trigger and
the lost price improvement, and its "does not survive" cannot tell which one did it.

- **v54s2** reruns the three strict rules with the engine's price, the limit or the filling bar's open if better:
  **through1o**, **vol3k1o**, **vol3k5o** (same trigger and volume as through1, vol3k1, vol3k5), plus asis.
- Same cells, same decision rule (section 3) and the same reading, applied to the "o" rules. v54s's verdicts stay
  as they are in the record.
