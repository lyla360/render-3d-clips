"""InkRoom 3D Engine v2 core utilities (Blender 4.0+ Cel-Shaded Toon + Dual-Weight Ink).

Extends the proven bru3D pipeline with:
  - 3-Tone Stylized Toon shaders with Fresnel Rim Light & optional Specular Catchlight
  - Dual-weight Freestyle collections (`InkObjects` 2.2px, `SoftFaceInk` 1.05px silhouette-only, `NoInkVFX` 0px)
  - Subtle GTAO Contact Shadows & selective emissive Bloom
  - 6-runner/20-runner chunk rendering & kinetic non-stop vertical camera choreography
"""

import math
import os
import subprocess
import sys

import bmesh
import bpy


def parse_args():
    """Parse CLI arguments passed after `--` to the Blender Python script."""
    argv = sys.argv
    args = argv[argv.index("--") + 1 :] if "--" in argv else []
    mode = args[0] if len(args) > 0 else "showcase"
    c_idx = int(args[1]) if len(args) > 1 else 0
    n_chunks = int(args[2]) if len(args) > 2 else 6
    return mode, c_idx, n_chunks


def clear_scene():
    """Reset Blender to an empty factory scene."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def ensure_collection(name, parent):
    """Return an existing child collection or create and link it under `parent`."""
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    col = bpy.data.collections.new(name)
    parent.children.link(col)
    return col


def move_to_col(obj, col):
    """Move `obj` exclusively into collection `col`."""
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)


def smooth_step(t):
    """Cubic Hermite interpolation clamped to [0.0, 1.0]."""
    t = max(0.0, min(1.0, float(t)))
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    """Linear interpolation between scalars `a` and `b`."""
    return a + (b - a) * t


def lerp3(a, b, t):
    """Linear interpolation between 3-tuples `a` and `b`."""
    return (lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t))


def get_rgba_mix_sockets(mix_node):
    """Return `(Factor, A, B, Result)` sockets on a Blender 4.0 `ShaderNodeMix` (RGBA)."""
    rgba_in = [s for s in mix_node.inputs if s.type == "RGBA"]
    rgba_out = [s for s in mix_node.outputs if s.type == "RGBA"]
    return mix_node.inputs[0], rgba_in[0], rgba_in[1], rgba_out[0]


def setup_bru3d_render_v2(
    width=1080,
    height=1920,
    fps=30,
    total_frames=120,
    ink_thickness=2.2,
    soft_ink_thickness=1.05,
    ink_color=(0.05, 0.05, 0.08),
    soft_ink_color=(0.08, 0.07, 0.10),
    world_color=(0.68, 0.72, 0.78),
):
    """Configure EEVEE, GTAO contact shadows, selective Bloom, Standard color, and Dual-Weight Freestyle."""
    scene = bpy.context.scene

    engines = [
        e.identifier
        for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    ]
    scene.render.engine = (
        "BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else "BLENDER_EEVEE_NEXT"
    )

    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.frame_start = 1
    scene.frame_end = total_frames
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"

    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0

    eevee = scene.eevee
    for attr, val in [
        ("taa_render_samples", 8),
        ("use_gtao", True),
        ("gtao_distance", 0.28),
        ("gtao_factor", 0.45),
        ("use_soft_shadows", False),
        ("shadow_cube_size", "1024"),
        ("shadow_cascade_size", "1024"),
        ("use_bloom", True),
        ("bloom_threshold", 1.35),
        ("bloom_intensity", 0.08),
        ("bloom_radius", 5.5),
    ]:
        if hasattr(eevee, attr):
            setattr(eevee, attr, val)

    world = bpy.data.worlds.new("InkRoomV2World")
    scene.world = world
    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node:
        bg_node.inputs["Color"].default_value = (*world_color, 1.0)
        bg_node.inputs["Strength"].default_value = 1.0

    col_ink = ensure_collection("InkObjects", scene.collection)
    col_soft_ink = ensure_collection("SoftFaceInk", scene.collection)
    col_vfx = ensure_collection("NoInkVFX", scene.collection)

    scene.render.use_freestyle = True
    scene.render.line_thickness_mode = "ABSOLUTE"
    scene.render.line_thickness = ink_thickness

    vl = scene.view_layers[0]
    vl.use_freestyle = True
    fs = vl.freestyle_settings
    fs.crease_angle = math.radians(138.0)
    while len(fs.linesets) > 0:
        fs.linesets.remove(fs.linesets[0])

    # Crisp exterior + crease ink for props, environment, furniture, clothes
    ls_main = fs.linesets.new("InkLineSet")
    ls_main.select_silhouette = True
    ls_main.select_border = True
    ls_main.select_crease = True
    ls_main.select_edge_mark = False
    ls_main.select_external_contour = True
    ls_main.select_material_boundary = False
    ls_main.select_by_collection = True
    ls_main.collection = col_ink
    ls_main.collection_negation = "INCLUSIVE"
    ls_main.linestyle.color = ink_color
    ls_main.linestyle.thickness = ink_thickness
    ls_main.linestyle.caps = "ROUND"

    # Subtle outer-contour-only soft ink for Tomas's skin & hair so the face stays super appealing
    ls_soft = fs.linesets.new("SoftFaceLineSet")
    ls_soft.select_silhouette = True
    ls_soft.select_border = False
    ls_soft.select_crease = False
    ls_soft.select_edge_mark = False
    ls_soft.select_external_contour = True
    ls_soft.select_material_boundary = False
    ls_soft.select_by_collection = True
    ls_soft.collection = col_soft_ink
    ls_soft.collection_negation = "INCLUSIVE"
    ls_soft.linestyle.color = soft_ink_color
    ls_soft.linestyle.thickness = soft_ink_thickness
    ls_soft.linestyle.caps = "ROUND"

    return scene, col_ink, col_soft_ink, col_vfx


def _build_3tone_toon_graph(
    nt,
    shadow_rgba,
    mid_rgba,
    lit_rgba,
    tex_image=None,
    tex_interp="Linear",
    tint_rgb=None,
    rim_color=(1.0, 0.94, 0.82),
    rim_strength=0.22,
    spec_strength=0.0,
    spec_roughness=0.14,
):
    """Build a unified 3-Tone Stylized Toon + Fresnel Rim + optional Specular shader graph."""
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (980, 0)

    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (-460, -120)
    diff.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    diff.inputs["Roughness"].default_value = 0.0

    s2r = nt.nodes.new("ShaderNodeShaderToRGB")
    s2r.location = (-240, -120)

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-20, -120)
    cr = ramp.color_ramp
    cr.interpolation = "LINEAR"
    cr.elements[0].position = 0.24
    cr.elements[0].color = shadow_rgba
    cr.elements[1].position = 0.72
    cr.elements[1].color = lit_rgba
    e_mid_lo = cr.elements.new(0.28)
    e_mid_lo.color = mid_rgba
    e_mid_hi = cr.elements.new(0.68)
    e_mid_hi.color = mid_rgba

    nt.links.new(diff.outputs["BSDF"], s2r.inputs["Shader"])
    nt.links.new(s2r.outputs["Color"], ramp.inputs["Fac"])

    cur_socket = ramp.outputs["Color"]

    if tex_image is not None:
        tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.location = (-60, 240)
        tex_node.image = tex_image
        tex_node.interpolation = tex_interp

        albedo_socket = tex_node.outputs["Color"]
        if tint_rgb is not None:
            tint_mix = nt.nodes.new("ShaderNodeMix")
            tint_mix.location = (150, 220)
            tint_mix.data_type = "RGBA"
            tint_mix.blend_type = "MULTIPLY"
            tf, ta, tb, tres = get_rgba_mix_sockets(tint_mix)
            tf.default_value = 0.65
            tb.default_value = (*tint_rgb, 1.0)
            nt.links.new(albedo_socket, ta)
            albedo_socket = tres

        mul_mix = nt.nodes.new("ShaderNodeMix")
        mul_mix.location = (320, 40)
        mul_mix.data_type = "RGBA"
        mul_mix.blend_type = "MULTIPLY"
        mf, ma, mb, mres = get_rgba_mix_sockets(mul_mix)
        mf.default_value = 1.0
        nt.links.new(albedo_socket, ma)
        nt.links.new(cur_socket, mb)
        cur_socket = mres

    if rim_strength > 0.0:
        lw = nt.nodes.new("ShaderNodeLayerWeight")
        lw.location = (180, -340)
        lw.inputs["Blend"].default_value = 0.25

        rim_ramp = nt.nodes.new("ShaderNodeValToRGB")
        rim_ramp.location = (370, -340)
        rcr = rim_ramp.color_ramp
        rcr.interpolation = "LINEAR"
        rcr.elements[0].position = 0.70
        rcr.elements[0].color = (0.0, 0.0, 0.0, 1.0)
        rcr.elements[1].position = 0.85
        rcr.elements[1].color = (*rim_color, 1.0)
        nt.links.new(lw.outputs["Fresnel"], rim_ramp.inputs["Fac"])

        rim_add = nt.nodes.new("ShaderNodeMix")
        rim_add.location = (580, 0)
        rim_add.data_type = "RGBA"
        rim_add.blend_type = "ADD"
        rf, ra, rb, rres = get_rgba_mix_sockets(rim_add)
        rf.default_value = rim_strength
        nt.links.new(cur_socket, ra)
        nt.links.new(rim_ramp.outputs["Color"], rb)
        cur_socket = rres

    if spec_strength > 0.0:
        gl = nt.nodes.new("ShaderNodeBsdfGlossy")
        gl.location = (180, 340)
        gl.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        gl.inputs["Roughness"].default_value = spec_roughness

        gs2r = nt.nodes.new("ShaderNodeShaderToRGB")
        gs2r.location = (370, 340)
        spec_ramp = nt.nodes.new("ShaderNodeValToRGB")
        spec_ramp.location = (540, 340)
        scr = spec_ramp.color_ramp
        scr.interpolation = "LINEAR"
        scr.elements[0].position = 0.74
        scr.elements[0].color = (0.0, 0.0, 0.0, 1.0)
        scr.elements[1].position = 0.82
        scr.elements[1].color = (1.0, 1.0, 1.0, 1.0)
        nt.links.new(gl.outputs["BSDF"], gs2r.inputs["Shader"])
        nt.links.new(gs2r.outputs["Color"], spec_ramp.inputs["Fac"])

        spec_add = nt.nodes.new("ShaderNodeMix")
        spec_add.location = (760, 40)
        spec_add.data_type = "RGBA"
        spec_add.blend_type = "ADD"
        sf, sa, sb, sres = get_rgba_mix_sockets(spec_add)
        sf.default_value = spec_strength
        nt.links.new(cur_socket, sa)
        nt.links.new(spec_ramp.outputs["Color"], sb)
        cur_socket = sres

    nt.links.new(cur_socket, out.inputs["Surface"])


def make_toon_v2_mat(
    name,
    lit_rgb,
    shadow_rgb=None,
    mid_rgb=None,
    rim_color=(1.0, 0.94, 0.82),
    rim_strength=0.22,
    spec_strength=0.0,
    spec_roughness=0.14,
):
    """Create a 3-tone Stylized Toon material with cool-shifted shadows & Fresnel Rim."""
    if shadow_rgb is None:
        shadow_rgb = (
            max(0.0, lit_rgb[0] * 0.56),
            max(0.0, lit_rgb[1] * 0.56),
            min(1.0, lit_rgb[2] * 0.66 + 0.03),
        )
    if mid_rgb is None:
        mid_rgb = lerp3(shadow_rgb, lit_rgb, 0.48)

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    _build_3tone_toon_graph(
        mat.node_tree,
        shadow_rgba=(*shadow_rgb, 1.0),
        mid_rgba=(*mid_rgb, 1.0),
        lit_rgba=(*lit_rgb, 1.0),
        rim_color=rim_color,
        rim_strength=rim_strength,
        spec_strength=spec_strength,
        spec_roughness=spec_roughness,
    )
    mat["inkroom_v2"] = 1
    return mat


def convert_material_to_toon_v2(
    mat,
    tint_rgb=None,
    rim_color=(1.0, 0.94, 0.82),
    rim_strength=0.20,
    spec_strength=0.0,
    spec_roughness=0.14,
):
    """Convert any Principled/textured Blender or glTF material cleanly into Engine v2 3-Tone Toon."""
    if mat is None or not mat.use_nodes or mat.get("inkroom_v2", 0):
        return mat

    # Keep glass panes (e.g. Poly Haven wall_clock cover) cleanly transparent instead of opaque white Toon
    mname_lo = (mat.name or "").lower()
    if "glass" in mname_lo or getattr(mat, "blend_method", "OPAQUE") == "BLEND":
        nt = mat.node_tree
        nt.nodes.clear()
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        trans = nt.nodes.new("ShaderNodeBsdfTransparent")
        gl = nt.nodes.new("ShaderNodeBsdfGlossy")
        gl.inputs["Roughness"].default_value = 0.08
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.inputs["Fac"].default_value = 0.14
        nt.links.new(trans.outputs["BSDF"], mix.inputs[1])
        nt.links.new(gl.outputs["BSDF"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
        mat["inkroom_v2"] = 1
        return mat

    nt = mat.node_tree
    tex_node = None
    base_rgb = (0.78, 0.76, 0.74)

    def _find_tex(sock, visited=None):
        if visited is None:
            visited = set()
        if sock is None or not sock.is_linked:
            return None
        node = sock.links[0].from_node
        if node in visited:
            return None
        visited.add(node)
        if node.type == "TEX_IMAGE" and getattr(node, "image", None) is not None:
            return node
        for inp in node.inputs:
            if inp.type in ("RGBA", "VECTOR", "VALUE"):
                found = _find_tex(inp, visited)
                if found is not None:
                    return found
        return None

    for node in nt.nodes:
        if node.type == "BSDF_PRINCIPLED":
            col_in = node.inputs.get("Base Color")
            if col_in is not None:
                tex_node = _find_tex(col_in)
                val = col_in.default_value
                base_rgb = (float(val[0]), float(val[1]), float(val[2]))
            break

    if tex_node is None:
        # Fallback: pick first diffuse-looking image texture if unlinked or non-Principled
        candidates = [
            n
            for n in nt.nodes
            if n.type == "TEX_IMAGE"
            and getattr(n, "image", None) is not None
            and not any(k in (n.image.name or "").lower() for k in ("nor", "normal", "rough", "arm", "metal", "_ao"))
        ]
        if candidates:
            tex_node = candidates[0]

    saved_img = tex_node.image if tex_node is not None else None
    saved_interp = tex_node.interpolation if tex_node is not None else "Linear"

    if saved_img is not None:
        # Light multipliers preserve painted/photo albedo details in Engine v2 3-tone shading
        _build_3tone_toon_graph(
            nt,
            shadow_rgba=(0.60, 0.59, 0.68, 1.0),
            mid_rgba=(0.86, 0.85, 0.89, 1.0),
            lit_rgba=(1.0, 1.0, 1.0, 1.0),
            tex_image=saved_img,
            tex_interp=saved_interp,
            tint_rgb=tint_rgb,
            rim_color=rim_color,
            rim_strength=rim_strength,
            spec_strength=spec_strength,
            spec_roughness=spec_roughness,
        )
    else:
        lit = tint_rgb if tint_rgb is not None else base_rgb
        shadow = (max(0.0, lit[0] * 0.56), max(0.0, lit[1] * 0.56), min(1.0, lit[2] * 0.66 + 0.03))
        mid = lerp3(shadow, lit, 0.48)
        _build_3tone_toon_graph(
            nt,
            shadow_rgba=(*shadow, 1.0),
            mid_rgba=(*mid, 1.0),
            lit_rgba=(*lit, 1.0),
            rim_color=rim_color,
            rim_strength=rim_strength,
            spec_strength=spec_strength,
            spec_roughness=spec_roughness,
        )

    mat["inkroom_v2"] = 1
    return mat


def make_toon_mat(name, lit_rgb, shadow_rgb, cutoff=0.35):
    """Backward-compatible wrapper mapping 2-tone calls to crisp Engine v2 3-tone shading."""
    return make_toon_v2_mat(name, lit_rgb, shadow_rgb=shadow_rgb, rim_strength=0.14)


def make_wood_floor_mat(
    name="WoodFloorToonV2",
    color1=(0.74, 0.60, 0.46),
    color2=(0.68, 0.55, 0.42),
    mortar=(0.45, 0.35, 0.27),
    scale=3.2,
):
    """Procedural plank wood floor shaded with a 3-tone Toon light ramp."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (760, 0)

    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-600, 220)

    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.location = (-360, 220)
    brick.offset = 0.5
    brick.inputs["Scale"].default_value = scale
    brick.inputs["Mortar Size"].default_value = 0.012
    brick.inputs["Mortar Smooth"].default_value = 0.0
    brick.inputs["Brick Width"].default_value = 1.6
    brick.inputs["Row Height"].default_value = 0.28
    brick.inputs["Color1"].default_value = (*color1, 1.0)
    brick.inputs["Color2"].default_value = (*color2, 1.0)
    brick.inputs["Mortar"].default_value = (*mortar, 1.0)
    nt.links.new(tex_coord.outputs["Object"], brick.inputs["Vector"])

    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.location = (-360, -140)
    diff.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)

    s2r = nt.nodes.new("ShaderNodeShaderToRGB")
    s2r.location = (-130, -140)

    light_ramp = nt.nodes.new("ShaderNodeValToRGB")
    light_ramp.location = (90, -140)
    lr = light_ramp.color_ramp
    lr.interpolation = "LINEAR"
    lr.elements[0].position = 0.24
    lr.elements[0].color = (0.62, 0.60, 0.68, 1.0)
    lr.elements[1].position = 0.72
    lr.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    em = lr.elements.new(0.28)
    em.color = (0.86, 0.85, 0.89, 1.0)

    nt.links.new(diff.outputs["BSDF"], s2r.inputs["Shader"])
    nt.links.new(s2r.outputs["Color"], light_ramp.inputs["Fac"])

    mix = nt.nodes.new("ShaderNodeMix")
    mix.location = (440, 40)
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    fac_in, a_in, b_in, res_out = get_rgba_mix_sockets(mix)
    fac_in.default_value = 1.0

    nt.links.new(brick.outputs["Color"], a_in)
    nt.links.new(light_ramp.outputs["Color"], b_in)
    nt.links.new(res_out, out.inputs["Surface"])
    return mat


