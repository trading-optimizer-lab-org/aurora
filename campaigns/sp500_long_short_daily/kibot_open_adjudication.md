# Kibot execution and signal-price adjudication

The frozen campaign keeps Stooq as the primary raw OHLCV source, Yahoo as the
independent reconciliation source, and State Street distributions as the
official event source. A bounded Kibot guest-API daily response is used only as
a third-source adjudicator when Stooq and Yahoo raw opening or closing prices
differ by more than the frozen five-basis-point tolerance. Open drives
execution; close drives the frozen causal signals.

The implementation never replaces an opening or closing price without
third-source support. It uses Yahoo when Kibot agrees only with Yahoo, uses
Kibot itself when its value lies within tolerance of both vendors, retains
Stooq when Kibot agrees only with Stooq, and records any date on which no pair
agrees. Every request has explicit start and end dates, requests the unadjusted
ETF feed, stores the raw bounded response with SHA-256 provenance, and is
rejected if it crosses the train, validation, or locked boundary.

If no pair is within five basis points but all three values remain inside a
25-basis-point total band, the canonical value is their median. This bounded
fallback cannot select an extreme vendor print. The five-basis-point return
gate remains unchanged. A wider three-source spread stays unresolved and
blocks the campaign.

When a confirmed opening or closing print falls just outside Stooq's original
high-low range, the range is expanded only far enough to include that confirmed
print. The audit lists every field-level consensus decision and every
mechanical OHLC-range repair; volume remains intact.

Kibot does not supply strategy features, returns, distributions, rankings, or
selection data. Its sole role is to adjudicate isolated raw open/close
disagreements before the unchanged open-to-open total-return ledger and causal
close-derived signals are built.
