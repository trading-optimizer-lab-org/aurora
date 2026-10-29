"""Context stills for the documentary sections (rendered larger, panned in the edit).

blender -b urda.blend --python stills.py -- <outdir> <still_id>
"""
import json
import os
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402

out, sid = sys.argv[sys.argv.index("--") + 1:][:2]
sc = bpy.context.scene
sc.cycles.time_limit = float(os.environ.get("URDA_TIME_LIMIT", "1500"))
sc.render.resolution_x, sc.render.resolution_y = 2560, 1440
sc.render.resolution_percentage = int(os.environ.get("URDA_PCT", "100"))
sc.render.use_motion_blur = False
dom = bpy.data.objects.get("dust_domain")
if dom:
    dom.hide_render = True

spec = plan.STILLS[sid]
cd = bpy.data.cameras.new(sid)
cd.lens = spec["lens"]
cd.sensor_width = 36
cd.clip_start = 0.5
cd.clip_end = 30000
cam = bpy.data.objects.new(sid, cd)
sc.collection.objects.link(cam)
cam.location = spec["loc"]
if spec.get("target"):
    cam.rotation_euler = (Vector(spec["target"]) - Vector(spec["loc"])).to_track_quat("-Z", "Y").to_euler()
else:
    cam.rotation_euler = (0, 0, 0)
sc.camera = cam
sc.frame_set(spec["frame"])

labels = []
for text, names in spec.get("labels", []):
    pts = [bpy.data.objects[n].matrix_world.translation for n in names if n in bpy.data.objects]
    if not pts:
        continue
    p = sum(pts, Vector()) / len(pts)
    v = world_to_camera_view(sc, cam, p)
    labels.append({"text": text, "x": v.x, "y": 1 - v.y})
os.makedirs(out, exist_ok=True)
with open(os.path.join(out, f"{sid}.json"), "w", encoding="utf-8") as fh:
    json.dump(labels, fh, ensure_ascii=False)
sc.render.filepath = os.path.join(out, f"{sid}.png")
bpy.ops.render.render(write_still=True)
print("STILL", sid, len(labels), flush=True)
