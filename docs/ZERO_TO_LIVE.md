# Zero To Live

Operator-facing path from clean clone to guarded live trading. Every command
either runs offline, or states the credential / data dependency it needs. No
step is "trust me". If a command requires a real exchange or live capital,
that is called out explicitly.

> **Prerequisite mindset.** OOS sagrado. Triple-gate live. If a check tells you
> to stop, stop. The protocol is enforced as code, not as suggestion.

---

## 0. What you are setting up

QuantForge is a quant research engine with a 7-stage protocol spine:

```
ProtocolPolicy -> DataProviderRegistry -> SnapshotStore ->
ExperimentRegistry -> ValidationPipeline -> AgentAuditGateway ->
Paper / Live Guard Pipeline
```

`policy_hash` propagates through every artifact. Tier reads beyond OOS_DEV
require explicit ceremonies. Live trades require a triple-gate: scoped token
+ env flag + active OOSGuard ceremony + operator countersignature.

If any of those words feel new, read [`SPINE.md`](SPINE.md) and
[`RESEARCH_PROTOCOL.md`](RESEARCH_PROTOCOL.md) before continuing.

---

## 1. Install

Tested on Python 3.10+ (developer machine here is 3.14).

```powershell
git clone <your-fork-or-mirror> QuantForge
cd QuantForge
python -m pip install -e ".[dev,ga]"
```

For the full stack including optional deep-learning, RL, monitoring and
broker integrations:

```powershell
python -m pip install -e ".[dev,all]"
```

Verify:

```powershell
python -c "import quantforge; print(quantforge.__version__)"
forge --version
```

If `forge` is missing from PATH, the entry point did not register. Re-run the
editable install or invoke `python -m quantforge.cli.forge` directly.

> **Important: pin one interpreter.** Subprocess-launching code (mutmut,
> the protocol-policy CLI smoke test, the live deploy gate) calls
> `sys.executable -m quantforge.cli.forge`. If you install editable under
> `C:/Python314/python.exe` but then run `make test` with a `python` on
> `$PATH` that resolves to a different interpreter (e.g. system Python
> 3.12 with no project deps), those subprocesses see
> "No module named quantforge" and the suite fails inside otherwise
> unrelated tests. Pin `PYTHON` in the Makefile and the install command
> to the same path:
>
> ```powershell
> make setup PYTHON="C:/Python314/python.exe"
> make test  PYTHON="C:/Python314/python.exe"
> ```

---

## 2. Run the fast test suite

```powershell
python -m pytest tests/ -m "not slow and not integration" --ignore=tests/test_config.py
```

Expected: green except 9 documented `test_markov_switching` failures
(statsmodels API drift, tracked as roadmap R17) plus 1 cosmetic
`test_lint_config` (R18).

Optional: run property-based tests under thorough profile.

```powershell
$env:HYPOTHESIS_PROFILE="thorough"
python -m pytest tests/test_property.py tests/test_property_v2.py
```

This runs each invariant under 200 generated examples instead of 15. Slower
but useful before any release.

---

## 3. Inspect the protocol policy

The policy is the source of truth: tiers, gates, ceremonies, risk limits and
cost model. Treat it as code, not as suggestion.

```powershell
forge policy show
forge policy verify
```

`policy show` prints the live policy. `policy verify` recomputes the
`policy_hash` and compares it to the declared hash in
`config/protocol_policy.yaml`. A mismatch means the YAML was edited without
re-hashing.

---

## 4. Run a deterministic smoke backtest

```python
from quantforge.core.seed import set_global_seed
from quantforge.core.engine import run_backtest
from quantforge.core.data_layer import load_asset
from quantforge.core.costs import IBKR_costs
from quantforge.strategies.library import MACross


set_global_seed(42)
prices = load_asset("SPY")  # IS-only by default

def signal_fn(p):
    return MACross(fast=20, slow=100).signals(p)

result = run_backtest(prices, signal_fn, costs=IBKR_costs)
print(result.metrics)
```

This call only reads data up to OOS_DEV. It never touches OOS_LOCKED or
FORWARD. Re-running with the same seed reproduces identical numbers.

---

## 5. Freeze a snapshot

A frozen snapshot is the unit of provenance. It binds the data window, the
content hash, and the active `policy_hash` together.

```powershell
forge freeze --asset SPY --upto-tier OOS_DEV
```

The CLI persists the snapshot under `$QF_SNAPSHOT_ROOT` (defaults via
`platformdirs`). The artifact carries the policy hash that was active at
freeze time. Snapshot integrity can be re-verified later:

```powershell
forge data verify --asset SPY
```

---

## 6. Validate a strategy

The validation pipeline runs the mandatory gates: walk-forward, MC bootstrap,
MC trade-reorder, SPP, lookahead, deflated Sharpe, noise injection and gap
simulation, plus the auditor gate.

