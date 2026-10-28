"""Writes .github/workflows/v44-canary.yml and v44.yml (run from the repo root)."""
from pathlib import Path

DATA_RUN = "40551641084"
CO = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
PY = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
RESTORE = "actions/cache/restore@0400d5f644dc74513175e3cd8d07132dd4860809"
UP = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DOWN = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"


def setup(sk: bool = False) -> str:
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


def cache(path: str, key: str, prefix: str | None = None, must: bool = True) -> str:
    p = path if "\n" not in path else "|\n" + "\n".join(f"            {x}" for x in path.split("\n"))
    rk = f"\n          restore-keys: {prefix}" if prefix else ""
    return f"""      - uses: {RESTORE}
        with:
          path: {p}
          key: {key}{rk}
          fail-on-cache-miss: {'true' if must else 'false'}
"""


def art(name: str, path: str, run_id: str) -> str:
    return f"""      - uses: {DOWN}
        with:
          name: {name}
          path: {path}
          run-id: {run_id}
          github-token: ${{{{ github.token }}}}
"""


def v44data(must: bool) -> str:
    # The cache version hashes the path list, so it must match v44-data.yml's save step exactly.
    path = "outputs/v44\n!outputs/v44/filing/minutes\n!outputs/v44/index_days\n!outputs/v44/tick_days"
    return cache(path,f"v44-data-{DATA_RUN}-none", f"v44-data-{DATA_RUN}-", must)


N_CACHES = (cache("outputs/v18", "v18-inputs-39433812183-1") + cache("outputs/v23/store", "v23-store-none", "v23-store-")
            + cache("outputs/v24/store", "v24-store-none", "v24-store-")
            + cache("outputs/v28/inputs\noutputs/v28/pmstore", "v28-inputs2-none", "v28-inputs2-"))
M_CACHES = (N_CACHES + cache("outputs/v26/store", "v26-store-none", "v26-store-")
            + cache("outputs/v43", "v43-data-none", "v43-data-")
            + art("v28-report", "outputs/v28w/report", "39915126980")
            + art("v33-choice", "outputs/v33w/choice", "40192951586"))
CHOICE = "--choice outputs/v33w/choice"


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


def canary() -> str:
    out = """name: "v44 canary: part N, M and C on a small grid"

# docs/research/V44_PREREGISTRATION.md: run_v44n's canary (every family's first configurations), run_v44m with
# V29_QUICK (the base unit, the first pair unit and a few more on shard 0) and its final, and run_v44c without part N's
# members. Uses whatever v44 data is cached (none: the features and families that need it stay empty).
# run: 2
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v44-canary.yml

""" + HEAD.format(group="v44-canary", extra='\n  V29_QUICK: "1"\n  V44_ALLOW_MISSING: "1"')
    out += """  canary:
    runs-on: ubuntu-24.04
    timeout-minutes: 300
    steps:
""" + setup(True) + M_CACHES + cache("outputs/v44", "v44-a-40486882613-1", "v44-a-", False) + f"""      - run: python scripts/run_v44m.py run --shard 0 --shards 300 --procs 4 {CHOICE} --out outputs/v44w/m/run
      - run: python scripts/run_v44m.py final --runs outputs/v44w/m/run --procs 4 {CHOICE} --out outputs/v44w/m/report
      - run: python scripts/run_v44c.py --procs 4 {CHOICE} --nsum outputs/v44w/n/none.json --msum outputs/v44w/m/report/v44m_summary.json --out outputs/v44w/c
      - if: always()
        run: python scripts/run_v44n.py real --canary --workers 4 --out outputs/v44w/n/canary
      - if: always()
        run: |
          for f in outputs/v44w/m/report/V44M_REPORT.md outputs/v44w/c/V44C_REPORT.md; do
            if [ -f "$f" ]; then cat "$f" >> "$GITHUB_STEP_SUMMARY"; fi
          done
      - if: always()
        uses: {UP}
        with:
          name: v44-canary
          path: |
            outputs/v44w/m/report
            outputs/v44w/c
          retention-days: 14
"""
    return out


