"""Writes .github/workflows/v51.yml (run from the repo root): V51_PREREGISTRATION.md section 4, every stage in one run.

  factory (20: one per setup and side) -> select -> account (300) -> pick -> books (300) -> pick2 -> confirm (51) -> final
Trades and prices pass between jobs only in caches keyed by the run; artifacts hold aggregate statistics only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import CO, PY, RESTORE, UP, DOWN  # noqa: E402

from aurora.research.v51_engine import SETUPS  # noqa: E402

DATA_RUN = "41206767350"  # v51-data: the event superset and its one-minute bars
SAVE = "actions/cache/save@0400d5f644dc74513175e3cd8d07132dd4860809"
GROUPS = [f"{s}-{d}" for s in SETUPS for d in ("short", "long")]
SHARDS, HALF, CONFIRM = 300, 150, 51
RUN = "${{ github.run_id }}"
W = "outputs/v51w"


def setup(swap: bool = False) -> str:
    out = f"""      - uses: {CO}
        with:
          persist-credentials: false
      - uses: {PY}
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install --upgrade pip && python -m pip install -e .
"""
    if swap:
        out += """      - name: Add swap
        run: |
          sudo swapoff -a
          avail=$(df --output=avail -BG /mnt | tail -1 | tr -dc 0-9)
          size=$(( avail > 40 ? 24 : avail - 10 ))
          sudo rm -f /mnt/swapfile
          sudo fallocate -l "${size}G" /mnt/swapfile
          sudo chmod 600 /mnt/swapfile
          sudo mkswap /mnt/swapfile
          sudo swapon /mnt/swapfile
"""
    return out


def restore(path: str, key: str, must: bool = True) -> str:
    p = path if "\n" not in path else "|\n" + "\n".join(f"            {x}" for x in path.split("\n"))
    return f"""      - uses: {RESTORE}
        with:
          path: {p}
          key: {key}
          fail-on-cache-miss: {'true' if must else 'false'}
"""


def save(path: str, key: str) -> str:
    return f"""      - uses: {SAVE}
        with:
          path: {path}
          key: {key}
"""


def up(name: str, path: str) -> str:
    return f"""      - if: always()
        uses: {UP}
        with:
          name: {name}
          path: {path}
          retention-days: 90
"""


def down(pattern: str, path: str, merge: bool = True) -> str:
    return f"""      - uses: {DOWN}
        with:
          pattern: {pattern}
          path: {path}
          merge-multiple: {'true' if merge else 'false'}