def make_emissive_mix_mat(name, rgb, alpha=0.80, strength=1.25):
    """Translucent unlit VFX material with animatable `AlphaMix` and `EmisNode`."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False

    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (420, 0)

    trans = nt.nodes.new("ShaderNodeBsdfTransparent")
    trans.location = (-80, 100)

    emis = nt.nodes.new("ShaderNodeEmission")
    emis.name = "EmisNode"
    emis.location = (-80, -80)
    emis.inputs["Color"].default_value = (*rgb, 1.0)
    emis.inputs["Strength"].default_value = strength

    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.name = "AlphaMix"
    mix.location = (180, 0)
    mix.inputs["Fac"].default_value = alpha

    nt.links.new(trans.outputs["BSDF"], mix.inputs[1])
    nt.links.new(emis.outputs["Emission"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def make_lamp_shade_mat(name, rgb, strength=1.45):
    """Emissive material for flames, lamp bulbs, or glowing highlights."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    emis = nt.nodes.new("ShaderNodeEmission")
    emis.name = "EmisNode"
    emis.inputs["Color"].default_value = (*rgb, 1.0)
    emis.inputs["Strength"].default_value = strength
    nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])
    return mat


def setup_vertical_camera(
    name="MainCam",
    lens=30.0,
    loc=(0.0, -4.0, 1.5),
    target=(0.0, 0.0, 1.0),
    col=None,
    sensor_width=36.0,
):
    """Create a vertical-ready camera using HORIZONTAL sensor_fit and TrackTo target."""
    scene = bpy.context.scene
    if col is None:
        col = scene.collection

    cam_target = add_empty(f"{name}_Target", target, col)
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = lens
    cam_data.sensor_width = sensor_width
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.clip_start = 0.05
    cam_data.clip_end = 100.0

    cam_obj = bpy.data.objects.new(name, cam_data)
    col.objects.link(cam_obj)
    cam_obj.location = loc

    track = cam_obj.constraints.new(type="TRACK_TO")
    track.target = cam_target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    scene.camera = cam_obj
    return cam_obj, cam_target


