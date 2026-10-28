"""Build the Urda reconstruction scene.

blender -b --python build.py -- <data_dir> <out.blend> [final|preview]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
DATA, OUT = args[0], args[1]
QUALITY = args[2] if len(args) > 2 else "final"

bpy.ops.wm.read_factory_settings(use_empty=True)
import lib  # noqa: E402

j = lib.load(DATA)
lib.LEAF = 1.0 if QUALITY == "final" else 0.15
import env  # noqa: E402
import trains  # noqa: E402
import dust  # noqa: E402
import shots  # noqa: E402

t0 = time.time()


def step(msg):
    print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)


bpy.context.scene.render.fps = 30 * lib.K
env.materials()
step("materials")
env.terrain(QUALITY)
step(f"terrain near x {lib.NEAR}")
env.track()
env.catenary()
env.fences()
step("track, catenary, fences")
iryo_front = sum(trains.SPEC["IRYO"]["lens"]) + 7 * lib.GAP
env.signal("signal_iryo", iryo_front + 9.0, lib.TR - 3.6, red=True)
env.signal("signal_passed", -1450.0, lib.TR - 3.6, red=True)
env.sky()
env.vegetation(j["trees"], QUALITY)
step("vegetation")
cars, by = trains.build_trains()
trains.extras(by)
trains.catenary_collapse(env.falling, env.zone_wires)
step("trains")
dust.dust(cars, by, 320 if QUALITY == "final" else 64)
step("dust")
shots.cameras()
shots.render_settings(QUALITY)
shots.compositor()
bpy.context.scene.frame_set(1)
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(OUT), compress=False)
step(f"saved {OUT}")
