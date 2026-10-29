"""Iryo ETR1000 (Frecciarossa 1000) and Renfe AVE S-103 (Velaro E) sets, crash kinematics, damage, debris."""
import math
import random

import bpy
from mathutils import Vector, noise

import lib
from lib import D, I, LAST, FPS, TOP, BALLAST, TR, TL, GAP, Builder, box_data, cyl_data, link, mesh_obj, set_anim, \
    ease_out, smooth
from env import plain, MATS

SLOPE_A = math.atan2(1.0, 1.6)

# body half-section, rail-top relative (y, z); underframe below z = 1.05
HALF = [(0, 1.05), (0.7, 1.05), (1.25, 1.06), (1.38, 1.12), (1.45, 1.3), (1.47, 1.6), (1.47, 2.0), (1.465, 2.45),
        (1.455, 2.8), (1.43, 3.05), (1.38, 3.28), (1.29, 3.5), (1.15, 3.68), (0.95, 3.82), (0.6, 3.92), (0, 3.96)]
ZB = [0.62, 1.35, 2.0, 2.05, 2.75, 2.8, 3.55]


def ring():
    """Dense ring, with extra vertices at the livery boundaries."""
    pts = []
    for (y0, z0), (y1, z1) in zip(HALF[:-1], HALF[1:]):
        seg = [0.0, 0.5]
        for zb in ZB:
            if min(z0, z1) < zb < max(z0, z1):
                seg.append((zb - z0) / (z1 - z0))
        for t in sorted(set(seg)):
            pts.append((y0 + (y1 - y0) * t, z0 + (z1 - z0) * t))
    pts.append(HALF[-1])
    return [(-y, z) for y, z in pts] + [(y, z) for y, z in reversed(pts[1:-1])]


RING = ring()
R = len(RING)

SPEC = {
    # ETR1000: long pointed nose, red with silver lower band and blue-black glazing band
    "IRYO": dict(LN=11.0, tip=1.2, wexp=0.62, texp=2.3, wmin=0.08, ws=(0.36, 0.72), panto=(1, 6),
                 lens=[26.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 26.0]),
    # Velaro E: shorter, blunter nose, white with thin purple stripe
    "AVE": dict(LN=7.6, tip=1.55, wexp=0.45, texp=1.7, wmin=0.22, ws=(0.42, 0.8), panto=(2, 5),
                lens=[25.5, 24.2, 24.2, 24.2, 24.2, 24.2, 24.2, 25.5]),
}


def livery():
    iryo_red = plain("iryo_red", (0.30, 0.004, 0.008), 0.36, 0.0, coat=0.2)
    out = {
        "IRYO": [iryo_red,
                 plain("iryo_silver", (0.48, 0.49, 0.5), 0.3, 0.75, coat=0.4),
                 plain("iryo_band", (0.012, 0.016, 0.03), 0.12, 0.2, coat=1.0),
                 plain("iryo_roof", (0.32, 0.33, 0.34), 0.5, 0.3)],
        "AVE": [plain("ave_white", (0.78, 0.79, 0.80), 0.3, 0.0, coat=0.35),
                plain("ave_purple", (0.18, 0.02, 0.2), 0.3, 0.1, coat=0.8),
                plain("ave_band", (0.16, 0.17, 0.18), 0.25, 0.4, coat=0.7),
                plain("ave_roof", (0.6, 0.61, 0.62), 0.45, 0.2)],
    }
    common = [plain("glass", (0.01, 0.012, 0.016), 0.03, 0.0, coat=1.0),
              plain("skirt", (0.07, 0.07, 0.075), 0.55, 0.3),
              plain("door_gap", (0.005, 0.005, 0.005), 0.7),
              plain("end_wall", (0.12, 0.12, 0.12), 0.6),
              plain("headlight", (0.9, 0.9, 0.9), 0.05, emit=(1.0, 0.97, 0.9), es=35),
              plain("taillight", (0.5, 0.0, 0.0), 0.1, emit=(1.0, 0.02, 0.0), es=25)]
    return out, common


LIV, COMMON = None, None
# material slot indices on a car mesh
BODY, LOWER, BAND, ROOF, GLASS, SKIRT, GAPM, ENDW, HEAD, TAIL = range(10)


