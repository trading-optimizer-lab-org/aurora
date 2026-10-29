"""Terrain from IGN MDT05 + PNOA orthophoto, track, catenary, fences, vegetation, sky."""
import math
import os
import random

import bpy
import numpy as np
from mathutils import Vector

import lib
from lib import D, TOP, BALLAST, FORM, TR, TL, Builder, box_data, cyl_data, link, mesh_obj, set_anim

X0, X1 = -1700.0, 1000.0
MATS = {}


# ---------------------------------------------------------------- materials
def img(path, cs="sRGB"):
    im = bpy.data.images.load(path, check_existing=True)
    im.colorspace_settings.name = cs
    return im


def ph(name, f):
    return os.path.join(lib.DATA, "ph", name, f)


def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree.nodes, m.node_tree.links, m.node_tree.nodes["Principled BSDF"]


def plain(name, color, rough=0.5, metal=0.0, coat=0.0, emit=None, es=0.0):
    m, N, L, b = new_mat(name)
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Coat Weight"].default_value = coat
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = es
    return m


def pbr(name, tex, scale, tint=(1, 1, 1), bump=1.0, metal=0.0, rough_mul=1.0, box=True):
    """Poly Haven PBR set with box projection in object space."""
    m, N, L, b = new_mat(name)
    tc = N.new("ShaderNodeTexCoord")
    mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / scale, 1 / scale, 1 / scale)
    L.new(tc.outputs["Object"], mp.inputs["Vector"])
    nodes = {}
    for key, cs in (("diff", "sRGB"), ("rough", "Non-Color"), ("nor", "Non-Color")):
        t = N.new("ShaderNodeTexImage")
        t.image = img(ph(tex, key + ".jpg"), cs)
        if box:
            t.projection = "BOX"
            t.projection_blend = 0.25
        L.new(mp.outputs["Vector"], t.inputs["Vector"])
        nodes[key] = t
    mix = N.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    L.new(nodes["diff"].outputs["Color"], mix.inputs["A"])
    mix.inputs["B"].default_value = (*tint, 1)
    L.new(mix.outputs["Result"], b.inputs["Base Color"])
    mr = N.new("ShaderNodeMath")
    mr.operation = "MULTIPLY"
    mr.inputs[1].default_value = rough_mul
    L.new(nodes["rough"].outputs["Color"], mr.inputs[0])
    L.new(mr.outputs[0], b.inputs["Roughness"])
    nm = N.new("ShaderNodeNormalMap")
    nm.inputs["Strength"].default_value = bump
    L.new(nodes["nor"].outputs["Color"], nm.inputs["Color"])
    L.new(nm.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Metallic"].default_value = metal
    return m


def mean_lum(path):
    im = img(path)
    n = im.size[0] * im.size[1]
    px = np.empty(n * 4, dtype=np.float32)
    im.pixels.foreach_get(px)
    px = px.reshape(-1, 4)[::97]
    return float((0.2126 * px[:, 0] + 0.7152 * px[:, 1] + 0.0722 * px[:, 2]).mean())


def terrain_mat(name, ortho, bbox, detail=True):
    """Real orthophoto colour, modulated by Poly Haven micro detail weighted per zone."""
    m, N, L, b = new_mat(name)
    tc = N.new("ShaderNodeTexCoord")
    uv = N.new("ShaderNodeUVMap")
    uv.uv_map = "ortho"
    ot = N.new("ShaderNodeTexImage")
    ot.image = img(ortho)
    ot.extension = "EXTEND"
    ot.interpolation = "Cubic"
    L.new(uv.outputs["UV"], ot.inputs["Vector"])
    # outside the photo footprint: neutral La Mancha tone
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(uv.outputs["UV"], sep.inputs["Vector"])
    inside = None
    for comp in ("X", "Y"):
        for op, v in (("GREATER_THAN", 0.0), ("LESS_THAN", 1.0)):
            c = N.new("ShaderNodeMath")
            c.operation = op
            c.inputs[1].default_value = v
            L.new(sep.outputs[comp], c.inputs[0])
            if inside is None:
                inside = c.outputs[0]
            else:
                mm = N.new("ShaderNodeMath")
                mm.operation = "MULTIPLY"
                L.new(inside, mm.inputs[0])
                L.new(c.outputs[0], mm.inputs[1])
                inside = mm.outputs[0]
    base = N.new("ShaderNodeMix")
    base.data_type = "RGBA"
    L.new(inside, base.inputs["Factor"])
    base.inputs["A"].default_value = (0.26, 0.19, 0.12, 1)
    L.new(ot.outputs["Color"], base.inputs["B"])
    # photo is display referred, bring to plausible albedo
    gain = N.new("ShaderNodeMix")
    gain.data_type = "RGBA"
    gain.blend_type = "MULTIPLY"
    gain.inputs["Factor"].default_value = 1.0
    L.new(base.outputs["Result"], gain.inputs["A"])
    gain.inputs["B"].default_value = (0.92, 0.92, 0.92, 1)
    col = gain.outputs["Result"]
    # rebuilt embankment slopes: the photo there is pale gravel smeared over a taller face; use the
    # brown earth seen in the Guardia Civil aerials
    geo = N.new("ShaderNodeNewGeometry")
    nz = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Normal"], nz.inputs["Vector"])
    st = N.new("ShaderNodeMapRange")
    st.inputs["From Min"].default_value = 0.97
    st.inputs["From Max"].default_value = 0.80
    st.inputs["To Min"].default_value = 0.0
    st.inputs["To Max"].default_value = 0.75
    L.new(nz.outputs["Z"], st.inputs["Value"])
    earth = N.new("ShaderNodeMix")
    earth.data_type = "RGBA"
    L.new(st.outputs["Result"], earth.inputs["Factor"])
    L.new(col, earth.inputs["A"])
    earth.inputs["B"].default_value = (0.30, 0.22, 0.14, 1)
    col = earth.outputs["Result"]
    if detail:
        attr = N.new("ShaderNodeAttribute")
        attr.attribute_name = "zone"
        sz = N.new("ShaderNodeSeparateColor")
        L.new(attr.outputs["Color"], sz.inputs["Color"])
        mp = N.new("ShaderNodeMapping")
        L.new(tc.outputs["Object"], mp.inputs["Vector"])
        acc_c = acc_n = acc_r = None
        for ch, tex, scale in (("Red", "withered_grass", 2.2), ("Green", "red_laterite_soil_stones", 2.6),
                               ("Blue", "dry_ground_rocks", 2.4)):
            sc = N.new("ShaderNodeMapping")
            sc.inputs["Scale"].default_value = (1 / scale, 1 / scale, 1 / scale)
            L.new(tc.outputs["Object"], sc.inputs["Vector"])
            outs = {}
            for key, cs in (("diff", "sRGB"), ("rough", "Non-Color"), ("nor", "Non-Color")):
                t = N.new("ShaderNodeTexImage")
                t.image = img(ph(tex, key + ".jpg"), cs)
                t.projection = "BOX"
                t.projection_blend = 0.3
                L.new(sc.outputs["Vector"], t.inputs["Vector"])
                outs[key] = t.outputs["Color"]
            # luminance ratio = detail without changing the real colour
            bw = N.new("ShaderNodeRGBToBW")
            L.new(outs["diff"], bw.inputs["Color"])
            ratio = N.new("ShaderNodeMath")
            ratio.operation = "DIVIDE"
            L.new(bw.outputs["Val"], ratio.inputs[0])
            ratio.inputs[1].default_value = max(0.02, mean_lum(ph(tex, "diff.jpg")))
            w = sz.outputs[ch]
            for kind, src in (("c", ratio.outputs[0]), ("r", outs["rough"]), ("n", outs["nor"])):
                mw = N.new("ShaderNodeVectorMath")
                mw.operation = "SCALE"
                L.new(src, mw.inputs[0])
                L.new(w, mw.inputs["Scale"])
                cur = {"c": acc_c, "r": acc_r, "n": acc_n}[kind]
                if cur is None:
                    out = mw.outputs[0]
                else:
                    ad = N.new("ShaderNodeVectorMath")
                    L.new(cur, ad.inputs[0])
                    L.new(mw.outputs[0], ad.inputs[1])
                    out = ad.outputs[0]
                if kind == "c":
                    acc_c = out
                elif kind == "r":
                    acc_r = out
                else:
                    acc_n = out
        # weights sum to 1 where detail applies; ratio 1 elsewhere
        wsum = N.new("ShaderNodeMath")
        wsum.operation = "ADD"
        L.new(sz.outputs["Red"], wsum.inputs[0])
        ws2 = N.new("ShaderNodeMath")
        ws2.operation = "ADD"
        L.new(wsum.outputs[0], ws2.inputs[0])
        L.new(sz.outputs["Green"], ws2.inputs[1])
        L.new(sz.outputs["Blue"], wsum.inputs[1])
        inv = N.new("ShaderNodeMath")
        inv.operation = "SUBTRACT"
        inv.inputs[0].default_value = 1.0
        L.new(ws2.outputs[0], inv.inputs[1])
        rat = N.new("ShaderNodeVectorMath")
        L.new(acc_c, rat.inputs[0])
        cmb = N.new("ShaderNodeCombineXYZ")
        for k in ("X", "Y", "Z"):
            L.new(inv.outputs[0], cmb.inputs[k])
        L.new(cmb.outputs[0], rat.inputs[1])
        md = N.new("ShaderNodeMix")
        md.data_type = "RGBA"
        md.blend_type = "MULTIPLY"
        md.inputs["Factor"].default_value = 0.85
        L.new(col, md.inputs["A"])
        L.new(rat.outputs[0], md.inputs["B"])
        col = md.outputs["Result"]
        rr = N.new("ShaderNodeSeparateXYZ")
        L.new(acc_r, rr.inputs[0])
        rmix = N.new("ShaderNodeMapRange")
        rmix.inputs["From Min"].default_value = 0.0
        rmix.inputs["From Max"].default_value = 1.0
        rmix.inputs["To Min"].default_value = 0.88
        rmix.inputs["To Max"].default_value = 1.0
        L.new(rr.outputs["X"], rmix.inputs["Value"])
        L.new(rmix.outputs["Result"], b.inputs["Roughness"])
        nmix = N.new("ShaderNodeMix")
        nmix.data_type = "RGBA"
        L.new(ws2.outputs[0], nmix.inputs["Factor"])
        nmix.inputs["A"].default_value = (0.5, 0.5, 1.0, 1)
        L.new(acc_n, nmix.inputs["B"])
        nm = N.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = 1.2
        L.new(nmix.outputs["Result"], nm.inputs["Color"])
        L.new(nm.outputs["Normal"], b.inputs["Normal"])
    else:
        b.inputs["Roughness"].default_value = 0.95
    L.new(col, b.inputs["Base Color"])
    return m


def materials():
    MATS["ballast"] = pbr("ballast", "gravel_floor", 1.1, tint=(0.80, 0.85, 0.95), bump=2.5)
    MATS["concrete"] = pbr("sleeper", "brushed_concrete", 1.2, tint=(0.82, 0.8, 0.77), bump=0.6)
    MATS["rail_side"] = pbr("rail_side", "rusty_metal_02", 0.8, tint=(0.75, 0.6, 0.5), bump=0.4, metal=0.6)
    MATS["rail_head"] = plain("rail_head", (0.62, 0.62, 0.62), 0.22, 1.0)
    MATS["galv"] = plain("galvanised", (0.56, 0.57, 0.58), 0.38, 1.0)
    MATS["steel_dark"] = plain("steel_dark", (0.08, 0.08, 0.085), 0.55, 0.6)
    MATS["copper"] = plain("contact_wire", (0.42, 0.24, 0.15), 0.35, 1.0)
    MATS["insulator"] = plain("insulator", (0.36, 0.2, 0.12), 0.25, 0.0, coat=0.8)
    MATS["foundation"] = pbr("foundation", "brushed_concrete", 1.0, tint=(0.7, 0.68, 0.64))
    MATS["signal_black"] = plain("signal_black", (0.012, 0.012, 0.012), 0.5)
    MATS["signal_white"] = plain("signal_white", (0.75, 0.75, 0.72), 0.5)
    MATS["red_lamp"] = plain("red_lamp", (0.4, 0.0, 0.0), 0.2, emit=(1.0, 0.02, 0.01), es=60)
    MATS["off_lamp"] = plain("off_lamp", (0.02, 0.02, 0.02), 0.1)
    m, N, L, b = new_mat("bark")
    m2 = pbr("bark_tex", "bark_brown_02", 0.6, tint=(0.62, 0.6, 0.55), bump=1.5)
    MATS["bark"] = m2
    # olive leaf: dark grey-green on top, silver underneath, slightly translucent
    m, N, L, b = new_mat("olive_leaf")
    geo = N.new("ShaderNodeNewGeometry")
    rnd = N.new("ShaderNodeObjectInfo")
    mixc = N.new("ShaderNodeMix")
    mixc.data_type = "RGBA"
    L.new(geo.outputs["Backfacing"], mixc.inputs["Factor"])
    mixc.inputs["A"].default_value = (0.055, 0.075, 0.035, 1)
    mixc.inputs["B"].default_value = (0.21, 0.23, 0.17, 1)
    hv = N.new("ShaderNodeHueSaturation")
    L.new(mixc.outputs["Result"], hv.inputs["Color"])
    mr = N.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = 0.8
    mr.inputs["To Max"].default_value = 1.2
    L.new(rnd.outputs["Random"], mr.inputs["Value"])
    L.new(mr.outputs["Result"], hv.inputs["Value"])
    L.new(hv.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.5
    b.inputs["Subsurface Weight"].default_value = 0.0
    tr = N.new("ShaderNodeBsdfTranslucent")
    tr.inputs["Color"].default_value = (0.09, 0.12, 0.04, 1)
    ms = N.new("ShaderNodeMixShader")
    ms.inputs[0].default_value = 0.18
    out = N["Material Output"]
    L.new(b.outputs[0], ms.inputs[1])
    L.new(tr.outputs[0], ms.inputs[2])
    L.new(ms.outputs[0], out.inputs["Surface"])
    MATS["leaf"] = m


# ---------------------------------------------------------------- terrain
def grid_mesh(name, X, Y, Z, uv, zone=None, keep=None, mats=()):
    ny, nx = X.shape
    verts = np.stack([X, Y, Z], -1).reshape(-1, 3).astype(np.float32)
    idx = np.arange(nx * ny).reshape(ny, nx)
    quads = np.stack([idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]], -1).reshape(-1, 4)
    if keep is not None:
        quads = quads[keep.reshape(-1)]
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.ravel())
    nl = quads.size
    me.loops.add(nl)
    me.loops.foreach_set("vertex_index", quads.ravel().astype(np.int32))
    me.polygons.add(len(quads))
    me.polygons.foreach_set("loop_start", np.arange(0, nl, 4, dtype=np.int32))
    me.update(calc_edges=True)
    me.polygons.foreach_set("use_smooth", np.ones(len(quads), dtype=bool))
    lay = me.uv_layers.new(name="ortho")
    uvv = uv.reshape(-1, 2)[quads.ravel()]
    lay.data.foreach_set("uv", uvv.astype(np.float32).ravel())
    if zone is not None:
        ca = me.color_attributes.new("zone", "FLOAT_COLOR", "POINT")
        ca.data.foreach_set("color", zone.reshape(-1, 4).astype(np.float32).ravel())
    for m in mats:
        me.materials.append(m)
    me.validate()
    return link(bpy.data.objects.new(name, me))


