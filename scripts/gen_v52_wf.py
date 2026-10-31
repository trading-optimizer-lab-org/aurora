"""Writes .github/workflows/v52.yml (run from the repo root): V52_PREREGISTRATION.md, every stage in one run.

  factory (one per group with frozen selections) -> book (22 shards) -> final
Trades and prices pass between jobs only in caches keyed by the run; artifacts hold aggregate statistics only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import CO, PY, RESTORE, UP, DOWN  # noqa: E402

DATA_RUN = "41219555974"  # v52-data: the 2016-2017 holdout events and their one-minute bars
SAVE = "actions/cache/save@0400d5f644dc74513175e3cd8d07132dd4860809"
FROZEN = json.loads(Path("docs/research/data/v52_frozen.json").read_text(encoding="utf-8"))
GROUPS = list(dict.fromkeys(c["group"] for c in FROZEN["configs"]))
SHARDS = 22
RUN = "${{ github.run_id }}"
W = "outputs/v52w"

SETUP = f"""      - uses: {CO}
        with:
          persist-credentials: false
      - uses: {PY}
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install --upgrade pip && python -m pip install -e .
"""


def restore(path: str, key: str) -> str:
    p = path if "\n" not in path else "|\n" + "\n".join(f"            {x}" for x in path.split("\n"))
    return f"""      - uses: {RESTORE}
        with:
          path: {p}
          key: {key}
          fail-on-cache-miss: true
"""


def up(name: str, path: str) -> str:
    return f"""      - if: always()
        uses: {UP}
        with:
          name: {name}
          path: {path}
          retention-days: 90
"""


def down(pattern: str, path: str) -> str:
    return f"""      - uses: {DOWN}
        with:
          pattern: {pattern}
          path: {path}
          merge-multiple: false
"""


def job(name: str, needs: str | None, minutes: int, body: str, matrix: list | None = None) -> str:
    out = f"  {name}:\n"
    if needs:
        out += f"    needs: [{needs}]\n    if: always() && needs.{needs}.result == 'success'\n"
    out += f"    runs-on: ubuntu-24.04\n    timeout-minutes: {minutes}\n"
    if matrix is not None:
        out += f"    strategy:\n      fail-fast: false\n      matrix:\n        shard: [{', '.join(map(str, matrix))}]\n"
    return out + "    steps:\n" + body


FAC = "${{ matrix.shard }}"
factory = (SETUP + restore("outputs/v18", "v18-inputs-39433812183-1")
           + restore("outputs/v28/inputs\noutputs/v28/pmstore", "v28-inputs2-39825946914-1")
           + restore("outputs/v52", f"v52-min-{DATA_RUN}-1")
           + f"      - run: python scripts/run_v52.py factory --group {FAC} --procs 4 --out {W}/fac/{FAC}\n"
           + f"""      - uses: {SAVE}
        with:
          path: {W}/fac/{FAC}
          key: v52-fac-{RUN}-{FAC}
""" + up(f"v52-fac-{FAC}", f"{W}/fac/{FAC}/report.json"))
book = (SETUP + "".join(restore(f"{W}/fac/{g}", f"v52-fac-{RUN}-{g}") for g in GROUPS)
        + f"      - run: python scripts/run_v52.py book --factory {W}/fac --shard {FAC} --shards {SHARDS} --procs 4 "
          f"--out {W}/runs\n" + up(f"v52-book-{FAC}", f"{W}/runs"))
final = (SETUP + down("v52-fac-*", f"{W}/facrep") + down("v52-book-*", f"{W}/runs")
         + "      - run: |\n"
           f"          python scripts/run_v52.py final --factory {W}/facrep --runs {W}/runs --out {W}/final\n"
           f"          cat {W}/final/V52_REPORT.md >> \"$GITHUB_STEP_SUMMARY\"\n"
         + up("v52-report", f"{W}/final"))

head = """name: "v52: v51's CRASH-long book on the 2016-2017 holdout"

# scripts/gen_v52_wf.py writes this file (V52_PREREGISTRATION.md). Trades and prices pass between jobs only in caches
# keyed by this run; artifacts hold aggregate statistics only.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v52.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v52
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"

jobs:
"""
body = (job("factory", None, 120, factory, [f'"{g}"' for g in GROUPS]) + "\n"
        + job("book", "factory", 120, book, list(range(SHARDS))) + "\n" + job("final", "book", 30, final))
Path(".github/workflows/v52.yml").write_text(head + body, encoding="utf-8", newline="\n")
print("wrote .github/workflows/v52.yml")