def nose_profile(sp, s):
    w = sp["wmin"] + (1 - sp["wmin"]) * math.sin(min(1, s) * math.pi / 2) ** sp["wexp"]
    top = sp["tip"] + (3.96 - sp["tip"]) * (1 - (1 - min(1, s)) ** sp["texp"])
    bot = 1.05 - 0.6 * smooth((0.45 - s) / 0.2)
    return w, top, bot


def build_car(name, train, idx, L):
    sp = SPEC[train]
    nose = "front" if idx == 0 else ("rear" if idx == 7 else None)
    LN = sp["LN"]
    # sections every 0.2 m plus window and door edges
    xs = set(round(-L / 2 + 0.2 * k, 3) for k in range(int(L / 0.2) + 1))
    xs.add(L / 2)
    doors = []
    for e in (-1, 1):
        if (nose == "front" and e > 0) or (nose == "rear" and e < 0):
            continue
        doors.append(e * (L / 2 - 1.9))
    for xd in doors:
        for d in (-0.47, -0.45, 0.45, 0.47):
            xs.add(round(xd + d, 3))
    wins = []
    lo = -L / 2 + (3.2 if nose != "rear" else LN + 0.8)
    hi = L / 2 - (3.2 if nose != "front" else LN + 0.8)
    x = lo
    while x + 1.45 <= hi:
        wins.append((x + 0.15, x + 1.45))
        xs.add(round(x + 0.15, 3))
        xs.add(round(x + 1.45, 3))
        x += 2.3
    xs = sorted(xs)
    verts, faces, fm, svals = [], [], [], []
    for x in xs:
        if nose == "front":
            s = (L / 2 - x) / LN
        elif nose == "rear":
            s = (x + L / 2) / LN
        else:
            s = 2.0
        s = max(0.0, s)
        if s < 1:
            w, top, bot = nose_profile(sp, s)
        else:
            w, top, bot = 1.0, 3.96, 1.05
        for y, z in RING:
            zn = (z - 1.05) / (3.96 - 1.05)
            verts.append((x, y * w, bot + zn * (top - bot)))
        svals.append(s)
    for i in range(len(xs) - 1):
        xm = (xs[i] + xs[i + 1]) / 2
        sm = (svals[i] + svals[i + 1]) / 2
        for k in range(R):
            a = i * R + k
            b = i * R + (k + 1) % R
            c = (i + 1) * R + (k + 1) % R
            d = (i + 1) * R + k
            faces.append((a, d, c, b))
            zm = (RING[k][1] + RING[(k + 1) % R][1]) / 2
            ym = abs((RING[k][0] + RING[(k + 1) % R][0]) / 2)
            mi = BODY
            if zm < 1.08 and ym < 1.3:
                mi = SKIRT
            elif zm > 3.55 and ym < 1.25:
                mi = ROOF
            elif train == "IRYO" and zm < 1.35:
                mi = LOWER
            elif train == "AVE" and 1.15 < zm < 1.3:
                mi = LOWER
            elif 2.0 < zm < 2.8:
                mi = BAND
                if 2.05 < zm < 2.75 and any(a0 < xm < a1 for a0, a1 in wins):
                    mi = GLASS
            if sm < 1:
                zn = (zm - 1.05) / 2.91
                if sp["ws"][0] < sm < sp["ws"][1] and zn > 0.55 and ym < 1.25:
                    mi = GLASS
                elif sm < 0.06 and 0.18 < zn < 0.3 and 0.25 < ym < 0.9:
                    mi = HEAD if nose == "front" else TAIL
                elif sm < 0.12 and zn < 0.3:
                    mi = LOWER if train == "IRYO" else BODY
            for xd in doors:
                if (abs(abs(xm - xd) - 0.46) < 0.011) and 1.1 < zm < 2.95 and ym > 1.3:
                    mi = GAPM
                elif abs(xm - xd) < 0.45 and 2.1 < zm < 2.6 and ym > 1.3 and abs(xm - xd) < 0.25:
                    mi = GLASS
            fm.append(mi)
    for end in (0, len(xs) - 1):
        c = len(verts)
        s = svals[end]
        verts.append((xs[end], 0, 2.4 if s >= 1 else verts[end * R][2]))
        for k in range(R):
            a = end * R + k
            b = end * R + (k + 1) % R
            faces.append((c, a, b) if end else (c, b, a))
            fm.append(ENDW if s >= 1 else (SKIRT if train == "IRYO" else BODY))
    mats = LIV[train] + COMMON
    ob = mesh_obj(name, verts, faces, mats, fm, smooth=True)
    ob.data.set_sharp_from_angle(angle=D(35)) if hasattr(ob.data, "set_sharp_from_angle") else None
    sub = ob.modifiers.new("sub", "SUBSURF")
    sub.levels = 0
    sub.render_levels = 1
    ob["L"] = L
    # underframe, bogies, wheels
    det = Builder()
    bog = [(-L / 2 + 2.9) if nose != "rear" else (-L / 2 + 7.5), (L / 2 - 2.9) if nose != "front" else (L / 2 - 7.5)]
    for cx in bog:
        for yy in (-1.0, 1.0):
            v, f = box_data(3.0, 0.22, 0.42, (cx, yy, 0.72))
            det.add(v, f, 1)
        v, f = box_data(0.5, 2.2, 0.3, (cx, 0, 0.82))
        det.add(v, f, 1)
        for wx in (-1.35, 1.35):
            v, f = cyl_data(0.075, 0.075, (cx + wx, -1.1, 0.46), (cx + wx, 1.1, 0.46), 10)
            det.add(v, f, 1)
            for wy in (-0.75, 0.75):
                v, f = cyl_data(0.46, 0.46, (cx + wx, wy - 0.07, 0.46), (cx + wx, wy + 0.07, 0.46), 24)
                det.add(v, f, 0)
                v, f = box_data(0.32, 0.2, 0.28, (cx + wx, wy * 1.36, 0.5))
                det.add(v, f, 1)
    ex0 = bog[0] + 1.8
    ex1 = bog[1] - 1.8
    v, f = box_data(ex1 - ex0, 2.76, 0.5, ((ex0 + ex1) / 2, 0, 0.8))
    det.add(v, f, 2)
    if nose != "front":
        v, f = box_data(GAP + 0.15, 2.5, 2.6, (L / 2 + GAP / 2, 0, 2.35))
        det.add(v, f, 3)
    if idx in sp["panto"]:
        z0 = 3.96
        v, f = box_data(1.7, 1.1, 0.12, (0, 0, z0 + 0.25))
        det.add(v, f, 4)
        for yy in (-0.45, 0.45):
            for xx in (-0.7, 0.7):
                v, f = cyl_data(0.07, 0.06, (xx, yy, z0), (xx, yy, z0 + 0.22), 10)
                det.add(v, f, 5)
        v, f = cyl_data(0.045, 0.04, (-0.6, 0, z0 + 0.32), (0.65, 0, z0 + 0.9), 8)
        det.add(v, f, 4)
        v, f = cyl_data(0.035, 0.03, (0.65, 0, z0 + 0.9), (-0.25, 0, 5.3 - 0.05), 8)
        det.add(v, f, 4)
        v, f = box_data(0.3, 1.9, 0.05, (-0.25, 0, 5.3 - 0.02))
        det.add(v, f, 4)
    dob = det.obj(name + "_detail", [MATS["galv"], COMMON[1], plain("underframe", (0.05, 0.05, 0.05), 0.6),
                                     plain("bellows", (0.02, 0.02, 0.02), 0.85), MATS["galv"], MATS["insulator"]])
    dob.parent = ob
    logos(ob, train, idx, L, nose)
    return ob


