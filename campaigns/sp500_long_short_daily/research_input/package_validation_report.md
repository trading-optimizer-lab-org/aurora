# Package validation report

**Status: PASS**

Validation scope:

- required files, UTF-8 and CSV/JSON/JSONL/YAML parsing;
- exact counts and conservative bibliographic verification count;
- candidate hashes, IDs, family coverage, causal boundaries, position and zero-cost contract;
- dataset dependency classes, including rejection of paid/rejected dependencies;
- five benchmarks and minimum metric contract;
- Codex prompt first sentence and self-contained execution content;
- input-manifest hashes and stale/forbidden-content scan.

## Counts

- `sources`: **249**
- `verified_primary_sources`: **160**
- `datasets`: **73**
- `free_usable_datasets`: **55**
- `families`: **28**
- `candidates`: **168**
- `features`: **168**
- `benchmarks`: **5**
- `mandatory_files`: **19**
- `total_files`: **22**

## Checks

- files_required=21; total_contract_files=22; mandatory=19
- csv_parse
- counts sources=249 verified=160 datasets=73 free_usable=55 features=168 families=28
- candidate_invariants_and_dependencies
- json_yaml_manifests
- codex_self_contained
- stale_and_forbidden_content_scan

No validation errors were found. The report validates structure and contracts; it does not validate strategy profitability or reproduce every paper result.
