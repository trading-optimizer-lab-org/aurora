"""Writes .github/workflows/v54s.yml (run from the repo root): V54S_PREREGISTRATION.md.

  minute (one job per fill rule, v51+v52 minute bars) -> final
Prices stay on the runners and in caches; artifacts hold aggregates only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import DOWN  # noqa: E402
from gen_v52_wf import SETUP, job, restore, up  # noqa: E402
from gen_v54d_wf import INPUTS  # noqa: E402
import run_v54s  # noqa: E402

W = "outputs/v54sw"
R = "${{ matrix.shard }}"
minute = (SETUP + INPUTS + restore("outputs/v51", "v51-min-41206767350-1")
          + restore("outputs/v52", "v52-min-41219555974-1")
          + "      - run: python scripts/run_v53.py merge --src outputs/v51 outputs/v52 --move --out outputs/v53\n"
          + f"      - run: python scripts/run_v54s.py minute --rule {R} --procs 4 --out {W}/res\n"
          + up(f"v54s-minute-{R}", f"{W}/res"))
final = (SETUP + f"""      - uses: {DOWN}
        with:
          pattern: v54s-minute-*
          path: {W}/res
          merge-multiple: true
""" + "      - run: |\n"
         f"          python scripts/run_v54s.py final --res {W}/res --out {W}/final\n"
         f"          cat {W}/final/V54S_REPORT.md >> \"$GITHUB_STEP_SUMMARY\"\n"
         + up("v54s-report", f"{W}/final"))

head = """name: "v54s: CRASH-long under strict fills"

# scripts/gen_v54s_wf.py writes this file (V54S_PREREGISTRATION.md). Artifacts hold aggregates only.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v54s.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v54s
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"

jobs:
"""
body = job("minute", None, 120, minute, list(run_v54s.RULES)) + "\n" + job("final", "minute", 20, final)
Path(".github/workflows/v54s.yml").write_text(head + body, encoding="utf-8", newline="\n")
print("wrote .github/workflows/v54s.yml")
