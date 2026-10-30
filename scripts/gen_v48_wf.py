"""Writes .github/workflows/v48-canary.yml and v48.yml (run from the repo root)."""
from pathlib import Path

DATA_RUN = "40551641084"  # the v44 data run whose cache v48 reads (as v46)
CO = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
PY = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
RESTORE = "actions/cache/restore@0400d5f644dc74513175e3cd8d07132dd4860809"
UP = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DOWN = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"


def setup(sk: bool = True) -> str:
    extra = " && python -m pip install scikit-learn" if sk else ""
    return f"""      - uses: {CO}
        with:
          persist-credentials: false
      - uses: {PY}
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install --upgrade pip && python -m pip install -e .{extra}
      - name: Add swap
        run: |
          sudo swapoff -a
          avail=$(df --output=avail -BG /mnt | tail -1 | tr -dc 0-9)
          size=$(( avail > 40 ? 24 : avail - 10 ))
          sudo rm -f /mnt/swapfile
          sudo fallocate -l "${{size}}G" /mnt/swapfile
          sudo chmod 600 /mnt/swapfile
          sudo mkswap /mnt/swapfile
          sudo swapon /mnt/swapfile
"""


def cache(path: str, key: str, prefix: str | None = None) -> str:
    p = path if "\n" not in path else "|\n" + "\n".join(f"            {x}" for x in path.split("\n"))
    rk = f"\n          restore-keys: {prefix}" if prefix else ""
    return f"""      - uses: {RESTORE}
        with:
          path: {p}
          key: {key}{rk}
          fail-on-cache-miss: true
"""


def art(name: str, path: str, run_id: str) -> str:
    return f"""      - uses: {DOWN}
        with:
          name: {name}
          path: {path}
          run-id: {run_id}
          github-token: ${{{{ github.token }}}}
"""


def down(pattern: str, path: str) -> str:
    return f"""      - uses: {DOWN}
        with:
          pattern: {pattern}
          path: {path}
          merge-multiple: true
"""


def up(name: str, path: str, days: int = 90) -> str:
    return f"""      - if: always()
        uses: {UP}
        with:
          name: {name}
          path: {path}
          retention-days: {days}
"""


# The cache version hashes the path list, so each must match its save step exactly (as in gen_v44_wf.py).
V44_DATA = "outputs/v44\n!outputs/v44/filing/minutes\n!outputs/v44/index_days\n!outputs/v44/tick_days"
CACHES = (cache("outputs/v18", "v18-inputs-39433812183-1") + cache("outputs/v23/store", "v23-store-none", "v23-store-")
          + cache("outputs/v24/store", "v24-store-none", "v24-store-")
          + cache("outputs/v28/inputs\noutputs/v28/pmstore", "v28-inputs2-none", "v28-inputs2-")
          + cache("outputs/v26/store", "v26-store-none", "v26-store-")
          + cache("outputs/v43", "v43-data-none", "v43-data-")
          + cache(V44_DATA, f"v44-data-{DATA_RUN}-none", f"v44-data-{DATA_RUN}-")
          + art("v28-report", "outputs/v28w/report", "39915126980")
          + art("v33-choice", "outputs/v33w/choice", "40192951586"))
CHOICE = "--choice outputs/v33w/choice"
RUN = "python scripts/run_v48.py"
SHARDS = 63  # len(run_v48.COMBOS)
CANARY = [0, 36]  # the base sizes and RU 0.25


HEAD = """permissions:
  contents: read
  actions: read

concurrency:
  group: {group}
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"{extra}

jobs:
"""


def summary(path: str) -> str:
    return f"""      - if: always()
        run: if [ -f {path} ]; then cat {path} >> "$GITHUB_STEP_SUMMARY"; fi
"""


OUT = "outputs/v48w"