def ease_out_expo(t):
    """Aggressive deceleration curve ideal for crash zooms and punch-ins."""
    t = max(0.0, min(1.0, float(t)))
    return 1.0 if t >= 1.0 else 1.0 - math.pow(2.0, -10.0 * t)


def ease_in_out_cubic(t):
    """Smooth acceleration/deceleration curve for whip-pans and sweeps."""
    t = max(0.0, min(1.0, float(t)))
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - math.pow(-2.0 * t + 2.0, 3) / 2.0


def orbit_pos(center, radius, azim_deg, z_height):
    """Return 3D camera `(x, y, z)` along a horizontal polar arc around `center` `(cx, cy)`."""
    rad = math.radians(azim_deg)
    return (
        center[0] + math.sin(rad) * radius,
        center[1] - math.cos(rad) * radius,
        z_height,
    )


def keyframe_kinetic_camera(
    cam_obj,
    cam_target,
    segments,
    total_frames,
    impact_frames=None,
    breathe_amp=0.012,
):
    """Keyframe dynamic non-stop Short camera choreography (`orbit`, `whip`, `zoom`, `glide`)."""
    impact_set = set(impact_frames or [])
    seg_lookup = {}
    for seg in segments:
        for f in range(seg["start"], seg["end"] + 1):
            seg_lookup[f] = seg

    def _in_impact(frame):
        return any(0 <= (frame - imp) <= 7 for imp in impact_set)

    for f in range(1, total_frames + 1):
        seg = seg_lookup.get(f)
        if seg is None:
            continue
        f0, f1 = seg["start"], seg["end"]
        stype = seg.get("type", "glide")
        is_bound = (f == f0 or f == f1)
        is_dense = (stype == "whip") or _in_impact(f)
        if not (is_bound or is_dense or f % 2 == 0):
            continue

        raw_u = max(0.0, min(1.0, (f - f0) / max(1, f1 - f0)))
        if stype == "zoom":
            u = ease_out_expo(raw_u)
        elif stype == "orbit":
            u = smooth_step(raw_u)
        else:
            u = ease_in_out_cubic(raw_u)

        if stype == "orbit":
            base_pos = orbit_pos(
                seg["center"],
                lerp(seg["r0"], seg["r1"], u),
                lerp(seg["az0"], seg["az1"], u),
                lerp(seg["z0"], seg["z1"], u),
            )
        else:
            base_pos = lerp3(seg["p0"], seg["p1"], u)

        tgt_pos = lerp3(seg["tgt0"], seg["tgt1"], u)
        lens_val = lerp(seg["l0"], seg["l1"], u)

        bx = math.sin(f * 0.09) * breathe_amp
        bz = math.cos(f * 0.07) * (breathe_amp * 0.75)
        sx = sz = 0.0
        for imp in impact_set:
            dt = f - imp
            if 0 <= dt <= 6:
                decay = (1.0 - dt / 7.0) * 0.036
                sx += math.sin(dt * 2.5) * decay
                sz += math.cos(dt * 3.2) * decay

        cam_obj.location = (base_pos[0] + bx + sx, base_pos[1], base_pos[2] + bz + sz)
        cam_target.location = tgt_pos
        cam_obj.data.lens = lens_val
        cam_obj.keyframe_insert(data_path="location", frame=f)
        cam_target.keyframe_insert(data_path="location", frame=f)
        cam_obj.data.keyframe_insert(data_path="lens", frame=f)