def near_rect():
    nb = lib.META["near_bbox"]
    best = None
    for x0 in range(-1500, 0, 10):
        for x1 in range(200, 700, 10):
            ok = True
            for x in (x0, x1):
                for y in (-170, 170):
                    E, N = lib.to_utm(x, y)
                    if not (nb[0] + 4 < E < nb[2] - 4 and nb[1] + 4 < N < nb[3] - 4):
                        ok = False
            if ok and (best is None or x1 - x0 > best[1] - best[0]):
                best = (x0, x1)
    return best


def zones(X, Y, Z):
    """R: dry grass field, G: tilled grove soil, B: rocky embankment slope."""
    a = np.abs(Y)
    slope = (a < 17.0).astype(np.float32)
    road = ((Y > 21) & (Y < 31)).astype(np.float32)
    east = (Y > 0) & (slope == 0)
    R = np.where((~east) & (slope == 0), 1.0, 0.0) + road * 0.0
    G = np.where(east & (road == 0), 1.0, 0.0)
    B = slope + road
    A = np.ones_like(X)
    return np.stack([R, G, B, A], -1).astype(np.float32)


def terrain(quality):
    x0, x1 = near_rect()
    lib.NEAR = (x0, x1, -170.0, 170.0)
    step = 1.0 if quality == "final" else 2.0
    xs = np.arange(x0, x1 + 0.01, step)
    yw = np.concatenate([np.arange(-170, -60, step), np.arange(-60, -26, 0.5), np.arange(-26, 26, 0.25),
                         np.arange(26, 60, 0.5), np.arange(60, 170.01, step)])
    X, Y = np.meshgrid(xs, yw)
    Z = lib.ground(X, Y)
    E, N = lib.to_utm(X, Y)
    nb = lib.META["near_bbox"]
    uv = np.stack([(E - nb[0]) / (nb[2] - nb[0]), (N - nb[1]) / (nb[3] - nb[1])], -1)
    near = grid_mesh("terrain_near", X, Y, Z, uv, zones(X, Y, Z),
                     mats=[terrain_mat("terrain_near", os.path.join(lib.DATA, "near.jpg"), nb)])
    # far: UTM-aligned grid, MDT05 resolution inside the DEM, coarse ring out to 12 km
    fb = lib.META["far_bbox"]
    cx, cy = (fb[0] + fb[2]) / 2, (fb[1] + fb[3]) / 2
    fs = 5.0 if quality == "final" else 10.0
    es = np.concatenate([np.linspace(cx - 12000, fb[0], 30)[:-1], np.arange(fb[0], fb[2] + 0.1, fs),
                         np.linspace(fb[2], cx + 12000, 30)[1:]])
    ns = np.concatenate([np.linspace(cy - 12000, fb[1], 30)[:-1], np.arange(fb[1], fb[3] + 0.1, fs),
                         np.linspace(fb[3], cy + 12000, 30)[1:]])
    EE, NN = np.meshgrid(es, ns)
    LX, LY = lib.to_local(EE, NN)
    ZZ = lib.dem_utm(EE, NN)
    rebuild = (LX > X0) & (LX < X1) & (np.abs(LY) < 60)
    ZZ = np.where(rebuild, lib.ground(LX, LY), ZZ)
    out = np.maximum(np.maximum(fb[0] - EE, EE - fb[2]), np.maximum(fb[1] - NN, NN - fb[3]))
    wout = np.clip(out / 4000.0, 0, 1)
    ZZ = ZZ * (1 - wout) + float(np.median(lib._dem)) - lib.Z0 - 4 * wout
    inside = (LX > x0 + 3) & (LX < x1 - 3) & (np.abs(LY) < 167)
    ZZ = np.where(inside, ZZ - 0.4, ZZ)
    keep = ~(inside[:-1, :-1] & inside[1:, 1:] & inside[:-1, 1:] & inside[1:, :-1])
    uvf = np.stack([(EE - fb[0]) / (fb[2] - fb[0]), (NN - fb[1]) / (fb[3] - fb[1])], -1)
    far = grid_mesh("terrain_far", LX, LY, ZZ, uvf, keep=keep,
                    mats=[terrain_mat("terrain_far", os.path.join(lib.DATA, "far.jpg"), fb, detail=False)])
    return near, far


