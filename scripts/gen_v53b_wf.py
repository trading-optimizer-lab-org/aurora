"""Writes .github/workflows/v53b.yml (run from the repo root): V53B_PREREGISTRATION.md.

  oos (v53's chosen books x scales, 128 shards) -> final
Reuses v53's run: its selection cache (trades) and its choose artifact (aggregate). Trades pass only in caches.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import DOWN  # noqa: E402
from gen_v52_wf import SETUP, job, restore, up  # noqa: E402

V53_RUN = "41226223974"
SHARDS = 128
FAC = "${{ matrix.shard }}"
W = "outputs/v53bw"

choose = f"""      - uses: {DOWN}
        with:
          name: v53-choose
          path: {W}/choose
          run-id: {V53_RUN}
          github-token: ${{{{ github.token }}}}
"""
oos = (SETUP + restore("outputs/v53w/sel", f"v53-sel-{V53_RUN}") + choose
       + f"      - run: python scripts/run_v53b.py oos --sel outputs/v53w/sel --choose {W}/choose --shard {FAC} "
         f"--shards {SHARDS} --procs 4 --out {W}/runs/oos\n" + up(f"v53b-oos-{FAC}", f"{W}/runs/oos"))
final = (SETUP + choose + f"""      - uses: {DOWN}
        with:
          pattern: v53b-oos-*
          path: {W}/runs/oos
          merge-multiple: false
""" + "      - run: |\n"
         f"          python scripts/run_v53b.py final --choose {W}/choose --oos {W}/runs/oos --out {W}/final\n"
         f"          cat {W}/final/V53B_REPORT.md >> \"$GITHUB_STEP_SUMMARY\"\n"
         + up("v53b-report", f"{W}/final"))

head = """name: "v53b: v53's walk-forward books at smaller sizes"

# scripts/gen_v53b_wf.py writes this file (V53B_PREREGISTRATION.md). Trades pass between jobs only in caches;
# artifacts hold aggregate statistics and account returns only.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v53b.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v53b
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"

jobs:
"""
body = job("oos", None, 120, oos, list(range(SHARDS))) + "\n" + job("final", "oos", 30, final)
Path(".github/workflows/v53b.yml").write_text(head + body, encoding="utf-8", newline="\n")
print("wrote .github/workflows/v53b.yml")
