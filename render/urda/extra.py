"""Extra pre-impact shots for the chronological edit, cameras built at render time.

SIG  empty line, slow push towards the red entry signal (trains hidden)
ORB  slow orbit around the Iryo stopped at the signal (AVE hidden)
CAB  last seconds seen from the nose of the AVE, until just before the impact

blender -b urda.blend --python extra.py -- <shard> <n_shards> <outdir>
"""
import math
import os
import sys
import time

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402

N_SIG, N_ORB, CAB_LAST = 240, 360, 326
TR, TOP = -2.35, 6.5


def tasks():
    out = [("SIG", 1, i) for i in range(N_SIG)] + [("ORB", 1, i) for i in range(N_ORB)]
    out += [("CAB", (r - 1) * plan.K + 1, r - 1) for r in range(1, CAB_LAST + 1)]
    return out


def train_objects(prefix):
    roots = [o for o in bpy.data.objects if o.name.upper().startswith(prefix)]
    seen = set()
    while roots:
        o = roots.pop()
        if o.name not in seen:
            seen.add(o.name)
            roots.extend(o.children)
    return [bpy.data.objects[n] for n in seen]


def look(cam, loc, tgt):
    cam.location = loc
    cam.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def sig_cam(i):
    u = smooth(i / (N_SIG - 1))
    x = 60 + 105 * u
    return (x, TR + 0.4, TOP + 3.0 - 0.4 * u), (214, TR - 3.0, TOP + 4.2)


def orb_cam(i):
    u = smooth(i / (N_ORB - 1))
    ang = math.radians(-125 + 95 * u)
    r = 150 - 30 * u
    cx, cy = 110, TR
    return (cx + r * math.cos(ang), cy + r * math.sin(ang), 42 - 14 * u), (cx - 10, cy, TOP)


def ave_nose():
    xs = []
    for o in AVE:
        if o.type == "MESH":
            xs += [(o.matrix_world @ Vector(c)).x for c in o.bound_box]
    return max(xs)


shard, n_shards, out = sys.argv[sys.argv.index("--") + 1:][:3]
shard, n_shards = int(shard), int(n_shards)
sc = bpy.context.scene
sc.cycles.time_limit = float(os.environ.get("URDA_TIME_LIMIT", "1200"))
sc.render.resolution_percentage = int(os.environ.get("URDA_PCT", "100"))
sc.render.motion_blur_shutter = 0.5 * plan.K
dom = bpy.data.objects.get("dust_domain")
if dom:
    dom.hide_render = True
IRYO, AVE = train_objects("IRYO"), train_objects("AVE")
cd = bpy.data.cameras.new("XCam")
cd.sensor_width = 36
cd.clip_start = 0.3
cd.clip_end = 30000
cam = bpy.data.objects.new("XCam", cd)
sc.collection.objects.link(cam)
sc.camera = cam

t = tasks()
only = os.environ.get("URDA_ONLY")  # review frames, e.g. "SIG:120,ORB:180,CAB:250"
if only:
    want = {(s, int(k)) for s, k in (p.split(":") for p in only.split(","))}
    t = [x for x in t if (x[0], x[2]) in want]
for shot, f, i in t[shard * len(t) // n_shards:(shard + 1) * len(t) // n_shards]:
    t0 = time.time()
    for o in IRYO:
        o.hide_render = shot == "SIG"
    for o in AVE:
        o.hide_render = shot in ("SIG", "ORB")
    cam.animation_data_clear()
    if shot == "CAB":
        cd.lens = 28
        # key the camera on the neighbouring scene frames too, so the motion blur sees the speed
        for g in (f - 1, f, f + 1):
            sc.frame_set(max(1, g))
            x = ave_nose()
            look(cam, (x + 0.6, TR, TOP + 3.1), (x + 400, TR, TOP + 2.0))
            cam.keyframe_insert("location", frame=max(1, g))
            cam.keyframe_insert("rotation_euler", frame=max(1, g))
        sc.render.use_motion_blur = True
    else:
        cd.lens = 35 if shot == "ORB" else 40
        look(cam, *(sig_cam(i) if shot == "SIG" else orb_cam(i)))
        sc.render.use_motion_blur = False
    sc.frame_set(f)
    sc.render.filepath = os.path.join(out, shot, f"f_{i + 1:04d}.png")
    bpy.ops.render.render(write_still=True)
    print(f"FRAME {shot} {i + 1} scene {f} {time.time() - t0:.0f}s", flush=True)