"""


def job(name: str, needs: str | None, minutes: int, body: str, matrix: list | None = None) -> str:
    out = f"  {name}:\n"
    if needs:
        need = [n.strip() for n in needs.split(",")]
        ok = " && ".join(f"needs.{n}.result == 'success'" for n in need[-1:])
        out += f"    needs: [{', '.join(need)}]\n    if: always() && {ok}\n"
    out += f"    runs-on: ubuntu-24.04\n    timeout-minutes: {minutes}\n"
    if matrix is not None:
        out += f"    strategy:\n      fail-fast: false\n      matrix:\n        shard: [{', '.join(map(str, matrix))}]\n"
    return out + "    steps:\n" + body


SEL = restore(f"{W}/sel", f"v51-sel-{RUN}")
factory = (setup(swap=True) + restore("outputs/v18", "v18-inputs-39433812183-1")
           + restore("outputs/v28/inputs\noutputs/v28/pmstore", "v28-inputs2-39825946914-1")
           + restore("outputs/v51", f"v51-min-{DATA_RUN}-1")
           + f"      - run: python scripts/run_v51.py factory --group ${{{{ matrix.shard }}}} --procs 4 "
             f"--out {W}/fac/${{{{ matrix.shard }}}}\n"
           + save(f"{W}/fac/${{{{ matrix.shard }}}}", f"v51-fac-{RUN}-${{{{ matrix.shard }}}}")
           + up("v51-fac-${{ matrix.shard }}", f"{W}/fac/${{{{ matrix.shard }}}}/report.json"))
select = (setup() + "".join(restore(f"{W}/fac/{g}", f"v51-fac-{RUN}-{g}", must=False) for g in GROUPS)
          + f"      - run: python scripts/run_v51.py select --factory {W}/fac --out {W}/sel\n"
          + save(f"{W}/sel", f"v51-sel-{RUN}") + up("v51-sel", f"{W}/sel/configs.json"))


def shard_job(cmd: str, extra: str, art: str, pre: str = "") -> str:
    return (setup() + SEL + pre + f"      - run: python scripts/run_v51.py {cmd} --sel {W}/sel {extra}"
            f"--shard ${{{{ matrix.shard }}}} --shards {SHARDS if cmd != 'confirm' else CONFIRM} --procs 4 "
            f"--out {W}/runs/{cmd}\n" + up(f"{art}-${{{{ matrix.shard }}}}", f"{W}/runs/{cmd}"))


account = shard_job("account", "", "v51-acc")
pick = (setup() + down("v51-acc-*", f"{W}/runs/account")
        + f"      - run: python scripts/run_v51.py pick --runs {W}/runs/account --out {W}/picks\n"
        + up("v51-picks", f"{W}/picks"))
PICKS = down("v51-picks", f"{W}/picks")
books = shard_job("books", f"--picks {W}/picks ", "v51-books", PICKS)
pick2 = (setup() + SEL + down("v51-books-*", f"{W}/runs/books")
         + f"      - run: python scripts/run_v51.py pick2 --runs {W}/runs/books --sel {W}/sel --out {W}/picks2\n"
         + up("v51-picks2", f"{W}/picks2"))
PICKS2 = PICKS + down("v51-picks2", f"{W}/picks")
confirm = shard_job("confirm", f"--picks {W}/picks ", "v51-conf", PICKS2)
final = (setup() + SEL + PICKS2 + down("v51-fac-*", f"{W}/facrep", merge=False)
         + down("v51-conf-*", f"{W}/runs/confirm")
         + "      - run: |\n"
           f"          python scripts/run_v51.py final --factory {W}/facrep --sel {W}/sel --picks {W}/picks "
           f"--runs {W}/runs/confirm --out {W}/final\n"
           f"          cat {W}/final/V51_REPORT.md >> \"$GITHUB_STEP_SUMMARY\"\n"
         + up("v51-report", f"{W}/final"))

head = """name: "v51: every small-cap setup on one-minute bars, the grid, the account and the books"

# scripts/gen_v51_wf.py writes this file (V51_PREREGISTRATION.md section 4). Trades and prices pass between jobs only
# in caches keyed by this run; artifacts hold aggregate statistics only.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v51.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v51
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"

jobs:
"""
body = (job("factory", None, 300, factory, GROUPS) + "\n" + job("select", "factory", 60, select) + "\n"
        + job("account_a", "select", 120, account, list(range(HALF))) + "\n"
        + job("account_b", "select", 120, account, list(range(HALF, SHARDS))) + "\n"
        + job("pick", "account_a, account_b", 30, pick).replace(
            "if: always() && needs.account_b.result == 'success'",
            "if: always() && needs.account_a.result == 'success' && needs.account_b.result == 'success'") + "\n"
        + job("books_a", "pick", 120, books, list(range(HALF))) + "\n"
        + job("books_b", "pick", 120, books, list(range(HALF, SHARDS))) + "\n"
        + job("pick2", "books_a, books_b", 30, pick2).replace(
            "if: always() && needs.books_b.result == 'success'",
            "if: always() && needs.books_a.result == 'success' && needs.books_b.result == 'success'") + "\n"
        + job("confirm", "pick2", 120, confirm, list(range(CONFIRM))) + "\n"
        + job("final", "confirm", 30, final))
Path(".github/workflows/v51.yml").write_text(head + body, encoding="utf-8")
print("wrote .github/workflows/v51.yml")
