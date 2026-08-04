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

One boundary case needs a separate, auditable rule. If Yahoo and Stooq exceed
the five-basis-point price limit by no more than one USD price tick, their daily
volumes agree within 0.001%, and Kibot's volume differs by more than 0.1%, the
two primary histories identify the same consolidated session while the guest
adjudicator does not. The canonical value is then Yahoo's unadjusted print and
the date is recorded as `primary_volume_supported_repair`. The raw
five-basis-point failure remains visible; this rule reconciles it rather than
raising the acceptance threshold.

The observed smoke boundary is 2008-09-12: Yahoo close/volume is
126.09/297,851,200, Stooq is 126.02211778261/297,851,196, and Kibot is
125.75/288,993,178. Yahoo and Stooq differ by 5.38 basis points and only four
shares of volume; Kibot's volume differs by roughly 3%. The rule therefore
chooses 126.09 and records all three raw observations in provenance.

When a confirmed opening or closing print falls just outside Stooq's original
high-low range, the range is expanded only far enough to include that confirmed
print. The audit lists every field-level consensus decision and every
mechanical OHLC-range repair; volume remains intact.

Kibot does not supply strategy features, returns, distributions, rankings, or
selection data. Its sole role is to adjudicate isolated raw open/close
disagreements before the unchanged open-to-open total-return ledger and causal
close-derived signals are built.
