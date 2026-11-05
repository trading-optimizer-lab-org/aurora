# v55 results: v49's book decided on the free IEX price at 15:50

Run 42048053366 (2026-11-05), pre-registered in V55_PREREGISTRATION.md. Check passed: the sip source reproduces
v50's TZC answer for DS0.20-NS0.40-RU0.20-N5 exactly ($8,498, ruin 0.0%).

## Answer: PASS

| source | median from $5,000 | ruin | HOT5 median / ruin | 2023+ median / ruin | close entries kept / dropped / added |
|---|---|---|---|---|---|
| sip | $8,498 | 0.0% | $8,332 / 0.0% | $7,351 / 0.0% | 489 / 41 / 3 |
| **iex** | **$7,978** | **0.0%** | $7,836 / 0.0% | $7,244 / 0.0% | 401 / 129 / 3 |
| iex10 | $7,963 | 0.0% | $7,825 / 0.0% | $7,289 / 0.0% | 370 / 160 / 3 |

iex keeps 94% of sip's median (the bar was 90%) with no ruin at base costs or HOT5. The cost, about $520 a year
from $5,000, comes mostly from sessions the bot cannot decide: 129 close entries dropped against sip's 41.

## The IEX price against the consolidated one

- The fetch got 330,926 IEX bars over 1,726 sessions of v43's store; 448 sessions had no IEX bar for any needed
  symbol. Of sip's 4,914 decision sessions, iex decides 76.1% and iex10 50.9%.
- iex: the last IEX bar is a median 3 minutes old, but 33% are 10 minutes or older (90th percentile 111 minutes).
  Price error: median 0.52%, 90th percentile 3.1%, 99th 9.9%, over 1% in 34% of sessions. High and low errors are
  about twice that, since IEX sees only part of the day's range.
- iex10 halves the price error but decides on a third fewer sessions and ends no better: requiring a fresh price
  does not pay.

## Reading

- The bot can decide the close entries on Alpaca's free IEX feed: read the last IEX trade before 15:50 and the IEX
  high and low since 09:30, and skip a symbol with no IEX trade that day.
- Same-day volume is not needed: NS's signal is the gap, the drop from the open and the place in the range; sizing
  uses the prior 20 sessions' dollar volume. v49's volume cap on close entries (10% of 15:55-15:59 volume) models
  the fill, not a decision.
- Possible gain left: the ~90 extra dropped entries are worth up to about 6% of the median if a second free source
  can price the sessions IEX misses.
