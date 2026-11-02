"""Writes .github/workflows/v54.yml (run from the repo root) from v50.yml, whose data steps it keeps unchanged:
126 book jobs with run_v54.py and a final that needs every one of them (V54_PREREGISTRATION.md)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v54  # noqa: E402

src = Path(".github/workflows/v50.yml").read_text(encoding="utf-8")
head, rest = src.split("jobs:\n", 1)
head = """name: "v54: the FREE daily book chosen year by year"

# scripts/gen_v54_wf.py writes this file from v50.yml (V54_PREREGISTRATION.md). Market data stays in the Actions
# cache; the jobs upload daily account returns.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v54.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v54
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"

"""
body = re.sub(r"book: \[[0-9, ]+\]", "book: [" + ", ".join(map(str, range(len(run_v54.BOOKS)))) + "]", rest)
body = body.replace("    needs: run\n    if: always()\n", "    needs: run\n    if: always() && needs.run.result == 'success'\n")
body = body.replace("run_v50.py run", "run_v54.py run").replace("v50-run-", "v54-run-").replace("outputs/v50w", "outputs/v54w")
body = body.replace("run_v50.py final --runs outputs/v54w/runs --out outputs/v54w/report",
                    "run_v54.py final --procs 4 --runs outputs/v54w/runs --out outputs/v54w/report")
body = body.replace("V50_REPORT", "V54_REPORT").replace("v50-report", "v54-report")
body = body.replace("    timeout-minutes: 60\n", "    timeout-minutes: 180\n")
assert "v50" not in body.replace("run_v50", ""), [l for l in body.splitlines() if "v50" in l]
Path(".github/workflows/v54.yml").write_text(head + "jobs:\n" + body, encoding="utf-8", newline="\n")
print("wrote .github/workflows/v54.yml")
