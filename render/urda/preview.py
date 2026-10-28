"""Quick review stills on a runner.

blender -b urda.blend --python preview.py -- <outdir> <pct> CAM:sceneframe ...
"""
import os
import sys

import bpy

a = sys.argv[sys.argv.index("--") + 1:]
out, pct = a[0], int(a[1])
sc = bpy.context.scene
sc.render.resolution_percentage = pct
sc.cycles.time_limit = float(os.environ.get("URDA_TIME_LIMIT", "240"))
for spec in a[2:]:
    cam, f = spec.split(":")
    sc.camera = bpy.data.objects[cam]
    sc.frame_set(int(f))
    sc.render.filepath = os.path.join(out, f"{cam}_{f}.png")
    bpy.ops.render.render(write_still=True)
    print("STILL", sc.render.filepath, flush=True)
