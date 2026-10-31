# v51: every small-cap setup on one-minute bars with premarket, after-hours and overnight holds: pre-registration

Written and committed on 2026-10-31, before any v51 return was computed (the data job only fetches bars and counts
events). The owner asked for one run that re-tests everything tried in small caps plus new ideas, on one-minute bars,
with premarket, after-hours and overnight holds, under TradeZero's real costs and rules, showing where the edge is.
Target as before: a one-year median of $10,000 from $5,000 with ruin of at most 2.5%.

## 1. One engine for every family

v14-v50 used many engines and cost models, so their figures cannot be compared. v51 rebuilds the small-cap families
as **setup x side x entry x exit x filters** on one engine:

- **Setups** (event day e, prior close pc, all prices split-adjusted; prior raw close $0.50-$20, prior 20-day dollar
  volume of $500k or more, from 2018-01-02):
  - close-decided: **RUNUP** close / five-session low (lows, e-4..e) of 2.5, 3, 4 or 6 or more (DS1, RU);
    **STRONG** close +30, +50, +100 or +200% over pc (day-2 fades, ON1); **FADE** open +30% or more, close 10% or more
    under the open and in the low quarter of the range, open +30/50/100/200% (NS); **CRASH** close -20, -30, -50 or
    -70% (bounces and continuations).
  - open-decided: **GAPUP** open +20, +30, +50 or +100%; **GAPDN** open -15, -25, -40 or -60% (gap fades, B8, S1, XS).
  - intraday-decided: **RUN40, RUN60, RUN100, RUN200**: the first regular-session minute whose high reaches pc +40, 60,
    100 or 200%; entries only after that minute (v22's lesson).
- **Sides**: short and long, every setup.
- **Entries** (minute 0 = 04:00 ET):
  - close-decided (19): the event day at 15:55 at market with the signal re-evaluated on the bars to 15:49 (no
    closing auction in the API, v47); after-hours resting limits at the close +0/5/10% (short; long -0/5/10%),
    16:01-19:59; next-day premarket resting limits at the close +0/5/10/20%, 04:00-09:28; next open auction; next
    day at market at 09:45, 10:30, 12:00, 15:55; next-day regular-session resting limits at the close +5/10/20%; next-day
    one-minute triggers: opening-range break (5 minutes), VWAP loss (reclaim for longs), high-of-day fail (10% off a
    high of +30%; low-of-day bounce for longs).
  - open-decided (13): at market at 09:31, 09:45, 10:30, 12:00, 15:55; the three triggers; after-hours limits at the
    close +0/10%; next premarket limits +0/10%; next open auction.
  - intraday-decided (8): at market 1, 16 and 61 minutes after the trigger; high-of-day fail after it; 15:55 if the
    trigger came before 15:50; after-hours limit at the close; next premarket limit at the close; next open auction.
- **Exits** (81) = time x target x stop. Time: the entry day at 15:55; the next open auction; next premarket resting
  limit at the entry day's close -3% (short; +3% long) or else the open; next day 09:45; next day 15:55; day 2 and
  day 3 at 15:55; day 5 and day 10 at the close. Target: none, 25%, 50% (resting limit, 04:00-19:59 every day).
  Stop: none, 25%, 100% (stop-limit with the limit 5% beyond the stop, 04:00-19:59; triggered and not filled, it is
  covered at the next open auction if triggered outside the session, else at market 5 minutes later). Stop before
  target when both hit in one bar or day.
- **Filters** (all known at the decision): prior raw close $0.50-1 / 1-2 / 2-5 / 5-10 / 10-20 (any contiguous range);
  setup strength (the four thresholds above); prior dollar volume $0.5M / 1M / 3M / 10M or more; shares outstanding
  (all, known only, under 10M, under 50M, 10M or more); borrow tier at the entry (all, no HOT, HOT only); listing age
  (all, under a year, a year or more). 10,800 filter sets.

## 2. Data

- Daily panel: v18b's (`v18-inputs`), survivorship-free FINRA universe.
- One-minute bars: Alpaca SIP, 04:00-19:59 ET, raw, scaled by the panel's split factor, for every symbol-day of the
  **event superset** (a high +20% over pc, a low -15%, or a high 2.5 times the five-session low, with the universe
  filters) and the next H sessions. The superset only decides which bars are fetched; every setup's trigger at any
  minute lies inside it. H is the largest of 3, 2, 1 whose estimated size fits 2.3 GB, so the Actions cache stays under
  its 10 GB limit and no old cache is evicted. Days after H use daily bars (stops and targets on the day's high and
  low, stop first).
- The 20:00-04:00 session is not modelled: TradeZero trades 04:00-20:00 only, and its data is a separate paid feed.

## 3. Fills and costs (TZC, v49-v50)

- Market orders fill at the open of the first minute bar with volume at or after the order (within the session),
  plus the half-spread of the price tier and leg: R4 (open, session, last minute; v22) in the session; in the
  premarket and after-hours 1.5 times v26's measured extended-session half-spread (<$2 0.69%, $2-5 0.62%, $5-10 0.38%,
  $10-20 0.27%). Open auctions fill at the official open with R4's open leg.
