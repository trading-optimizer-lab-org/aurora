# Mutation Testing (R12)

QuantForge uses [mutmut](https://github.com/boxed/mutmut) to measure how
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

## Limits

- mutmut only mutates Python source. Numba `@jit`-compiled hot paths get
  mutated at the source level, but recompilation may shadow the mutant.
  Verify any survivor in `core/engine_jit.py` by stepping through with
  `numba` disabled (`NUMBA_DISABLE_JIT=1`).
- Mutation testing is not a substitute for property tests, integration
  tests, or code review. It is one extra signal.
