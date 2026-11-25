"""Automatic CC0 3D asset & rigged character/animal loader for InkRoom 3D Engine v2.

Prefers native `.blend` library loading from Poly Haven API and automatically falls
back to `glTF` for Blender 5.0+ assets; also supports ready-made rigged `.glb` humans/animals.
"""

import json
import math
import os
import sys
import time
import urllib.request

import bpy
from mathutils import Vector

from bru3d_core import add_empty, convert_material_to_toon_v2, move_to_col


USER_AGENT = "InkRoom3D-Engine/2.0"


def _download_file(url, dest_path, expected_size=None, retries=3):
    """Download a single file with size-skip cache and automatic retries."""
    if (
        os.path.exists(dest_path)
        and expected_size is not None
        and os.path.getsize(dest_path) == expected_size
    ):
        return dest_path

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            with open(dest_path, "wb") as f:
                f.write(data)
            return dest_path
        except Exception as err:
            last_err = err
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed downloading {url}: {last_err}")


def _fetch_polyhaven_files(asset_id):
    api_url = f"https://api.polyhaven.com/files/{asset_id}"
    req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_polyhaven_bundle(asset_id, fmt="blend", cache_dir="assets/polyhaven", res="1k"):
    """Download a Poly Haven `.blend` or `.gltf` asset bundle + textures into local cache."""
    files_meta = _fetch_polyhaven_files(asset_id)
    fmt_block = files_meta.get(fmt, {})
    chosen_res = res if res in fmt_block else next(iter(fmt_block.keys()), None)
    if not chosen_res:
        raise RuntimeError(f"No {fmt} bundle available for Poly Haven asset {asset_id}")

    entry = fmt_block[chosen_res].get(fmt, {})
    main_url = entry["url"]
    sub_dir = asset_id if fmt == "blend" else f"{asset_id}_gltf"
    asset_dir = os.path.abspath(os.path.join(cache_dir, sub_dir))
    main_name = os.path.basename(main_url.split("?")[0])
    main_path = os.path.join(asset_dir, main_name)

    _download_file(main_url, main_path, expected_size=entry.get("size"))
    for rel_path, inc_info in entry.get("include", {}).items():
        inc_dest = os.path.join(asset_dir, rel_path)
        _download_file(inc_info["url"], inc_dest, expected_size=inc_info.get("size"))

    print(f"PolyHaven cached [{asset_id}@{chosen_res}/{fmt}] -> {main_path}")
    return main_path


def _world_bounds(meshes):
    """Compute aggregate `(min_vec, max_vec)` world-space axis-aligned bounding box."""
    min_c = [1e9, 1e9, 1e9]
    max_c = [-1e9, -1e9, -1e9]
    for m in meshes:
        mw = m.matrix_world
        for corner in m.bound_box:
            wc = mw @ Vector(corner)
            min_c[0] = min(min_c[0], wc.x)
            min_c[1] = min(min_c[1], wc.y)
            min_c[2] = min(min_c[2], wc.z)
            max_c[0] = max(max_c[0], wc.x)
            max_c[1] = max(max_c[1], wc.y)
            max_c[2] = max(max_c[2], wc.z)
    return Vector(min_c), Vector(max_c)


def _load_from_blend(blend_path, scene):
    """Load objects from native `.blend`, raising OSError if header is unsupported."""
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        data_to.objects = list(data_from.objects)

    loaded = [o for o in data_to.objects if o is not None]
    keep_objs = []
    for o in loaded:
        if o.type in ("CAMERA", "LIGHT"):
            bpy.data.objects.remove(o, do_unlink=True)
            continue
        if o.hide_render:
            continue
        scene.collection.objects.link(o)
        keep_objs.append(o)
    return keep_objs


def _load_from_gltf(gltf_path):
    """Fallback loader via glTF addon (exposing system numpy dist-packages if needed)."""
    for sp in ("/usr/lib/python3/dist-packages",):
        if os.path.isdir(sp) and sp not in sys.path:
            sys.path.append(sp)

    before_objs = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=gltf_path)
    new_objs = [o for o in bpy.data.objects if o not in before_objs]

    keep_objs = []
    for o in list(new_objs):
        if o.type in ("CAMERA", "LIGHT"):
            bpy.data.objects.remove(o, do_unlink=True)
            continue
        keep_objs.append(o)
    return keep_objs


