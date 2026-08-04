# Official bounded inputs

Training uses two frozen official layers and one operational source:

1. `state_street_spy_distribution_events_2006_2010.csv` contains exact SPY
   ex-dates and amounts from the State Street page archived on 2011-01-03. The
   page itself is explicitly dated 2010-12-29 and contains no later event.
2. `sec_spy_distribution_fiscal_totals_1993_2009.csv` contains audited
   per-share totals from SPY SEC filings. Those periods cover the earlier
   history and overlap State Street for an independent check.
3. Yahoo's bounded event endpoint supplies operational rows only after every
   row passes the exact-event or audited-period gate. Yahoo rows are never
   labelled as State Street or SEC data.

`official_source_audit.json` records the source URLs, limits and the discarded
Wayback redirect that returned a later workbook. That workbook is not a
campaign input.

Validation, only after the train freeze and the explicit validation gate, uses:

```text
state_street_spy_distributions_2011_2020.csv
```

Validation remains unavailable until train selection is cryptographically
frozen and the exact `OPEN_VALIDATION_2011_2020_ONCE` acknowledgement is
supplied. A file or response containing 2021 or later is rejected.
