"""Cameras (documentary drone / trackside), Cycles settings, compositor."""
import math
import random

import bpy
from mathutils import Vector, noise

import lib
from lib import D, I, LAST, TOP, TR, FORM, link, set_anim, smooth
from trains import AVE_SHIFT


def look_rot(loc, tgt):
    return (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def ave_front(f):
    return -0.3 + AVE_SHIFT[min(max(f, 1), I)]


def camera(name, lens, fn, frames, fstop=8.0, shake=0.0, drift=0.12):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36
    cd.clip_start = 0.3
    cd.clip_end = 30000
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = fstop
    ob = link(bpy.data.objects.new(name, cd))
    rng = random.Random(len(name) * 31)
    seed = Vector((rng.uniform(0, 50), rng.uniform(0, 50), 0))
    locs, rots, foc = [], [], []
    for f in frames:
        loc, tgt = fn(f)
        loc = Vector(loc)
        t = f / 30.0
        # slow drone drift
        loc += drift * Vector((noise.noise(seed + Vector((t * 0.4, 0, 0))), noise.noise(seed + Vector((0, t * 0.4, 3))),
                               noise.noise(seed + Vector((5, 0, t * 0.4)))))
        if shake and f > I:
            a = shake * math.exp(-(f - I) / 20.0)
            loc += a * Vector((noise.noise(seed + Vector((t * 9, 1, 1))), noise.noise(seed + Vector((2, t * 9, 2))),
                               noise.noise(seed + Vector((3, 3, t * 9)))))
        e = look_rot(loc, tgt)
        locs.append(tuple(loc))
        rots.append((e.x, e.y, e.z))
        foc.append(((Vector(tgt) - loc).length,))
    set_anim(ob, "location", locs, frames)
    set_anim(ob, "rotation_euler", rots, frames)
    set_anim(cd, "dof.focus_distance", foc, frames)
    return ob


def shot_a(f):
    xf = ave_front(f)
    t = f / 150
    return (xf - 92 + 22 * t, 44 - 9 * t, TOP + 30 - 7 * t), (xf + 70, TR, TOP - 2)


def shot_b(f):
    t = (f - 151) / 150
    return (36 - 5 * t, -6.6, FORM + 1.55), (-160, TR + 0.3, TOP + 1.0)


def shot_c(f):
    t = (f - 301) / 150
    return (92 - 12 * t, -88 + 6 * t, 30 - 3 * t), (12, -6, 4)


def shot_d(f):
    t = (f - 318) / 60
    return (-38 + 24 * t, -44, 52), (12, -5, 3)


def shot_e(f):
    t = smooth((f - 451) / 330)
    ang = D(-105 + 150 * t)
    r = 165 - 35 * t
    cx, cy = 15, -6
    return (cx + r * math.cos(ang), cy + r * math.sin(ang), 75 - 28 * t), (cx + 6, cy - 3, 2)


def cameras():
    camera("CamA", 35, shot_a, list(range(1, 152)), fstop=8)
    camera("CamB", 50, shot_b, list(range(150, 302)), fstop=4, drift=0.03)
    camera("CamC", 32, shot_c, list(range(300, 452)), fstop=8, shake=0.3)
    camera("CamD", 30, shot_d, list(range(316, 380)), fstop=8, shake=0.2)
    camera("CamE", 28, shot_e, list(range(450, LAST + 1)), fstop=11)


def sa(obj, attr, val):
    try:
        setattr(obj, attr, val)
    except Exception as ex:
        print("skip", attr, ex)


def render_settings(quality):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "CPU"
    cy.samples = 1024 if quality == "final" else 64
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.012
    cy.adaptive_min_samples = 64 if quality == "final" else 16
    cy.use_denoising = True
    sa(cy, "denoiser", "OPENIMAGEDENOISE")
    sa(cy, "denoising_input_passes", "RGB_ALBEDO_NORMAL")
    sa(cy, "denoising_prefilter", "ACCURATE")
    sa(cy, "denoising_quality", "HIGH")
    cy.max_bounces = 10
    cy.diffuse_bounces = 4
    cy.glossy_bounces = 4
    cy.transmission_bounces = 8
    cy.volume_bounces = 2
    cy.transparent_max_bounces = 24
    cy.sample_clamp_indirect = 8.0
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.blur_glossy = 1.0
    cy.volume_step_rate = 1.0
    cy.volume_max_steps = 512
    sa(cy, "use_light_tree", True)
    sc.render.use_persistent_data = True
    sc.render.use_motion_blur = True
    sc.render.motion_blur_shutter = 0.5 * lib.K
    sa(cy, "motion_blur_position", "CENTER")
    sc.render.fps = 30 * lib.K
    sc.render.resolution_x = 1920
    sc.render.resolution_y = 1080
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    sa(sc.view_settings, "look", "AgX - Medium High Contrast")
    sc.view_settings.exposure = 0.0
    sc.frame_start, sc.frame_end = 1, lib.F(LAST)
    sc.camera = bpy.data.objects["CamA"]
    vl = sc.view_layers[0]
    vl.use_pass_mist = True
    sc.world.mist_settings.start = 150
    sc.world.mist_settings.depth = 7000
    sc.world.mist_settings.falloff = "QUADRATIC"


def compositor():
    sc = bpy.context.scene
    sc.use_nodes = True
    nt = sc.node_tree
    N, L = nt.nodes, nt.links
    rl, cp = N["Render Layers"], N["Composite"]
    # aerial perspective: blend distant terrain into the morning haze
    haze = N.new("CompositorNodeMixRGB")
    haze.blend_type = "MIX"
    mm = N.new("CompositorNodeMath")
    mm.operation = "MULTIPLY"
    mm.inputs[1].default_value = 0.55
    L.new(rl.outputs["Mist"], mm.inputs[0])
    L.new(mm.outputs[0], haze.inputs[0])
    L.new(rl.outputs["Image"], haze.inputs[1])
    haze.inputs[2].default_value = (0.62, 0.66, 0.72, 1)
    cur = haze.outputs[0]
    gl = N.new("CompositorNodeGlare")
    sa(gl, "glare_type", "FOG_GLOW")
    sa(gl, "quality", "HIGH")
    sa(gl, "mix", -0.9)
    sa(gl, "threshold", 2.0)
    for nm, v in (("Threshold", 2.0), ("Strength", 0.15)):
        if nm in gl.inputs:
            gl.inputs[nm].default_value = v
    L.new(cur, gl.inputs["Image"])
    cur = gl.outputs["Image"]
    ld = N.new("CompositorNodeLensdist")
    for nm, v in (("Distort", -0.012), ("Dispersion", 0.006)):
        if nm in ld.inputs:
            ld.inputs[nm].default_value = v
    sa(ld, "use_fit", True)
    L.new(cur, ld.inputs["Image"])
    cur = ld.outputs["Image"]
    em = N.new("CompositorNodeEllipseMask")
    sa(em, "width", 1.15)
    sa(em, "height", 1.25)
    for nm, v in (("Size", (1.15, 1.25)),):
        if nm in em.inputs:
            try:
                em.inputs[nm].default_value = v
            except Exception:
                pass
    bl = N.new("CompositorNodeBlur")
    sa(bl, "size_x", 300)
    sa(bl, "size_y", 300)
    sa(bl, "filter_type", "GAUSS")
    L.new(em.outputs["Mask"], bl.inputs["Image"])
    vig = N.new("CompositorNodeMixRGB")
    vig.blend_type = "MULTIPLY"
    vig.inputs[0].default_value = 1.0
    L.new(cur, vig.inputs[1])
    vr = N.new("CompositorNodeMapRange")
    vr.inputs["To Min"].default_value = 0.72
    vr.inputs["To Max"].default_value = 1.0
    L.new(bl.outputs["Image"], vr.inputs["Value"])
    L.new(vr.outputs["Value"], vig.inputs[2])
    L.new(vig.outputs[0], cp.inputs["Image"])
