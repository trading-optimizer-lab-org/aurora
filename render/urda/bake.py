"""Bake the Mantaflow dust and save the .blend next to its cache.

blender -b urda.blend --python bake.py -- [resolution]
"""
import sys
import time

import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
dom = bpy.data.objects["dust_domain"]
ds = dom.modifiers["Fluid"].domain_settings
if args:
    ds.resolution_max = int(args[0])
bpy.context.view_layer.objects.active = dom
dom.select_set(True)
bpy.context.scene.frame_set(ds.cache_frame_start)
t0 = time.time()
with bpy.context.temp_override(active_object=dom, object=dom, selected_objects=[dom]):
    bpy.ops.fluid.bake_all()
print(f"BAKED {ds.cache_frame_start}-{ds.cache_frame_end} res {ds.resolution_max} in {time.time() - t0:.0f}s", flush=True)
bpy.ops.wm.save_mainfile()
