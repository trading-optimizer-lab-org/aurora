# SP500 Strategy Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Subagents and forks are prohibited for this repository.

**Goal:** Build and commit a deterministic, machine-readable catalog covering all 240 SP500 lanes and all 14 approved cross rules without reading market data or changing the active DEHB campaign.

**Architecture:** A pure configuration generator loads the frozen data and feature contracts, enumerates valid discrete lane configurations, chooses deterministic covering sets, expands approved cross rules, canonicalizes scientific recipes, and writes five mutually consistent artifacts. The generator never imports a market-data engine and never evaluates performance; all acceptance checks operate on configuration metadata only.

**Tech Stack:** Python 3.14, standard library (`dataclasses`, `hashlib`, `itertools`, `json`, `csv`, `pathlib`, `tempfile`), existing Aurora feature/data contracts, pytest.

## Global Constraints

- Authoritative worktree: `C:\Users\HP\AURORA_sp500_search_method_benchmark_short`.
- Branch: `codex/sp500-search-method-benchmark-short`.
- `search_end=2010-12-31`.
- `validation_opened=false`; do not mount or read 2011-2020.
- `locked_opened=false`; do not mount or read 2021+.
- Do not use subagents or forks.
- Do not stop, mutate, or restart the active campaign.
- Do not run a backtest, search, optimization, robustness pass, or market-data load.
- Do not add costs, drawdown, Sharpe, objectives, data sources, feature lanes, or cross rules.
- Keep daily SPY positions binary (`+1` or `-1`); catalog composition `0` means carry the prior position.
- The catalog recommends `initial_fidelity=1` but does not execute it.
- All source edits use `apply_patch`; generated catalog artifacts are written by the finished generator.

---

### Task 1: Canonical catalog models and scientific identities

**Files:**
- Create: `infra/sp500_megarun/strategy_catalog.py`
- Create: `tests/test_sp500_megarun_strategy_catalog.py`

**Interfaces:**
- Consumes: `FrozenFeatureContract` from `aurora.infra.sp500_megarun.feature_contract`.
- Produces: `CatalogBuildError`, `CatalogComponentV1`, `StrategyCatalogEntryV1`, `canonical_json_bytes()`, `configuration_sha256()`, and `strategy_id_for()`.

- [ ] **Step 1: Write failing identity and boundary tests**

```python
def test_catalog_identity_is_stable_across_mapping_order() -> None:
    left = {"window": 20, "kind": "sma"}
    right = {"kind": "sma", "window": 20}
    assert configuration_sha256("F001", left) == configuration_sha256("F001", right)


def test_catalog_entry_rejects_open_boundaries() -> None:
    with pytest.raises(CatalogBuildError, match="CATALOG_BOUNDARY_OPEN"):
        StrategyCatalogEntryV1.from_payload(
            _single_payload(validation_opened=True)
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_strategy_catalog.py -q`

Expected: collection fails because `strategy_catalog` does not exist.

- [ ] **Step 3: Implement immutable models and canonical hashing**

```python
CATALOG_ID_DOMAIN = b"AURORA-SP500-STRATEGY-CATALOG-V1\0"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def configuration_sha256(lane_id: str, configuration: Mapping[str, object]) -> str:
    payload = {"lane_id": lane_id, "configuration": dict(configuration)}
    return hashlib.sha256(CATALOG_ID_DOMAIN + canonical_json_bytes(payload)).hexdigest()
```

`StrategyCatalogEntryV1.from_payload()` must enforce schema version 1, one to five unique components, valid SHA-256 fields, `search_end == "2010-12-31"`, both boundary flags false, `initial_fidelity == 1`, and `performance_status == "not_evaluated"`.

