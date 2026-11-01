"""Writes .github/workflows/v53c.yml (run from the repo root): V53C_PREREGISTRATION.md, one final job.

Reads v53's choose artifact and v53b's (book x scale) daily returns, both aggregate; no trades or prices.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import DOWN  # noqa: E402
from gen_v52_wf import SETUP, job, up  # noqa: E402

V53_RUN, V53B_RUN = "41226223974", "41231859502"
W = "outputs/v53cw"


def down(sel: str, path: str, run: str) -> str:
    return f"""      - uses: {DOWN}
        with:
          {sel}
          path: {path}
          run-id: {run}
          github-token: ${{{{ github.token }}}}
"""


final = (SETUP + down("name: v53-choose", f"{W}/choose", V53_RUN)
         + down("pattern: v53b-oos-*", f"{W}/oos", V53B_RUN)
         + "      - run: |\n"
           f"          python scripts/run_v53c.py final --choose {W}/choose --oos {W}/oos --out {W}/final\n"
           f"          cat {W}/final/V53C_REPORT.md >> \"$GITHUB_STEP_SUMMARY\"\n"
         + up("v53c-report", f"{W}/final"))

head = """name: "v53c: v53's walk-forward books, size chosen out of sample"

# scripts/gen_v53c_wf.py writes this file (V53C_PREREGISTRATION.md). Inputs are aggregate artifacts only.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v53c.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v53c
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"

jobs:
"""
Path(".github/workflows/v53c.yml").write_text(head + job("final", None, 90, final), encoding="utf-8", newline="\n")
print("wrote .github/workflows/v53c.yml")
