# v52: v51's CRASH-long book on 2016-2017, years v51 never used: pre-registration

Written and committed on 2026-10-31, after v52's data job started (it only fetches bars and counts events) and before
any v52 return was computed.

## 1. Why

v51's pre-registered answer failed after 2022. After the run, all six confirmed books with all-paths ruin at most 2.5%
held CRASH-long c_1555 d1pm. That pattern was found by looking at all of 2018-2026, so every 2018-2026 figure for it
is biased upward, and a walk-forward inside 2018-2026 cannot remove the bias: the family was chosen with those years.
v51 used events from 2018-01-02 on; the daily panel and Alpaca's SIP bars start in January 2016. Events from
2016-02-01 to 2017-12-29 were never used by v51 (earlier daily and minute studies, v18-v28, had 2016+ in their designs;
none produced these configurations). v52 runs the frozen book there with v51's engine unchanged.

## 2. Data

- v51's event superset and filters on 2016-02-01 to 2017-12-29 (the first weeks of 2016 lack 20 sessions of history),
  one-minute bars 04:00-19:59 for the event day and the next H sessions, H chosen as in v51 with a 0.8 GB budget at
  6.5 KB a symbol-day (v51 measured 6.1), so the Actions cache stays under 10 GB and no cache is evicted.
- FINRA short interest starts in 2018. Before it, the HOT tier rests on the gap, the rise and the threshold list
  only, so some HOT shorts may be labelled HTB. A stress set treats every short as HOT.

## 3. Frozen (`data/v52_frozen.json`, from v51 run 41213703767)

- **H1, the only hypothesis that decides**: CRASH-long c_1555 d1pm/t0.25/s1.00 [prior dollar volume $1M or more]
  30% + RUNUP-short c_ah5 d10c [close 4 times the five-session low, $1M] 30% + FADE-short c_pm0 d1pm/t0.50/s1.00
  [$2-20] 30%, at most 5 new a day (v51 selections 6, 60 and 88).
- Reported only: the other five v51 books with all-paths ruin at most 2.5%, v51's answer, v50's book in v51's terms;
  the 10 CRASH-long selections alone at 10/20/30/40%, 3 and 5 new a day; all 193 of v51's selections at the trade
  level (trades, PF, mean, worst on 2016-2017 next to their 2018-2022 and 2023+ PF).

## 4. Engine and paths

v51's engine, fills, TZC costs and account rules unchanged. One-year paths are drawn from the sessions 2016-02-01 to
2017-12-29 (v29's bootstrap: 4,000 paths, blocks of 20, five equity levels) from $5,000, ruin at or under $1,250;
31 seeds (seed 0 keeps every candidate, the others drop 10%), at base and with a HOT locate of $0.05. Trades still open
on 2017-12-29 count up to that session. Stress sets: borrow x2, locates never fail, locates fail HOT 25% / HTB 5%,
every short HOT, the symbol halves; and the actual sequence from $5,000 through the two years.

## 5. Decision

**MET** if H1's ensemble median is $10,000 or more with ensemble ruin at most 2.5%, at base and at HOT 5%. One book,
no choice among books, so no selection on 2016-2017. Everything else only reports.

## 6. Caveats fixed now

- Two years, an older market with fewer small-cap events than 2020-2021; a small sample.
- The tier caveat of section 2; extended-session limit fills stay optimistic as in v51.
- A pass supports the book on years not used to find it; it does not make 2018-2026 figures unbiased.