def logos(ob, train, idx, L, nose):
    if train == "IRYO":
        text, col, size, z = "iryo", (0.9, 0.9, 0.9), 0.85, 1.55
        cars = (0, 3, 7)
    else:
        text, col, size, z = "renfe", (0.2, 0.02, 0.22), 0.6, 1.5
        cars = (0, 7)
    if idx not in cars:
        return
    m = plain(f"logo_{train}", col, 0.35, coat=0.5)
    for side in (-1, 1):
        cu = bpy.data.curves.new(f"{ob.name}_logo", "FONT")
        cu.body = text
        cu.size = size
        cu.extrude = 0.002
        cu.align_x = "CENTER"
        t = link(bpy.data.objects.new(f"{ob.name}_logo", cu))
        t.data.materials.append(m)
        xo = 0.0 if nose is None else (-1 if nose == "front" else 1) * (L / 2 - SPEC[train]["LN"] - 3.5)
        t.location = (xo, side * 1.478, z)
        t.rotation_euler = (D(90), 0, 0 if side < 0 else D(180))
        t.parent = ob


# ---------------------------------------------------------------- damage (shape keys)
def crush(ob, end, depth, final, amp, seed, roof_drop=0.0):
    """Compress the last `depth` metres at one end into `final` metres and crumple them."""
    if not ob.data.shape_keys:
        ob.shape_key_add(name="Basis")
    sk = ob.shape_key_add(name="crush", from_mix=False)
    L = ob["L"]
    off = Vector((seed * 13.7, seed * 3.1, seed * 7.9))
    for v, kv in zip(ob.data.vertices, sk.data):
        p = v.co
        d = L / 2 - p.x * end
        if d >= depth:
            kv.co = p.copy()
            continue
        t = 1 - d / depth
        nd = (depth - final) + d * final / depth
        q = p * 0.9 + off
        n1 = noise.noise(q)
        n2 = noise.noise(q * 2.3 + Vector((5, 1, 2)))
        n3 = noise.noise(q * 4.1 + Vector((2, 7, 3)))
        x = end * (L / 2 - nd) + end * amp * 0.4 * n3 * t
        y = p.y * (1 + 0.45 * t * abs(n1)) + amp * t ** 0.7 * n2
        z = p.z + amp * 0.6 * t ** 0.7 * n1 - roof_drop * t * max(0, p.z - 1.6) / 2.4
        kv.co = Vector((x, y, z))
    return sk


