"""Writes .github/workflows/v54dd.yml (run from the repo root): descriptive, no choice made.

  final: v54's daily account returns (run 41497719624, artifacts v54-run-*) max drawdown of two fixed books
Artifacts hold aggregates only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import DOWN  # noqa: E402
from gen_v52_wf import SETUP, job, up  # noqa: E402

W = "outputs/v54ddw"
RUN = 41497719624
final = (SETUP + f"""      - uses: {DOWN}
        with:
          pattern: v54-run-*
          path: {W}/runs
          merge-multiple: true
          run-id: {RUN}
          github-token: ${{{{ github.token }}}}
""" + "      - run: |\n"
         f"          python scripts/run_v54dd.py final --runs {W}/runs --out {W}/final\n"
         f"          cat {W}/final/V54DD_REPORT.md >> \"$GITHUB_STEP_SUMMARY\"\n"
         + up("v54dd-report", f"{W}/final"))

head = """name: "v54dd: maximum drawdown of the fixed daily books"

# scripts/gen_v54dd_wf.py writes this file. Artifacts hold aggregates only.
# run: 2
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v54dd.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v54dd
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"

jobs:
"""
Path(".github/workflows/v54dd.yml").write_text(head + job("final", None, 60, final), encoding="utf-8", newline="\n")
print("wrote .github/workflows/v54dd.yml")
