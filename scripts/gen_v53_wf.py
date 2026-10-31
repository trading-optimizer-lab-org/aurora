"""Writes .github/workflows/v53.yml (run from the repo root): V53_PREREGISTRATION.md, every stage in one run.

  factory (20) -> select -> account (300) -> pick -> books (300) -> choose -> oos (80) -> final
Trades and prices pass between jobs only in caches keyed by the run; artifacts hold aggregate statistics and account
returns only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_v49_wf import CO, PY, RESTORE, UP, DOWN  # noqa: E402

from aurora.research.v51_engine import SETUPS  # noqa: E402

V51_DATA, V52_DATA = "41206767350", "41219555974"
SAVE = "actions/cache/save@0400d5f644dc74513175e3cd8d07132dd4860809"
GROUPS = [f"{s}-{d}" for s in SETUPS for d in ("short", "long")]
SHARDS, HALF, OOS = 300, 150, 80
RUN = "${{ github.run_id }}"
W = "outputs/v53w"
M = "${{ matrix.shard }}"


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


SEL = restore(f"{W}/sel", f"v53-sel-{RUN}")
factory = (setup(swap=True) + restore("outputs/v18", "v18-inputs-39433812183-1")
           + restore("outputs/v28/inputs\noutputs/v28/pmstore", "v28-inputs2-39825946914-1")
           + restore("outputs/v51", f"v51-min-{V51_DATA}-1") + restore("outputs/v52", f"v52-min-{V52_DATA}-1")
           + "      - run: python scripts/run_v53.py merge --src outputs/v51 outputs/v52 --move --out outputs/v53\n"
           + f"      - run: python scripts/run_v53.py factory --group {M} --procs 4 --out {W}/fac/{M}\n"
           + save(f"{W}/fac/{M}", f"v53-fac-{RUN}-{M}") + up(f"v53-fac-{M}", f"{W}/fac/{M}/report.json"))
select = (setup() + "".join(restore(f"{W}/fac/{g}", f"v53-fac-{RUN}-{g}") for g in GROUPS)
          + f"      - run: python scripts/run_v53.py select --factory {W}/fac --out {W}/sel\n"
          + save(f"{W}/sel", f"v53-sel-{RUN}")
          + up("v53-sel", f"|\n            {W}/sel/configs.json\n            {W}/sel/contexts.json"))
account = (setup() + SEL + f"      - run: python scripts/run_v53.py account --sel {W}/sel --shard {M} --shards {SHARDS} "
           f"--procs 4 --out {W}/runs/acc\n" + up(f"v53-acc-{M}", f"{W}/runs/acc"))
pick = (setup() + down("v53-acc-*", f"{W}/runs/acc")
        + f"      - run: python scripts/run_v53.py pick --runs {W}/runs/acc --out {W}/picks\n"
        + up("v53-picks", f"{W}/picks"))
books = (setup() + SEL + down("v53-picks", f"{W}/picks")
         + f"      - run: python scripts/run_v53.py books --sel {W}/sel --picks {W}/picks --shard {M} "
           f"--shards {SHARDS} --procs 4 --out {W}/runs/books\n" + up(f"v53-books-{M}", f"{W}/runs/books"))
choose = (setup() + down("v53-acc-*", f"{W}/runs/acc") + down("v53-books-*", f"{W}/runs/books")
          + f"      - run: python scripts/run_v53.py choose --acc {W}/runs/acc --books {W}/runs/books "
            f"--out {W}/choose\n" + up("v53-choose", f"{W}/choose"))
oos = (setup() + SEL + down("v53-choose", f"{W}/choose")
       + f"      - run: python scripts/run_v53.py oos --sel {W}/sel --choose {W}/choose --shard {M} --shards {OOS} "
         f"--procs 4 --out {W}/runs/oos\n" + up(f"v53-oos-{M}", f"{W}/runs/oos"))
final = (setup() + down("v53-sel", f"{W}/sel") + down("v53-choose", f"{W}/choose")
         + down("v53-fac-*", f"{W}/facrep", merge=False) + down("v53-oos-*", f"{W}/runs/oos")
         + "      - run: |\n"
           f"          python scripts/run_v53.py final --factory {W}/facrep --sel {W}/sel --choose {W}/choose "
           f"--oos {W}/runs/oos --out {W}/final\n"
           f"          cat {W}/final/V53_REPORT.md >> \"$GITHUB_STEP_SUMMARY\"\n"
         + up("v53-report", f"{W}/final"))

head = """name: "v53: the whole grid by walk-forward on 2016-2026, every year chosen out of sample"

# scripts/gen_v53_wf.py writes this file (V53_PREREGISTRATION.md). Trades and prices pass between jobs only in caches
# keyed by this run; artifacts hold aggregate statistics and account returns only.
# run: 1
on:
  push:
    branches: [research/stock-catalog]
    paths:
      - .github/workflows/v53.yml

permissions:
  contents: read
  actions: read

concurrency:
  group: v53
  cancel-in-progress: false

env:
  V14_UNLOCK_SEALED: yes-the-owner-asked
  OMP_NUM_THREADS: "1"
  OPENBLAS_NUM_THREADS: "1"
  MKL_NUM_THREADS: "1"

jobs:
"""


def two(name: str, needs: str, body: str) -> str:
    return (job(f"{name}_a", needs, 150, body, list(range(HALF))) + "\n"
            + job(f"{name}_b", needs, 150, body, list(range(HALF, SHARDS))))


def after(name: str, a: str, b: str, minutes: int, body: str) -> str:
    return job(name, f"{a}, {b}", minutes, body).replace(
        f"if: always() && needs.{b}.result == 'success'",
        f"if: always() && needs.{a}.result == 'success' && needs.{b}.result == 'success'")


body = (job("factory", None, 330, factory, GROUPS) + "\n" + job("select", "factory", 60, select) + "\n"
        + two("account", "select", account) + "\n" + after("pick", "account_a", "account_b", 30, pick) + "\n"
        + two("books", "pick", books) + "\n" + after("choose", "books_a", "books_b", 30, choose) + "\n"
        + job("oos", "choose", 120, oos, list(range(OOS))) + "\n" + job("final", "oos", 30, final))
Path(".github/workflows/v53.yml").write_text(head + body, encoding="utf-8", newline="\n")
print("wrote .github/workflows/v53.yml")