def dents(ob, amp, seed):
    if not ob.data.shape_keys:
        ob.shape_key_add(name="Basis")
    sk = ob.shape_key_add(name="dents", from_mix=False)
    off = Vector((seed * 5.3, seed * 1.7, 0))
    for v, kv in zip(ob.data.vertices, sk.data):
        p = v.co
        n = noise.noise(p * 0.55 + off)
        m = noise.noise(p * 1.7 + off * 2)
        sgn = -1 if p.y > 0 else 1
        kv.co = Vector((p.x, p.y + sgn * amp * max(0, n) * (0.6 + 0.4 * m), p.z - amp * 0.4 * max(0, m) * (p.z > 3.3)))
    return sk


def key_value(ob, name, frames, values):
    kb = ob.data.shape_keys.key_blocks[name]
    for f, v in zip(frames, values):
        kb.value = v
        kb.keyframe_insert("value", frame=lib.F(f))


# ---------------------------------------------------------------- layout + kinematics
def layout(lens, front_x):
    cs, x = [], front_x
    for L in lens:
        cs.append(x - L / 2)
        x -= L + GAP
    return cs


V_IMPACT = 55.6   # ~200 km/h, Transport Ministry estimate (unconfirmed)


def ave_speed(t):
    tI = (I - 1) / FPS
    tb = tI - 1.5
    if t < tb:
        return 57.0
    return 57.0 - (57.0 - V_IMPACT) * min(1.0, (t - tb) / 1.5)


def ave_shift():
    cum = [0.0]
    for f in range(2, I + 1):
        cum.append(cum[-1] + ave_speed((f - 2) / FPS) / FPS)
    return {f: cum[f - 1] - cum[I - 1] for f in range(1, I + 1)}


AVE_SHIFT = ave_shift()

# Final rest positions from the Guardia Civil aerials (RTVE, 20minutos, Gareth Dennis, 28/10/2026):
# Iryo 1-2 on the rails, 3-5 derailed but upright, 6-8 down the west bank with 7-8 on their side and the
# rear cab destroyed. The AVE head car broke away down the opposite (east) bank, car 2 broke up across
# the tracks, car 3 was pierced by a rail and the rest of the AVE derailed onto the adjacent track.
# (dx, y, yaw, roll, extra_pitch)
IRYO_F = [(15, TR, 0, 0, 0), (15, TR, 0, 0, 0), (14.5, TR - 0.5, 2, 3, 0), (14, TR - 1.1, -4, 5, 0),
          (13.5, TR - 2.4, 7, 10, 0), (13.1, -10.6, -10, 30, 0), (15.8, -10.2, 15, 84, 0), (24.0, -6.2, -22, 80, 0)]