def add_pierced_wall(name, x_inner, y_vals, z_vals, holes, thickness, col, mat):
    """Build a watertight single-mesh wall slab with rectangular openings and zero interior seams."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    if mat:
        obj.data.materials.append(mat)

    bm = bmesh.new()
    for iy in range(len(y_vals) - 1):
        y0, y1 = y_vals[iy], y_vals[iy + 1]
        for iz in range(len(z_vals) - 1):
            z0, z1 = z_vals[iz], z_vals[iz + 1]
            ym, zm = 0.5 * (y0 + y1), 0.5 * (z0 + z1)
            in_hole = any(
                (hy0 < ym < hy1 and hz0 < zm < hz1) for (hy0, hy1, hz0, hz1) in holes
            )
            if in_hole:
                continue
            v0 = bm.verts.new((x_inner, y0, z0))
            v1 = bm.verts.new((x_inner, y1, z0))
            v2 = bm.verts.new((x_inner, y1, z1))
            v3 = bm.verts.new((x_inner, y0, z1))
            bm.faces.new((v0, v1, v2, v3))

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
    ret = bmesh.ops.extrude_face_region(bm, geom=list(bm.faces))
    extruded_verts = [e for e in ret["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(-thickness, 0.0, 0.0))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    return obj


def add_box(name, size, loc, col, mat, rot=(0.0, 0.0, 0.0), bevel=0.0):
    """Create a scaled cube with optional bevel and assign to `col`."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc, rotation=rot)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel > 0.0:
        bmod = obj.modifiers.new("Bevel", "BEVEL")
        bmod.width = bevel
        bmod.segments = 2
    if mat:
        obj.data.materials.append(mat)
    move_to_col(obj, col)
    return obj


