"""Main InkRoom 3D Engine v2 production script for `NEVER Pour Water on a Grease Fire`.

Zero characters (15 auto-downloaded CC0 Poly Haven models + rich Toon v2 Look-Dev +
beat-synchronized kinetic camera matched 1:1 to `assets/audio/master_audio.m4a` = 46.86s).

CI modes:
  - `preview`              : Gate B — 12 storyboard keyframes across all 11 spoken beats
  - `thumb`                : Dedicated Stage 7 3D cover render
  - `chunk <idx> <chunks>` : 20-way parallel final render (`frames 1..1406`)
"""

import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "engine")))

from bru3d_core import (  # noqa: E402
    add_box,
    add_cone,
    add_cylinder,
    add_empty,
    add_sphere,
    add_torus,
    attach_local,
    clear_scene,
    keyframe_kinetic_camera,
    lerp,
    lerp3,
    make_emissive_mix_mat,
    make_lamp_shade_mat,
    make_toon_v2_mat,
    make_wood_floor_mat,
    orbit_pos,
    parse_args,
    render_chunk,
    render_named_views,
    render_preview_frames,
    set_hidden,
    setup_bru3d_render_v2,
    setup_vertical_camera,
    smooth_step,
)
from polyhaven_loader import import_polyhaven_asset  # noqa: E402

FPS = 30
TOTAL_FRAMES = 1406  # exact ceil(46.860000s * 30fps)
PREVIEW_FRAMES = [42, 130, 195, 345, 520, 695, 815, 920, 1035, 1125, 1210, 1315]


def build_stylized_fire(name, loc, col_vfx, scale_base=1.0):
    """Build multi-layered saturated Toon flames + embers."""
    root = add_empty(name, loc, col_vfx)
    mat_outer = make_lamp_shade_mat(f"{name}_OuterMat", (0.94, 0.14, 0.03), strength=1.02)
    mat_mid = make_lamp_shade_mat(f"{name}_MidMat", (1.0, 0.38, 0.04), strength=1.10)
    mat_core = make_lamp_shade_mat(f"{name}_CoreMat", (1.0, 0.78, 0.16), strength=1.22)

    flames = []
    specs = [
        ("OuterC", 0.095 * scale_base, 0.012 * scale_base, 0.26 * scale_base, (0.0, 0.0, 0.12 * scale_base), (0.0, 0.0, 0.0), mat_outer),
        ("OuterL", 0.068 * scale_base, 0.010 * scale_base, 0.20 * scale_base, (-0.070 * scale_base, -0.02 * scale_base, 0.095 * scale_base), (0.0, math.radians(-16), 0.2), mat_outer),
        ("OuterR", 0.068 * scale_base, 0.010 * scale_base, 0.21 * scale_base, (0.070 * scale_base, 0.02 * scale_base, 0.095 * scale_base), (0.1, math.radians(15), -0.3), mat_outer),
        ("MidC", 0.058 * scale_base, 0.008 * scale_base, 0.19 * scale_base, (0.01 * scale_base, -0.015 * scale_base, 0.090 * scale_base), (0.0, math.radians(5), 0.0), mat_mid),
        ("MidL", 0.042 * scale_base, 0.006 * scale_base, 0.15 * scale_base, (-0.042 * scale_base, -0.015 * scale_base, 0.070 * scale_base), (-0.1, math.radians(-10), 0.1), mat_mid),
        ("CoreC", 0.036 * scale_base, 0.005 * scale_base, 0.11 * scale_base, (0.0, -0.022 * scale_base, 0.055 * scale_base), (0.0, 0.0, 0.0), mat_core),
    ]
    for tag, r1, r2, dp, lloc, lrot, mat in specs:
        c = add_cone(f"{name}_{tag}", r1, r2, dp, (0.0, 0.0, 0.0), col_vfx, mat, verts=16)
        attach_local(c, root, lloc, lrot)
        flames.append(c)

    embers = []
    for i in range(6):
        ang = i * (2.0 * math.pi / 6.0)
        em = add_sphere(f"{name}_Ember_{i}", 0.012 * scale_base, (0.0, 0.0, 0.0), col_vfx, mat_core, subsurf=0)
        attach_local(em, root, (0.06 * math.cos(ang), 0.06 * math.sin(ang), 0.18 + i * 0.03))
        embers.append(em)

    return {"root": root, "objs": flames + embers}


def build_fireball_plume(name, loc, col_vfx):
    """Build vivid fiery orange-crimson-gold 1,700x mushroom explosion column."""
    root = add_empty(name, loc, col_vfx)
    mat_fire_hot = make_lamp_shade_mat(f"{name}_Hot", (1.0, 0.80, 0.20), strength=1.22)
    mat_fire_mid = make_lamp_shade_mat(f"{name}_Mid", (1.0, 0.36, 0.04), strength=1.08)
    mat_fire_edge = make_lamp_shade_mat(f"{name}_Edge", (0.90, 0.12, 0.04), strength=0.98)
    mat_steam = make_emissive_mix_mat(f"{name}_Steam", (0.86, 0.95, 1.0), alpha=0.52, strength=1.05)

    stem_core = add_cone(f"{name}_StemCore", 0.06, 0.16, 0.84, (0.0, 0.0, 0.0), col_vfx, mat_fire_hot, verts=18)
    attach_local(stem_core, root, (0.0, -0.05, 0.42))

    stem_outer = add_cone(f"{name}_StemOuter", 0.13, 0.30, 0.82, (0.0, 0.0, 0.0), col_vfx, mat_fire_mid, verts=18)
    attach_local(stem_outer, root, (0.0, 0.0, 0.42))

    objs = [stem_core, stem_outer]
    lobe_specs = [
        ((0.0, -0.04, 0.84), 0.22, mat_fire_hot),
        ((-0.18, -0.04, 0.80), 0.21, mat_fire_edge),
        ((0.18, -0.02, 0.82), 0.22, mat_fire_mid),
        ((0.02, 0.14, 0.90), 0.23, mat_fire_edge),
        ((-0.11, -0.10, 0.95), 0.18, mat_fire_mid),
        ((0.12, -0.08, 0.98), 0.19, mat_fire_edge),
        ((0.0, 0.04, 1.04), 0.18, mat_fire_mid),
    ]
    for idx, (lloc, rad, mat) in enumerate(lobe_specs):
        lb = add_sphere(f"{name}_Crown_{idx}", rad, (0.0, 0.0, 0.0), col_vfx, mat, scale=(1.1, 1.0, 0.92), subsurf=0)
        attach_local(lb, root, lloc)
        objs.append(lb)

    steam_ring = add_torus(f"{name}_SteamShock", 0.20, 0.045, (0.0, 0.0, 0.0), col_vfx, mat_steam)
    attach_local(steam_ring, root, (0.0, 0.0, 0.08))
    objs.append(steam_ring)

    return {"root": root, "objs": objs}