# ---------------------------------------------------------------- track
UIC60 = [(0.075, 0.0), (0.075, 0.0115), (0.03, 0.025), (0.011, 0.033), (0.0083, 0.04), (0.0083, 0.118),
         (0.012, 0.128), (0.034, 0.135), (0.036, 0.148), (0.0345, 0.162), (0.028, 0.170), (0.0, 0.172)]
RAIL_RING = [(y, z) for y, z in UIC60] + [(-y, z) for y, z in reversed(UIC60[:-1])]


def rail_mesh(b, yc, x0, x1):
    n = len(RAIL_RING)
    base = len(b.v)
    for x in (x0, x1):
        b.v += [(x, yc + y, BALLAST + 0.225 + z) for y, z in RAIL_RING]
    for k in range(n - 1):
        z = (RAIL_RING[k][1] + RAIL_RING[k + 1][1]) / 2
        b.f.append((base + k, base + k + 1, base + n + k + 1, base + n + k))
        b.m.append(1 if z > 0.16 else 0)


def sleeper_unit():
    b = Builder()
    # AI-04 monoblock: 2.6 m, trapezoidal section, rail seats slightly raised
    v = []
    for y in (-1.3, -0.55, 0.55, 1.3):
        hz = 0.22 if abs(y) > 0.6 else 0.18
        v.append([(-0.15, y, 0), (0.15, y, 0), (0.11, y, hz), (-0.11, y, hz)])
    verts = [p for ring in v for p in ring]
    faces = []
    for j in range(3):
        for k in range(4):
            faces.append((j * 4 + k, j * 4 + (k + 1) % 4, (j + 1) * 4 + (k + 1) % 4, (j + 1) * 4 + k))
    faces.append((3, 2, 1, 0))
    faces.append((12, 13, 14, 15))
    b.add([(x, y, z + BALLAST - 0.035) for x, y, z in verts], faces, 0)
    for yc in (-0.7175, 0.7175):
        for s in (-1, 1):
            pv, pf = box_data(0.18, 0.05, 0.03, (0, yc + s * 0.11, BALLAST + 0.2))
            b.add(pv, pf, 1)
            cv, cf = box_data(0.03, 0.09, 0.035, (s * 0.04, yc + s * 0.075, BALLAST + 0.225))
            b.add(cv, cf, 1)
    return b


