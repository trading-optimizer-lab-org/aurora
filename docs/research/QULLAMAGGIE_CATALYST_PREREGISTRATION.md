# Qullamaggie phase 5, episodic pivots with a real earnings catalyst: pre-registration

Written and committed on 2026-10-18 **before any SEC data was downloaded or any result computed**. Question: his
episodic pivots are gaps on unexpected earnings with big growth. Does requiring a real earnings release, and
strong revenue growth, improve the intraday EP results of phases 1-4
([QULLAMAGGIE_SIZING_RESULTS.md](QULLAMAGGIE_SIZING_RESULTS.md))?

Exact rules are the code in `research/qullamaggie_catalyst.py`. Everything not stated is as in the earlier
phases (intraday EP rule `IEP_*_Q05_K5_XQ3_20`, breakouts `MODEL` top 3, 0.5% risk, 20% cap, 2016-2020).

## Data (SEC EDGAR, free; nothing after 2020-12-31 is used)

- Ticker to CIK from the SEC's `company_tickers.json` (today's tickers, like the panel).
- Earnings releases: 8-K filings listing **Item 2.02** (results of operations) from each company's submissions
  history (`data.sec.gov/submissions`).
- Revenue: the XBRL frames API (`data.sec.gov/api/xbrl/frames`), quarterly values (`CY####Q#`) of `Revenues`,
  `RevenueFromContractWithCustomerExcludingAssessedTax` and `SalesRevenueNet`, in that order of preference.
- Requests identify themselves with the `SEC_USER_AGENT` repository secret, as the SEC requires, at most 8 a
  second. Data stays in the Actions cache; only reports are published. Coverage (share of EP candidates with a
  CIK, filings and revenue) is reported.

## Catalyst labels for an EP gap on day t

- `EARN`: an Item 2.02 8-K with filing date on the prior trading day or on day t (after-close and pre-market
  releases; EDGAR dates filings after 17:30 to the next business day).
- `EARNG`: `EARN` and revenue of the latest calendar quarter that ended 5 to 120 days before t is at least 25%
  above the same quarter a year earlier. The figure comes from the later 10-Q/10-K XBRL, used as a proxy for the
  number in the press release that caused the gap (the information was public at the open; only our structured
  source is later). Quarters without both values do not qualify.
- `NOEARN`: a company with filings data and no Item 2.02 8-K in that window.
- `ANY`: no catalyst requirement (as in phases 2-4).

## Trials (16)

`CAT_<ANY|EARN|EARNG|NOEARN>_<N1|N0>_<EP|MIX>`: catalyst x the "not rallied" filter (`N1` as before, or `N0`
without it, since a real surprise matters more than the prior trend) x book (`EP` alone, or `MIX` with the three
best model-scored breakouts of the day). `CAT_ANY_N1_EP` and `CAT_ANY_N1_MIX` must reproduce `I_EP_E0`
(phase 2) and `I_MIX_MODEL_N3_E0` (phase 3).

Reporting as in phase 4 (2016-2018, 2019-2020, 2016-2020; pass criteria on 2016-2020; deflated Sharpe over these
plus all 249,182 earlier trials), plus trade-level EP statistics per label.

## Limits

Same period as phases 1-4 (already seen): a lead at most. The clean tests remain forward paper trading and the
locked 2021+ period, used once and only on the owner's request.
