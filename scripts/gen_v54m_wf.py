"""Writes .github/workflows/v54m.yml (run from the repo root): V54M_PREREGISTRATION.md.

  final: v54's daily account returns (run 41497719624, artifacts v54-run-*) graded as fixed books
Artifacts hold aggregates only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import DOWN  # noqa: E402
from gen_v52_wf import SETUP, job, up  # noqa: E402

W = "outputs/v54mw"
RUN = 41497719624
final = (SETUP + f"""      - uses: {DOWN}
        with:
          pattern: v54-run-*
          path: {W}/runs
          merge-multiple: true
          run-id: {RUN}
          github-token: ${{{{ github.token }}}}
""" + "      - run: |\n"
         f"          python scripts/run_v54m.py final --procs 4 --runs {W}/runs --out {W}/final\n"
         f"          cat {W}/final/V54M_REPORT.md >> \"$GITHUB_STEP_SUMMARY\"\n"
         + up("v54m-report", f"{W}/final"))

head = """name: "v54m: the cost of a safety margin on the fixed daily book"

# scripts/gen_v54m_wf.py writes this file (V54M_PREREGISTRATION.md). Artifacts hold aggregates only.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v54m.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v54m
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"

jobs:
"""
Path(".github/workflows/v54m.yml").write_text(head + job("final", None, 240, final), encoding="utf-8", newline="\n")
print("wrote .github/workflows/v54m.yml")