def track():
    xs = np.arange(X0, X1 + 0.1, 10.0)
    dz = lib.crest(xs) - FORM
    prof = [(-6.95, FORM), (-4.7, BALLAST + 0.17), (4.7, BALLAST + 0.17), (6.95, FORM)]
    bl = Builder()
    for x, z in zip(xs, dz):
        bl.v += [(x, y, h + z) for y, h in prof]
    for i in range(len(xs) - 1):
        for j in range(3):
            a = i * 4 + j
            bl.f.append((a, a + 4, a + 5, a + 1))
            bl.m.append(0)
    bl.obj("ballast", [MATS["ballast"]], smooth=True)
    rb = Builder()
    n = len(RAIL_RING)
    for yc in (TR, TL):
        for s in (-0.7175, 0.7175):
            base = len(rb.v)
            for x, z in zip(xs, dz):
                rb.v += [(x, yc + s + y, BALLAST + 0.225 + h + z) for y, h in RAIL_RING]
            for i in range(len(xs) - 1):
                for k in range(n - 1):
                    o = base + i * n
                    rb.f.append((o + k, o + k + 1, o + n + k + 1, o + n + k))
                    rb.m.append(1 if (RAIL_RING[k][1] + RAIL_RING[k + 1][1]) / 2 > 0.16 else 0)
    rb.obj("rails", [MATS["rail_side"], MATS["rail_head"]], smooth=True)
    su = sleeper_unit()
    sl = mesh_obj("sleeper", su.v, su.f, [MATS["concrete"], MATS["steel_dark"]], su.m)
    sx = np.arange(X0 + 0.3, X1, 0.6)
    sz = lib.crest(sx) - FORM
    items = [(float(x), yc, float(z), 1.0, 0.0) for yc in (TR, TL) for x, z in zip(sx, sz)]
    instancer("sleepers", items, sl)


