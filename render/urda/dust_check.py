"""Fail unless the grafted dust domain actually reads its baked cache.

blender -b urda.blend --python dust_check.py -- <sceneframe>
"""
import os
import sys

import bpy
import numpy as np

f = int(sys.argv[sys.argv.index("--") + 1])
dom = bpy.data.objects["dust_domain"]
ds = dom.modifiers["Fluid"].domain_settings
d = bpy.path.abspath(ds.cache_directory)
n = sum(len(x[2]) for x in os.walk(d)) if os.path.isdir(d) else -1
print("DUST dir", d, "files", n, "type", ds.cache_type, "range", ds.cache_frame_start, ds.cache_frame_end,
      "baked", ds.has_cache_baked_data, "hide_render", dom.hide_render, flush=True)
bpy.context.scene.frame_set(f)
ev = dom.evaluated_get(bpy.context.evaluated_depsgraph_get()).modifiers["Fluid"].domain_settings
g = np.array(ev.density_grid[:])
print("DUST frame", f, "cells", g.size, "sum", float(g.sum()), "max", float(g.max()) if g.size else 0, flush=True)
sys.exit(0 if g.size and g.sum() > 0 else 1)