AVE_F = [(44.0, 9.6, -24, -32, 0), (47.5, 1.6, -15, 7, -10), (49.5, 0.8, -8, 5, 0),
         (49.0, TL - 0.4, -3, 3, 0), (49.0, TL - 0.2, -1, 2, 0), (49.0, TL - 0.1, 1, 1, 0),
         (49.0, TL, 0, 1, 0), (49.0, TL, 0, 0, 0)]


def g_off(x, y):
    """Height a derailed car end rests on."""
    if abs(y) <= 5.3:
        return TOP - 0.32
    return lib.gz(x, y)


def slope_sign(y):
    if y < -7.2:
        return SLOPE_A
    if y > 7.2:
        return -SLOPE_A
    return 0.0


def rail_z(x):
    return float(lib.crest(x)) + (TOP - lib.FORM)


def animate_car(c):
    ob, L = c["ob"], c["L"]
    xF, yF, yawF, rollF, peF = c["final"]
    d, T, derail = c["params"]
    rng = random.Random(hash(ob.name) & 0xffff)
    ph = [rng.uniform(0, 6.28) for _ in range(3)]
    frames = list(range(1, LAST + 1))
    raw = []
    for f in frames:
        if f <= I:
            x = c["x0"] + (AVE_SHIFT[f] if c["train"] == "AVE" else 0.0)
            raw.append((x, TR, 0.0, 0.0, False))
            continue
        u = (f - I - d) / T
        x = c["x0"] + (xF - c["x0"]) * ease_out(u)
        ul = (f - I - d - T * 0.08) / (T * 0.92)
        y = TR + (yF - TR) * smooth(ul)
        yaw = yawF * smooth(ul)
        ur = (f - I - d - T * 0.25) / (T * 0.75)
        roll = rollF * smooth(ur)
        raw.append((x, y, yaw, roll, derail and ul > 0))
    zs, pitches = [], []
    for (x, y, yaw, roll, off) in raw:
        hx, hy = L / 2 * math.cos(yaw), L / 2 * math.sin(yaw)
        if off:
            zf, zr = g_off(x + hx, y + hy), g_off(x - hx, y - hy)
            if abs(y + hy - TR) < 0.6 and abs(y - TR) < 1.0:
                zf = rail_z(x + hx)
        else:
            zf, zr = rail_z(x + hx), rail_z(x - hx)
        rel = abs(roll - slope_sign(y))
        zc = (zf + zr) / 2 + 1.46 * math.sin(min(rel, math.pi / 2)) - (0.0 if rel < 0.05 else 0.25 * min(1, rel))
        if rel > math.pi / 2:
            zc += 0.2
        zs.append(zc)
        pitches.append(-math.atan2(zf - zr, L))
    for k, f in enumerate(frames):
        if f > I:
            pitches[k] += D(peF) * smooth((f - I - d - T * 0.2) / (T * 0.8))

    def smooth_arr(a, win=4):
        out = list(a)
        for k in range(I, len(a)):
            lo, hi = max(I - 1, k - win), min(len(a), k + win + 1)
            out[k] = sum(a[lo:hi]) / (hi - lo)
        return out

    zs = smooth_arr(zs)
    pitches = smooth_arr(pitches)
    locs, rots = [], []
    for k, f in enumerate(frames):
        x, y, yaw, roll, off = raw[k]
        jit, tt = 0.0, 0.0
        if f > I and (derail or c["train"] == "AVE" and c["i"] < 6 or c["train"] == "IRYO" and c["i"] > 2):
            tt = (f - I) / FPS
            jit = math.exp(-tt * 1.6) * D(1.6)
        locs.append((x, y, zs[k]))
        rots.append((roll + (jit * math.sin(tt * 23 + ph[0]) if jit else 0.0),
                     pitches[k] + (jit * 0.5 * math.sin(tt * 17 + ph[1]) if jit else 0.0),
                     yaw + (jit * 0.6 * math.sin(tt * 13 + ph[2]) if jit else 0.0)))
    set_anim(ob, "location", locs, frames)
    set_anim(ob, "rotation_euler", rots, frames)