# ---------------------------------------------------------------- catenary
POLE_X = [-1695 + 60 * k for k in range(45)]
falling = []
zone_wires = []


def zt(x):
    return float(lib.crest(x))


def catenary():
    g = Builder()
    fnd = Builder()
    ins = Builder()
    zone = Builder()
    for side, yc in ((-1, TR), (1, TL)):
        yp = side * 6.3
        for x in POLE_X:
            if x > X1 - 5:
                continue
            z0 = zt(x)
            rt = z0 + (TOP - FORM)
            tgt = zone if (side < 0 and -40 <= x <= 110) else g
            parts = Builder()
            # HEB 260 pole, flanges along the track
            for dy in (-0.12, 0.12):
                v, f = box_data(0.26, 0.018, 8.6, (0, dy, 4.3))
                parts.add(v, f, 0)
            v, f = box_data(0.012, 0.24, 8.6, (0, 0, 4.3))
            parts.add(v, f, 0)
            # cantilever: top tube, diagonal tube, registration arm
            ztop, zbot = (TOP - FORM) + 6.75, (TOP - FORM) + 5.35
            reach = -side * (6.3 - abs(yc) + 0.5)
            v, f = cyl_data(0.03, 0.03, (0, 0, ztop), (0, reach, ztop - 0.15), 8)
            parts.add(v, f, 0)
            v, f = cyl_data(0.028, 0.028, (0, 0, zbot), (0, reach, ztop - 0.35), 8)
            parts.add(v, f, 0)
            stag = 0.2 if (x // 60) % 2 else -0.2
            v, f = cyl_data(0.015, 0.015, (0, reach * 0.8, ztop - 0.6), (0, reach + side * stag - side * 0.6, (TOP - FORM) + 5.32), 6)
            parts.add(v, f, 0)
            for zz in (ztop, zbot):
                for k in range(5):
                    v, f = cyl_data(0.09, 0.09, (0, -side * (0.35 + k * 0.06), zz), (0, -side * (0.38 + k * 0.06), zz), 10)
                    ins.add([(p[0] + x, p[1] + yp, p[2] + z0) for p in v], f, 0)
            v, f = box_data(0.9, 0.9, 1.0, (0, 0, -0.45))
            fnd.add([(p[0] + x, p[1] + yp, p[2] + z0) for p in v], f, 0)
            if tgt is zone:
                piv = link(bpy.data.objects.new("pole_pivot", None))
                piv.location = (x, yp, z0)
                ob = parts.obj("pole_fall", [MATS["galv"]])
                ob.parent = piv
                falling.append((piv, side, x))
            else:
                g.add([(p[0] + x, p[1] + yp, p[2] + z0) for p in parts.v], parts.f, 0)
    g.obj("catenary_poles", [MATS["galv"]])
    fnd.obj("catenary_foundations", [MATS["foundation"]])
    ins.obj("insulators", [MATS["insulator"]])
    # wires: messenger with sag + droppers, straight contact wire with stagger
    for yc in (TR, TL):
        for (xa, xb, broken) in ((X0 + 5, -45, False), (-45, 165, True), (165, X1 - 5, False)):
            w = Builder()
            xs = [x for x in POLE_X if xa <= x <= xb]
            pts = [xa] + xs + [xb]
            for p0, p1 in zip(pts[:-1], pts[1:]):
                n = max(2, int((p1 - p0) / 6))
                prev_m = prev_c = None
                for k in range(n + 1):
                    x = p0 + (p1 - p0) * k / n
                    u = (x - p0) / max(1e-6, p1 - p0)
                    rt = zt(x) + (TOP - FORM)
                    sag = 4 * u * (1 - u) * 0.3
                    pm = (x, yc, rt + 6.6 - sag)
                    stag = 0.2 * math.cos(math.pi * ((x + 1695) / 60.0))
                    pc = (x, yc + stag, rt + 5.3)
                    if prev_m:
                        v, f = cyl_data(0.0065, 0.0065, prev_m, pm, 6, cap=False)
                        w.add(v, f, 0)
                        v, f = cyl_data(0.0062, 0.0062, prev_c, pc, 6, cap=False)
                        w.add(v, f, 1)
                    if 0 < k < n:
                        v, f = cyl_data(0.0025, 0.0025, (x, yc + stag * 0.5, pc[2]), (x, yc, pm[2]), 4, cap=False)
                        w.add(v, f, 0)
                    prev_m, prev_c = pm, pc
            ob = w.obj("wires", [MATS["galv"], MATS["copper"]])
            if broken:
                zone_wires.append(ob)


def fences():
    panel, post = sorted(import_parts("modular_chainlink_fence", {"modular_chainlink_fence_double",
                                                                "modular_chainlink_fence_post"}, recenter=False),
                         key=lambda o: o.name)
    for v in panel.data.vertices:
        v.co.x += 1.95
    for v in post.data.vertices:
        v.co.x += 1.0
        v.co.y -= 1.0
    bpy.ops.object.select_all(action="DESELECT")
    panel.select_set(True)
    post.select_set(True)
    bpy.context.view_layer.objects.active = panel
    bpy.ops.object.join()
    unit = panel.data
    chunk = 10
    clen = 1.95 * chunk
    for side in (-1, 1):
        y = side * 18.6
        x = X0 + 20
        while x < X1 - 20:
            z0 = lib.gz(x, y)
            z1 = lib.gz(x + clen, y)
            ob = link(bpy.data.objects.new("fence", unit))
            ob.location = (x, y, min(z0, z1) - 0.05)
            ob.rotation_euler = (0, -math.atan2(z1 - z0, clen), 0)
            am = ob.modifiers.new("arr", "ARRAY")
            am.count = chunk
            am.use_relative_offset = False
            am.use_constant_offset = True
            am.constant_offset_displace = (1.95, 0, 0)
            x += clen
    bpy.data.objects.remove(panel)


def signal(name, x, y, red=True, facing=1):
    b = Builder()
    z0 = lib.gz(x, y) if abs(y) > 7 else zt(x)
    v, f = cyl_data(0.07, 0.06, (0, 0, -0.6), (0, 0, 4.3), 12)
    b.add(v, f, 0)
    v, f = box_data(0.36, 0.42, 1.25, (facing * -0.05, 0, 4.5))
    b.add(v, f, 1)
    v, f = box_data(0.02, 0.6, 1.45, (facing * -0.24, 0, 4.5))
    b.add(v, f, 2)
    for k, zz in enumerate((4.88, 4.5, 4.12)):
        v, f = cyl_data(0.075, 0.075, (facing * -0.23, 0, zz), (facing * -0.27, 0, zz), 16)
        b.add(v, f, 3 if (red and k == 2) else 4)
        v, f = box_data(0.18, 0.2, 0.02, (facing * -0.32, 0, zz + 0.12))
        b.add(v, f, 1)
    ob = b.obj(name, [MATS["galv"], MATS["signal_black"], MATS["signal_white"], MATS["red_lamp"], MATS["off_lamp"]])
    ob.location = (x, y, z0)
    return ob


# ---------------------------------------------------------------- vegetation
def olive_variant(k, crown):
    """Procedural olive tree at real size: gnarled trunk, scaffold limbs, ~35-60 k leaves."""
    rng = random.Random(1000 + k)
    h = crown * 1.75
    wood = Builder()
    trunk_h = h * 0.32
    lean = Vector((rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), 1)).normalized()
    p = Vector((0, 0, -0.2))
    r = 0.11 + 0.07 * crown
    for s in range(4):
        q = p + lean * (trunk_h / 3) + Vector((rng.uniform(-0.06, 0.06), rng.uniform(-0.06, 0.06), 0))
        v, f = cyl_data(r, r * 0.92, p, q, 10, cap=False)
        wood.add(v, f, 0)
        p, r = q, r * 0.92
    fork = p
    tips = []
    nlimb = rng.randint(3, 5)
    for i in range(nlimb):
        a = 2 * math.pi * i / nlimb + rng.uniform(-0.4, 0.4)
        d = Vector((math.cos(a) * 0.65, math.sin(a) * 0.65, 1.0)).normalized()
        q0, rr = fork, r * 0.7
        for s in range(3):
            q1 = q0 + d * (crown * 0.42) + Vector((rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 0.1), 0))
            v, f = cyl_data(rr, rr * 0.7, q0, q1, 7, cap=False)
            wood.add(v, f, 0)
            tips.append(q1.copy())
            q0, rr = q1, rr * 0.7
            d = (d + Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), rng.uniform(-0.1, 0.25)))).normalized()
    leaves = Builder()
    cz = trunk_h + crown * 0.95
    nclu = int(40 * crown * crown) + 30
    for c in range(nclu):
        while True:
            u = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
            if 0.35 < u.length <= 1:
                break
        u.z *= 0.72
        cc = Vector((0, 0, cz)) + u * crown
        t = min(tips, key=lambda q: (q - cc).length)
        v, f = cyl_data(0.012, 0.006, t, cc, 4, cap=False)
        wood.add(v, f, 0)
        for _ in range(int(lib.LEAF * 900 / max(1.0, crown ** 0.2))):
            o = Vector((rng.gauss(0, 0.16), rng.gauss(0, 0.16), rng.gauss(0, 0.12)))
            base = cc + o
            dirv = (o + Vector((0, 0, 0.15))).normalized()
            side = dirv.orthogonal().normalized()
            rot = rng.uniform(0, math.pi)
            side = side * math.cos(rot) + dirv.cross(side) * math.sin(rot)
            ln, wd = rng.uniform(0.045, 0.075), rng.uniform(0.009, 0.013)
            a0 = base
            a1 = base + dirv * ln
            leaves.v += [tuple(a0 - side * wd * 0.2), tuple(a0 + side * wd * 0.2),
                         tuple(a0 + dirv * ln * 0.5 + side * wd), tuple(a1),
                         tuple(a0 + dirv * ln * 0.5 - side * wd)]
            o5 = len(leaves.v) - 5
            leaves.f += [(o5, o5 + 1, o5 + 2, o5 + 3), (o5, o5 + 3, o5 + 4)]
            leaves.m += [1, 1]
    wood.v += leaves.v
    off = len(wood.v) - len(leaves.v)
    wood.f += [tuple(i + off for i in fc) for fc in leaves.f]
    wood.m += leaves.m
    ob = wood.obj(f"olive_{k}", [MATS["bark"], MATS["leaf"]], smooth=True)
    return ob