- [ ] **Step 4: Run the focused tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_strategy_catalog.py -q`

Expected: identity and boundary tests pass.

- [ ] **Step 5: Commit the core schema**

```powershell
git add -- infra/sp500_megarun/strategy_catalog.py tests/test_sp500_megarun_strategy_catalog.py
git commit -m "feat: add SP500 catalog identities"
```

### Task 2: Deterministic individual-lane coverage

**Files:**
- Modify: `infra/sp500_megarun/strategy_catalog.py`
- Modify: `tests/test_sp500_megarun_strategy_catalog.py`

**Interfaces:**
- Consumes: `FrozenFeatureContract.lanes` and the existing forbidden-pair/triplet definitions from `dehb_configspace.py`.
- Produces: `enumerate_valid_configurations(lane)`, `individual_coverage_requirements(lane, valid)`, `select_covering_configurations(lane, valid)`, and `build_individual_entries(contract)`.

- [ ] **Step 1: Write failing enumeration and coverage tests**

```python
def test_individual_catalog_covers_every_value_and_compatible_pair(feature_contract) -> None:
    entries, report = build_individual_entries(feature_contract)
    assert {entry.components[0].lane_id for entry in entries} == {
        f"F{index:03d}" for index in range(1, 241)
    }
    assert report["lane_count"] == 240
    assert report["uncovered_requirements"] == []


def test_individual_catalog_excludes_forbidden_f002_pairs(feature_contract) -> None:
    entries, _report = build_individual_entries(feature_contract)
    f002 = [entry for entry in entries if entry.components[0].lane_id == "F002"]
    assert all(entry.components[0].configuration["fast"] < entry.components[0].configuration["slow"] for entry in f002)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_strategy_catalog.py -q`

Expected: tests fail because individual coverage functions are absent.

- [ ] **Step 3: Implement valid Cartesian enumeration**

Use `itertools.product()` over parameter values in contract order. Reject a configuration when every named value in an existing forbidden pair or triplet matches. Sort valid configurations by `canonical_json_bytes()`.

```python
def _matches_constraint(config: Mapping[str, object], constraint: tuple[tuple[str, object], ...]) -> bool:
    return all(config[name] == value for name, value in constraint)
```

Require the raw Cartesian count to equal 55,763 across all lanes before filtering; fail with `CATALOG_RAW_CARTESIAN_COUNT_MISMATCH` if the frozen contract drifts.

- [ ] **Step 4: Implement deterministic set-cover selection**

The requirement universe contains every one-way parameter value and every two-parameter value pair present in at least one valid configuration. Select the valid default first, then repeatedly choose the configuration covering the most uncovered requirements; break ties by canonical bytes.

```python
while uncovered:
    winner = min(
        candidates,
        key=lambda item: (-len(item.requirements & uncovered), item.canonical_bytes),
    )
    if not (winner.requirements & uncovered):
        raise CatalogBuildError("CATALOG_INDIVIDUAL_COVERAGE_STALLED")
    selected.append(winner)
    uncovered.difference_update(winner.requirements)
```

Emit one `single` entry per selected configuration with `composition={"kind": "identity"}` and coverage tags sorted canonically.

- [ ] **Step 5: Run coverage tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_strategy_catalog.py -q`

Expected: all tests pass; report shows 240 lanes and no uncovered requirement.

- [ ] **Step 6: Commit individual generation**

```powershell
git add -- infra/sp500_megarun/strategy_catalog.py tests/test_sp500_megarun_strategy_catalog.py
git commit -m "feat: generate covered SP500 lane catalog"
```

### Task 3: Approved cross-rule expansion and deduplication

**Files:**
- Modify: `infra/sp500_megarun/strategy_catalog.py`
- Modify: `tests/test_sp500_megarun_strategy_catalog.py`

**Interfaces:**
- Consumes: individual entries grouped by lane and `FrozenCrossRule` records from the feature contract.
- Produces: `expand_lane_specs()`, `canonicalize_composition()`, `build_cross_entries()`, and `merge_duplicate_entries()`.

- [ ] **Step 1: Write failing rule, arity, composition, and dedupe tests**