def add_cylinder(
    name, radius, depth, loc, col, mat, rot=(0.0, 0.0, 0.0), verts=22, bevel=0.0
):
    """Create a smooth-shaded cylinder with optional bevel and assign to `col`."""
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=verts, radius=radius, depth=depth, location=loc, rotation=rot
    )
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()
    if bevel > 0.0:
        bmod = obj.modifiers.new("Bevel", "BEVEL")
        bmod.width = bevel
        bmod.segments = 2
    if mat:
        obj.data.materials.append(mat)
    move_to_col(obj, col)
    return obj


def add_sphere(
    name, radius, loc, col, mat, scale=(1.0, 1.0, 1.0), rot=(0.0, 0.0, 0.0), subsurf=1
):
    """Create a smooth UV sphere and assign to `col`."""
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=18, ring_count=12, radius=radius, location=loc
    )
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.rotation_euler = rot
    bpy.ops.object.shade_smooth()
    if subsurf > 0:
        smod = obj.modifiers.new("Subsurf", "SUBSURF")
        smod.levels = subsurf
        smod.render_levels = subsurf
    if mat:
        obj.data.materials.append(mat)
    move_to_col(obj, col)
    return obj


def add_cone(name, r1, r2, depth, loc, col, mat, rot=(0.0, 0.0, 0.0), verts=18):
    """Create a smooth cone/frustum and assign to `col`."""
    bpy.ops.mesh.primitive_cone_add(
        vertices=verts, radius1=r1, radius2=r2, depth=depth, location=loc, rotation=rot
    )
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()
    if mat:
        obj.data.materials.append(mat)
    move_to_col(obj, col)
    return obj