def import_parts(model, names=None, recenter=True):
    path = os.path.join(lib.DATA, "ph", model, model + ".gltf")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    out = []
    for o in new:
        if o.type != "MESH" or (names and o.name not in names):
            continue
        o.parent = None
        mw = o.matrix_world.copy()
        o.data.transform(mw)
        o.matrix_world.identity()
        if not recenter:
            out.append(o)
            continue
        xs = [v.co for v in o.data.vertices]
        cx = sum(v.x for v in xs) / len(xs)
        cy = sum(v.y for v in xs) / len(xs)
        mz = min(v.z for v in xs)
        for v in o.data.vertices:
            v.co.x -= cx
            v.co.y -= cy
            v.co.z -= mz
        out.append(o)
    for o in new:
        if o not in out:
            bpy.data.objects.remove(o)
    return out


def instancer(name, items, child):
    """Face instancing: one quad per item (x, y, z, scale, angle)."""
    v, f = [], []
    for x, y, z, s, a in items:
        k = len(v)
        h = s / 2
        ca, sa = math.cos(a), math.sin(a)
        for cx, cy in ((-h, -h), (h, -h), (h, h), (-h, h)):
            v.append((x + cx * ca - cy * sa, y + cx * sa + cy * ca, z))
        f.append((k, k + 1, k + 2, k + 3))
    me = bpy.data.meshes.new(name)
    me.from_pydata(v, [], f)
    ob = link(bpy.data.objects.new(name, me))
    ob.instance_type = "FACES"
    ob.show_instancer_for_render = False
    ob.show_instancer_for_viewport = False
    ob.use_instance_faces_scale = True
    ob.instance_faces_scale = 1.0
    child.parent = ob
    child.location = (0, 0, 0)
    return ob


