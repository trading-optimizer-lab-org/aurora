# Data acquisition and causal normalization plan

## 1. Reuse the V1 target ledger exactly

The target P&L ledger is not rebuilt opportunistically. Codex must first verify the embedded V1 result artifact and reuse the audited SPY session/open/distribution logic. Any deliberate correction creates a new campaign version and invalidates cached V1 return streams for the combined test.

Target return for a decision after close `t`:

```text
position decided at close t
position becomes active at open t+1
realized interval = total return from open t+1 to open t+2
long receives distributions; short owes them
short_return = -long_return at zero costs
```

## 2. Raw SPY OHLCV predictor snapshot

Acquire bounded raw SPY OHLCV only through `2010-12-31`.

Required steps:

1. Request explicit start/end.
2. Store raw bytes, HTTP metadata, retrieval time and SHA-256.
3. Reject any row dated `>=2021-01-01` before logging its values.
4. Reconcile sessions and raw close returns with the exact V1 snapshot.
5. Apply split factors consistently to open/high/low/close; transform volume inversely so dollar volume is split-invariant.
6. Do not infer an adjusted open from adjusted close.
7. Do not use cash distributions in OHLC geometry or predictor-ETF ratios.

## 3. Fixed nine-sector panel

Symbols:

```text
XLB XLE XLF XLI XLK XLP XLU XLV XLY
```

All are treated as fixed traded instruments, not as reconstructed S&P 500 constituents. Their official inception is `1998-12-16` and listing date is `1998-12-22`; Codex must still verify each first lawful raw bar.

Panel rules:

- no synthetic pre-inception values;
- no future fill;
- intersect only required symbols on real sessions;
- split-normalize price-only closes;
- require all nine components for breadth and dispersion;
- reject a candidate if post-warmup coverage is below the gate.

## 4. Fixed cross-asset/risk panel

```text
DIA QQQ IWM IEF TLT SPY
```

Expected inception anchors to verify against sponsor metadata and first raw bar:

```text
DIA 1998-01-14
QQQ 1999-03-10
IWM 2000-05-22
IEF 2002-07-22
TLT 2002-07-22
```

Each ratio begins only after both instruments exist plus its full warmup. There is no synthetic history, index substitution or backfilled total-return series.

## 5. Equal-weight concentration proxy

Use `RSP/SPY`, with expected RSP inception `2003-04-24` subject to official and raw-bar verification. This family is allowed to fail the minimum-history gate. It must never receive an earlier synthetic history.

## 6. Predictor return convention

For every non-target ETF:

```text
Q_t = split-normalized price-only close
predictor_return = ln(Q_t/Q_{t-h})
cash distributions excluded
```

This convention is intentional: it avoids incomplete historical dividend reconstruction across many ETFs. It must be disclosed in outputs and cannot be changed after observing results.

## 7. Provider adjudication

Primary operational source: bounded Yahoo chart snapshots, because it succeeded in V1. Secondary cross-check: Stooq when available. Sponsor pages verify identity/inception; they are not price feeds.

Fail-closed rules:

- no silent provider substitution;
- no mixed source history without a row-level manifest;
- no unresolved split discrepancy;
- no duplicate sessions;
- no zero/negative OHLC;
- `low <= min(open,close) <= max(open,close) <= high`;
- nonnegative volume;
- all bars mapped to NYSE sessions;
- raw snapshot hashes included in final artifact.

## 8. Embedded prior artifacts

The package includes:

```text
prior_campaign/SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_FINAL.zip
prior_campaign/sp500-ls-train-yahoo-fallback-r8-results.zip
```

Codex must verify their hashes from `prior_campaign_reference.json`. Missing or mismatched prior results make cumulative multiple testing incomplete and prohibit promotion to validation.