def import_polyhaven_asset(
    asset_id,
    name,
    col_ink,
    target_dim=None,
    dim_axis="z",
    loc=(0.0, 0.0, 0.0),
    rot_z_deg=0.0,
    tint_rgb=None,
    rim_color=(1.0, 0.94, 0.82),
    rim_strength=0.20,
    spec_strength=0.0,
    spec_roughness=0.14,
    cache_dir="assets/polyhaven",
    res="1k",
):
    """Download, import (.blend with automatic glTF fallback), ground, scale, and shade as Toon v2."""
    scene = bpy.context.scene
    blend_path = download_polyhaven_bundle(asset_id, fmt="blend", cache_dir=cache_dir, res=res)
    try:
        keep_objs = _load_from_blend(blend_path, scene)
    except OSError as err:
        print(f"PolyHaven[{asset_id}] blend incompatible with Blender 4.0.2 ({err}); falling back to glTF...")
        gltf_path = download_polyhaven_bundle(asset_id, fmt="gltf", cache_dir=cache_dir, res=res)
        keep_objs = _load_from_gltf(gltf_path)

    meshes = []
    for o in keep_objs:
        if o.type == "MESH":
            move_to_col(o, col_ink)
            for p in o.data.polygons:
                p.use_smooth = True
            for slot in o.material_slots:
                convert_material_to_toon_v2(
                    slot.material,
                    tint_rgb=tint_rgb,
                    rim_color=rim_color,
                    rim_strength=rim_strength,
                    spec_strength=spec_strength,
                    spec_roughness=spec_roughness,
                )
            meshes.append(o)
        else:
            move_to_col(o, col_ink)

    if not meshes:
        raise RuntimeError(f"Poly Haven {asset_id} loaded zero visible meshes")

    root = add_empty(name, (0.0, 0.0, 0.0), col_ink)
    inner = add_empty(f"{name}_Inner", (0.0, 0.0, 0.0), col_ink, parent=root)

    keep_set = set(keep_objs)
    top_objs = [o for o in keep_objs if o.parent is None or o.parent not in keep_set]
    for o in top_objs:
        mw = o.matrix_world.copy()
        o.parent = inner
        o.matrix_world = mw

    bpy.context.view_layer.update()
    bmin, bmax = _world_bounds(meshes)
    raw_dims = bmax - bmin
    cx = 0.5 * (bmin.x + bmax.x)
    cy = 0.5 * (bmin.y + bmax.y)

    inner.location = (-cx, -cy, -bmin.z)

    scale_fac = 1.0
    if target_dim is not None:
        axis_map = {
            "x": raw_dims.x,
            "y": raw_dims.y,
            "z": raw_dims.z,
            "max": max(raw_dims.x, raw_dims.y, raw_dims.z),
        }
        denom = max(0.0001, axis_map.get(dim_axis, raw_dims.z))
        scale_fac = float(target_dim) / denom

    root.scale = (scale_fac, scale_fac, scale_fac)
    root.location = loc
    root.rotation_euler = (0.0, 0.0, math.radians(rot_z_deg))
    bpy.context.view_layer.update()

    fmin, fmax = _world_bounds(meshes)
    final_dims = fmax - fmin
    print(
        f"PolyHaven[{asset_id}] -> '{name}': "
        f"raw=({raw_dims.x:.3f},{raw_dims.y:.3f},{raw_dims.z:.3f}) "
        f"final=({final_dims.x:.3f},{final_dims.y:.3f},{final_dims.z:.3f}) at {loc}"
    )

    return {
        "root": root,
        "inner": inner,
        "meshes": meshes,
        "dims": (final_dims.x, final_dims.y, final_dims.z),
        "bounds": (tuple(fmin), tuple(fmax)),
    }


def import_rigged_glb_asset(
    source_url_or_path,
    name,
    col_ink,
    col_soft_ink=None,
    target_height=None,
    loc=(0.0, 0.0, 0.0),
    rot_z_deg=0.0,
    rim_strength=0.22,
    spec_strength=0.08,
    cache_dir="assets/characters",
):
    """Download/load a ready-made rigged CC0 `.glb` human or animal, ground it, shade Toon v2, and expose armature + actions."""
    if source_url_or_path.startswith(("http://", "https://")):
        fname = os.path.basename(source_url_or_path.split("?")[0]) or f"{name}.glb"
        local_path = os.path.abspath(os.path.join(cache_dir, fname))
        _download_file(source_url_or_path, local_path)
    else:
        local_path = os.path.abspath(source_url_or_path)

    before_actions = set(bpy.data.actions)
    keep_objs = _load_from_gltf(local_path)
    new_actions = [a for a in bpy.data.actions if a not in before_actions]

    armature = next((o for o in keep_objs if o.type == "ARMATURE"), None)
    meshes = [o for o in keep_objs if o.type == "MESH"]
    target_col = col_soft_ink if col_soft_ink is not None else col_ink

    for m in meshes:
        move_to_col(m, target_col)
        for p in m.data.polygons:
            p.use_smooth = True
        for slot in m.material_slots:
            convert_material_to_toon_v2(
                slot.material,
                rim_strength=rim_strength,
                spec_strength=spec_strength,
            )

    root = add_empty(name, (0.0, 0.0, 0.0), col_ink)
    inner = add_empty(f"{name}_Inner", (0.0, 0.0, 0.0), col_ink, parent=root)
    keep_set = set(keep_objs)
    for o in [o for o in keep_objs if o.parent is None or o.parent not in keep_set]:
        mw = o.matrix_world.copy()
        o.parent = inner
        o.matrix_world = mw

    bpy.context.view_layer.update()
    if meshes:
        bmin, bmax = _world_bounds(meshes)
        raw_h = max(0.001, bmax.z - bmin.z)
        inner.location = (-0.5 * (bmin.x + bmax.x), -0.5 * (bmin.y + bmax.y), -bmin.z)
        sc = float(target_height) / raw_h if target_height else 1.0
        root.scale = (sc, sc, sc)
    root.location = loc
    root.rotation_euler = (0.0, 0.0, math.radians(rot_z_deg))
    bpy.context.view_layer.update()

    print(
        f"RiggedGLB[{name}] -> armature={armature.name if armature else None}, "
        f"meshes={len(meshes)}, actions={[a.name for a in new_actions]}"
    )
    return {"root": root, "armature": armature, "meshes": meshes, "actions": new_actions}
