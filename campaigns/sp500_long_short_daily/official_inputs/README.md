# Official bounded inputs

This directory intentionally contains no reconstructed or convenience data.

The campaign requires a State Street sponsor export containing SPY ex-dates
and per-share distributions. Train and smoke use:

```text
state_street_spy_distributions_through_2010.csv
```

Validation, only after the train freeze and the explicit validation gate, uses:

```text
state_street_spy_distributions_2011_2020.csv
```

Required columns are `ex_date` and `distribution`. A file containing any date
outside its phase is rejected. Yahoo events are an independent comparison and
are never labelled as State Street data.