def build_trains():
    global LIV, COMMON
    LIV, COMMON = livery()
    cars = []
    for train in ("IRYO", "AVE"):
        lens = SPEC[train]["lens"]
        if train == "IRYO":
            xs = layout(lens, sum(lens) + GAP * 7)        # Iryo rear tip at x = 0
        else:
            xs = layout(lens, -0.3)                          # AVE nose at impact
        for i in range(8):
            ob = build_car(f"{train}_{i + 1}", train, i, lens[i])
            cars.append(dict(train=train, i=i, L=lens[i], ob=ob, x0=xs[i]))
    for c in cars:
        dx, y, yaw, roll, pe = (IRYO_F if c["train"] == "IRYO" else AVE_F)[c["i"]]
        c["final"] = (c["x0"] + dx, y, D(yaw), D(roll), pe)
        if c["train"] == "IRYO":
            c["params"] = (7 - c["i"], 40 + 4 * c["i"], c["i"] >= 2)
        else:
            c["params"] = (min(c["i"], 5), max(30, int(2 * dx * FPS / V_IMPACT)), True)
        animate_car(c)
    by = {(c["train"], c["i"]): c for c in cars}
    # damage
    a1 = by[("AVE", 0)]["ob"]
    crush(a1, +1, 16.0, 5.5, 0.55, 1, roof_drop=0.8)
    key_value(a1, "crush", [I - 1, I + 3, I + 9], [0, 0.6, 1])
    i8 = by[("IRYO", 7)]["ob"]
    crush(i8, -1, 14.0, 5.0, 0.6, 2, roof_drop=1.6)
    key_value(i8, "crush", [I - 1, I + 3, I + 9], [0, 0.7, 1])
    for (t, i), amp in ((("AVE", 1), 0.35), (("AVE", 2), 0.3), (("IRYO", 6), 0.3), (("IRYO", 5), 0.22),
                        (("IRYO", 4), 0.15), (("AVE", 3), 0.12)):
        ob = by[(t, i)]["ob"]
        dents(ob, amp, i + (10 if t == "AVE" else 0))
        d = by[(t, i)]["params"][0]
        key_value(ob, "dents", [I + d, I + d + 25], [0, 1])
    a2 = by[("AVE", 1)]["ob"]
    crush(a2, +1, 6.0, 3.2, 0.35, 3)
    key_value(a2, "crush", [I + 1, I + 6, I + 14], [0, 0.5, 1])
    return cars, by


# ---------------------------------------------------------------- torn rail, cab shell, debris
def extras(by):
    rpiv = link(bpy.data.objects.new("rail_pivot", None))
    rpiv.location = (-32, TR - 0.7, TOP - 0.1)
    rb = Builder()
    from env import RAIL_RING
    n = len(RAIL_RING)
    for x in (0.0, 26.0):
        rb.v += [(x, y, z - 0.08) for y, z in RAIL_RING]
    for k in range(n - 1):
        rb.f.append((k, k + 1, n + k + 1, n + k))
        rb.m.append(0)
    rail = rb.obj("rail_torn", [MATS["rail_side"]], smooth=True)
    bend = rail.modifiers.new("bend", "SIMPLE_DEFORM")
    bend.deform_method = "BEND"
    bend.deform_axis = "Z"
    bend.angle = D(14)
    rail.parent = rpiv
    set_anim(rpiv, "rotation_euler", [(0, 0, 0), (0, 0, 0), (0, D(-16), D(8)), (0, D(-25), D(9))],
             [1, I + 6, I + 16, I + 34])
    set_anim(rpiv, "scale", [(0, 0, 0), (0, 0, 0), (1, 1, 1)], [1, I + 5, I + 6], interp="CONSTANT")
    # upper shell of the Iryo rear cab, torn off and thrown onto the embankment
    sp = SPEC["IRYO"]
    b = Builder()
    xs = [k * 0.4 for k in range(16)]
    top = [(y, z) for y, z in RING if z > 2.3]
    for x in xs:
        s = x / sp["LN"]
        w, tp, bt = nose_profile(sp, s)
        b.v += [(x, y * w * 1.05, bt + (z - 1.05) / 2.91 * (tp - bt) + 0.2 * noise.noise(Vector((x, y, z)) * 1.3))
                for y, z in top]
    n = len(top)
    for i in range(len(xs) - 1):
        for k in range(n - 1):
            b.f.append((i * n + k, (i + 1) * n + k, (i + 1) * n + k + 1, i * n + k + 1))
            zm = top[k][1]
            b.m.append(1 if (sp["ws"][0] < xs[i] / sp["LN"] < sp["ws"][1] and zm > 2.6) else 0)
    shell = b.obj("iryo_cab_shell", [LIV["IRYO"][0], COMMON[0]], smooth=True)
    sol = shell.modifiers.new("thick", "SOLIDIFY")
    sol.thickness = 0.06
    z12 = lib.gz(24, -12)
    pts = [(1, (0.0, TR, TOP), (0, 0, 0)), (I + 1, (0.0, TR, TOP), (0, 0, 0)),
           (I + 12, (12, -7, TOP + 8), (D(70), D(20), D(40))),
           (I + 26, (22, -12, z12 + 2.0), (D(150), D(10), D(80))),
           (I + 34, (24, -12.5, z12 + 0.5), (D(162), D(26), D(95)))]
    set_anim(shell, "location", [p[1] for p in pts], [p[0] for p in pts])
    set_anim(shell, "rotation_euler", [p[2] for p in pts], [p[0] for p in pts])
    set_anim(shell, "scale", [(0, 0, 0), (0, 0, 0), (1, 1, 1)], [1, I, I + 1], interp="CONSTANT")
    debris(by)