def build_animated_cutaway_stage(name, loc, col_ink, col_vfx):
    """Build animated Dark Science 3D cutaway: sinking water spheres -> 1,700x steam blast."""
    root = add_empty(name, loc, col_ink)

    mat_bg = make_lamp_shade_mat(f"{name}_SlateBG", (0.08, 0.12, 0.20), strength=1.0)
    mat_pan = make_toon_v2_mat(f"{name}_Pan", (0.28, 0.31, 0.38), rim_color=(0.75, 0.88, 1.0), rim_strength=0.30, spec_strength=0.25)
    mat_coil = make_lamp_shade_mat(f"{name}_Coil", (1.0, 0.24, 0.05), strength=1.25)
    mat_oil = make_toon_v2_mat(f"{name}_Oil", (0.96, 0.68, 0.14), (0.72, 0.44, 0.06), rim_strength=0.18, spec_strength=0.28)
    mat_water = make_lamp_shade_mat(f"{name}_Water", (0.12, 0.66, 1.0), strength=1.18)
    mat_steam = make_emissive_mix_mat(f"{name}_Steam", (0.78, 0.95, 1.0), alpha=0.50, strength=1.12)
    mat_burst = make_lamp_shade_mat(f"{name}_Burst", (1.0, 0.38, 0.06), strength=1.12)
    mat_burst_hot = make_lamp_shade_mat(f"{name}_BurstHot", (1.0, 0.78, 0.18), strength=1.24)
    mat_arrow_up = make_lamp_shade_mat(f"{name}_ArrowUp", (1.0, 0.24, 0.14), strength=1.15)
    mat_arrow_dn = make_lamp_shade_mat(f"{name}_ArrowDn", (0.20, 0.76, 1.0), strength=1.15)

    bg_card = add_box(f"{name}_SlateCard", (2.10, 0.03, 2.40), (0.0, 0.0, 0.0), col_vfx, mat_bg, bevel=0.015)
    attach_local(bg_card, root, (0.0, 0.26, 0.16))

    coil = add_torus(f"{name}_BurnerCoil", 0.19, 0.018, (0.0, 0.0, 0.0), col_vfx, mat_coil)
    attach_local(coil, root, (0.0, 0.0, -0.02))

    pan_base = add_box(f"{name}_PanBase", (0.58, 0.30, 0.028), (0.0, 0.0, 0.0), col_ink, mat_pan, bevel=0.006)
    attach_local(pan_base, root, (0.0, 0.04, 0.0))
    wall_l = add_box(f"{name}_WallL", (0.028, 0.30, 0.16), (0.0, 0.0, 0.0), col_ink, mat_pan, bevel=0.005)
    attach_local(wall_l, root, (-0.28, 0.04, 0.08))
    wall_r = add_box(f"{name}_WallR", (0.028, 0.30, 0.16), (0.0, 0.0, 0.0), col_ink, mat_pan, bevel=0.005)
    attach_local(wall_r, root, (0.28, 0.04, 0.08))
    wall_b = add_box(f"{name}_WallB", (0.58, 0.028, 0.16), (0.0, 0.0, 0.0), col_ink, mat_pan, bevel=0.005)
    attach_local(wall_b, root, (0.0, 0.18, 0.08))

    oil_slab = add_box(f"{name}_OilLayer", (0.52, 0.25, 0.09), (0.0, 0.0, 0.0), col_ink, mat_oil, bevel=0.006)
    attach_local(oil_slab, root, (0.0, 0.035, 0.065))

    base_objs = [bg_card, coil, pan_base, wall_l, wall_r, wall_b, oil_slab]

    # Sinking blue water droplets (`f282..f560`) + downward density arrows
    water_drops = []
    for idx, wx in enumerate((-0.10, -0.04, 0.02, 0.08, -0.01, 0.05)):
        wd = add_sphere(f"{name}_WaterSink_{idx}", 0.022, (0.0, 0.0, 0.0), col_ink, mat_water, scale=(1.0, 0.7, 1.25), subsurf=0)
        attach_local(wd, root, (wx, -0.105, 0.22))
        water_drops.append((wd, wx))

    dn_arrows = []
    for sx in (-0.18, 0.18):
        ar_s = add_box(f"{name}_DnShaft_{sx}", (0.020, 0.020, 0.10), (0.0, 0.0, 0.0), col_vfx, mat_arrow_dn)
        ar_t = add_cone(f"{name}_DnTip_{sx}", 0.036, 0.002, 0.055, (0.0, 0.0, 0.0), col_vfx, mat_arrow_dn, verts=12)
        attach_local(ar_s, root, (sx, -0.06, 0.24))
        attach_local(ar_t, root, (sx, -0.06, 0.16), (math.radians(180), 0.0, 0.0))
        dn_arrows.extend([ar_s, ar_t])

    # Expanding 1,700x steam dome (`f520..f749`) + fiery upward eruption plume (`f635..f749`)
    steam_dome = add_sphere(f"{name}_SteamFlash", 0.075, (0.0, 0.0, 0.0), col_vfx, mat_steam, scale=(1.35, 0.70, 0.95), subsurf=0)
    attach_local(steam_dome, root, (0.0, -0.085, 0.065))

    plume_root = add_empty(f"{name}_PlumeRoot", (0.0, 0.0, 0.0), col_vfx, parent=root)
    attach_local(plume_root, root, (0.0, 0.0, 0.09))
    plume_main = add_cone(f"{name}_ExplosionCone", 0.06, 0.17, 0.34, (0.0, 0.0, 0.0), col_vfx, mat_burst, verts=16)
    attach_local(plume_main, plume_root, (0.0, 0.0, 0.17))
    plume_top = add_sphere(f"{name}_ExplosionTop", 0.15, (0.0, 0.0, 0.0), col_vfx, mat_burst, scale=(1.15, 0.85, 0.9), subsurf=0)
    attach_local(plume_top, plume_root, (0.0, 0.0, 0.34))
    plume_hot = add_sphere(f"{name}_ExplosionCore", 0.09, (0.0, 0.0, 0.0), col_vfx, mat_burst_hot, scale=(1.0, 0.85, 1.0), subsurf=0)
    attach_local(plume_hot, plume_root, (0.0, -0.06, 0.27))

    up_arrows = []
    for sx in (-0.21, 0.21):
        ar_s = add_box(f"{name}_UpShaft_{sx}", (0.022, 0.022, 0.12), (0.0, 0.0, 0.0), col_vfx, mat_arrow_up)
        ar_t = add_cone(f"{name}_UpTip_{sx}", 0.040, 0.002, 0.065, (0.0, 0.0, 0.0), col_vfx, mat_arrow_up, verts=12)
        attach_local(ar_s, root, (sx, -0.06, 0.24))
        attach_local(ar_t, root, (sx, -0.06, 0.33))
        up_arrows.extend([ar_s, ar_t])

    plume_objs = [plume_main, plume_top, plume_hot] + up_arrows

    return {
        "root": root,
        "base_objs": base_objs,
        "coil": coil,
        "water_drops": water_drops,
        "water_objs": [w[0] for w in water_drops] + dn_arrows,
        "steam_dome": steam_dome,
        "plume_root": plume_root,
        "plume_objs": plume_objs,
        "mat_coil": mat_coil,
    }


def build_badge_x(name, loc, col_ink):
    """Chunky beveled 3D Red X alert badge."""
    root = add_empty(name, loc, col_ink)
    mat_x = make_toon_v2_mat(f"{name}_Mat", (0.96, 0.24, 0.24), (0.68, 0.12, 0.14), rim_strength=0.22)
    b1 = add_box(f"{name}_A", (0.28, 0.055, 0.062), (0.0, 0.0, 0.0), col_ink, mat_x, bevel=0.008)
    b2 = add_box(f"{name}_B", (0.28, 0.055, 0.062), (0.0, 0.0, 0.0), col_ink, mat_x, bevel=0.008)
    attach_local(b1, root, (0.0, 0.0, 0.0), (0.0, math.radians(45), 0.0))
    attach_local(b2, root, (0.0, 0.0, 0.0), (0.0, math.radians(-45), 0.0))
    return root, [b1, b2]


