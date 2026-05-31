# Roadmap Blockers

Honest accounting of items in [`ROADMAP_PENDING.md`](ROADMAP_PENDING.md)
that cannot be completed inside this repository alone. Each entry names
the external dependency, the smallest first slice, and what work HAS
landed in repo as preparation.

---

## R2. Real alt-data feeds

**Blocker.** Each feed needs:

- A registered API account with a real provider (FRED, SEC EDGAR,
  Reddit API, Twitter API, on-chain provider, options vendor,
  satellite vendor).
- Credentials stored outside the repo (env vars or secrets manager).
- A rate-limit policy negotiated against the provider's terms.
- Backfill access where the provider charges for historical depth.

**What is in repo today.**

- Skeleton adapters under `altdata/` for: FRED macro, SEC filings,
  Reddit, Twitter, on-chain crypto, options flow, satellite, news LLM,
  earnings transcripts, Google trends.
- Each adapter is mock-friendly: tests inject a fake client.
- Adapters do not read real APIs; production code paths require
  callers to inject a configured client.

**First slice (recommended): FRED macro.**

- Public, free, well-documented.
- API key required but throwaway.
- Mostly daily series; rate limits comfortable.
- Implementation outline:

  1. Add `aurora.altdata.fred_macro.FREDClient` that wraps `requests`
     under a `requests.Session`. Read API key from `$FRED_API_KEY`.
  2. Add a thin retry/backoff layer (already a util in
     `dataeng/`).
  3. Add an integration test marked `@pytest.mark.integration` that
     skips when `$FRED_API_KEY` is missing.
  4. Wire as a DataProvider in `core/data_providers/` so the
     ProtocolPolicy can mark FRED as PIT-aware where applicable.
  5. Document the credential path and rate limits in
     `docs/altdata/FRED.md`.

**Order to follow.** FRED -> SEC -> on-chain -> options flow ->
Reddit/Twitter -> satellite. Sequenced by signal-to-noise per dollar
of integration effort.

**Acceptance per feed.** Credentials env-only. Rate limit honoured.
Backfill path documented. Integration test marked + skipped without
credentials. Provenance metadata stamps source, as-of date, content
hash.

---

## R3. Compliance reporting endpoints

**Blocker.** Production-grade compliance reporting requires:

- Legal review of which jurisdictions / report types apply (MiFID II,
  13F, CTA, AIFMD, etc).
- Authoritative schemas downloaded from the regulator (or a paid
  vendor for some filings).
- A stable production endpoint per regulator (e.g. SEC EDGAR submitter
  account + test environment access).
- An internal sign-off process: nothing should leave the building
  unsigned.

**What is in repo today.**

- Skeleton modules under `compliance/`: MiFID II, 13F, CTA-style.
- Encryption-at-rest, RBAC, two-factor and PII handler primitives are
  in place as design-time hooks.
- Trade reconstruction module lives under
  `compliance/trade_reconstruction.py`.

**Recommended first slice.** Pick ONE jurisdiction + ONE report type.
13F (US equity holdings) is usually the simplest:

1. Pin the official 13F XML schema.
2. Build a fixture pack (golden files) covering the cases your firm
   actually files.
3. Wire validation against the schema.
4. Stop short of submission. Submission requires SEC EDGAR
   credentials and operator sign-off; that lives outside the repo.

**Acceptance.** At least one report has schema + golden-file
validation. Filing assumptions are explicit. No report claims
"regulator-ready" without legal sign-off.

---

## R4. Real execution adapters

**Blocker.** Real broker integration requires:

- A funded (or sandboxed) broker account with API access enabled:
  Interactive Brokers TWS or IB Gateway, Alpaca paper / live, Coinbase
  Advanced, Kraken, Binance, etc.
- API credentials stored securely.
- A live order-routing path with documented partial-fill, cancel and
  reconciliation behaviour per venue.
- Operational discipline around rate limits, kill switches and
  reconciliation drift detection.

**What is in repo today.**

- Adapter classes under `deployment/brokers.py` (Paper, IB, Alpaca,
  Coinbase, Kraken) plus the CCXT adapter under
  `deployment/ccxt_adapter.py`.
- Triple-gate live trading flow in `agent_gateway/`: scoped tokens +
  env flag + active OOSGuard + operator countersignature.
- Kill switch + audit log + rate limiter in the live wrapper.

**Recommended first slice.** Paper execution simulator with realistic
partial fills and slippage:

1. Extend `PaperBroker` to model partial fills under a configurable
   queue model.
2. Write a reconciliation harness that compares expected vs reported
   fill on a synthetic broker tape.
3. Only then deepen one real adapter (Alpaca paper is the cheapest
   place to start) end-to-end.
4. Smart order routing waits until real fill / reconcile data exists.

**Acceptance.** Partial fills modelled. Reconciliation detects drift.
Kill switch and audit log non-bypassable. Live operations require
explicit operator ceremony.

---

## R5. GPU triage backend (gated)

**Blocker.** GPU acceleration is not justified until:

- A CPU triage benchmark proves a real bottleneck on a workload the
  team actually runs.
- Target speedup (say, 10x) and memory-budget envelope are written down.
- CuPy or PyTorch GPU install posture is verified on the CI hardware
  AND on operator machines.

**Status.** Deferred. The roadmap explicitly gates this item behind
benchmarking. Do not start until the gate is met.

**Recommended preparation.**

1. Add a benchmark script under `examples/benchmarks/triage_cpu.py`
   that times the existing CPU pathway on a realistic variant count.
2. Capture a baseline number per machine; commit a JSON fixture for
   regression comparison.
3. Re-evaluate the GPU case ONLY after that fixture is in place.

**Acceptance.** Benchmark reveals an actual bottleneck. CPU and GPU
outputs match within tolerance. Lazy import keeps the base install
light. Fallback path stays deterministic.

---

## R6. Rust core engine (gated)

**Blocker.** A Rust extension adds toolchain complexity (PyO3, maturin,
cross-platform wheels). It only makes sense if the profiler points at
a hot path that Python + numba cannot serve. Today, several hot paths
already use numba JIT and are within an order of magnitude of native
code.

**Status.** Deferred. The roadmap explicitly gates this item behind
profiling. Do not start until the gate is met.

**Recommended preparation.**

1. Profile a representative end-to-end run. Capture the top 10 hot
   functions and their share of wall time.
2. Examine each for "Python or numba can do better" before reaching
   for Rust.
3. If Rust is genuinely the answer for a top function, write a
   parity-test fixture FIRST: identical inputs must produce identical
   outputs across Python and Rust.

**Acceptance.** Native extension is optional. Python fallback stays
canonical. Cross-platform wheel + build story is documented. Engine
parity tests pass.

---

## Closed Former Blockers

These entries used to block or confuse the roadmap, but current
verification says they are no longer live blockers. They stay here for
audit history only.

### R17. Markov switching API drift

**Status.** Closed in the 2026-05-08 verification pass. The previously
reported 9 failures are no longer reproducible in this workspace.

**Evidence.**

- `python -m pytest tests/ -m "not slow and not integration"` ->
  2781 passed, 23 skipped, 10 deselected.
- `tests/test_markov_switching.py` is included in that pass.

**Follow-up.** Remove the stale known-issue entry from `CLAUDE.md`
under R25 and mention the verified baseline in the changelog under
R27.
