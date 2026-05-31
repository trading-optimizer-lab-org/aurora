# Mutation Testing (R12)

Aurora uses [mutmut](https://github.com/boxed/mutmut) to measure how
strongly the test suite catches subtle code changes.

## Why

A passing test suite proves "this code does not crash on these inputs".
Mutation testing asks the harder question: "if I silently change one
operator or constant, does any test fail?". Surviving mutations expose
weak tests. Big test count is not the same as strong test coverage.

## When to run

| Frequency | Target | Speed |
|-----------|--------|-------|
| Weekly / before release | full curated target list | slow (hours) |
| Per-PR (gated, optional) | one focused module | minutes |
| Local debugging | one file at a time | minutes |

Mutation testing is intentionally NOT in the default `make test` target.
It is opt-in.

## Curated targets

`pyproject.toml` lists the canonical mutation targets under
`[tool.mutmut].paths_to_mutate`:

- `core/engine.py`, `core/engine_multi.py`
- `core/costs.py`, `core/metrics.py`
- `core/data_tiers.py`, `core/data_layer.py`
- `core/protocol_policy.py`
- `validation/walk_forward.py`, `validation/monte_carlo.py`
- `validation/spp.py`, `validation/deflated_sharpe.py`
- `validation/lookahead_check.py`, `validation/pipeline.py`
- `ga/fitness.py`

These are the modules where a silent mutation translates into wrong PnL,
lost provenance, or a leaky tier guard. Other modules (CLI, reporting,
examples) are intentionally excluded.

## Commands

```bash
# Fast, narrow run on metrics module only
make mutate

# Full curated sweep (slow)
make mutate-full

# Inspect surviving mutants
make mutate-results

# Inspect a specific survivor by id
python -m mutmut show <id>
```

The runner is configured to run the focused property-based tests plus
the matching unit tests for each target. See `[tool.mutmut].runner` in
`pyproject.toml`.

## Reading results

```
Mutation testing results:
- Killed:    412   <- a test failed -> good
- Survived:    7   <- nothing failed -> weak test
- Skipped:     3
- Timeout:     1
- Suspicious:  0
```

A mutation score of "killed / (killed + survived)" above ~85% on the
core targets is the working bar. Scores below that mean the property /
unit tests are not exercising the actual semantics of the mutated lines.

## Workflow when survivors appear

1. Run `mutmut show <id>`. Read the surviving mutation.
2. Decide:
   - **Add a test** that distinguishes the original from the mutant. This
     is the usual answer.
   - **Mark the line `# no-mutate`** if the mutation is provably
     equivalent (rare). The pre-mutation hook in `mutmut_config.py`
     respects this marker.
3. Re-run mutmut on the affected file.
4. Commit the new test in the same change.

## Known noisy categories

mutmut can produce false positives in the following areas. These are
disabled by default via `disable_mutation_types = "string,fstring"`:

- String literal mutations (typically affect log messages only).
- f-string format spec mutations.

If a string mutation matters semantically (e.g. a key name in a hashed
dict), add a dedicated test rather than re-enabling these categories
globally.

## Numba JIT shadow-mutation workaround (R72)

mutmut edits Python source. Numba `@jit` decorators compile that source
once at import time and the compiled kernel keeps running the
unmodified code through the rest of the test session. Result: a
mutation in `core/engine_jit.py` (or any other JIT-decorated module)
can look "killed" without ever executing.

**Canonical mitigation:** run mutation testing with `NUMBA_DISABLE_JIT=1`.

The runner inherits the env var, so set it before invoking mutmut:

```bash
NUMBA_DISABLE_JIT=1 make mutate-full
```

Or pin the env in `[tool.mutmut].runner` so every developer sees the
same configuration. The current runner does NOT yet pin the env -- if
you rely on the survivor count, set it manually until the runner config
is updated.

Why disable rather than per-test recompile: forcing per-invocation
recompile slows the suite by 5-10x with no semantic gain. Disable JIT
makes mutmut see the actual source semantics; the JIT-vs-Python parity
is the responsibility of `tests/test_jit_parity.py`, not of mutation
testing.

## Limits

- mutmut only mutates Python source. Numba `@jit`-compiled hot paths get
  mutated at the source level, but recompilation may shadow the mutant.
  Set `NUMBA_DISABLE_JIT=1` (see workaround section above) when
  validating survivors in JIT modules.
- Mutation testing is not a substitute for property tests, integration
  tests, or code review. It is one extra signal.
- mutmut native Windows is unsupported (upstream issue 397). Run the
  full sweep on Linux / macOS / WSL only.

## R41 -- First full sweep procedure

The first full sweep establishes the baseline survivor table. Procedure
(must run on Linux / macOS / WSL because of the Windows limit above):

```bash
# 1. Clean previous mutation state.
rm -rf .mutmut-cache mutants/

# 2. Run the curated sweep with JIT disabled.
NUMBA_DISABLE_JIT=1 make mutate-full

# 3. Capture the result table.
python -m mutmut results > docs/mutation_baseline_$(date -u +%Y%m%d).txt

# 4. Inspect each survivor.
for id in $(python -m mutmut results | grep "^[0-9]" | awk '{print $1}'); do
    python -m mutmut show "$id" >> docs/mutation_survivors_$(date -u +%Y%m%d).txt
    echo "----" >> docs/mutation_survivors_$(date -u +%Y%m%d).txt
done

# 5. Treat survivors per the workflow above (add test or mark
#    `# no-mutate` if equivalent).
```

### Acceptance for R41

- `docs/mutation_baseline_<YYYYMMDD>.txt` exists with the killed /
  survived / skipped / timeout / suspicious counts.
- `docs/mutation_survivors_<YYYYMMDD>.txt` exists with one entry per
  survivor, ready for the workflow above.
- Mutation score on the curated targets >= 85% (working bar from the
  "Reading results" section).

### Why the baseline is captured manually rather than in CI

A full curated sweep takes hours. Wiring it into a per-PR CI gate is a
separate cost / value decision (R42 already runs the property
`thorough` profile on a daily cron; mutmut on the same cadence would
double CI compute spend). Treat the manual baseline as the canonical
reference; rerun monthly or before each release.
