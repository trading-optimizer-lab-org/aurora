# Autonomous SPY discovery campaign

This directory is the campaign ledger, not a data dump. Every batch must
register candidates before evaluating them, bind the effective-rule hash to
the result, and preserve the train/validation/locked boundary.

- `research/`: source-derived hypotheses and evidence references.
- `data_registry/`: dataset identities and causal date limits.
- `feature_registry/`: causal feature definitions and lag declarations.
- `candidates/`: pre-registered candidate manifests.
- `search_spaces/`: reproducible mutation/search spaces.
- `checkpoints/`: append-only batch and freeze evidence.

The campaign never opens validation until a train freeze artifact proves that
at least one candidate passed every train and multiplicity gate.
