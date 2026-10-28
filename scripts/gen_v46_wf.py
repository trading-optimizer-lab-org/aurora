"""Writes .github/workflows/v46-canary.yml and v46.yml (run from the repo root)."""
from pathlib import Path

DATA_RUN = "40551641084"  # the v44 data run whose cache v46 reads
CO = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
PY = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
RESTORE = "actions/cache/restore@0400d5f644dc74513175e3cd8d07132dd4860809"
UP = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DOWN = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
S1_SHARDS, S2_SHARDS = 164, 300


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
RUN = "python scripts/run_v46.py"


def shards(lo: int, hi: int) -> str:
    return "[" + ", ".join(str(i) for i in range(lo, hi)) + "]"


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


def canary() -> str:
    out = """name: "v46 canary: every stage on a small grid"

# docs/research/V46_PREREGISTRATION.md with V29_QUICK: stage 1 on the base and the first and last value of each
# dimension, the selection, stage 2 on three combinations (the base, the next, the last) and the final, on the real
# cached data.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v46-canary.yml

""" + HEAD.format(group="v46-canary", extra='\n  V29_QUICK: "1"')
    out += """  canary:
    runs-on: ubuntu-24.04
    timeout-minutes: 300
    steps:
""" + setup() + CACHES + f"""      - run: {RUN} stage1 --shard 0 --shards 1 --procs 4 {CHOICE} --out outputs/v46w/s1
      - run: {RUN} select --runs outputs/v46w/s1 --procs 4 {CHOICE} --out outputs/v46w/sel
      - run: {RUN} stage2 --shard 0 --shards 1 --sel outputs/v46w/sel --procs 4 {CHOICE} --out outputs/v46w/s2
      - run: {RUN} final --s1 outputs/v46w/s1 --s2 outputs/v46w/s2 --sel outputs/v46w/sel --procs 4 {CHOICE} --out outputs/v46w/report
""" + summary("outputs/v46w/report/V46_REPORT.md") + up("v46-canary", "outputs/v46w", 14)
    return out


def full() -> str:
    out = f"""name: "v46: the book's trades on one-minute bars, technical analysis of every kind"

# docs/research/V46_PREREGISTRATION.md: stage 1 ({S1_SHARDS} shards, one replay each with its 55 filters), the
# selection on 2018-2022, stage 2 ({S2_SHARDS} shards of the 98,304 factorial replays with the 8 chosen filters) and
# the final. Market data stays in the Actions cache; the shards upload strategy returns.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v46.yml

""" + HEAD.format(group="v46", extra="")
    half1 = S1_SHARDS // 2
    for h, (lo, hi) in (("a", (0, half1)), ("b", (half1, S1_SHARDS))):
        out += f"""  s1_{h}:
    runs-on: ubuntu-24.04
    timeout-minutes: 240
    strategy:
      fail-fast: false
      matrix:
        shard: {shards(lo, hi)}
    steps:
""" + setup() + CACHES + f"""      - run: {RUN} stage1 --shard ${{{{ matrix.shard }}}} --shards {S1_SHARDS} --procs 4 {CHOICE} --out outputs/v46w/s1
""" + up("v46-s1-${{ matrix.shard }}", "outputs/v46w/s1") + "\n"
    out += """  select:
    needs: [s1_a, s1_b]
    if: always() && needs.s1_a.result == 'success' && needs.s1_b.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
""" + setup(False) + down("v46-s1-*", "outputs/v46w/s1") + f"""      - run: {RUN} select --runs outputs/v46w/s1 {CHOICE} --out outputs/v46w/sel | tee -a "$GITHUB_STEP_SUMMARY"
""" + up("v46-selection", "outputs/v46w/sel") + "\n"
    half2 = S2_SHARDS // 2
    for h, (lo, hi) in (("a", (0, half2)), ("b", (half2, S2_SHARDS))):
        out += f"""  s2_{h}:
    needs: select
    if: always() && needs.select.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 350
    strategy:
      fail-fast: false
      matrix:
        shard: {shards(lo, hi)}
    steps:
""" + setup() + CACHES + f"""      - uses: {DOWN}
        with:
          name: v46-selection
          path: outputs/v46w/sel
      - run: {RUN} stage2 --shard ${{{{ matrix.shard }}}} --shards {S2_SHARDS} --sel outputs/v46w/sel --procs 4 {CHOICE} --out outputs/v46w/s2
""" + up("v46-s2-${{ matrix.shard }}", "outputs/v46w/s2") + "\n"
    out += """  final:
    needs: [select, s2_a, s2_b]
    if: always() && needs.select.result == 'success' && needs.s2_a.result == 'success' && needs.s2_b.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 300
    steps:
""" + setup() + CACHES + down("v46-s1-*", "outputs/v46w/s1") + down("v46-s2-*", "outputs/v46w/s2") + f"""      - uses: {DOWN}
        with:
          name: v46-selection
          path: outputs/v46w/sel
      - run: {RUN} final --s1 outputs/v46w/s1 --s2 outputs/v46w/s2 --sel outputs/v46w/sel --procs 4 {CHOICE} --out outputs/v46w/report
""" + summary("outputs/v46w/report/V46_REPORT.md") + up("v46-report", "outputs/v46w/report")
    return out


Path(".github/workflows/v46-canary.yml").write_bytes(canary().encode())
Path(".github/workflows/v46.yml").write_bytes(full().encode())