def add_torus(name, major_r, minor_r, loc, col, mat, rot=(0.0, 0.0, 0.0)):
    """Create a smooth torus ring and assign to `col`."""
    bpy.ops.mesh.primitive_torus_add(
        major_segments=28,
        minor_segments=10,
        major_radius=major_r,
        minor_radius=minor_r,
        location=loc,
        rotation=rot,
    )
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()
    if mat:
        obj.data.materials.append(mat)
    move_to_col(obj, col)
    return obj


def add_empty(name, loc, col, parent=None, rot=(0.0, 0.0, 0.0)):
    """Create a clean local-space Empty pivot with zeroed parent inverse matrix."""
    emp = bpy.data.objects.new(name, None)
    emp.empty_display_size = 0.08
    col.objects.link(emp)
    if parent is not None:
        emp.parent = parent
        emp.matrix_parent_inverse.identity()
    emp.location = loc
    emp.rotation_euler = rot
    return emp


def attach_local(obj, parent, local_loc=(0.0, 0.0, 0.0), local_rot=(0.0, 0.0, 0.0)):
    """Attach `obj` strictly in parent's local coordinates."""
    obj.parent = parent
    obj.matrix_parent_inverse.identity()
    obj.location = local_loc
    obj.rotation_euler = local_rot


def set_hidden(objs, hidden, frame):
    """Keyframe both `hide_render` and `hide_viewport` cleanly."""
    for o in objs:
        o.hide_render = hidden
        o.hide_viewport = hidden
        o.keyframe_insert(data_path="hide_render", frame=frame)
        o.keyframe_insert(data_path="hide_viewport", frame=frame)