def build_badge_ok(name, loc, col_ink):
    """Chunky beveled 3D Green Checkmark badge."""
    root = add_empty(name, loc, col_ink)
    mat_ok = make_toon_v2_mat(f"{name}_Mat", (0.24, 0.88, 0.42), (0.12, 0.58, 0.24), rim_strength=0.22)
    b1 = add_box(f"{name}_Short", (0.12, 0.055, 0.058), (0.0, 0.0, 0.0), col_ink, mat_ok, bevel=0.008)
    b2 = add_box(f"{name}_Long", (0.24, 0.055, 0.058), (0.0, 0.0, 0.0), col_ink, mat_ok, bevel=0.008)
    attach_local(b1, root, (-0.055, 0.0, -0.020), (0.0, math.radians(42), 0.0))
    attach_local(b2, root, (0.045, 0.0, 0.025), (0.0, math.radians(-46), 0.0))
    return root, [b1, b2]


def build_scene():
    clear_scene()
    scene, col_ink, _col_soft_ink, col_vfx = setup_bru3d_render_v2(
        width=1080,
        height=1920,
        fps=FPS,
        total_frames=TOTAL_FRAMES,
        ink_thickness=2.2,
        soft_ink_thickness=1.05,
        world_color=(0.70, 0.78, 0.84),
    )

    # ------------------------------------------------------------------
    # 1. Centered Modern 3D Kitchen + 3-Point & Dynamic Fire Lighting
    # ------------------------------------------------------------------
    mat_floor = make_wood_floor_mat("KitchenFloor", (0.76, 0.63, 0.48), (0.70, 0.57, 0.43), (0.48, 0.38, 0.29), scale=3.0)
    mat_wall = make_toon_v2_mat("KitchenWall", (0.94, 0.94, 0.90), (0.76, 0.78, 0.80), rim_strength=0.08)
    mat_tile = make_toon_v2_mat("SubwayTile", (0.86, 0.92, 0.91), (0.64, 0.72, 0.74), rim_strength=0.10, spec_strength=0.18)
    mat_cab = make_toon_v2_mat("CabinetSage", (0.36, 0.54, 0.56), (0.22, 0.35, 0.39), rim_strength=0.16)
    mat_cab_door = make_toon_v2_mat("CabinetDoor", (0.42, 0.61, 0.63), (0.26, 0.40, 0.44), rim_strength=0.18)
    mat_counter = make_toon_v2_mat("ButcherCounter", (0.84, 0.69, 0.52), (0.62, 0.48, 0.34), rim_strength=0.16, spec_strength=0.10)
    mat_hood = make_toon_v2_mat("RangeHood", (0.82, 0.85, 0.89), (0.56, 0.60, 0.68), rim_strength=0.22, spec_strength=0.28)
    mat_brass = make_toon_v2_mat("BrassPull", (0.92, 0.74, 0.34), (0.62, 0.46, 0.16), rim_strength=0.20, spec_strength=0.35)
    mat_oak = make_toon_v2_mat("OakShelf", (0.78, 0.60, 0.40), (0.55, 0.40, 0.25), rim_strength=0.16)

    add_box("FloorSlab", (8.0, 8.0, 0.10), (0.0, 0.0, -0.05), col_vfx, mat_floor)
    add_box("CeilingSlab", (8.0, 8.0, 0.12), (0.0, 0.0, 2.92), col_vfx, mat_wall)
    add_box("BackWall", (8.0, 0.16, 3.6), (0.0, 1.22, 1.75), col_ink, mat_wall)
    add_box("LeftWall", (0.16, 6.0, 3.6), (-1.75, -0.5, 1.75), col_ink, mat_wall)
    add_box("RightWall", (0.16, 6.0, 3.6), (1.75, -0.5, 1.75), col_ink, mat_wall)
    add_box("Baseboard", (8.0, 0.04, 0.10), (0.0, 1.13, 0.05), col_ink, mat_wall)
    add_box("TileBacksplash", (2.60, 0.03, 0.72), (0.0, 1.13, 1.22), col_ink, mat_tile, bevel=0.004)

    add_box("CabLeft", (0.88, 0.62, 0.82), (-0.74, 0.83, 0.41), col_ink, mat_cab, bevel=0.008)
    add_box("CounterLeft", (0.92, 0.66, 0.045), (-0.75, 0.81, 0.842), col_ink, mat_counter, bevel=0.008)
    add_box("DoorLeft1", (0.36, 0.025, 0.64), (-0.96, 0.515, 0.41), col_ink, mat_cab_door, bevel=0.006)
    add_box("DoorLeft2", (0.36, 0.025, 0.64), (-0.52, 0.515, 0.41), col_ink, mat_cab_door, bevel=0.006)

    add_box("CabRight", (0.88, 0.62, 0.82), (0.74, 0.83, 0.41), col_ink, mat_cab, bevel=0.008)
    add_box("CounterRight", (0.92, 0.66, 0.045), (0.75, 0.81, 0.842), col_ink, mat_counter, bevel=0.008)
    add_box("DoorRight1", (0.36, 0.025, 0.64), (0.52, 0.515, 0.41), col_ink, mat_cab_door, bevel=0.006)
    add_box("DoorRight2", (0.36, 0.025, 0.64), (0.96, 0.515, 0.41), col_ink, mat_cab_door, bevel=0.006)

    for hx in (-0.82, -0.66, 0.66, 0.82):
        add_box(f"Pull_{hx}", (0.018, 0.024, 0.11), (hx, 0.495, 0.60), col_ink, mat_brass, bevel=0.003)

    add_box("HoodChimney", (0.28, 0.24, 0.85), (0.0, 0.98, 2.24), col_ink, mat_hood, bevel=0.01)
    add_cone("HoodCanopy", 0.38, 0.18, 0.28, (0.0, 0.84, 1.72), col_ink, mat_hood, rot=(0.0, 0.0, math.radians(45)), verts=4)
    add_box("KitchenShelf", (0.68, 0.22, 0.032), (-0.78, 1.02, 1.54), col_ink, mat_oak, bevel=0.006)

    def _add_light(name, ltype, energy, loc, rot_deg, color, size=1.0, shadow=False):
        ld = bpy.data.lights.new(name, type=ltype)
        ld.energy = energy
        ld.color = color
        if ltype == "SUN":
            ld.angle = math.radians(2.2)
        elif ltype == "AREA":
            ld.size = size
        elif ltype == "POINT":
            ld.shadow_soft_size = size
        if shadow and hasattr(ld, "use_shadow"):
            ld.use_shadow = True
            if hasattr(ld, "use_contact_shadow"):
                ld.use_contact_shadow = True
                ld.contact_shadow_distance = 0.22
                ld.contact_shadow_thickness = 0.08
        lo = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(lo)
        lo.location = loc
        lo.rotation_euler = tuple(math.radians(a) for a in rot_deg)
        return lo, ld

    _sun_obj, sun_data = _add_light("KeySun", "SUN", 2.3, (1.8, -2.5, 3.2), (48, 12, 30), (1.0, 0.96, 0.88), shadow=True)
    _ov_obj, ov_data = _add_light("CeilingFill", "AREA", 52.0, (0.0, 0.0, 2.55), (0, 0, 0), (1.0, 0.96, 0.92), size=2.8)
    _fill_obj, fill_data = _add_light("CoolFill", "AREA", 36.0, (-2.2, -1.6, 1.5), (65, 0, -45), (0.76, 0.88, 1.0), size=3.2)
    _rim_obj, rim_data = _add_light("WarmRim", "AREA", 110.0, (1.45, 0.88, 2.10), (-42, 0, 145), (1.0, 0.90, 0.72), size=1.4)
    _fire_obj, fire_l_data = _add_light("FirePoint", "POINT", 24.0, (-0.12, 0.62, 1.05), (0, 0, 0), (1.0, 0.44, 0.12), size=0.18)

    # ------------------------------------------------------------------
    # 2. Automatic 15 CC0 Sculpted Kitchen & Fire-Safety Assets (Poly Haven)
    # ------------------------------------------------------------------
    import_polyhaven_asset("electric_stove", "PolyStove", col_ink, target_dim=0.86, dim_axis="z", loc=(0.0, 0.78, 0.0), rot_z_deg=0.0, rim_strength=0.18, spec_strength=0.12)
    import_polyhaven_asset("brass_pan_01", "PolyPan", col_ink, target_dim=0.40, dim_axis="max", loc=(-0.12, 0.66, 0.862), rot_z_deg=26.0, tint_rgb=(0.45, 0.42, 0.44), rim_strength=0.22, spec_strength=0.22)
    import_polyhaven_asset("pot_enamel_01", "PolyPot", col_ink, target_dim=0.22, dim_axis="max", loc=(0.12, 0.86, 0.862), rot_z_deg=-20.0, rim_strength=0.22, spec_strength=0.25)
    jug = import_polyhaven_asset("jug_01", "PolyWaterJug", col_ink, target_dim=0.22, dim_axis="z", loc=(0.44, 0.66, 0.864), rot_z_deg=180.0, tint_rgb=(0.88, 0.95, 1.0), rim_strength=0.26, spec_strength=0.35)
    import_polyhaven_asset("vintage_electric_kettle", "PolyKettle", col_ink, target_dim=0.25, dim_axis="z", loc=(0.82, 0.76, 0.864), rot_z_deg=-25.0, rim_strength=0.22, spec_strength=0.28)
    import_polyhaven_asset("korean_fire_extinguisher_01", "PolyExtinguisher", col_ink, target_dim=0.52, dim_axis="z", loc=(0.94, 0.36, 0.0), rot_z_deg=-20.0, rim_strength=0.24, spec_strength=0.22)
    import_polyhaven_asset("fire_alarm", "PolyFireAlarm", col_ink, target_dim=0.18, dim_axis="z", loc=(0.74, 1.13, 1.88), rot_z_deg=0.0, rim_strength=0.22, spec_strength=0.25)
    import_polyhaven_asset("wooden_cutting_board", "PolyBoard", col_ink, target_dim=0.38, dim_axis="x", loc=(-0.68, 0.70, 0.864), rot_z_deg=8.0, rim_strength=0.16)
    import_polyhaven_asset("wooden_spoon", "PolySpoon", col_ink, target_dim=0.25, dim_axis="y", loc=(-0.56, 0.66, 0.902), rot_z_deg=35.0, rim_strength=0.16)
    import_polyhaven_asset("yellow_onion", "PolyOnion", col_ink, target_dim=0.08, dim_axis="max", loc=(-0.78, 0.68, 0.902), rot_z_deg=12.0, rim_strength=0.20)
    import_polyhaven_asset("food_apple_01", "PolyApple", col_ink, target_dim=0.085, dim_axis="max", loc=(-0.64, 0.76, 0.902), rot_z_deg=-22.0, rim_strength=0.22, spec_strength=0.22)
    import_polyhaven_asset("wooden_bowl_01", "PolyBowl", col_ink, target_dim=0.22, dim_axis="x", loc=(-0.98, 0.72, 0.864), rot_z_deg=0.0, rim_strength=0.18)
    import_polyhaven_asset("potted_plant_04", "PolyPlant", col_ink, target_dim=0.24, dim_axis="z", loc=(-0.78, 1.02, 1.556), rot_z_deg=-15.0, rim_strength=0.20)
    import_polyhaven_asset("wall_clock", "PolyClock", col_ink, target_dim=0.30, dim_axis="z", loc=(-0.76, 1.11, 1.98), rot_z_deg=0.0, rim_strength=0.16, spec_strength=0.0)
    lamp = import_polyhaven_asset("modern_ceiling_lamp_01", "PolyLamp", col_ink, target_dim=0.72, dim_axis="z", loc=(0.0, 0.14, 2.16), rot_z_deg=0.0, rim_strength=0.18, spec_strength=0.28)

    # ------------------------------------------------------------------
    # 3. Beat-Specific Animated VFX & Educational Props
    # ------------------------------------------------------------------
    fire = build_stylized_fire("GreaseFire", (-0.12, 0.62, 0.885), col_vfx, scale_base=1.18)
    fireball = build_fireball_plume("FireballPlume", (-0.12, 0.62, 0.89), col_vfx)
    cutaway = build_animated_cutaway_stage("OilWaterCutaway", (0.0, 0.0, 1.54), col_ink, col_vfx)

    # Secondary flames spreading onto shelf, hood/ceiling & right cabinet during Beat 6 (`f840..985`)
    fire_shelf = build_stylized_fire("ShelfFire", (-0.72, 0.90, 1.56), col_vfx, scale_base=1.18)
    fire_hood = build_stylized_fire("HoodFire", (0.0, 0.72, 2.02), col_vfx, scale_base=1.35)
    fire_cab_r = build_stylized_fire("RightCabFire", (0.62, 0.78, 0.90), col_vfx, scale_base=1.05)
    spread_objs = fire_shelf["objs"] + fire_hood["objs"] + fire_cab_r["objs"]

    # 14 flying burning oil droplets during Beat 6 explosion (`f750..985`)
    mat_fire_drop = make_lamp_shade_mat("FlyingOilDropMat", (1.0, 0.45, 0.08), strength=1.22)
    fly_drops = []
    for i in range(14):
        ang = i * (2.0 * math.pi / 14.0)
        fd = add_sphere(f"FlyOilDrop_{i}", 0.022, (-0.12, 0.62, 0.95), col_vfx, mat_fire_drop, scale=(0.8, 0.8, 1.4), subsurf=0)
        fly_drops.append((fd, ang, 0.35 + (i % 5) * 0.12))

    # Water stream pouring from `jug_01` (`f95..259`)
    mat_water = make_lamp_shade_mat("WaterDropMat", (0.18, 0.72, 1.0), strength=1.25)
    pour_drops = [add_sphere(f"PourDrop_{i}", 0.020, (-0.10, 0.62, 1.10), col_vfx, mat_water, scale=(0.8, 0.8, 1.45), subsurf=0) for i in range(6)]

    # Pulsing red alarm waves around PolyFireAlarm
    mat_alarm = make_emissive_mix_mat("AlarmWaveMat", (1.0, 0.16, 0.14), alpha=0.80, strength=1.35)
    alarm_rings = [
        add_torus(f"AlarmRing_{i}", 0.13 + i * 0.06, 0.010, (0.74, 1.08, 1.97), col_vfx, mat_alarm, rot=(math.radians(90), 0.0, 0.0))
        for i in range(2)
    ]

    # Beat 7 (`f986..1085`): Animated Wet Towel + sideways oil splatter droplets
    towel_root = add_empty("WetTowelRoot", (0.28, 0.60, 1.32), col_ink)
    mat_towel = make_toon_v2_mat("WetTowelMat", (0.48, 0.76, 0.96), (0.28, 0.50, 0.72), rim_strength=0.22)
    towel_body = add_box("WetTowelBody", (0.28, 0.22, 0.032), (0.0, 0.0, 0.0), col_ink, mat_towel, bevel=0.010)
    towel_fold = add_box("WetTowelFold", (0.24, 0.18, 0.026), (0.0, 0.0, 0.0), col_ink, mat_towel, bevel=0.008)
    attach_local(towel_body, towel_root, (0.0, 0.0, 0.0))
    attach_local(towel_fold, towel_root, (0.0, 0.01, 0.022))
    towel_objs = [towel_body, towel_fold]
    for di, (dx, dy) in enumerate([(-0.08, -0.05), (0.02, 0.04), (0.09, -0.04), (-0.04, 0.06)]):
        tb = add_sphere(f"TowelBead_{di}", 0.014, (0.0, 0.0, 0.0), col_ink, mat_water, subsurf=0)
        attach_local(tb, towel_root, (dx, dy, 0.025))
        towel_objs.append(tb)

    splatter_drops = []
    for si in range(10):
        ang = math.radians(-160 + si * 34)
        sd = add_sphere(f"SplatterOil_{si}", 0.018, (-0.12, 0.62, 0.92), col_vfx, mat_fire_drop, scale=(0.8, 1.4, 0.8), subsurf=0)
        splatter_drops.append((sd, ang))

    # Beat 8 (`f1086..1159`): Stove front burner LED indicator + Green rotation arrow
    mat_led_on = make_lamp_shade_mat("BurnerLEDOn", (1.0, 0.18, 0.12), strength=1.50)
    mat_green = make_toon_v2_mat("DialGreenMat", (0.24, 0.90, 0.44), (0.12, 0.58, 0.24), rim_strength=0.22)
    burner_led = add_sphere("BurnerStatusLED", 0.014, (-0.16, 0.46, 0.775), col_vfx, mat_led_on, subsurf=0)
    dial_arrow_root = add_empty("DialArrowRoot", (-0.09, 0.43, 0.792), col_ink)
    dial_arc = add_torus("DialTurnArc", 0.034, 0.007, (0.0, 0.0, 0.0), col_ink, mat_green, rot=(math.radians(90), 0.0, 0.0))
    dial_tip = add_cone("DialTurnTip", 0.015, 0.002, 0.028, (0.0, 0.0, 0.0), col_ink, mat_green, verts=12)
    attach_local(dial_arc, dial_arrow_root, (0.0, 0.0, 0.0), (math.radians(90), 0.0, 0.0))
    attach_local(dial_tip, dial_arrow_root, (-0.034, 0.0, 0.010), (math.radians(180), 0.0, 0.0))
    dial_objs = [dial_arc, dial_tip]

    # Beat 9-11 (`f1160..1406`): Sliding Chrome Smother Lid + O2 deflection + Extinguisher Halo + Cool Wisps
    mat_lid = make_toon_v2_mat("SmotherLidMat", (0.80, 0.84, 0.90), (0.50, 0.54, 0.64), rim_strength=0.26, spec_strength=0.35)
    lid_root = add_empty("SmotherLidRoot", (0.30, 0.62, 0.94), col_ink)
    lid_disc = add_cylinder("SmotherLidDisc", 0.165, 0.016, (0.0, 0.0, 0.0), col_ink, mat_lid, verts=28, bevel=0.004)
    lid_handle = add_torus("SmotherLidHandle", 0.036, 0.009, (0.0, 0.0, 0.0), col_ink, mat_lid, rot=(math.radians(90), 0.0, 0.0))
    attach_local(lid_disc, lid_root, (0.0, 0.0, 0.0))
    attach_local(lid_handle, lid_root, (0.0, 0.0, 0.024), (math.radians(90), 0.0, 0.0))
    lid_objs = [lid_disc, lid_handle]

    mat_o2 = make_toon_v2_mat("O2ArrowMat", (0.14, 0.72, 0.98), (0.06, 0.44, 0.72), rim_strength=0.20)
    o2_arrows = []
    for ox in (-0.24, 0.0, 0.24):
        oroot = add_empty(f"O2Arrow_{ox}", (-0.12 + ox, 0.62, 1.12), col_ink)
        os_ = add_box(f"O2Shaft_{ox}", (0.016, 0.016, 0.065), (0.0, 0.0, 0.0), col_ink, mat_o2)
        ot_ = add_cone(f"O2Tip_{ox}", 0.028, 0.002, 0.045, (0.0, 0.0, 0.0), col_ink, mat_o2, verts=12)
        attach_local(os_, oroot, (0.0, 0.0, 0.04))
        attach_local(ot_, oroot, (0.0, 0.0, 0.0), (math.radians(180), 0.0, 0.0))
        o2_arrows.append((oroot, os_, ot_, ox))
    o2_objs = [o for tup in o2_arrows for o in (tup[1], tup[2])]

    mat_halo = make_emissive_mix_mat("ExtinguisherHaloMat", (0.28, 0.95, 0.48), alpha=0.78, strength=1.35)
    ext_halo = add_torus("ExtinguisherHalo", 0.24, 0.018, (0.94, 0.36, 0.025), col_vfx, mat_halo)

    mat_wisp = make_emissive_mix_mat("CoolWispMat", (0.88, 0.96, 1.0), alpha=0.40, strength=1.02)
    cool_wisps = [add_sphere(f"CoolWisp_{wi}", 0.026 + wi * 0.006, (-0.12, 0.62, 0.98 + wi * 0.06), col_vfx, mat_wisp, scale=(1.2, 1.0, 0.7), subsurf=0) for wi in range(4)]

    red_x_root, red_x_objs = build_badge_x("KitchenRedX", (0.44, 0.64, 1.24), col_ink)
    green_ok_root, green_ok_objs = build_badge_ok("KitchenGreenOK", (-0.12, 0.62, 1.24), col_ink)

    # ------------------------------------------------------------------
    # 4. Exact Audio-Locked Beat Animation (`TOTAL_FRAMES = 1406`)
    # ------------------------------------------------------------------
    bg_node = scene.world.node_tree.nodes.get("Background")

    dense_frames = set(range(1, TOTAL_FRAMES + 1, 4)) | set(PREVIEW_FRAMES) | {
        1, 87, 88, 158, 162, 259, 260, 282, 461, 462, 648, 749, 750, 852,
        985, 986, 1026, 1085, 1086, 1113, 1159, 1160, 1225, 1280, 1281, 1332, 1333, 1406,
    }

    for f in sorted(dense_frames):
        in_cutaway = (260 <= f <= 749)
        in_boom1 = (159 <= f <= 259)
        in_boom2 = (750 <= f <= 985)
        in_explosion = in_boom1 or in_boom2

        # World & 3-point lighting mood
        if in_cutaway:
            sun_e, ov_e, fill_e, rim_e, fire_e = 0.05, 6.0, 12.0, 140.0, 14.0
            bg_col = (0.10, 0.14, 0.22)
        elif in_boom1:
            u_e = smooth_step((f - 159) / 10.0)
            sun_e, ov_e, fill_e = lerp(2.3, 0.70, u_e), lerp(52.0, 26.0, u_e), lerp(36.0, 22.0, u_e)
            rim_e = lerp(110.0, 290.0, u_e)
            fire_e = lerp(28.0, 185.0, u_e) * (0.9 + 0.15 * abs(math.sin(f * 0.75)))
            bg_col = lerp3((0.70, 0.78, 0.84), (0.36, 0.28, 0.28), u_e)
        elif in_boom2:
            u_e = smooth_step((f - 750) / 12.0)
            sun_e, ov_e, fill_e = lerp(1.2, 0.55, u_e), lerp(34.0, 22.0, u_e), lerp(28.0, 18.0, u_e)
            rim_e = 310.0
            fire_e = 195.0 * (0.9 + 0.15 * abs(math.sin(f * 0.80)))
            bg_col = (0.34, 0.25, 0.26)
        elif f >= 1225:
            sun_e, ov_e, fill_e, rim_e, fire_e = 2.5, 58.0, 38.0, 125.0, 0.0
            bg_col = (0.74, 0.84, 0.88)
        else:
            sun_e, ov_e, fill_e, rim_e = 2.3, 52.0, 36.0, 110.0
            fire_e = 24.0 + 10.0 * abs(math.sin(f * 0.65)) if f <= 1224 else 4.0
            bg_col = (0.70, 0.78, 0.84)

        for ld, en in ((sun_data, sun_e), (ov_data, ov_e), (fill_data, fill_e), (rim_data, rim_e), (fire_l_data, fire_e)):
            ld.energy = en
            ld.keyframe_insert(data_path="energy", frame=f)
        if bg_node:
            bg_node.inputs["Color"].default_value = (*bg_col, 1.0)
            bg_node.inputs["Color"].keyframe_insert(data_path="default_value", frame=f)

        set_hidden(lamp["meshes"], in_cutaway, f)

        # Pan Grease Fire (`f1..164`, `f986..1225`, choked cleanly across `1175..1225`)
        fire_vis = (f <= 165) or (986 <= f <= 1224)
        set_hidden(fire["objs"], not fire_vis, f)
        if fire_vis:
            choke = 1.0 if f < 1175 else max(0.05, 1.0 - smooth_step((f - 1175) / 48.0))
            fsc = (0.92 + 0.16 * abs(math.sin(f * 0.55))) * choke
            fire["root"].scale = (fsc, fsc, (0.88 + 0.24 * abs(math.cos(f * 0.72))) * choke)
            fire["root"].rotation_euler = (0.0, 0.0, 0.08 * math.sin(f * 0.4))
            fire["root"].keyframe_insert(data_path="scale", frame=f)
            fire["root"].keyframe_insert(data_path="rotation_euler", frame=f)

        # Jug lift & pour into pan (`f88..f160`)
        if 88 <= f <= 164:
            u_pour = smooth_step((f - 88) / 18.0)
            jug["root"].location = lerp3((0.44, 0.66, 0.864), (0.14, 0.62, 1.18), u_pour)
            jug["root"].rotation_euler = (math.radians(-62.0 * u_pour), 0.0, math.radians(lerp(180.0, 90.0, u_pour)))
        else:
            jug["root"].location = (0.44, 0.66, 0.864)
            jug["root"].rotation_euler = (0.0, 0.0, math.radians(180.0))
        jug["root"].keyframe_insert(data_path="location", frame=f)
        jug["root"].keyframe_insert(data_path="rotation_euler", frame=f)

        pour_vis = (102 <= f <= 160)
        set_hidden(pour_drops, not pour_vis, f)
        if pour_vis:
            for idx, dp in enumerate(pour_drops):
                cyc = ((f - 102 + idx * 3) % 12) / 12.0
                dp.location = (-0.08 + 0.03 * math.sin(idx), 0.62, 1.12 - 0.24 * cyc)
                dp.keyframe_insert(data_path="location", frame=f)

        # Fireball explosion plume + alarm waves (`f159..259` and `f750..985`)
        set_hidden(fireball["objs"], not in_explosion, f)
        set_hidden(alarm_rings, not in_explosion, f)
        if in_explosion:
            t_start = 159 if in_boom1 else 750
            u_b = smooth_step((f - t_start) / 12.0)
            damp = 1.0 if f < 840 else (1.0 - 0.45 * smooth_step((f - 840) / 36.0))
            fb_sc = (0.28 + 0.94 * u_b + 0.04 * math.sin(f * 0.6)) * damp
            fireball["root"].scale = (fb_sc, fb_sc, fb_sc * (0.96 + 0.08 * math.cos(f * 0.5)))
            fireball["root"].rotation_euler = (0.0, 0.0, 0.06 * math.sin(f * 0.35))
            fireball["root"].keyframe_insert(data_path="scale", frame=f)
            fireball["root"].keyframe_insert(data_path="rotation_euler", frame=f)
            for ridx, ar in enumerate(alarm_rings):
                ap = 0.85 + 0.36 * abs(math.sin(f * 0.45 + ridx * 1.4))
                ar.scale = (ap, ap, ap)
                ar.keyframe_insert(data_path="scale", frame=f)

        # Beat 6 (`f750..985`): Flying burning oil droplets + cabinet/hood spreading flames (`f840..985`)
        set_hidden([t[0] for t in fly_drops], not in_boom2, f)
        if in_boom2:
            for idx, (fd, ang, rad) in enumerate(fly_drops):
                cyc = ((f - 750 + idx * 5) % 34) / 34.0
                u_arc = smooth_step(cyc)
                fd.location = (-0.12 + rad * u_arc * math.cos(ang), 0.62 + 0.25 * math.sin(ang) * u_arc, 0.95 + 1.35 * cyc - 0.30 * cyc * cyc)
                fd.keyframe_insert(data_path="location", frame=f)

        sp_vis = (840 <= f <= 985)
        set_hidden(spread_objs, not sp_vis, f)
        if sp_vis:
            ssc = smooth_step((f - 840) / 16.0) * (0.92 + 0.14 * abs(math.sin(f * 0.6)))
            for fr_root in (fire_shelf["root"], fire_hood["root"], fire_cab_r["root"]):
                fr_root.scale = (ssc, ssc, ssc)
                fr_root.keyframe_insert(data_path="scale", frame=f)

        # Beat 3-5 (`f260..749`): Animated Dark Science Cutaway
        set_hidden(cutaway["base_objs"], not in_cutaway, f)
        set_hidden(cutaway["water_objs"], not (in_cutaway and f <= 620), f)
        if in_cutaway and f <= 620:
            for idx, (wd, wx) in enumerate(cutaway["water_drops"]):
                u_sink = smooth_step((f - (280 + idx * 14)) / 65.0)
                wd.location = (wx, -0.105, lerp(0.22, 0.032, u_sink))
                wd.keyframe_insert(data_path="location", frame=f)

        steam_vis = in_cutaway and (f >= 485)
        set_hidden([cutaway["steam_dome"]], not steam_vis, f)
        if steam_vis:
            u_st = smooth_step((f - 485) / 165.0)
            st_sc = 0.35 + 1.55 * u_st
            cutaway["steam_dome"].scale = (st_sc * 1.25, st_sc * 0.70, st_sc * 0.95)
            cutaway["steam_dome"].keyframe_insert(data_path="scale", frame=f)

        plume_vis = in_cutaway and (f >= 605)
        set_hidden(cutaway["plume_objs"], not plume_vis, f)
        if plume_vis:
            u_pl = smooth_step((f - 605) / 55.0)
            psc = 0.15 + 0.95 * u_pl + 0.04 * abs(math.sin(f * 0.5))
            cutaway["plume_root"].scale = (psc, psc, psc)
            cutaway["plume_root"].keyframe_insert(data_path="scale", frame=f)

        # Beat 7 (`f986..1085`): Wet Towel Slap + Sideways Splatter
        tw_vis = (986 <= f <= 1085)
        set_hidden(towel_objs, not tw_vis, f)
        if tw_vis:
            u_tw = smooth_step((f - 992) / 30.0)
            towel_root.location = lerp3((0.32, 0.58, 1.32), (-0.12, 0.62, 0.98), u_tw)
            towel_root.rotation_euler = (math.radians(-18.0 + 32.0 * u_tw), math.radians(15.0 * (1.0 - u_tw)), 0.0)
            towel_root.keyframe_insert(data_path="location", frame=f)
            towel_root.keyframe_insert(data_path="rotation_euler", frame=f)

        spl_vis = (1022 <= f <= 1085)
        set_hidden([t[0] for t in splatter_drops], not spl_vis, f)
        if spl_vis:
            for idx, (sd, ang) in enumerate(splatter_drops):
                cyc = ((f - 1022 + idx * 2) % 24) / 24.0
                sd.location = (-0.12 + 0.52 * cyc * math.cos(ang), 0.62 + 0.35 * cyc * math.sin(ang), 0.92 + 0.28 * math.sin(cyc * math.pi))
                sd.keyframe_insert(data_path="location", frame=f)

        # Beat 8 (`f1086..1159`): Turn Off Burner Dial + Red LED turns dark
        dial_vis = (1086 <= f <= 1159)
        set_hidden([burner_led] + dial_objs, not dial_vis, f)
        if dial_vis:
            u_turn = smooth_step((f - 1098) / 20.0)
            dial_arrow_root.rotation_euler = (0.0, math.radians(-115.0 * u_turn), 0.0)
            dial_arrow_root.keyframe_insert(data_path="rotation_euler", frame=f)
            led_on = (f < 1113)
            mat_led_on.node_tree.nodes["EmisNode"].inputs["Strength"].default_value = 1.60 if led_on else 0.08
            mat_led_on.node_tree.nodes["EmisNode"].inputs["Strength"].keyframe_insert(data_path="default_value", frame=f)

        # Beat 9-11 (`f1160..1406`): Sliding Metal Lid + O2 Deflect + Extinguisher Halo + Cool Wisps
        lid_vis = (f >= 1160)
        set_hidden(lid_objs, not lid_vis, f)
        if lid_vis:
            u_sl = smooth_step((f - 1172) / 48.0)
            lid_root.location = (lerp(0.32, -0.12, u_sl), 0.62, lerp(0.95, 0.905, smooth_step((f - 1210) / 15.0)))
            lid_root.keyframe_insert(data_path="location", frame=f)

        o2_vis = (1205 <= f <= 1280)
        set_hidden(o2_objs, not o2_vis, f)
        if o2_vis:
            for oroot, _, _, ox in o2_arrows:
                u_bounce = smooth_step((f - 1225) / 28.0) if f >= 1225 else 0.0
                oroot.location = (-0.12 + ox * (1.0 + 0.55 * u_bounce), 0.62, 1.06 + 0.16 * u_bounce)
                oroot.keyframe_insert(data_path="location", frame=f)

        halo_vis = (1281 <= f <= 1335)
        set_hidden([ext_halo], not halo_vis, f)
        if halo_vis:
            hs = 0.95 + 0.18 * abs(math.sin(f * 0.35))
            ext_halo.scale = (hs, hs, hs)
            ext_halo.keyframe_insert(data_path="scale", frame=f)

        wisp_vis = (f >= 1330)
        set_hidden(cool_wisps, not wisp_vis, f)
        if wisp_vis:
            for wi, cw in enumerate(cool_wisps):
                cyc = ((f - 1330 + wi * 9) % 45) / 45.0
                cw.location = (-0.12 + 0.03 * math.sin(f * 0.15 + wi), 0.62, 0.96 + 0.28 * cyc)
                cw.keyframe_insert(data_path="location", frame=f)

        # Badges
        show_x = (1 <= f <= 155) or (995 <= f <= 1082)
        set_hidden(red_x_objs, not show_x, f)
        if show_x:
            rx_loc = (0.44, 0.64, 1.24) if f <= 155 else (-0.12, 0.62, 1.28)
            red_x_root.location = rx_loc
            red_x_root.rotation_euler = (0.0, 0.0, 0.14 * math.sin(f * 0.22))
            red_x_root.keyframe_insert(data_path="location", frame=f)
            red_x_root.keyframe_insert(data_path="rotation_euler", frame=f)

        show_ok = (f >= 1225)
        set_hidden(green_ok_objs, not show_ok, f)
        if show_ok:
            ok_sc = smooth_step((f - 1225) / 14.0)
            green_ok_root.scale = (ok_sc, ok_sc, ok_sc)
            green_ok_root.keyframe_insert(data_path="scale", frame=f)

    # ------------------------------------------------------------------
    # 5. Kinetic 22-Segment Non-Stop Camera Choreography (`1..1406`)
    # ------------------------------------------------------------------
    cam_obj, cam_tgt = setup_vertical_camera("MainCam", lens=28.0, loc=(0.08, -2.02, 1.32), target=(0.0, 0.56, 0.92))

    cam_segments = [
        # Beat 1 (1..87): Wide opening kitchen orbit + push into burning pan
        {"start": 1, "end": 44, "type": "orbit", "center": (0.06, 0.64), "r0": 2.04, "r1": 1.76, "az0": 20.0, "az1": -10.0, "z0": 1.34, "z1": 1.24, "tgt0": (0.02, 0.58, 0.92), "tgt1": (0.06, 0.64, 0.98), "l0": 28.0, "l1": 32.0},
        {"start": 45, "end": 87, "type": "zoom", "p0": orbit_pos((0.06, 0.64), 1.76, -10.0, 1.24), "p1": (0.14, -0.78, 1.24), "tgt0": (0.06, 0.64, 0.98), "tgt1": (0.04, 0.64, 1.00), "l0": 32.0, "l1": 38.0},
        # Beat 2 (88..259): Whip onto water pouring into fire -> dramatic fireball blast pull-back
        {"start": 88, "end": 97, "type": "whip", "p0": (0.14, -0.78, 1.24), "p1": (0.24, -0.36, 1.22), "tgt0": (0.04, 0.64, 1.00), "tgt1": (0.02, 0.64, 1.00), "l0": 38.0, "l1": 39.0},
        {"start": 98, "end": 158, "type": "orbit", "center": (0.02, 0.64), "r0": 1.02, "r1": 0.90, "az0": 14.0, "az1": -14.0, "z0": 1.22, "z1": 1.14, "tgt0": (0.02, 0.64, 1.00), "tgt1": (-0.08, 0.64, 1.00), "l0": 39.0, "l1": 42.0},
        {"start": 159, "end": 208, "type": "zoom", "p0": orbit_pos((0.02, 0.64), 0.90, -14.0, 1.14), "p1": (-0.18, -1.86, 1.28), "tgt0": (-0.08, 0.64, 1.00), "tgt1": (0.04, 0.54, 1.16), "l0": 42.0, "l1": 27.5},
        {"start": 209, "end": 259, "type": "orbit", "center": (0.04, 0.54), "r0": 2.40, "r1": 2.48, "az0": -5.0, "az1": 16.0, "z0": 1.28, "z1": 1.36, "tgt0": (0.04, 0.54, 1.16), "tgt1": (0.06, 0.56, 1.22), "l0": 27.5, "l1": 27.0},
        # Beat 3-4 (260..461): Whip to Dark Science Cutaway -> water droplets sinking under oil
        {"start": 260, "end": 271, "type": "whip", "p0": orbit_pos((0.04, 0.54), 2.48, 16.0, 1.36), "p1": (0.0, -1.08, 1.72), "tgt0": (0.06, 0.56, 1.22), "tgt1": (0.0, 0.0, 1.70), "l0": 27.0, "l1": 42.0},
        {"start": 272, "end": 340, "type": "orbit", "center": (0.0, 0.0), "r0": 1.08, "r1": 0.98, "az0": 0.0, "az1": -10.0, "z0": 1.72, "z1": 1.70, "tgt0": (0.0, 0.0, 1.70), "tgt1": (0.0, 0.0, 1.64), "l0": 42.0, "l1": 44.0},
        {"start": 341, "end": 405, "type": "orbit", "center": (0.0, 0.0), "r0": 0.98, "r1": 0.92, "az0": -10.0, "az1": 10.0, "z0": 1.70, "z1": 1.66, "tgt0": (0.0, 0.0, 1.64), "tgt1": (0.0, 0.0, 1.60), "l0": 44.0, "l1": 46.0},
        {"start": 406, "end": 461, "type": "glide", "p0": orbit_pos((0.0, 0.0), 0.92, 10.0, 1.66), "p1": (-0.08, -0.96, 1.66), "tgt0": (0.0, 0.0, 1.60), "tgt1": (0.0, 0.0, 1.58), "l0": 46.0, "l1": 45.0},
        # Beat 5 (462..749): Tight coil glow -> 1,700x steam expansion eruption inside cutaway
        {"start": 462, "end": 540, "type": "orbit", "center": (0.0, 0.0), "r0": 0.96, "r1": 0.86, "az0": -5.0, "az1": 8.0, "z0": 1.66, "z1": 1.62, "tgt0": (0.0, 0.0, 1.58), "tgt1": (0.0, 0.0, 1.58), "l0": 45.0, "l1": 49.0},
        {"start": 541, "end": 647, "type": "orbit", "center": (0.0, 0.0), "r0": 0.86, "r1": 1.06, "az0": 8.0, "az1": -4.0, "z0": 1.62, "z1": 1.72, "tgt0": (0.0, 0.0, 1.58), "tgt1": (0.0, 0.0, 1.74), "l0": 49.0, "l1": 41.0},
        {"start": 648, "end": 749, "type": "zoom", "p0": orbit_pos((0.0, 0.0), 1.06, -4.0, 1.72), "p1": (0.04, -1.04, 1.74), "tgt0": (0.0, 0.0, 1.74), "tgt1": (0.0, 0.0, 1.74), "l0": 41.0, "l1": 40.0},
        # Beat 6 (750..985): Whip back to kitchen blast + flying oil droplets -> tilt up to cabinet & ceiling flames
        {"start": 750, "end": 760, "type": "whip", "p0": (0.04, -1.04, 1.74), "p1": (-0.18, -1.86, 1.24), "tgt0": (0.0, 0.0, 1.74), "tgt1": (0.06, 0.56, 1.20), "l0": 40.0, "l1": 27.5},
        {"start": 761, "end": 845, "type": "orbit", "center": (0.06, 0.56), "r0": 2.42, "r1": 2.24, "az0": -5.0, "az1": 18.0, "z0": 1.24, "z1": 1.36, "tgt0": (0.06, 0.56, 1.20), "tgt1": (0.04, 0.64, 1.34), "l0": 27.5, "l1": 28.0},
        {"start": 846, "end": 985, "type": "orbit", "center": (-0.04, 0.86), "r0": 2.46, "r1": 2.34, "az0": 12.0, "az1": -14.0, "z0": 1.44, "z1": 1.40, "tgt0": (0.04, 0.64, 1.34), "tgt1": (-0.04, 0.82, 1.48), "l0": 28.0, "l1": 28.0},
        # Beat 7 (986..1085): Whip to wet towel slap + sideways burning oil splatters
        {"start": 986, "end": 996, "type": "whip", "p0": orbit_pos((-0.06, 0.86), 2.34, -14.0, 1.40), "p1": (0.24, -0.46, 1.20), "tgt0": (-0.08, 0.86, 1.62), "tgt1": (-0.06, 0.64, 1.00), "l0": 29.0, "l1": 36.0},
        {"start": 997, "end": 1085, "type": "orbit", "center": (-0.06, 0.64), "r0": 1.14, "r1": 1.26, "az0": 16.0, "az1": -12.0, "z0": 1.20, "z1": 1.18, "tgt0": (-0.06, 0.64, 1.00), "tgt1": (-0.08, 0.66, 0.94), "l0": 36.0, "l1": 34.0},
        # Beat 8 (1086..1159): Snap down onto stove knob + green turn-off arrow + red LED off
        {"start": 1086, "end": 1096, "type": "whip", "p0": orbit_pos((-0.06, 0.64), 1.26, -12.0, 1.18), "p1": (-0.18, -0.02, 0.78), "tgt0": (-0.08, 0.66, 0.94), "tgt1": (-0.08, 0.50, 0.74), "l0": 34.0, "l1": 46.0},
        {"start": 1097, "end": 1159, "type": "orbit", "center": (-0.08, 0.50), "r0": 0.53, "r1": 0.48, "az0": -11.0, "az1": 10.0, "z0": 0.78, "z1": 0.76, "tgt0": (-0.08, 0.50, 0.74), "tgt1": (-0.12, 0.52, 0.75), "l0": 46.0, "l1": 50.0},
        # Beat 9 (1160..1280): Slide metal lid horizontally across pan + starve O2
        {"start": 1160, "end": 1170, "type": "whip", "p0": orbit_pos((-0.08, 0.50), 0.48, 10.0, 0.76), "p1": (0.24, -0.62, 1.24), "tgt0": (-0.12, 0.52, 0.75), "tgt1": (0.02, 0.64, 0.98), "l0": 50.0, "l1": 33.0},
        {"start": 1171, "end": 1280, "type": "orbit", "center": (-0.04, 0.64), "r0": 1.28, "r1": 1.18, "az0": 12.0, "az1": -14.0, "z0": 1.24, "z1": 1.16, "tgt0": (0.02, 0.64, 0.98), "tgt1": (-0.10, 0.62, 0.98), "l0": 33.0, "l1": 35.0},
        # Beat 10-11 (1281..1406): Extinguisher spotlight -> safe cool kitchen finale
        {"start": 1281, "end": 1291, "type": "whip", "p0": orbit_pos((-0.04, 0.64), 1.18, -14.0, 1.16), "p1": (0.58, -1.28, 0.92), "tgt0": (-0.10, 0.62, 0.98), "tgt1": (0.40, 0.52, 0.56), "l0": 35.0, "l1": 30.0},
        {"start": 1292, "end": 1342, "type": "orbit", "center": (0.40, 0.52), "r0": 1.80, "r1": 1.94, "az0": 6.0, "az1": 20.0, "z0": 0.92, "z1": 1.08, "tgt0": (0.40, 0.52, 0.56), "tgt1": (0.18, 0.58, 0.80), "l0": 30.0, "l1": 28.5},
        {"start": 1343, "end": 1406, "type": "orbit", "center": (0.06, 0.58), "r0": 2.40, "r1": 2.52, "az0": 14.0, "az1": -8.0, "z0": 1.24, "z1": 1.32, "tgt0": (0.18, 0.58, 0.80), "tgt1": (0.0, 0.58, 0.94), "l0": 28.5, "l1": 27.5},
    ]

    keyframe_kinetic_camera(
        cam_obj,
        cam_tgt,
        cam_segments,
        TOTAL_FRAMES,
        impact_frames=[12, 162, 168, 262, 650, 665, 760, 1026, 1115, 1225],
        breathe_amp=0.011,
    )

    return scene


def main():
    mode, c_idx, n_chunks = parse_args()
    build_scene()
    if mode == "preview":
        render_preview_frames(PREVIEW_FRAMES, out_dir="out/preview")
    elif mode == "thumb":
        views = [
            {"filename": "thumb_top_fire.png", "frame": 130, "cam_loc": (0.20, -0.44, 1.22), "cam_target": (0.0, 0.64, 1.00), "lens": 38.0},
            {"filename": "thumb_bot_lid.png", "frame": 1350, "cam_loc": (0.14, -1.72, 1.24), "cam_target": (0.04, 0.56, 0.86), "lens": 29.0},
        ]
        render_named_views(views, out_dir="out/thumb")
    elif mode == "chunk":
        render_chunk(c_idx, n_chunks, TOTAL_FRAMES, fps=FPS, out_prefix="chunk")
    else:
        raise ValueError(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
