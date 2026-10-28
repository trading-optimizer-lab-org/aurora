"""Write .github/workflows/urda-crash-render.yml from the shard plan.

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


def render_job(which, n):
    shards = ", ".join(str(i) for i in range(n))
    cache = ""
    if which == "late":
        cache = f"""      - name: Cache chunk
        id: c
        run: echo "chunk=$(( ${{{{ matrix.shard }}}} / {plan.CHUNK} ))" >> "$GITHUB_OUTPUT"
      - uses: {DL}
        with:
          name: dust-c${{{{ steps.c.outputs.chunk }}}}
          path: scene
"""
    return f"""  render-{which}:
    needs: [{'build' if which == 'early' else 'bake'}]
    runs-on: ubuntu-24.04
    timeout-minutes: 240
    strategy:
      fail-fast: false
      matrix:
        shard: [{shards}]
    steps:
{checkout}{swap}{libs}{get_blender}      - uses: {DL}
        with:
          name: urda-blend-{which}
          path: scene
{cache}      - name: Render shard
        env:
          URDA_TIME_LIMIT: "1200"
        run: |
          nproc; free -g
          "$BLENDER" -b scene/urda.blend --python render/urda/render_shard.py -- {which} ${{{{ matrix.shard }}}} out 2>&1 | grep -E "FRAME|Error|rror:|Traceback|Fra:1 .*Sample 1/" || true
          ls -R out | head -20
          test -n "$(find out -name '*.png')"
      - uses: {UP}
        with:
          name: frames-{which}-${{{{ matrix.shard }}}}
          path: out
          retention-days: 7
          compression-level: 0
"""


chunk_uploads = "".join(f"""      - uses: {UP}
        with:
          name: dust-c{c}
          path: chunks/c{c}
          retention-days: 3
          compression-level: 1
""" for c in range(plan.N_CHUNKS))

yml = f"""name: urda-crash-render

on:
  push:
    branches: [render/urda-crash]
    paths:
      - .github/workflows/urda-crash-render.yml
      - render/urda/**
  workflow_dispatch:

permissions:
  contents: read
  actions: read

concurrency:
  group: urda-crash-render
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
          curl -sSL -o bl/blender.tar.xz https://download.blender.org/release/Blender{BL[:3]}/blender-{BL}-linux-x64.tar.xz
          tar xJf bl/blender.tar.xz -C bl
      - name: Build scene
        run: bl/blender-{BL}-linux-x64/blender -b --python render/urda/build.py -- data scene/urda.blend final 2>&1 | grep -E "^\[|Error|rror:|Traceback|File " ; test -f scene/urda.blend && ls -la scene
      - uses: {UP}
        with:
          name: blender-bin
          path: bl/blender.tar.xz
          retention-days: 3
          compression-level: 0
      - uses: {UP}
        with:
          name: urda-blend-early
          path: scene/urda.blend
          retention-days: 3
          compression-level: 1

  bake:
    needs: [build]
    runs-on: ubuntu-24.04
    timeout-minutes: 300
    steps:
{checkout}{swap}{libs}{get_blender}      - uses: {DL}
        with:
          name: urda-blend-early
          path: scene
      - name: Bake Mantaflow dust
        run: |
          "$BLENDER" -b scene/urda.blend --python render/urda/bake.py -- 320 2>&1 | grep -E "BAKED|Error|rror:|Traceback" || true
          du -sh scene/dust_cache && find scene/dust_cache -type f | wc -l
          test -n "$(find scene/dust_cache -name '*.vdb')"
      - name: Split cache per shard group
        run: python3 render/urda/split_cache.py scene/dust_cache chunks && du -sh chunks/* | head -30
      - uses: {UP}
        with:
          name: urda-blend-late
          path: scene/urda.blend
          retention-days: 3
          compression-level: 1
{chunk_uploads}
{render_job("early", plan.EARLY_SHARDS)}
{render_job("late", plan.LATE_SHARDS)}
  assemble:
    needs: [render-early, render-late]
    if: ${{{{ !cancelled() }}}}
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
{checkout}      - uses: {DL}
        with:
          pattern: frames-*
          merge-multiple: true
          path: frames
      - name: Assemble video
        run: |
          which ffmpeg || (sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg)
          for j in J1 J2 J3 J4 J5; do echo "$j $(ls frames/$j | wc -l)"; done
          python3 render/urda/assemble.py frames work urda_reconstruccion_1080p.mp4
          ls -la urda_reconstruccion_1080p.mp4
      - uses: {UP}
        with:
          name: urda-video
          path: urda_reconstruccion_1080p.mp4
          retention-days: 14
          compression-level: 0
"""
open(sys.argv[1], "w", encoding="utf-8", newline="\n").write(yml)
print("written", sys.argv[1])
