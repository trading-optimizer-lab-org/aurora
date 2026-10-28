"""Shared helpers for the Urda reconstruction scene (Blender 4.5, Cycles)."""
import json
import math
import os
import random

import bpy
import numpy as np
from mathutils import Vector

D = math.radians
K = 3                 # scene frames per real frame (scene runs at 90 fps, video at 30 fps)
FPS = 30
I = 330               # impact, real frame
LAST = 800
Z0 = 780.5            # local z = 0 at surrounding ground level (m a.s.l.)
FORM = 5.5            # formation level at the crash site (crest 786 m)
BALLAST = FORM + 0.55
TOP = BALLAST + 0.40  # rail top
TR, TL = -2.35, 2.35  # Iryo/AVE use the right-hand (west) track
GAP = 0.7

DATA = None
LEAF = 1.0
NEAR = None
META = None
_dem = None


def F(r):
    """Real frame -> scene frame."""
    return (r - 1) * K + 1


def load(data_dir):
    global DATA, META, _dem
    DATA = data_dir
    j = json.load(open(os.path.join(data_dir, "scene_data.json")))
    META = j["meta"]
    _dem = np.load(os.path.join(data_dir, "dem.npy"))
    return j


def to_utm(x, y):
    P0, U, V = META["P0"], META["U"], META["V"]
    return P0[0] + x * U[0] + y * V[0], P0[1] + x * U[1] + y * V[1]


def to_local(E, N):
    P0, U, V = META["P0"], META["U"], META["V"]
    dx, dy = E - P0[0], N - P0[1]
    return dx * U[0] + dy * U[1], dx * V[0] + dy * V[1]


def dem_utm(E, N):
    """Bilinear MDT05 sample (array-friendly), local height."""
    ox, oy = META["dem_origin"]
    px = META["dem_px"][0]
    c = np.clip((np.asarray(E) - ox) / px - 0.5, 0, _dem.shape[1] - 1.001)
    r = np.clip((oy - np.asarray(N)) / px - 0.5, 0, _dem.shape[0] - 1.001)
    c0, r0 = np.floor(c).astype(int), np.floor(r).astype(int)
    fc, fr = c - c0, r - r0
    a = _dem[r0, c0] * (1 - fc) + _dem[r0, c0 + 1] * fc
    b = _dem[r0 + 1, c0] * (1 - fc) + _dem[r0 + 1, c0 + 1] * fc
    return a * (1 - fr) + b * fr - Z0


def crest(x):
    """Formation level along the line: flat at the site, 0.77 % down towards Urda station."""
    x = np.asarray(x, dtype=float)
    return FORM + np.minimum(0.0, x + 200.0) * 0.0077


def ground(x, y):
    """Terrain height with the embankment rebuilt on top of the bare-earth DEM."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    E, N = to_utm(x, y)
    g = dem_utm(E, N)
    El, Nl = to_utm(x, -24.0)
    Er, Nr = to_utm(x, 24.0)
    gl, gr = dem_utm(El, Nl), dem_utm(Er, Nr)
    t = np.clip((y + 24.0) / 48.0, 0, 1)
    inner = np.abs(y) < 24.0
    g = np.where(inner, gl * (1 - t) + gr * t, g)
    zc = crest(x)
    a = np.maximum(np.abs(y) - 7.0, 0.0)
    fill = np.maximum(g, zc - a / 1.6)
    cut = np.minimum(g, zc + a / 1.6)
    h = np.where(g < zc, fill, cut)
    return np.where(np.abs(y) <= 7.0, zc, h)


def gz(x, y):
    return float(ground(x, y))


def link(ob, coll=None):
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def mesh_obj(name, verts, faces, mats, fmat=None, coll=None, smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    for m in mats:
        me.materials.append(m)
    if fmat:
        me.polygons.foreach_set("material_index", fmat)
    if smooth:
        me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    me.update()
    return link(bpy.data.objects.new(name, me), coll)


def box_data(sx, sy, sz, c=(0, 0, 0)):
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    v = [(c[0] + a * hx, c[1] + b * hy, c[2] + d * hz) for d in (-1, 1) for (a, b) in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f


def box(name, sx, sy, sz, loc, m, coll=None):
    v, f = box_data(sx, sy, sz)
    ob = mesh_obj(name, v, f, [m], coll=coll)
    ob.location = loc
    return ob


def cyl_data(r0, r1, p0, p1, n=8, cap=True):
    """Tapered cylinder between two points."""
    p0, p1 = Vector(p0), Vector(p1)
    ax = (p1 - p0).normalized()
    t = ax.orthogonal().normalized()
    b = ax.cross(t)
    v = []
    for p, r in ((p0, r0), (p1, r1)):
        for k in range(n):
            a = 2 * math.pi * k / n
            v.append(tuple(p + r * (math.cos(a) * t + math.sin(a) * b)))
    f = [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)]
    if cap:
        f.append(tuple(range(n - 1, -1, -1)))
        f.append(tuple(range(n, 2 * n)))
    return v, f


class Builder:
    """Accumulates many small parts into one mesh."""

    def __init__(self):
        self.v, self.f, self.m = [], [], []

    def add(self, verts, faces, mi=0):
        o = len(self.v)
        self.v += [tuple(p) for p in verts]
        self.f += [tuple(i + o for i in fc) for fc in faces]
        self.m += [mi] * len(faces)

    def obj(self, name, mats, coll=None, smooth=False):
        return mesh_obj(name, self.v, self.f, mats, self.m, coll, smooth)


def set_anim(ob, path, data, frames, interp="BEZIER", real=True):
    """Write a whole F-curve in one go. Frames are real frames unless real=False."""
    frames = [F(f) if real else f for f in frames]
    ob.keyframe_insert(path, frame=frames[0])
    fcs = ob.animation_data.action.fcurves
    n = len(data[0]) if hasattr(data[0], "__len__") else 1
    for idx in range(n):
        fc = fcs.find(path, index=idx)
        if fc is None:
            # nested paths on some ID types: fall back to per-key insertion
            owner, _, prop = path.rpartition(".")
            tgt = ob.path_resolve(owner) if owner else ob
            for fr, val in zip(frames, data):
                setattr(tgt, prop, val[idx] if hasattr(val, "__len__") else val)
                ob.keyframe_insert(path, frame=fr)
            continue
        fc.keyframe_points.clear()
        fc.keyframe_points.add(len(frames))
        co = []
        for fr, val in zip(frames, data):
            co += [fr, val[idx] if hasattr(val, "__len__") else val]
        fc.keyframe_points.foreach_set("co", co)
        for kp in fc.keyframe_points:
            kp.interpolation = interp
            kp.handle_left_type = "AUTO_CLAMPED"
            kp.handle_right_type = "AUTO_CLAMPED"
        fc.update()


def key_socket(sock, values, frames):
    for fr, val in zip(frames, values):
        sock.default_value = val
        sock.keyframe_insert("default_value", frame=F(fr))


def ease_out(u):
    u = min(max(u, 0.0), 1.0)
    return 1 - (1 - u) ** 2


def smooth(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


RNG = random.Random(7)