def vegetation(trees, quality):
    rng = random.Random(3)
    # olive trees at their real orthophoto positions
    classes = [1.0, 1.7, 2.5]
    variants = {}
    for c, cr in enumerate(classes):
        for j in range(2 if quality == "final" else 1):
            variants[(c, j)] = olive_variant(c * 2 + j, cr)
    buckets = {k: [] for k in variants}
    shrubs = []
    for x, y, rad, kind, s in trees:
        if kind == "shrub":
            if y > 0 or s > 34:
                shrubs.append((x, y, rad))
            continue
        cr = min(2.9, max(0.8, rad * 0.95))
        c = min(range(3), key=lambda i: abs(classes[i] - cr))
        j = rng.randrange(2) if quality == "final" else 0
        buckets[(c, j)].append((x, y, cr / classes[c]))
    for key, lst in buckets.items():
        if not lst:
            continue
        xs = np.array([p[0] for p in lst])
        ys = np.array([p[1] for p in lst])
        zs = lib.ground(xs, ys)
        items = [(x, y, float(z) - 0.05, s, rng.uniform(0, 6.283)) for (x, y, s), z in zip(lst, zs)]
        instancer(f"olives_{key[0]}_{key[1]}", items, variants[key])
    # embankment scrub
    parts = import_parts("shrub_02")
    sb = {i: [] for i in range(len(parts))}
    for x, y, rad in shrubs:
        for _ in range(2):
            px, py = x + rng.uniform(-1.2, 1.2), y + rng.uniform(-1.2, 1.2)
            sb[rng.randrange(len(parts))].append((px, py, float(lib.gz(px, py)) - 0.1, rng.uniform(0.6, 1.15), rng.uniform(0, 6.283)))
    # low scrub scattered over both embankment slopes, as seen in the Guardia Civil aerials
    for side in (-1, 1):
        n = int(1300 * 15 * 0.04 * (1.0 if quality == "final" else 0.15))
        for _ in range(n):
            px, py = rng.uniform(-600, 700), side * rng.uniform(7.6, 22.0)
            sb[rng.randrange(len(parts))].append((px, py, float(lib.gz(px, py)) - 0.1, rng.uniform(0.45, 1.0), rng.uniform(0, 6.283)))
    for i, lst in sb.items():
        if lst:
            instancer(f"scrub_{i}", lst, parts[i])
    # dry grass tufts: crash site field and the embankment slopes along the approach
    grass = [grass_tuft(k) for k in range(6)]
    gb = {i: [] for i in range(len(grass))}
    q = 1.0 if quality == "final" else 0.15
    area = [(-160, 320, -95, -16.5, 2.6), (-160, 320, -16.5, -7.2, 2.6), (-160, 320, 7.2, 20.5, 2.6),
            (-950, -160, -24, -7.2, 0.6), (-950, -160, 7.2, 24, 0.6), (320, 900, -24, -7.2, 0.5), (320, 900, 7.2, 24, 0.5)]
    for xa, xb, ya, yb, dens in area:
        n = int((xb - xa) * (yb - ya) * dens * q)
        xs = np.random.default_rng(len(gb[0]) + n).uniform(xa, xb, n)
        ys = np.random.default_rng(n + 7).uniform(ya, yb, n)
        zs = lib.ground(xs, ys)
        for x, y, z in zip(xs, ys, zs):
            gb[rng.randrange(len(grass))].append((float(x), float(y), float(z) - 0.02, rng.uniform(0.7, 1.5),
                                                  rng.uniform(0, 6.283)))
    for i, lst in gb.items():
        if lst:
            instancer(f"grass_{i}", lst, grass[i])


