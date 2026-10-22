# v28: the small-cap megarun: pre-registration

Written and committed on 2026-10-22, before any v28 result was computed, at the owner's request ("prepara un megarun
nocturno enorme para probar todo lo posible"; plan approved with "si"). The list of ideas is
docs/research/SMALLCAP_PENDIENTE_ES.md plus the additions of the plan. Exact rules: `research/v28_ideas.py`,
`scripts/run_v28.py` (on `scripts/run_v26.py` and `scripts/run_v22.py`), the data in `scripts/run_v28_data.py`;
tests in `tests/test_v28.py`. Workflows: `v28-data.yml`, `v28.yml`, and `v28-after.yml` (the after-report stages of
section 6, committed before the report exists).

## 1. Data (all free; nothing published)

- **SEC**: quarterly form indexes (EFFECT, NT 10-K, NT 10-Q, S-4, 424B4); full-text search hits in ten-day windows
  ("substantial doubt" in 10-K/10-Q; "treasury reserve asset", "digital asset treasury", "bitcoin treasury", "crypto
  treasury", "consummated the previously announced business combination", "PDUFA", "share/stock repurchase program"
  in 8-Ks); the PDUFA target dates read from those 8-Ks (a date within 250 characters of the word, 1-500 days after
  the filing); XBRL company facts (cash, quarterly operating cash flow and net income, assets, equity) by filing date;
  SIC codes and former names; the fails-to-deliver files. v14's 8-K items (3.02 unregistered sales, 2.02 earnings,
  8.01 other events). Every filing maps to the first session after its date (v14's ticker history).
- **Nasdaq** daily Reg SHO threshold lists (the list of a session is the one published for it).
- **FINRA** consolidated short interest, as far back as its API serves (about 2018); usable 12 days after the
  settlement date. Fails to deliver: 31 days after the settlement date.
- **VIX** (FRED). ICE's high-yield spread on FRED has only three years, so the credit regime is HYG over IEF instead.
- **Gap-day premarket store**: Alpaca SIP minute bars from 16:00 of the session before to 09:29 of every small-cap
  gap of 15% or more (prior close $1-$20, $500k of prior 20-day dollar volume, the 100 largest gaps a session), in a
  seeded random order within a 150-minute budget; the report states the coverage.
- The v18b inputs, the v23 liquid, v24 mover and v26 night stores, as in v26.

## 2. Block B: v26's entries with new filters (shield 2)

The 103 entries of v26 (the walk-forward picks of the 23 families that passed in v19r-v25), crossed with: hold d1,
d2, d3, d5 and **d10** (new); v26's seven stops; v26's four extended-session stops; and either one of **30 filters**
(no target) or one of three **profit targets** (cover at a fall of 20%, 30% or 50% from the entry, on the daily lows
of the sessions after the entry day; filled at the open when it opens below; no filter). An intraday entry held to its
own close has no night, so no extended-session stop and no target. Rally exits and split covers (no help in v26) are
left out. 425,838 configurations.

Filters (unknown values keep the trade, except the 'keep only' rules):
- fails to deliver over shares outstanding (max of the last 10 known settlement days) at least 0.5%, 1%, 2%: skip;
- on the threshold list in the last five sessions: skip; or keep only those;
- short interest at least 10% or 20% of shares outstanding: skip; days to cover at least 3 or 5: skip;
- cash runway (cash over the monthly operating cash burn of the latest reported period, 3-12 months, as 10-Qs report
  cash flows year to date) under 6 or 12 months: keep only those;
  12 months or more: keep only those;
- a going-concern doubt filed in the last 400 sessions: keep only those; or skip them;
- shares outstanding up 20% or 50% over 250 sessions: keep only those;
- the count of small caps closing +50% the session before at or over its 250-session 80th or 90th percentile: skip;
- Bitcoin up 10% over five days, IWM up 4% over five days, ARKK over its 50-day average, HYG/IEF over its 50-day
  average, VIX under 15 (all at the prior close): skip;
- entries on Fridays, or on Thursdays and Fridays: skip;
- an 8-K 2.02 that session or the one before: skip;
- **squeeze model** (ml10, ml20, ml30): skip the name-days in the riskiest 10/20/30% of the model's training scores.
  Each year from 2017 a logistic regression (L2, standardized features) is fit on the earlier years' candidate
  name-days (small caps with a gap of 10% or more, a prior day of +20% or more, or a close 50% over the 20-session low;
  only rows whose label is known before the year starts). Label: the high of the session or the two after reaches 50%
  over the session's open. Features at the open: gap, prior-day return, rise over the 20-session low, price, dollar
  volume, shares outstanding, prior-day float rotation, fails to deliver, threshold list, short interest (and whether
  known), days to cover, cash runway, going concern, recent offering, dilution, mania count, VIX, Friday, listing age,
  a +100% day in 60 sessions, earnings 8-K.

## 3. Block C: new short entries (under the shield)

Daily event families, each crossed with: run-up before (any; +30% over the 5-session low; +100% over the 20-session
low), price band ($1-5, $5-20), trigger (the next open; the first close under the prior low in five sessions; the
first red close in five sessions; v19's triggers), hold d1-d10, stops 10/20/35/50%, 2 and 4 ATR, the four
extended-session stops; one entry a symbol in 20 sessions.

| family | event (setup known before the entry) | parameters |
|---|---|---|
| EFFECT | an EFFECT notice | any; only after an 8-K 3.02 in the 120 sessions before |
| PIPE | an 8-K with item 3.02 | |
| NT | NT 10-K or NT 10-Q | |
| GC | the first going-concern doubt in 400 sessions | |
| CRYPTO | an 8-K with a crypto-treasury phrase | |
| RENAME | a former name ends (name change) | |
| DESPAC | an 8-K closing a business combination | |
| S4 | an S-4 | |
| EARN | an 8-K 2.02 and the session closes +15% or +30% | |
| IPO | a listing after 2016-02 with a 424B4 in the 20 sessions up to it, closing 50/100/300% over its first open within ten sessions | |
| LOCKUP | 62 or 124 sessions after such a listing, entered 5 or 1 sessions before | open only |
| SYMPATHY | a same-SIC company closes +50%; this one closes +10% or +20% without an 8-K | |

Premarket entries (C:PM): on the gap day, at 07:00, 08:00, 09:00 or 09:25, on that minute bar's open, when the price is
20/40/80% over the prior close (any; or 10% under the premarket high so far); stops 20/35/50% live on the premarket
bars after the entry, then as in the shield; hold d1-d5; band; extended-session stops none or both. After-hours
entries (C:AH): a session closing +30/60/100%, at 16:05, 16:30, 17:30 or 19:00 on that bar's open (any; or only under
the regular close); stops live on the after-hours bars after the entry (and the next premarket with 'pm'); the night's
P&L is booked with the next session; one night of borrow. Their placebos move each real trade to a random other
symbol of the same store night, at the same minute and rules.

## 4. Block D: longs and diversifiers (own exits)

- PDUFA run-up: buy the open 40/20/10/5 sessions before a PDUFA date read from an 8-K filed before the entry, sell
  1 or 3 sessions before the date; stops none/15%/25%; band low/high/all; any or not already up 50% over 20 sessions.
- Buyback: an 8-K with a repurchase program; the next open or the first green close; hold 5/10/20; stops none/10/20%;
  band; any or under 50 million shares.
- January losers: at the last or fifth-last December close, small caps down 40/60/80% since the year's first close;
  sell at the 5th/10th/20th January close; band.
- Mania basket (the squeeze hedge): after a session whose +50% count is at or over its 80th/90th percentile (or every
  session), buy the top 3/5/10 gainers at the next open; hold 1-3; stop none/15%.
- Monthly factor books: at each month's last close, small caps over $1 or $3 with $1M or $5M of dollar volume, ranked
  by cash runway, return on assets, net issuance (less is better), going concern (none is better) or their average z;
  long the best 10/20%, short the worst, or both; borrow from v15's table; costs per rebalance.
- Leveraged ETF pairs: short both legs (IWM pairs only; index pairs; all available of 15 pairs), equal weights reset
  weekly or monthly, flat after a VIX close over 30 or not; borrow 5% a year (x3 high), 5 bps a rebalance.

Placebos: v19's daily placebo (the same entries on random symbols of the band that day); factor books rank at
random; ETF pairs short random liquid stocks ($50M a day) instead.

## 5. Costs, selection and target

**466,074 configurations in 43 families** (B 425,838; C events 37,440; premarket 1,152; after-hours 1,152; D longs 360,
factor books 120, ETF pairs 12).

R4 with v26's extended-session legs, scenarios low/middle/high/auction/gross; sizing as the source families (intraday
0.5% risk to the stop, 20% cap, 2% of the dollar volume before the entry, five trades a day; daily 5% cap, 1% of the
20-day dollar volume). run_v22's procedure unchanged: walk-forward 2018-2026 with the activity rule, plateau picks by
family each year on earlier data, 500 placebos for each selected configuration, the gate, `COMBO28` (a family joins a
year when its pick scored at least 1.0 and beat its placebos at p <= 0.05; inverse-volatility weights), CPCV PBO,
Hansen's SPA and the deflated Sharpe over all v28 configurations and the earlier trials. Selection by Sortino alone.
**Target: COMBO28 monthly Sortino 4 (3 in each half, PBO under 20%, 3 in 2023-07+)**, as v26.