def debris(by):
    spark = plain("spark", (1, 0.4, 0.1), 0.5, emit=(1.0, 0.42, 0.1), es=80)
    mats = [COMMON[1], COMMON[0], LIV["IRYO"][0], LIV["AVE"][0], MATS["galv"], MATS["ballast"]]
    rng = random.Random(11)
    for n in range(320):
        is_spark = n >= 220
        if is_spark:
            v, f = box_data(0.03, 0.03, 0.03)
            ob = mesh_obj("spark", v, f, [spark])
        else:
            s = rng.uniform(0.04, 0.5) if n % 3 else rng.uniform(0.03, 0.09)
            v, f = box_data(s * rng.uniform(0.4, 2.2), s, s * rng.uniform(0.05, 0.6))
            ob = mesh_obj("debris", v, f, [rng.choice(mats) if n % 3 else MATS["ballast"]])
        p = Vector((rng.uniform(-1, 2), TR + rng.uniform(-1.5, 1.5), TOP + rng.uniform(0.2, 3.6)))
        vel = Vector((rng.uniform(8, 42), rng.uniform(-14, 5), rng.uniform(1, 13)))
        if is_spark:
            vel *= 1.4
        w = Vector((rng.uniform(-14, 14), rng.uniform(-14, 14), rng.uniform(-14, 14)))
        start = I + rng.randint(0, 8)
        life = rng.randint(5, 16) if is_spark else 10 ** 6
        frames, locs, rots, scs = [1, start - 1], [tuple(p), tuple(p)], [(0, 0, 0)] * 2, [(0, 0, 0), (0, 0, 0)]
        rot = Vector((0, 0, 0))
        rest = False
        for f in range(start, min(LAST, start + 150)):
            dt = 1 / FPS
            if not rest:
                vel.z -= 9.81 * dt
                p += vel * dt
                rot += w * dt
                gz = g_off(p.x, p.y)
                if p.z < gz + 0.03:
                    p.z = gz + 0.03
                    vel.z = -vel.z * 0.3
                    vel.x *= 0.5
                    vel.y *= 0.5
                    w *= 0.5
                    if vel.length < 0.8:
                        rest = True
            alive = (f - start) < life
            frames.append(f)
            locs.append(tuple(p))
            rots.append(tuple(rot))
            scs.append(((1, 1, 6) if is_spark else (1, 1, 1)) if alive else (0, 0, 0))
        set_anim(ob, "location", locs, frames, interp="LINEAR")
        set_anim(ob, "rotation_euler", rots, frames, interp="LINEAR")
        set_anim(ob, "scale", scs, frames, interp="CONSTANT")


def catenary_collapse(falling, zone_wires):
    for piv, side, x in falling:
        delay = int(max(0, x + 40) / 55.0 * FPS * 0.6) + 3
        frames = [1, I + delay, I + delay + 12, I + delay + 22, I + delay + 26]
        ang = [0, 0, D(25), D(78), D(74)]
        set_anim(piv, "rotation_euler", [(-side * a, 0.0, 0.0) for a in ang], frames)
    for w in zone_wires:
        set_anim(w, "scale", [(1, 1, 1), (1, 1, 1), (0, 0, 0)], [1, I + 3, I + 4], interp="CONSTANT")
