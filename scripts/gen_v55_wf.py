"""Writes .github/workflows/v55.yml (run from the repo root): V55_PREREGISTRATION.md.

  fetch: Alpaca's IEX bars of v43's symbol-days, saved to the Actions cache only
  run:   v49's book under TZC with the 15:50 decision from sip, iex and iex10; final: the report
Artifacts hold aggregates only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import CACHES, CHOICE, HEAD, cache, down, setup, summary, up  # noqa: E402

SAVE = "actions/cache/save@0400d5f644dc74513175e3cd8d07132dd4860809"
RUN = "python scripts/run_v55.py"
OUT = "outputs/v55w"
IEX = "outputs/v55/iex"
KEY = "v55-iex-${{ github.run_id }}"

out = """name: "v55: v49's book decided on the free IEX price at 15:50"

# scripts/gen_v55_wf.py writes this file (docs/research/V55_PREREGISTRATION.md). IEX bars stay in the Actions cache;
# the jobs upload strategy returns and aggregate errors only.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v55.yml

""" + HEAD.format(group="v55", extra="")
out += """  fetch:
    runs-on: ubuntu-24.04
    timeout-minutes: 180
    env:
      APCA_API_KEY_ID: ${{ secrets.ALPACA_API_KEY_ID }}
      APCA_API_SECRET_KEY: ${{ secrets.ALPACA_API_SECRET_KEY }}
    steps:
""" + setup(False) + cache("outputs/v43", "v43-data-none", "v43-data-") + f"""      - run: {RUN} fetch --data outputs/v43 --iex {IEX}
      - uses: {SAVE}
        with:
          path: {IEX}
          key: {KEY}

  run:
    needs: fetch
    runs-on: ubuntu-24.04
    timeout-minutes: 350
    strategy:
      fail-fast: false
      matrix:
        source: [sip, iex, iex10]
    steps:
""" + setup() + CACHES + cache(IEX, KEY) + f"""      - run: {RUN} run --source ${{{{ matrix.source }}}} --procs 4 {CHOICE} --iex {IEX} --out {OUT}/runs
""" + up("v55-run-${{ matrix.source }}", f"{OUT}/runs") + "\n"
out += """  final:
    needs: run
    if: always()
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
""" + setup(False) + down("v55-run-*", f"{OUT}/runs") + f"""      - run: {RUN} final --runs {OUT}/runs --out {OUT}/report
""" + summary(f"{OUT}/report/V55_REPORT.md") + up("v55-report", f"{OUT}/report")

Path(".github/workflows/v55.yml").write_text(out, encoding="utf-8", newline="\n")