def grass_tuft(k):
    rng = random.Random(500 + k)
    b = Builder()
    for _ in range(rng.randint(22, 40)):
        h = rng.uniform(0.12, 0.5)
        a = rng.uniform(0, 2 * math.pi)
        r0 = rng.uniform(0, 0.07)
        lean = rng.uniform(0.15, 0.7)
        w = rng.uniform(0.003, 0.0065)
        bx, by = r0 * math.cos(a), r0 * math.sin(a)
        dx, dy = math.cos(a) * lean * h, math.sin(a) * lean * h
        px, py = -math.sin(a) * w, math.cos(a) * w
        v = [(bx - px, by - py, 0), (bx + px, by + py, 0),
             (bx + dx * 0.4 + px * 0.8, by + dy * 0.4 + py * 0.8, h * 0.55),
             (bx + dx * 0.4 - px * 0.8, by + dy * 0.4 - py * 0.8, h * 0.55),
             (bx + dx, by + dy, h)]
        b.add(v, [(0, 1, 2, 3), (3, 2, 4)], 0)
    if "straw" not in MATS:
        m, N, L, bs = new_mat("straw")
        info = N.new("ShaderNodeObjectInfo")
        ramp = N.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (0.30, 0.25, 0.15, 1)
        ramp.color_ramp.elements[1].color = (0.52, 0.43, 0.25, 1)
        L.new(info.outputs["Random"], ramp.inputs["Fac"])
        L.new(ramp.outputs["Color"], bs.inputs["Base Color"])
        bs.inputs["Roughness"].default_value = 0.75
        tr = N.new("ShaderNodeBsdfTranslucent")
        L.new(ramp.outputs["Color"], tr.inputs["Color"])
        ms = N.new("ShaderNodeMixShader")
        ms.inputs[0].default_value = 0.25
        L.new(bs.outputs[0], ms.inputs[1])
        L.new(tr.outputs[0], ms.inputs[2])
        L.new(ms.outputs[0], N["Material Output"].inputs["Surface"])
        MATS["straw"] = m
    return b.obj(f"tuft_{k}", [MATS["straw"]])


# ---------------------------------------------------------------- sky
def sky():
    sc = bpy.context.scene
    world = bpy.data.worlds.new("World")
    sc.world = world
    world.use_nodes = True
    N, L = world.node_tree.nodes, world.node_tree.links
    bg = N["Background"]
    sk = N.new("ShaderNodeTexSky")
    sk.sky_type = "NISHITA"
    sk.sun_disc = False
    el = D(12.4)
    # sun bearing 118.8 deg true -> local azimuth from +X
    b = D(118.8)
    E, Nn = math.sin(b), math.cos(b)
    U, V = lib.META["U"], lib.META["V"]
    lx, ly = E * U[0] + Nn * U[1], E * V[0] + Nn * V[1]
    az = math.atan2(ly, lx)
    sk.sun_elevation = el
    sk.sun_rotation = math.pi / 2 - az
    sk.altitude = 790
    sk.air_density = 1.0
    sk.dust_density = 2.2
    sk.ozone_density = 1.0
    L.new(sk.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.32
    sd = bpy.data.lights.new("Sun", "SUN")
    sd.energy = 5.0
    sd.angle = D(0.53)
    sd.color = (1.0, 0.80, 0.62)
    sun = link(bpy.data.objects.new("Sun", sd))
    sv = Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    sun.rotation_euler = sv.to_track_quat("Z", "Y").to_euler()
    return sun