def render_named_views(views_spec, out_dir):
    """Render static showcase frames from camera specs (`filename`, `frame`, `cam_loc`, `cam_target`, `lens`)."""
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    cam = scene.camera
    target = cam.constraints["Track To"].target if "Track To" in cam.constraints else None

    for idx, spec in enumerate(views_spec):
        fname = spec["filename"]
        frame = spec.get("frame", 1)
        scene.frame_set(frame)
        if "cam_loc" in spec:
            cam.location = spec["cam_loc"]
        if target is not None and "cam_target" in spec:
            target.location = spec["cam_target"]
        if "lens" in spec:
            cam.data.lens = spec["lens"]
        out_p = os.path.abspath(os.path.join(out_dir, fname))
        scene.render.filepath = out_p
        bpy.ops.render.render(write_still=True)
        print(f"Rendered view {idx:02d} ({fname}, frame {frame}) -> {out_p}")


def render_preview_frames(frame_list, out_dir="out/preview"):
    """Render 1 representative storyboard keyframe PNG for every listed frame index."""
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    for idx, f in enumerate(frame_list):
        scene.frame_set(f)
        out_p = os.path.abspath(os.path.join(out_dir, f"prev_{idx:02d}_f{f:04d}.png"))
        scene.render.filepath = out_p
        bpy.ops.render.render(write_still=True)
        print(f"Rendered preview {idx:02d} frame {f} -> {out_p}")