## 6. After the report (v28-after.yml)

**A. Realism of the one-account book** of COMBO28's members (and of COMBO26's, for comparison), v26's book rules
(one position a symbol, at most 20 open, v14's liquidity caps):
- margin by price as TradeZero International states it: a short under $2.50 needs $2.50 a share; $2.50-$5, 100% of
  its value; $5 or more, a sixth intraday and half overnight; after-hours, $5 a share under $2.50. The sum of the
  open positions' requirements may not pass the equity. Variant TradeZero US: $5 a share under $5 at all times.
  Variant none: v26's notional cap.
- locate cost per short of 0, 0.25, 0.5, 1, 2, 3% of its value; pre-borrow of 0, 0.5, 1% a night held;
- spreads x1, x1.25, x1.5, x1.75, x2; intraday entries 0, 1, 2, 5 minutes late (B families);
- each year left out; before and after 2024-05-28 (T+1) and 2025-01-17 (Nasdaq's accelerated delisting);
- accounts $25k, $100k, $250k, $500k, $1M;
- the 50 worst trades listed with flags (a pause of four minutes or more in the entry day's bars, a split factor
  change while held, an open through the stop).

**F. Book construction**: at most 10/20/30 open; at most 3/5/10 new trades a day; order of entry by time (v26), size
of the move, liquidity, or lowest squeeze-model score; at most two open a four-digit SIC code or no limit; risk 0.25,
0.5, 1, 1.5, 2%; caps 20/40%; gross 1/1.5/2x. **The choice**: the owner's rule of v19s (the highest median bootstrap
CAGR with a chance of a 75% drawdown in ten years of at most 1%, gross at most 2x) under TradeZero International's
margin with a 0.5% locate cost per short at the middle costs; the high-cost twin is reported.

**G. Symbol halves**: each family's walk-forward stream recomputed on each half of the symbols (SHA-256 parity of the
ticker, as v27), with the same picks. This is weaker than v27's holdout (the picks saw both halves); it shows whether
a result rests on one half of the names.

## 7. Notes added before any result (2026-10-22, after the canary)

- IPO family: a new listing has no 20-day dollar volume in its first ten sessions, so its size cap and liquidity
  filter use the mean dollar volume of its sessions so far (DV) and before the entry (DV1); other families unchanged.
- The shards take blocks of 50 neighbouring configurations in a seeded random order (the premarket and after-hours
  families are slow); the configurations and their names are unchanged.
- Premarket and after-hours trades are walked once at the middle slippage; their gross record reuses those walks.
