"""Write the Urda render workflow (v3: fresh dust bake, context stills, documentary edit).

python gen_workflow.py <out.yml>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402

CHECKOUT = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
PY = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
DL = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
UP = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
BL = "4.5.10"
NAME = "urda-crash-render-v3"

checkout = f"""      - uses: {CHECKOUT}
        with:
          sparse-checkout: render/urda
          persist-credentials: false
"""
swap = """      - name: Add swap
        run: |
          sudo fallocate -l 16G /mnt/urda.swap && sudo chmod 600 /mnt/urda.swap && sudo mkswap /mnt/urda.swap && sudo swapon /mnt/urda.swap || true
          free -g
"""
libs = """      - name: Blender runtime libraries
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y -qq libxi6 libxxf86vm1 libxfixes3 libxrender1 libgl1 libxkbcommon0 libsm6 libegl1 libx11-6 >/dev/null
"""
get_blender = f"""      - uses: {DL}
        with:
          name: blender-bin
          path: bl
      - name: Unpack Blender
        run: tar xJf bl/blender.tar.xz -C bl && echo "BLENDER=$PWD/bl/blender-{BL}-linux-x64/blender" >> "$GITHUB_ENV"
"""


def dl(name, path="scene"):
    return f"""      - uses: {DL}
        with:
          name: {name}
          path: {path}
"""


def dl_chunks(chunks):
    return "".join(dl(f"dust-c{c}") for c in sorted(set(chunks) - {None}))


def up(name, path, days=3, level=1):
    return f"""      - uses: {UP}
        with:
          name: {name}
          path: {path}
          retention-days: {days}
          compression-level: {level}
"""


def render_job(which, n):
    shards = ", ".join(str(i) for i in range(n))
    cache = ""
    if which == "late":
        cache = f"""      - name: Cache chunk
        id: c
        run: echo "chunk=$(( ${{{{ matrix.shard }}}} / {plan.CHUNK} ))" >> "$GITHUB_OUTPUT"
""" + dl("dust-c${{ steps.c.outputs.chunk }}")
    return f"""  render-{which}:
    needs: [{'build' if which == 'early' else 'bake, dustcheck'}]
    runs-on: ubuntu-24.04
    timeout-minutes: 240
    strategy:
      fail-fast: false
      matrix:
        shard: [{shards}]
    steps:
{checkout}{swap}{libs}{get_blender}{dl('urda-blend' if which == 'early' else 'urda-blend-late')}{cache}      - name: Render shard
        env:
          URDA_TIME_LIMIT: "1200"
        run: |
          nproc; free -g
          nice -n 10 "$BLENDER" -b scene/urda.blend --python render/urda/render_shard.py -- {which} ${{{{ matrix.shard }}}} out 2>&1 | grep -E "FRAME|Error|rror:|Traceback|Fra:1 .*Sample 1/" || true
          ls -R out | head -20
          test -n "$(find out -name '*.png')"
{up(f"frames-{which}-${{{{ matrix.shard }}}}", "out", 7, 0)}"""


chunk_uploads = "".join(up(f"dust-c{c}", f"chunks/c{c}") for c in range(plan.N_CHUNKS))
preview_specs = " ".join(f"{c}:{f}" for c, f in plan.PREVIEW)
still_ids = ", ".join(plan.STILLS)

yml = f"""name: {NAME}