def render_chunk(chunk_idx, num_chunks, total_frames, fps=30, out_prefix="chunk"):
    """Render an indexed frame slice to PNGs and encode a libx264 chunk MP4 for CI merge."""
    os.makedirs("out/frames", exist_ok=True)
    os.makedirs("out/ci_chunks", exist_ok=True)

    per_chunk = math.ceil(total_frames / num_chunks)
    start_f = chunk_idx * per_chunk + 1
    end_f = min(total_frames, (chunk_idx + 1) * per_chunk)
    if start_f > total_frames:
        print(f"Chunk {chunk_idx} has no frames; skipping.")
        return

    scene = bpy.context.scene
    for f in range(start_f, end_f + 1):
        scene.frame_set(f)
        scene.render.filepath = os.path.abspath(f"out/frames/frame_{f:04d}.png")
        bpy.ops.render.render(write_still=True)

    chunk_mp4 = os.path.abspath(f"out/ci_chunks/{out_prefix}_{chunk_idx:02d}.mp4")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", str(fps),
        "-start_number", str(start_f),
        "-i", os.path.abspath("out/frames/frame_%04d.png"),
        "-frames:v", str(end_f - start_f + 1),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        chunk_mp4,
    ]
    subprocess.run(cmd, check=True)
    print(f"Rendered chunk {chunk_idx:02d}: frames {start_f}..{end_f} -> {chunk_mp4}")
