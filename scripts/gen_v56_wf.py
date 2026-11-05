"""Writes .github/workflows/v56.yml (run from the repo root): V56_PREREGISTRATION.md.

  run:   48 books under TZC in four locate worlds, close entries decided on v55's IEX bars; final: the report
Artifacts hold aggregates only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import CACHES, CHOICE, HEAD, cache, down, setup, summary, up  # noqa: E402

RUN = "python scripts/run_v56.py"
OUT = "outputs/v56w"
IEX = "outputs/v55/iex"
KEY = "v55-iex-42048053366"  # v55's IEX bars
BOOKS = 48  # len(run_v56.BOOKS)

out = """name: "v56: the locate fill rate for 150% a year at 5% ruin"

# scripts/gen_v56_wf.py writes this file (docs/research/V56_PREREGISTRATION.md). Market data stays in the Actions
# cache; the jobs upload strategy returns only.
# run: 3
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v56.yml

""" + HEAD.format(group="v56", extra="")
out += f"""  run:
    runs-on: ubuntu-24.04
    timeout-minutes: 350
    strategy:
      fail-fast: false
      matrix:
        book: [{", ".join(str(k) for k in range(BOOKS))}]
    steps:
""" + setup() + CACHES + cache(IEX, KEY) + f"""      - run: {RUN} run --book ${{{{ matrix.book }}}} --procs 4 {CHOICE} --iex {IEX} --out {OUT}/runs
""" + up("v56-run-${{ matrix.book }}", f"{OUT}/runs") + "\n"
out += """  final:
    needs: run
    if: always()
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
""" + setup(False) + down("v56-run-*", f"{OUT}/runs") + f"""      - run: {RUN} final --runs {OUT}/runs --out {OUT}/report
""" + summary(f"{OUT}/report/V56_REPORT.md") + up("v56-report", f"{OUT}/report")

Path(".github/workflows/v56.yml").write_text(out, encoding="utf-8", newline="\n")