on:
  push:
    branches: [render/urda-crash-v3]
    paths:
      - .github/workflows/{NAME}.yml
      - render/urda/**
  workflow_dispatch:

permissions:
  contents: read
  actions: read

concurrency:
  group: {NAME}
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-24.04
    timeout-minutes: 90
    steps:
{checkout}{swap}{libs}      - uses: {PY}
        with:
          python-version: "3.12"
      - name: Real terrain and assets (IGN PNOA + MDT05, Poly Haven CC0)
        run: |
          pip install -q numpy pillow
          python render/urda/tools/fetch_assets.py data
          python render/urda/tools/prep.py data
      - name: Download Blender {BL}
        run: |
          mkdir -p bl
          curl -sSL --retry 5 -o bl/blender.tar.xz https://download.blender.org/release/Blender{BL[:3]}/blender-{BL}-linux-x64.tar.xz
          tar xJf bl/blender.tar.xz -C bl
      - name: Build scene
        run: bl/blender-{BL}-linux-x64/blender -b --python render/urda/build.py -- data scene/urda.blend final 2>&1 | grep -E "^.....[0-9.]+s. |Error|rror:|Traceback|File " ; test -f scene/urda.blend && ls -la scene
{up("blender-bin", "bl/blender.tar.xz", 3, 0)}{up("urda-blend", "scene/urda.blend")}
  bake:
    needs: [build]
    runs-on: ubuntu-24.04
    timeout-minutes: 300
    steps:
{checkout}{swap}{libs}{get_blender}{dl("urda-blend")}      - name: Bake Mantaflow dust
        run: |
          "$BLENDER" -b scene/urda.blend --python render/urda/bake.py -- 320 2>&1 | grep -E "BAKED|Error|rror:|Traceback" || true
          du -sh scene/dust_cache && find scene/dust_cache -type f | wc -l
          test -n "$(find scene/dust_cache -name '*.vdb')"
      - name: Split cache per shard group
        run: python3 render/urda/split_cache.py scene/dust_cache chunks && du -sh chunks/* | head -30
{up("urda-blend-late", "scene/urda.blend")}{chunk_uploads}
  dustcheck:
    needs: [bake]
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
{checkout}{libs}{get_blender}{dl("urda-blend-late")}{dl_chunks([plan.chunk_of(1258)])}      - name: Dust cache is readable
        run: |
          set -o pipefail
          "$BLENDER" -b scene/urda.blend --python-exit-code 1 --python render/urda/dust_check.py -- 1258 2>&1 | grep -E "DUST|Error|rror:|Traceback|^Blender quit"

  preview:
    needs: [bake]
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
{checkout}{libs}{get_blender}{dl("urda-blend-late")}{dl_chunks([plan.chunk_of(f) for _, f in plan.PREVIEW])}      - name: Review stills
        run: |
          nice -n 10 "$BLENDER" -b scene/urda.blend --python render/urda/preview.py -- prev 50 {preview_specs} 2>&1 | grep -E "STILL|Error|rror:|Traceback" || true
          ls prev
{up("urda-preview", "prev", 7)}
  stills:
    needs: [build]
    runs-on: ubuntu-24.04
    timeout-minutes: 120
    strategy:
      fail-fast: false
      matrix:
        sid: [{still_ids}]
    steps:
{checkout}{swap}{libs}{get_blender}{dl("urda-blend")}      - name: Render context still
        env:
          URDA_TIME_LIMIT: "1500"
        run: |
          nice -n 10 "$BLENDER" -b scene/urda.blend --python render/urda/stills.py -- st ${{{{ matrix.sid }}}} 2>&1 | grep -E "STILL|Error|rror:|Traceback" || true
          ls -la st
          test -f st/${{{{ matrix.sid }}}}.png
{up("stills-${{ matrix.sid }}", "st", 7, 0)}
{render_job("early", plan.EARLY_SHARDS)}
{render_job("late", plan.LATE_SHARDS)}
  assemble:
    needs: [render-early, render-late, stills]
    if: ${{{{ !cancelled() }}}}
    runs-on: ubuntu-24.04
    timeout-minutes: 90
    steps:
{checkout}      - uses: {PY}
        with:
          python-version: "3.12"
      - uses: {DL}
        with:
          pattern: frames-*
          merge-multiple: true
          path: frames
      - uses: {DL}
        with:
          pattern: stills-*
          merge-multiple: true
          path: stills
      - name: Assemble documentary
        run: |
          which ffmpeg || (sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg)
          pip install -q pillow pyproj
          for j in J1 J2 J3 J4 J5; do echo "$j $(ls frames/$j | wc -l)"; done
          ls stills
          python render/urda/assemble.py frames stills work urda_reconstruccion_v3_1080p.mp4
          ls -la urda_reconstruccion_v3_1080p.mp4
{up("urda-video-v3", "urda_reconstruccion_v3_1080p.mp4", 14, 0)}"""
open(sys.argv[1], "w", encoding="utf-8", newline="\n").write(yml)
print("written", sys.argv[1])
