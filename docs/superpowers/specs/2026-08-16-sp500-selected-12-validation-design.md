# SP500 selected-12 validation design

## Decision

Open the 2011-01-01 through 2020-12-31 validation partition exactly once for
the twelve strategies selected before validation. Keep every date from
2021-01-01 onward physically and logically closed.

## Frozen selection

The input is a committed manifest containing the exact twelve strategy
recipes, their components and composition rules. The manifest is derived from
the successful train-only catalog run 31932275712 and the previously frozen
DEHB selections. Validation must reject a changed count, duplicated recipe,
unknown lane, mutable parameter or train metric mismatch.

## Data boundary

GitHub Actions downloads two immutable inputs:

- the train-only runtime pack from run 31418682679;
- the separately stored closed validation snapshot from preflight run
  31418658411.

The validation job verifies both manifests and every dataset hash before use.
It may combine 1993-2010 with 2011-2020 in an ephemeral snapshot so rolling
signals retain their historical warm-up. Scores and reported returns are
restricted to 2011-2020. Any row dated 2021-01-01 or later aborts the run.

## Evaluation

All twelve strategies run without parameter fitting or reselection. Their
signal recipes stay identical to the train evaluation. The output records:

- annualized strategy return and annualized alpha;
- weekly SPY-beating, positive, and union rates;
- annual strategy, SPY and active returns for every year;
- counts of positive years, SPY-beating years and years satisfying both;
- worst annual return and worst annual active return;
- average strategy return in years when SPY falls.

The result ranks strategies for reporting, but does not alter or rerun them.
Using validation to compare twelve candidates means 2011-2020 is no longer an
independent final test for the eventual winner. The untouched 2021+ partition
remains the final locked test.

## Evidence and failure policy

The workflow emits the frozen input manifest, one result per strategy, a
summary table and a receipt binding source runs, commit, hashes, date limits
and authorization. It fails closed for missing or extra strategies, source
hash conflicts, any locked row, an opened locked flag, incomplete annual
coverage, non-finite metrics or output duplication.

## Execution boundary

Scientific execution occurs only in GitHub Actions. Local activity is limited
to code, tests with synthetic fixtures, manifest inspection and Git. No
subagents or forks are used.
