"""Render one shard of the shot plan.

blender -b urda.blend --python render_shard.py -- <early|late> <shard> <outdir>
"""
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402

which, n, out = sys.argv[sys.argv.index("--") + 1:][:3]
sc = bpy.context.scene
sc.cycles.time_limit = float(os.environ.get("URDA_TIME_LIMIT", "1200"))
pct = int(os.environ.get("URDA_PCT", "100"))
sc.render.resolution_percentage = pct
if which == "early":
    dom = bpy.data.objects.get("dust_domain")
    if dom:
        dom.hide_render = True
for j, cam, f, idx, slow in plan.shard(which, int(n)):
    t0 = time.time()
    sc.camera = bpy.data.objects[cam]
    sc.render.motion_blur_shutter = 0.5 * plan.K / slow
    sc.frame_set(f)
    sc.render.filepath = os.path.join(out, j, f"f_{idx:04d}.png")
    bpy.ops.render.render(write_still=True)
    print(f"FRAME {j} {idx} scene {f} {time.time() - t0:.0f}s", flush=True)