```python
def test_cross_catalog_covers_every_rule_composition_and_arity(feature_contract) -> None:
    singles, _ = build_individual_entries(feature_contract)
    crosses, report = build_cross_entries(feature_contract, singles)
    assert report["rule_count"] == 14
    assert report["uncovered_rule_composition_arities"] == []
    assert report["uncovered_authorized_left_right_pairs"] == []
    assert all(2 <= entry.feature_count <= 5 for entry in crosses)


def test_commutative_crosses_deduplicate_component_permutations() -> None:
    left = _cross_payload(composition="and", lane_ids=("F001", "F019"))
    right = _cross_payload(composition="and", lane_ids=("F019", "F001"))
    assert scientific_recipe_sha256(left) == scientific_recipe_sha256(right)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_strategy_catalog.py -q`

Expected: tests fail because cross generation is absent.

- [ ] **Step 3: Expand exact left-right pairs**

Expand `Fnnn-Fmmm` inclusively and canonicalize duplicate lane specifications. For each rule, authorized composition, and unique left-right pair, create an arity-two recipe. Reject equal lane IDs and unknown lanes.

Assert the frozen pre-dedup rule/pair/composition count equals 26,480.

- [ ] **Step 4: Add deterministic arities three through five**

For each allowed arity, composition, and rule, cycle through sorted left and right lanes for `max(len(left), len(right))` rows. Fill remaining component positions from the sorted union using a deterministic offset while skipping duplicates. Add supplemental rows until every lane appears and every parameter value of every participating lane occurs in at least one cross.

- [ ] **Step 5: Implement exact composition canonicalization**

`and`, `vote`, and `weighted_score` are commutative and sort `(component, attached_weight)` pairs. `gate` keeps the base first. `override` keeps the base first and priority component last. `vote` emits both `majority` and `unanimity`. `weighted_score` uses only `{-2, -1, -0.5, 0.5, 1, 2}`, removes proportional tuples, fixes the first non-zero weight positive, and uses pairwise weight coverage.

- [ ] **Step 6: Merge scientific duplicates without losing provenance**

Group by scientific recipe hash. Merge and sort `cross_rule_ids`, rationales, and coverage tags. Raise `CATALOG_STRATEGY_ID_COLLISION` if equal IDs have different scientific recipes.

- [ ] **Step 7: Run cross tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_strategy_catalog.py -q`

Expected: all rule, composition, arity, pair, parameter-value, and dedupe tests pass.

- [ ] **Step 8: Commit cross generation**

```powershell
git add -- infra/sp500_megarun/strategy_catalog.py tests/test_sp500_megarun_strategy_catalog.py
git commit -m "feat: generate approved SP500 cross catalog"
```

### Task 4: Atomic artifact writer and CLI

**Files:**
- Modify: `infra/sp500_megarun/strategy_catalog.py`
- Create: `scripts/build_sp500_megarun_strategy_catalog.py`
- Modify: `tests/test_sp500_megarun_strategy_catalog.py`

**Interfaces:**
- Consumes: `build_individual_entries()` and `build_cross_entries()`.
- Produces: `build_strategy_catalog()`, `write_strategy_catalog()`,
  `build_and_write_strategy_catalog()`, `verify_strategy_catalog_directory()`,
  and the CLI exit code.

- [ ] **Step 1: Write failing byte-reproducibility and artifact-consistency tests**

```python
def test_catalog_artifacts_are_byte_reproducible(tmp_path, feature_contract_paths) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_and_write_strategy_catalog(*feature_contract_paths, output_dir=first)
    build_and_write_strategy_catalog(*feature_contract_paths, output_dir=second)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }


def test_catalog_manifest_matches_all_rows(tmp_path, feature_contract_paths) -> None:
    output = tmp_path / "catalog"
    build_and_write_strategy_catalog(*feature_contract_paths, output_dir=output)
    receipt = verify_strategy_catalog_directory(output)
    assert receipt["accepted"] is True
    assert receipt["uncovered_requirement_count"] == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_strategy_catalog.py -q`

Expected: artifact APIs are missing.

- [ ] **Step 3: Implement pure build orchestration**

`build_strategy_catalog(data_contract_path, feature_contract_path)` loads only the two JSON contracts, checks 240 executable lanes and closed boundaries, and returns sorted entries plus full coverage and manifest payloads. Add a dependency guard test that patches market-data loaders to raise if imported or called.

- [ ] **Step 4: Implement deterministic writers**

Write canonical newline-terminated JSONL, RFC-4180 CSV with fixed column order, canonical JSON reports, and a static README. Compute SHA-256 for `catalog.jsonl`, `catalog.csv`, `coverage.json`, and `README.md`; record them in `manifest.json`. Write to a sibling temporary directory, verify every file, then replace only the five exact final files.

- [ ] **Step 5: Implement the CLI**

```python
parser.add_argument("--data-contract", type=Path, required=True)
parser.add_argument("--feature-contract", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
```

Print only the canonical verification receipt. Return non-zero on every `CatalogBuildError`.

- [ ] **Step 6: Run focused tests and static checks**

Run:

```powershell
C:/Python314/python.exe -m pytest tests/test_sp500_megarun_strategy_catalog.py -q
C:/Python314/python.exe -m ruff check infra/sp500_megarun/strategy_catalog.py scripts/build_sp500_megarun_strategy_catalog.py tests/test_sp500_megarun_strategy_catalog.py
```

Expected: all tests and Ruff checks pass.

- [ ] **Step 7: Commit writer and CLI**

```powershell
git add -- infra/sp500_megarun/strategy_catalog.py scripts/build_sp500_megarun_strategy_catalog.py tests/test_sp500_megarun_strategy_catalog.py
git commit -m "feat: write verifiable SP500 strategy catalog"
```

### Task 5: Generate, verify, and commit the catalog

**Files:**
- Create: `config/sp500_megarun_strategy_catalog_v1/catalog.jsonl`
- Create: `config/sp500_megarun_strategy_catalog_v1/catalog.csv`
- Create: `config/sp500_megarun_strategy_catalog_v1/manifest.json`
- Create: `config/sp500_megarun_strategy_catalog_v1/coverage.json`
- Create: `config/sp500_megarun_strategy_catalog_v1/README.md`

**Interfaces:**
- Consumes: the CLI and frozen repository contracts.
- Produces: the final independent catalog and its verification receipt.

- [ ] **Step 1: Generate the final catalog**

Run:

```powershell
C:/Python314/python.exe scripts/build_sp500_megarun_strategy_catalog.py `
  --data-contract config/sp500_megarun_free_data_240.json `
  --feature-contract config/sp500_megarun_feature_contract_240.json `
  --output-dir config/sp500_megarun_strategy_catalog_v1
```

Expected: accepted receipt, 240 individual lanes, 14 cross rules, zero uncovered requirements, validation false, and locked false.

- [ ] **Step 2: Generate a second copy and compare bytes**

Use a temporary directory under the workspace, rerun the CLI, compare SHA-256 for all five files, and remove only that verified temporary directory after comparison.

- [ ] **Step 3: Run acceptance tests**

Run:

```powershell
C:/Python314/python.exe -m pytest tests/test_sp500_megarun_strategy_catalog.py tests/test_sp500_megarun_dehb_configspace.py tests/test_sp500_megarun_feature_contract.py -q
C:/Python314/python.exe -m ruff check infra/sp500_megarun/strategy_catalog.py scripts/build_sp500_megarun_strategy_catalog.py tests/test_sp500_megarun_strategy_catalog.py
git diff --check
```

Expected: all tests pass, Ruff is clean, and Git reports no whitespace errors.

- [ ] **Step 4: Inspect final manifest and boundaries**

Verify that every artifact hash matches, `performance_status` is `not_evaluated` on every row, no date exceeds 2010, and no validation/locked flag is true.

- [ ] **Step 5: Commit generated artifacts**

```powershell
git add -- config/sp500_megarun_strategy_catalog_v1
git commit -m "data: add SP500 strategy catalog v1"
```

- [ ] **Step 6: Final repository verification**

Run:

```powershell
git status --short
git log -6 --oneline --decorate
```

Expected: clean worktree with the catalog commits on `codex/sp500-search-method-benchmark-short`. Do not launch or modify any DEHB campaign.