- Resting limits fill only when a bar trades through the limit by 0.1%, at the limit or the bar's open if better,
  with no spread. Outside the session TradeZero takes only limit and stop-limit orders; the model uses only those.
- TradeZero International: $0.005 a share (minimum $0.49, maximum $7.95 a leg), SEC and TAF fees, the reporting fee.
  Shorts: no entry under $0.50; skipped under the SEC price test (a low 10% under the prior close on the prior
  session or before the entry); per-share locate $0.01 HTB and $0.03 HOT (HOT 5% task: $0.05); borrow by calendar
  day at the model's rate (twice the IBKR cell fee, at least 100% a year); 9% margin interest by calendar day;
  failed locates HOT 50% and HTB 10% (seeded as v49). Longs: 9% margin interest by calendar day. Tiers as v29.
- Data cost by entry: FREE (daily facts, resting orders, fixed-time market orders; the server, $6 a month), IEX (a
  free IEX snapshot to scan the open or 15:50, $6), PAID (one-minute triggers need full real-time SIP, $105).

## 4. Stages and decision rule

1. **Factory and grid** (one job per setup and side): every event's minute path walked once per entry for all 81
   exits; returns net of TZC costs at a $1,000 reference size. For every entry, exit and filter set: the score
   **(PF - 1) x trades a year** on design 2018-2022, vetoes at least 10 trades a year and PF 1.1 in design. The 2023+
   PF, the yearly table and the worst trade are reported. Edge maps: each dimension's marginal for the best exits.
2. **Selection**: the top 200 configurations across groups by design score, at most 10 per group, identical trade sets
   counted once.
3. **Account alone** (300+ runners): each selection at sizes 10/20/30/40% of equity (capped at 1% of the prior dollar
   volume), at most 3 or 5 new a day, 10 open: v29's one-year bootstrap (4,000 paths, blocks of 20, five equity levels)
   from $5,000, ruin at or under $1,250, 5 dropout seeds (10% of candidates out). The account: overnight margin
   (2:1, $2.50 a share under $2.50), intraday positions up to 6:1 (TradeZero International), one position at most 50%
   of buying power, liquidation when equity falls to 15% of the short value at the day's adverse extreme (all
   positions at once, conservative).
4. **Books**: the 12 best single configurations by design median with design ruin at most 2.5% at base and HOT 5%;
   every book of 1-3 of them at 10/20/30% each, 3 or 5 new a day.
5. **Confirmation**: the 50 best books by design median, plus v50's book written in v51's terms (DS1: RUNUP 4,
   next open, target 50% or day 5 at 20%; RU: RUNUP 4, next open, target 50% or day 10 at 20%; NS: FADE, $2-5, 15:55,
   day 3 at 60%; dollar volume $1M or more), with 31 seeds at base and HOT 5%, and stress sets: borrow x2, locates
   never fail, locates fail HOT 25% / HTB 5%, the symbol halves.
6. **Answer**: among confirmed books with ensemble ruin at most 2.5% on design paths at base and HOT 5%, the highest
   ensemble median on design paths. **MET** if its all-paths median is $10,000 or more with all-paths ruin at most
   2.5% at base and HOT 5%. If none passes, no answer.

## 5. Caveats fixed now

- Hundreds of millions of configurations on data already seen 2018-2026: the best is biased upward. Design 2018-2022
  chooses; 2023+ and the symbol halves only report. The total count is reported for the deflation.
- v51's account engine is new; v50's book in v51's terms is reported next to v50's $9,065 to show the difference.
- Locate failure rates and borrow rates are model assumptions, the largest cost (v50); every confirmed book is shown
  with locates never failing and failing half as often.
- No SEC filing tags in the grid filters; listing age stands for IPO age; issuer country is not modelled.
- Daily bars after H sessions; no 20:00-04:00 session; the closing auction is not used.

## 6. Amendments before any return (2026-10-31, after a code review, before the run)

- Confirmation takes the 50 best books by design median **and** the 50 best of those eligible at 6 seeds (up to 100
  books), plus v50's book; the answer rule is unchanged and v50's book can be the answer.
- RUN setups: the trigger may come at any regular-session minute; entries that need time after it (1, 16 or 61
  minutes later, 15:55, the high-of-day fail) still need it before 15:50 or 15:55.
- The borrow-tier filter uses the tier at the entry: the signal day's, and the entry day's once its open is known.
- Forced liquidation counts the loss an open position carries from its earlier sessions.
- Definitions fixed in code: the long high-of-day trigger is a 10% bounce off a low of -20% or more; a market exit
  with no trade from its minute to 15:59 fills at the official close; a triggered stop-limit is marketable and pays
  the half-spread.