```powershell
forge validate --strategy MACross --asset SPY --n-trials 5
```

Tier knob:

- `--tier oos_dev` is the default for post-GA validation.
- `--tier oos_locked` requires `--i-understand-ceremony` AND an active
  `OOSGuard("explicit_unlock_oos_locked")` block AND
  `QF_ALLOW_OOS_LOCKED=1`. Locked tier reads are accountable.
- `--tier forward` is reserved for paper / live and requires
  `OOSGuard("explicit_unlock_forward")` + the matching env flag.

The pipeline writes its report with a `policy_hash` field. The hash must
match `forge policy show` for the run to be considered valid downstream.

---

## 7. Submit a candidate to the Research Factory

The factory is the controlled funnel from "an idea" to "validated candidate
in the review queue".

```powershell
forge research submit --spec specs/macross_v1.yaml
```

The factory:

1. Runs the IS backtest.
2. Runs walk-forward inside IS.
3. Runs OOS_DEV validation -- but the factory never touches OOS_LOCKED or
   FORWARD. That is hard-coded.
4. Either archives a failure with a reason, or pushes a survivor into the
   review queue.

List queue:

```powershell
forge research review-queue
```

---

## 8. Review queue and promotion

A queue entry is a candidate, not an approved strategy. To promote a survivor
beyond OOS_DEV, the operator runs the OOS_LOCKED ceremony.

```powershell
$env:QF_ALLOW_OOS_LOCKED="1"
forge research promote --candidate <id> --tier oos_locked --i-understand-ceremony
```

A failed promotion is not a setback -- it is the protocol working. Approved
candidates get the validation-marker stamp that paper / live wrappers expect.

---

## 9. Paper trading

```powershell
forge ops daily   # generate the operational daily report first
```

Then start a paper run via your chosen wrapper. Lumibot example:

```python
from quantforge.deployment.paper import QFPaperStrategy

strat = QFPaperStrategy(strategy_name="MACross", asset="SPY")
strat.bind()  # checks the validation marker; halts if missing
```

The wrapper enforces:

- Validation-marker check on `initialize()`. Bypass requires
  `bypass_validation_check=True` AND `LiveConfig.bypass_validation_check`
  AND a logged warning.
- Kill switch hooks.
- Audit log appends.
- Per-strategy rate limiter.

90-day minimum paper-trading exposure is the documented expectation before
any live capital. Earlier is the operator's call -- and accountability.

---

## 10. Live trading checklist

Live deployment requires the triple-gate plus operator countersignature. The
spine refuses to execute a live order otherwise.

Pre-flight:

- [ ] Strategy completed OOS_LOCKED ceremony with passing audit report.
- [ ] Paper run covers at least the configured minimum (default 90 days).
- [ ] Monitoring dashboard is up: `forge dashboard`.
- [ ] Daily ops report is wired to your alert channel:
      `forge ops alerts --slack-webhook ...` or email.
- [ ] Capital cap and max-concurrent-positions sized to your loss budget.
- [ ] Kill switch confirmed reachable (manual test).
- [ ] You have read `docs/RESEARCH_PROTOCOL.md` Lockbox section.

Authorisation envelope:

```powershell
$env:QF_AGENT_LIVE_AUTH="1"
# Operator HMAC for the staged action; see forge agent commit --help.
$env:QF_OPERATOR_KEY="<32+ char secret>"

forge agent stage --strategy MACross --asset SPY --notional 1000
forge agent commit --staged-id <id>   # requires HMAC signature
forge agent push --staged-id <id>
```

Without all three of: scoped token + `QF_AGENT_LIVE_AUTH=1` + active
`OOSGuard("agent_live_authorized")`, the gateway refuses. CCXT additionally
requires `QF_CCXT_ALLOW_LIVE_<EX>` consent per exchange.

> **Live deployment is the operator's responsibility.** This guide does not
> authorise live trading. It only documents the path. If anything in this
> section is unclear, do not deploy capital.

---

## 11. After the first live session

- Pull the daily ops report: `forge ops daily`.
- Pull the gateway audit chain: `forge agent audit-verify`.
- Pull the SOC2 trail: read `$QF_AUDIT_LOG`.
- Re-run validation against the latest data window if appropriate.
- Decide: continue, scale, or halt.

The protocol assumes you will halt before you scale. That is intentional.

---

## 12. Where to go next

- [ARCHITECTURE.md](ARCHITECTURE.md) -- module dependency graph and design.
- [SPINE.md](SPINE.md) -- v4.0 spine reference.
- [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) -- formal data-split policy.
- [STRATEGY_AUTHOR.md](STRATEGY_AUTHOR.md) -- writing a custom Strategy.
- [GLOSSARY.md](GLOSSARY.md) -- metric and gate definitions.
- API reference: `make docs && open docs/_build/html/index.html`.
