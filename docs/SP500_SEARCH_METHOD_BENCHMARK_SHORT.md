# SP500 Search Method Benchmark Short

This campaign compares exactly seven search methods on one common causal
`StrategyGrammarBenchmarkV1` space:

* `M0_RANDOM`
* `M1_SCRAMBLED_SOBOL`
* `M2_TPE`
* `M3_SMAC_RF_SMBO`
* `M4_DIFFERENTIAL_EVOLUTION`
* `M5_STRONGLY_TYPED_GENETIC_PROGRAMMING`
* `M6_GP_TO_TPE_HYBRID`

Each method runs with the same seven seeds, 32 common scrambled-Sobol warm-start
candidates, at most 256 unique evaluations, and a 15-minute search budget.
Each method/seed unit uses two deterministic evaluation workers. The first
search period is `1998-01-01..2005-12-31`; the frozen generalisation audit is
`2006-01-01..2010-12-31`.

The trading contract is fixed: SPY only, positions `-1/+1`, no cash, no
leverage, no scaling, zero costs, and decisions after close `t` executed at the
next tradable open. The official validation period
`2011-01-01..2020-12-31` and locked period `>=2021-01-01` are never loaded.

Date handling is fail-closed. Text dates are parsed as dates; numeric
timestamps require an explicit unit. The test suite locks the known boundary
fixture `2004-05-03..2010-12-30`, preventing seconds/milliseconds/nanoseconds
from silently changing the period.

The single workflow is:

`prepare -> preflight -> smoke -> 49 method/seed units -> freeze_check ->
audit 2006-2010 -> aggregate -> independent_verify -> conclude`.

The final artifact is `sp500-search-method-benchmark-results`.