def canary() -> str:
    out = """name: "v48 canary: two size sets, the choice, the API check and the report"

# docs/research/V48_PREREGISTRATION.md with V29_QUICK: the base sizes and RU 0.25 with seeds 0-2, the choice, both
# API checks and the final, on the real cached data.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v48-canary.yml

""" + HEAD.format(group="v48-canary", extra='\n  V29_QUICK: "1"')
    out += """  canary:
    runs-on: ubuntu-24.04
    timeout-minutes: 340
    steps:
""" + setup() + CACHES
    for k in CANARY:
        out += f"""      - run: {RUN} run --shard {k} --procs 4 {CHOICE} --out {OUT}/runs
"""
    out += f"""      - run: {RUN} select --runs {OUT}/runs {CHOICE} --out {OUT}/choice
      - run: {RUN} api --which chosen --procs 4 {CHOICE} --choice-dir {OUT}/choice --out {OUT}/api
      - run: {RUN} api --which base --procs 4 {CHOICE} --choice-dir {OUT}/choice --out {OUT}/api
      - run: {RUN} final --runs {OUT}/runs --api {OUT}/api {CHOICE} --choice-dir {OUT}/choice --out {OUT}/report
""" + summary(f"{OUT}/report/V48_REPORT.md") + up("v48-canary", OUT, 14)
    return out


def full() -> str:
    out = f"""name: "v48: per-name sizes judged on an ensemble of trade sets"

# docs/research/V48_PREREGISTRATION.md: {SHARDS} size sets (each at 3 and 5 new positions a day, 31 seeds), the
# choice on 2018-2022 paths, the API check of the choice and the base book, and the report. Market data stays in the
# Actions cache; the jobs upload strategy returns.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v48.yml

""" + HEAD.format(group="v48", extra="")
    out += f"""  run:
    runs-on: ubuntu-24.04
    timeout-minutes: 350
    strategy:
      fail-fast: false
      matrix:
        shard: [{", ".join(str(k) for k in range(SHARDS))}]
    steps:
""" + setup() + CACHES + f"""      - run: {RUN} run --shard ${{{{ matrix.shard }}}} --procs 4 {CHOICE} --out {OUT}/runs
""" + up("v48-run-${{ matrix.shard }}", f"{OUT}/runs") + "\n"
    out += """  select:
    needs: run
    if: always() && needs.run.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
""" + setup(False) + down("v48-run-*", f"{OUT}/runs") + f"""      - run: {RUN} select --runs {OUT}/runs {CHOICE} --out {OUT}/choice | tee -a "$GITHUB_STEP_SUMMARY"
""" + up("v48-choice", f"{OUT}/choice") + "\n"
    out += """  api:
    needs: select
    if: always() && needs.select.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 350
    strategy:
      fail-fast: false
      matrix:
        which: [base, chosen]
    steps:
""" + setup() + CACHES + f"""      - uses: {DOWN}
        with:
          name: v48-choice
          path: {OUT}/choice
      - run: {RUN} api --which ${{{{ matrix.which }}}} --procs 4 {CHOICE} --choice-dir {OUT}/choice --out {OUT}/api
""" + up("v48-api-${{ matrix.which }}", f"{OUT}/api") + "\n"
    out += """  final:
    needs: [run, select, api]
    if: always() && needs.select.result == 'success' && needs.api.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
""" + setup(False) + down("v48-run-*", f"{OUT}/runs") + down("v48-api-*", f"{OUT}/api") + f"""      - uses: {DOWN}
        with:
          name: v48-choice
          path: {OUT}/choice
      - run: {RUN} final --runs {OUT}/runs --api {OUT}/api {CHOICE} --choice-dir {OUT}/choice --out {OUT}/report
""" + summary(f"{OUT}/report/V48_REPORT.md") + up("v48-report", f"{OUT}/report")
    return out


Path(".github/workflows/v48-canary.yml").write_bytes(canary().encode())
Path(".github/workflows/v48.yml").write_bytes(full().encode())
