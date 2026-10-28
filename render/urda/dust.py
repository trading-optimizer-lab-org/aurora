"""Mantaflow dust: domain over the crash zone, emitters on the impact point, bogies and bank strikes."""
import bpy

import lib
from lib import I, LAST, TOP, TR, F, set_anim
from trains import SPEC


def volume_material():
    m = bpy.data.materials.new("dust")
    m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links
    N.remove(N["Principled BSDF"])
    pv = N.new("ShaderNodeVolumePrincipled")
    pv.inputs["Color"].default_value = (0.80, 0.70, 0.56, 1)
    pv.inputs["Absorption Color"].default_value = (0.35, 0.28, 0.2, 1)
    pv.inputs["Anisotropy"].default_value = 0.4
    at = N.new("ShaderNodeAttribute")
    at.attribute_name = "density"
    tc = N.new("ShaderNodeTexCoord")
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 0.35
    nz.inputs["Detail"].default_value = 8
    nz.inputs["Roughness"].default_value = 0.62
    L.new(tc.outputs["Generated"], nz.inputs["Vector"])
    mr = N.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = 0.3
    mr.inputs["From Max"].default_value = 0.75
    mr.inputs["To Min"].default_value = 0.25
    mr.inputs["To Max"].default_value = 1.6
    L.new(nz.outputs["Fac"], mr.inputs["Value"])
    mul = N.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    L.new(at.outputs["Fac"], mul.inputs[0])
    L.new(mr.outputs["Result"], mul.inputs[1])
    gain = N.new("ShaderNodeMath")
    gain.operation = "MULTIPLY"
    gain.inputs[1].default_value = 1.5
    L.new(mul.outputs[0], gain.inputs[0])
    L.new(gain.outputs[0], pv.inputs["Density"])
    L.new(pv.outputs["Volume"], N["Material Output"].inputs["Volume"])
    return m


def emitter(name, loc, size, on, off, parent=None, temp=1.0, dens=1.0, vel=None, follow=True):
    bpy.ops.mesh.primitive_ico_sphere_add(radius=1.0, subdivisions=2, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    if parent:
        ob.parent = parent
        ob.location = loc
    mod = ob.modifiers.new("Fluid", "FLUID")
    mod.fluid_type = "FLOW"
    fs = mod.flow_settings
    fs.flow_type = "SMOKE"
    fs.flow_behavior = "INFLOW"
    fs.flow_source = "MESH"
    fs.surface_distance = 0.8
    fs.density = dens
    fs.temperature = temp
    fs.smoke_color = (0.8, 0.7, 0.56)
    fs.subframes = 1
    fs.use_initial_velocity = True
    fs.velocity_factor = 0.55 if follow else 0.0
    if vel:
        fs.velocity_coord = vel
    ob.hide_render = True
    tiny = (0.001, 0.001, 0.001)
    set_anim(ob, "scale", [tiny, tiny, size, size, tiny], [1, on - 1, on, off, off + 1], interp="CONSTANT")
    return ob


def dust(cars, by, res):
    x0, x1, y0, y1, z0, z1 = -225.0, 165.0, -60.0, 34.0, -0.5, 48.0
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    dom = bpy.context.active_object
    dom.name = "dust_domain"
    dom.scale = (x1 - x0, y1 - y0, z1 - z0)
    mod = dom.modifiers.new("Fluid", "FLUID")
    mod.fluid_type = "DOMAIN"
    ds = mod.domain_settings
    ds.domain_type = "GAS"
    ds.resolution_max = res
    ds.use_adaptive_domain = True
    ds.adapt_threshold = 0.004
    ds.adapt_margin = 6
    ds.cache_type = "ALL"
    ds.cache_directory = "//dust_cache"
    ds.cache_data_format = "OPENVDB"
    ds.openvdb_cache_compress_type = "BLOSC"
    ds.openvdb_data_depth = "16"
    ds.cache_frame_start = F(I - 1)
    ds.cache_frame_end = F(LAST)
    ds.alpha = -0.08
    ds.beta = 0.5
    ds.vorticity = 0.12
    ds.use_dissolve_smoke = True
    ds.use_dissolve_smoke_log = True
    ds.dissolve_speed = 700
    ds.use_noise = False
    for p in ("use_collision_border_front", "use_collision_border_back", "use_collision_border_right",
              "use_collision_border_left", "use_collision_border_top"):
        setattr(ds, p, False)
    ds.use_collision_border_bottom = True
    dom.data.materials.append(volume_material())
    # impact plume and ballast blast
    emitter("em_impact", (2.0, TR - 0.5, TOP + 1.2), (4.0, 3.0, 2.5), I, I + 18, temp=2.5, dens=1.6,
            vel=(28.0, -5.0, 4.0), follow=False)
    emitter("em_impact_low", (6.0, TR - 2.0, TOP - 0.6), (6.0, 4.0, 1.4), I + 2, I + 40, temp=0.8, dens=1.2,
            vel=(14.0, -7.0, 1.5), follow=False)
    # derailed bogies ploughing through ballast and soil
    for c in cars:
        d, T, derail = c["params"]
        if not derail:
            continue
        L = c["L"]
        for e in (-1, 1):
            emitter(f"em_{c['ob'].name}_{e}", (e * (L / 2 - 3.0), 0.0, 0.3), (2.6, 2.0, 0.9),
                    I + d + 2, I + d + int(T * 0.95), parent=c["ob"], temp=0.4, dens=1.0)
    # cars striking the west bank
    for key in (("IRYO", 4), ("IRYO", 5), ("IRYO", 6), ("IRYO", 7), ("AVE", 0), ("AVE", 2)):
        c = by[key]
        xF, yF = c["final"][0], c["final"][1]
        d, T, _ = c["params"]
        zg = lib.gz(xF, yF)
        emitter(f"em_bank_{key[0]}_{key[1]}", (xF, yF - 1.5, zg + 0.8), (c["L"] * 0.45, 4.0, 1.6),
                I + d + int(T * 0.55), I + d + T + 12, temp=0.6, dens=1.4, vel=(0, -4.0, 2.5), follow=False)
    # light breeze from the north-east carries the cloud across the field
    bpy.ops.object.effector_add(type="WIND", location=(-60, 40, 10))
    w = bpy.context.active_object
    w.rotation_euler = (lib.D(90), 0, lib.D(45))
    w.field.strength = 2.0
    w.field.flow = 0.5
    return dom
