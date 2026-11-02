"""Writes .github/workflows/v54d.yml (run from the repo root): V54D_PREREGISTRATION.md.

  daily (daily panel) and minute (v51+v52 minute bars: minute and cover) -> final
Prices stay on the runners and in caches; artifacts hold aggregates only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import DOWN  # noqa: E402
from gen_v52_wf import SETUP, job, restore, up  # noqa: E402

W = "outputs/v54dw"
INPUTS = (restore("outputs/v18", "v18-inputs-39433812183-1")
          + restore("outputs/v28/inputs\noutputs/v28/pmstore", "v28-inputs2-39825946914-1"))
daily = (SETUP + INPUTS + f"      - run: python scripts/run_v54d.py daily --out {W}/res\n"
         + up("v54d-daily", f"{W}/res"))
minute = (SETUP + INPUTS + restore("outputs/v51", "v51-min-41206767350-1")
          + restore("outputs/v52", "v52-min-41219555974-1")
          + "      - run: python scripts/run_v53.py merge --src outputs/v51 outputs/v52 --move --out outputs/v53\n"
          + f"      - run: python scripts/run_v54d.py minute --procs 4 --out {W}/res\n"
          + f"      - run: python scripts/run_v54d.py cover --procs 4 --out {W}/res\n"
          + up("v54d-minute", f"{W}/res"))
final = (SETUP + f"""      - uses: {DOWN}
        with:
          pattern: v54d-*
          path: {W}/res
          merge-multiple: true
""" + "      - run: |\n"
         f"          python scripts/run_v54d.py final --res {W}/res --out {W}/final\n"
         f"          cat {W}/final/V54D_REPORT.md >> \"$GITHUB_STEP_SUMMARY\"\n"
         + up("v54d-report", f"{W}/final"))

head = """name: "v54d: CRASH-long by year, market or data"

# scripts/gen_v54d_wf.py writes this file (V54D_PREREGISTRATION.md). Artifacts hold aggregates only.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v54d.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v54d
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"

jobs:
"""
body = (job("daily", None, 60, daily) + "\n" + job("minute", None, 120, minute) + "\n"
        + "  final:\n    needs: [daily, minute]\n    if: always() && needs.daily.result == 'success' && "
          "needs.minute.result == 'success'\n    runs-on: ubuntu-24.04\n    timeout-minutes: 20\n    steps:\n" + final)
Path(".github/workflows/v54d.yml").write_text(head + body, encoding="utf-8", newline="\n")
print("wrote .github/workflows/v54d.yml")