def wait(name: str, needs: str | None) -> str:
    nd = f"\n    needs: {needs}" if needs else ""
    return f"""  {name}:{nd}
    runs-on: ubuntu-24.04
    timeout-minutes: 350
    steps:
      - name: Wait for the v44 data run to finish
        env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: |
          for i in $(seq 1 330); do
            a=$(gh run view {DATA_RUN} --repo "${{{{ github.repository }}}}" --json status,conclusion -q '.status + " " + .conclusion' || echo unknown)
            echo "$(date -u +%H:%M) data=$a"
            if [ "$a" = "completed success" ]; then exit 0; fi
            case "$a" in completed*) echo "the data run did not succeed"; exit 1;; esac
            sleep 60
          done
          {'exit 0' if needs is None else 'exit 1'}
"""


def full() -> str:
    out = f"""name: "v44: new one-minute families, the book's meta-labels and execution, their combination"

# docs/research/V44_PREREGISTRATION.md. Waits for the v44 data run ({DATA_RUN}); then part N (run_v44n: 300 shards
# of real returns, selection, 300 shards of placebos, report), part M (run_v44m: 300 shards of books, final) and part C
# (run_v44c). Market data stays in the Actions cache; the shards upload strategy returns.
# run: 4
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v44.yml

""" + HEAD.format(group="v44", extra="")
    out += wait("wait_a", None) + "\n" + wait("wait_b", "wait_a") + "\n"
    for half, (lo, hi) in (("a", (0, 150)), ("b", (150, 300))):
        out += f"""  n_real_{half}:
    needs: wait_b
    runs-on: ubuntu-24.04
    timeout-minutes: 360
    strategy:
      fail-fast: false
      matrix:
        shard: {shards(lo, hi)}
    steps:
""" + setup() + N_CACHES + v44data(True) + f"""      - run: python scripts/run_v44n.py real --shard ${{{{ matrix.shard }}}} --shards 300 --workers 4 --out outputs/v44w/n/part
      - if: always()
        uses: {UP}
        with:
          name: v44n-real-${{{{ matrix.shard }}}}
          path: outputs/v44w/n/part
          retention-days: 14

"""
    out += """  n_select:
    needs: [n_real_a, n_real_b]
    runs-on: ubuntu-24.04
    timeout-minutes: 120
    outputs:
      names: ${{ steps.sel.outputs.names }}
    steps:
""" + setup() + cache("outputs/v18", "v18-inputs-39433812183-1") + f"""      - uses: {DOWN}
        with:
          pattern: v44n-real-*
          path: outputs/v44w/n/real-parts
      - id: sel
        run: |
          python scripts/run_v44n.py select --parts outputs/v44w/n/real-parts --out outputs/v44w/n/sel
          echo "names=$(cat outputs/v44w/n/sel/selected.txt)" >> "$GITHUB_OUTPUT"
      - uses: {UP}
        with:
          name: v44n-selection
          path: outputs/v44w/n/sel
          retention-days: 30

"""
    for half, (lo, hi) in (("a", (0, 150)), ("b", (150, 300))):
        out += f"""  n_placebo_{half}:
    needs: n_select
    runs-on: ubuntu-24.04
    timeout-minutes: 360
    env:
      SELECTED: ${{{{ needs.n_select.outputs.names }}}}
    strategy:
      fail-fast: false
      matrix:
        shard: {shards(lo, hi)}
    steps:
""" + setup() + N_CACHES + v44data(True) + f"""      - run: python scripts/run_v44n.py placebo --shard ${{{{ matrix.shard }}}} --shards 300 --workers 4 --selected "$SELECTED" --out outputs/v44w/n/part
      - if: always()
        uses: {UP}
        with:
          name: v44n-plac-${{{{ matrix.shard }}}}
          path: outputs/v44w/n/part
          retention-days: 14

"""
    out += """  n_report:
    needs: [n_select, n_placebo_a, n_placebo_b]
    if: always() && needs.n_select.result == 'success' && needs.n_placebo_a.result == 'success' && needs.n_placebo_b.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 180
    steps:
""" + setup() + N_CACHES + v44data(True) + f"""      - uses: {DOWN}
        with:
          name: v44n-selection
          path: outputs/v44w/n/sel
      - uses: {DOWN}
        with:
          pattern: v44n-plac-*
          path: outputs/v44w/n/parts
      - run: |
          mv outputs/v44w/n/sel/real outputs/v44w/n/parts/real
          python scripts/run_v44n.py report --inputs outputs/v18/v14 --parts outputs/v44w/n/parts --selected outputs/v44w/n/sel/selected.json --out outputs/v44w/n/report
          python scripts/run_v44n.py halves --inputs outputs/v18 --selected outputs/v44w/n/sel/selected.json --report outputs/v44w/n/report/REPORT.md
      - if: always()
        run: if [ -f outputs/v44w/n/report/REPORT.md ]; then cat outputs/v44w/n/report/REPORT.md >> "$GITHUB_STEP_SUMMARY"; fi
      - if: always()
        uses: {UP}
        with:
          name: v44n-report
          path: |
            outputs/v44w/n/report/REPORT.md
            outputs/v44w/n/report/summary.json
            outputs/v44w/n/report/streams.parquet
          retention-days: 90

"""
    for half, (lo, hi) in (("a", (0, 150)), ("b", (150, 300))):
        out += f"""  m_run_{half}:
    needs: wait_b
    runs-on: ubuntu-24.04
    timeout-minutes: 350
    strategy:
      fail-fast: false
      matrix:
        shard: {shards(lo, hi)}
    steps:
""" + setup(True) + M_CACHES + v44data(True) + f"""      - run: python scripts/run_v44m.py run --shard ${{{{ matrix.shard }}}} --shards 300 --procs 4 {CHOICE} --out outputs/v44w/m/run
      - if: always()
        uses: {UP}
        with:
          name: v44m-run-${{{{ matrix.shard }}}}
          path: outputs/v44w/m/run
          retention-days: 90

"""
    out += """  m_final:
    needs: [m_run_a, m_run_b]
    if: always() && needs.m_run_a.result == 'success' && needs.m_run_b.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 240
    steps:
""" + setup(True) + M_CACHES + v44data(True) + f"""      - uses: {DOWN}
        with:
          pattern: v44m-run-*
          path: outputs/v44w/m/run
          merge-multiple: true
      - run: python scripts/run_v44m.py final --runs outputs/v44w/m/run --procs 4 {CHOICE} --out outputs/v44w/m/report
      - if: always()
        run: if [ -f outputs/v44w/m/report/V44M_REPORT.md ]; then cat outputs/v44w/m/report/V44M_REPORT.md >> "$GITHUB_STEP_SUMMARY"; fi
      - if: always()
        uses: {UP}
        with:
          name: v44m-report
          path: outputs/v44w/m/report
          retention-days: 90

  c_final:
    needs: [n_report, m_final]
    if: always() && needs.m_final.result == 'success' && needs.n_report.result == 'success'
    runs-on: ubuntu-24.04
    timeout-minutes: 240
    steps:
""" + setup(True) + M_CACHES + v44data(True) + f"""      - uses: {DOWN}
        with:
          name: v44m-report
          path: outputs/v44w/m/report
      - uses: {DOWN}
        with:
          name: v44n-report
          path: outputs/v44w/n/report
      - run: python scripts/run_v44c.py --procs 4 {CHOICE} --nsum outputs/v44w/n/report/summary.json --msum outputs/v44w/m/report/v44m_summary.json --out outputs/v44w/c
      - if: always()
        run: if [ -f outputs/v44w/c/V44C_REPORT.md ]; then cat outputs/v44w/c/V44C_REPORT.md >> "$GITHUB_STEP_SUMMARY"; fi
      - if: always()
        uses: {UP}
        with:
          name: v44c-report
          path: outputs/v44w/c
          retention-days: 90
"""
    return out


Path(".github/workflows/v44-canary.yml").write_bytes(canary().encode())
Path(".github/workflows/v44.yml").write_bytes(full().encode())
