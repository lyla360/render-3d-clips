#!/usr/bin/env python3
"""
Shared Blender 4.0.x headless HTTP worker for both Oracle Cloud (CPU) and Google Colab (GPU).
Runs an HTTP server in a background thread and executes all `bpy` operations strictly on Blender's main thread.
"""

from __future__ import annotations

import contextlib
import hmac
import http.server
import io
import json
import math
import mimetypes
import os
import platform
import queue
import re
import shutil
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import bpy
from mathutils import Euler, Vector

HOST = os.environ.get("BLENDER_WORKER_HOST", "127.0.0.1")
PORT = int(os.environ.get("BLENDER_WORKER_PORT", "19876"))
API_TOKEN = os.environ.get("BLENDER_API_TOKEN", "").strip()
BACKEND_NAME = os.environ.get("BLENDER_BACKEND_NAME", "oracle").strip() or "oracle"
WORKSPACE_DIR = os.path.abspath(
    os.environ.get("BLENDER_WORKSPACE_DIR", "/opt/blender-hub/workspace")
)
DRIVE_BACKUP_DIR = os.environ.get("BLENDER_DRIVE_BACKUP_DIR", "").strip()
MAX_UPLOAD_BYTES = int(os.environ.get("BLENDER_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
MAX_IMPORT_BYTES = int(os.environ.get("BLENDER_MAX_IMPORT_BYTES", str(256 * 1024 * 1024)))

SUBDIRS = ("projects", "renders", "assets")

if not API_TOKEN:
    print("[blender_worker] ERROR: BLENDER_API_TOKEN must be set.", file=sys.stderr, flush=True)
    sys.exit(2)


def ensure_workspace_dirs() -> None:
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    for sub in SUBDIRS:
        os.makedirs(os.path.join(WORKSPACE_DIR, sub), exist_ok=True)
    if DRIVE_BACKUP_DIR:
        try:
            os.makedirs(DRIVE_BACKUP_DIR, exist_ok=True)
            for sub in SUBDIRS:
                os.makedirs(os.path.join(DRIVE_BACKUP_DIR, sub), exist_ok=True)
        except Exception as exc:
            print(f"[blender_worker] Warning: could not prepare DRIVE_BACKUP_DIR: {exc}", file=sys.stderr, flush=True)


def mirror_to_drive(rel_path: str, abs_src: str) -> str | None:
    if not DRIVE_BACKUP_DIR:
        return None
    try:
        dest = os.path.join(DRIVE_BACKUP_DIR, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(abs_src, dest)
        return dest
    except Exception as exc:
        print(f"[blender_worker] Warning: Drive backup failed for {rel_path}: {exc}", file=sys.stderr, flush=True)
        return None


def safe_workspace_path(rel_path: str) -> str:
    if not rel_path or "\x00" in rel_path:
        raise ValueError("Invalid relative path")
    clean = rel_path.replace("\\", "/").lstrip("/")
    root_real = os.path.realpath(WORKSPACE_DIR)
    target_real = os.path.realpath(os.path.join(root_real, clean))
    if target_real != root_real and not target_real.startswith(root_real + os.sep):
        raise ValueError("Path escapes workspace directory")
    return target_real


def sanitize_name(name: str, fallback: str = "scene") -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()).strip("._-")
    return base or fallback


def sanitize_project_name(name: str) -> str:
    raw = (name or "").strip()
    if raw.lower().endswith(".blend"):
        raw = raw[:-6]
    return sanitize_name(raw, fallback="untitled")


def get_eevee_engine_id() -> str:
    enum_items = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    ids = {item.identifier for item in enum_items}
    if "BLENDER_EEVEE_NEXT" in ids and "BLENDER_EEVEE" not in ids:
        return "BLENDER_EEVEE_NEXT"
    return "BLENDER_EEVEE"


def normalize_engine_name(engine: str | None) -> str:
    if not engine:
        return bpy.context.scene.render.engine
    upper = engine.strip().upper()
    if upper in ("EEVEE", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        return get_eevee_engine_id()
    if upper in ("CYCLES",):
        return "CYCLES"
    if upper in ("WORKBENCH", "BLENDER_WORKBENCH"):
        return "BLENDER_WORKBENCH"
    return upper


class WorkerState:
    def __init__(self) -> None:
        self.active_project: str | None = None
        self.gpu_available: bool = False
        self.gpu_backend: str | None = None
        self.gpu_names: list[str] = []
        self.exec_globals: dict[str, Any] = {}
        self.reset_exec_globals()

    def reset_exec_globals(self) -> None:
        self.exec_globals = {
            "__name__": "__blender_mcp__",
            "bpy": bpy,
            "math": math,
            "mathutils": __import__("mathutils"),
            "Vector": Vector,
            "Euler": Euler,
            "os": os,
            "json": json,
            "WORKSPACE_DIR": WORKSPACE_DIR,
        }


STATE = WorkerState()


def configure_cycles_devices(apply_to_scene: bool = True) -> dict[str, Any]:
    """Detect NVIDIA CUDA/OptiX GPUs cleanly; fall back to CPU if unavailable."""
    gpu_names: list[str] = []
    gpu_backend: str | None = None
    try:
        prefs = bpy.context.preferences
        cycles_addon = prefs.addons.get("cycles")
        if cycles_addon is not None:
            cprefs = cycles_addon.preferences
            for compute_type in ("OPTIX", "CUDA"):
                try:
                    cprefs.compute_device_type = compute_type
                    cprefs.get_devices()
                    found_gpu = []
                    for dev in cprefs.devices:
                        if dev.type == compute_type:
                            dev.use = True
                            found_gpu.append(dev.name)
                        elif dev.type == "CPU":
                            dev.use = False
                    if found_gpu:
                        gpu_names = found_gpu
                        gpu_backend = compute_type
                        break
                except Exception:
                    continue
            if not gpu_names:
                try:
                    cprefs.compute_device_type = "NONE"
                except Exception:
                    pass
    except Exception as exc:
        print(f"[blender_worker] GPU detection warning: {exc}", file=sys.stderr, flush=True)

    STATE.gpu_available = len(gpu_names) > 0
    STATE.gpu_backend = gpu_backend
    STATE.gpu_names = gpu_names

    if apply_to_scene and bpy.context.scene is not None:
        scene = bpy.context.scene
        if STATE.gpu_available:
            scene.cycles.device = "GPU"
        else:
            scene.cycles.device = "CPU"
        # Configure denoiser safely (ARM64 Linux packages may omit OpenImageDenoise)
        try:
            scene.cycles.use_denoising = True
            if STATE.gpu_backend == "OPTIX":
                scene.cycles.denoiser = "OPTIX"
            else:
                scene.cycles.denoiser = "OPENIMAGEDENOISE"
        except Exception:
            try:
                scene.cycles.use_denoising = False
            except Exception:
                pass

    return {
        "gpu_available": STATE.gpu_available,
        "gpu_backend": STATE.gpu_backend,
        "gpu_names": STATE.gpu_names,
    }


def vec_to_list(v: Any) -> list[float]:
    return [round(float(x), 5) for x in v]


def build_scene_summary(include_details: bool = True) -> dict[str, Any]:
    scene = bpy.context.scene
    objs_out: list[dict[str, Any]] = []
    lights_out: list[dict[str, Any]] = []

    for obj in scene.objects:
        mats = []
        if hasattr(obj, "material_slots"):
            mats = [slot.material.name for slot in obj.material_slots if slot.material]
        entry: dict[str, Any] = {
            "name": obj.name,
            "type": obj.type,
            "location": vec_to_list(obj.location),
            "rotation_euler": vec_to_list(obj.rotation_euler),
            "scale": vec_to_list(obj.scale),
            "dimensions": vec_to_list(obj.dimensions),
            "materials": mats,
            "hide_render": bool(obj.hide_render),
            "visible": bool(obj.visible_get()),
        }
        if obj.parent is not None:
            entry["parent"] = obj.parent.name
        objs_out.append(entry)
        if obj.type == "LIGHT" and obj.data is not None:
            lights_out.append(
                {
                    "name": obj.name,
                    "light_type": obj.data.type,
                    "energy": round(float(obj.data.energy), 4),
                    "color": vec_to_list(obj.data.color),
                }
            )

    data: dict[str, Any] = {
        "scene_name": scene.name,
        "active_project": STATE.active_project,
        "engine": scene.render.engine,
        "cycles_device": getattr(scene.cycles, "device", "CPU"),
        "resolution": [int(scene.render.resolution_x), int(scene.render.resolution_y)],
        "resolution_percentage": int(scene.render.resolution_percentage),
        "fps": int(scene.render.fps),
        "frame_current": int(scene.frame_current),
        "frame_start": int(scene.frame_start),
        "frame_end": int(scene.frame_end),
        "active_camera": scene.camera.name if scene.camera else None,
        "object_count": len(scene.objects),
        "objects": objs_out,
    }
    if include_details:
        data["collections"] = [c.name for c in bpy.data.collections]
        data["lights"] = lights_out
        data["materials"] = [m.name for m in bpy.data.materials]
        data["cameras"] = [o.name for o in scene.objects if o.type == "CAMERA"]
        if scene.world and scene.world.use_nodes:
            bg = scene.world.node_tree.nodes.get("Background")
            if bg:
                data["world_background"] = {
                    "color": vec_to_list(bg.inputs[0].default_value),
                    "strength": round(float(bg.inputs[1].default_value), 4),
                }
    return data


def get_health_payload() -> dict[str, Any]:
    scene = bpy.context.scene
    return {
        "ok": True,
        "backend": BACKEND_NAME,
        "blender_version": bpy.app.version_string,
        "arch": platform.machine(),
        "gpu_available": STATE.gpu_available,
        "gpu_backend": STATE.gpu_backend,
        "gpu_names": STATE.gpu_names,
        "active_project": STATE.active_project,
        "object_count": len(scene.objects) if scene else 0,
        "active_engine": scene.render.engine if scene else None,
        "workspace_dir": WORKSPACE_DIR,
    }


def point_camera_at(cam_obj: bpy.types.Object, target: Vector) -> None:
    direction = target - cam_obj.location
    rot_quat = direction.to_track_quat("-Z", "Y")
    cam_obj.rotation_euler = rot_quat.to_euler()


def compute_scene_bounds(scene: bpy.types.Scene) -> tuple[Vector, float]:
    geom_types = {"MESH", "CURVE", "SURFACE", "META", "FONT", "GPENCIL", "VOLUME"}
    pts: list[Vector] = []
    for obj in scene.objects:
        if obj.hide_render:
            continue
        if obj.type in geom_types:
            for corner in obj.bound_box:
                pts.append(obj.matrix_world @ Vector(corner))
    if not pts:
        for obj in scene.objects:
            if obj.type not in ("CAMERA", "LIGHT") and not obj.hide_render:
                pts.append(obj.matrix_world.translation.copy())
    if not pts:
        return Vector((0.0, 0.0, 0.6)), 3.0

    min_v = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    max_v = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (min_v + max_v) * 0.5
    diag = (max_v - min_v).length
    return center, max(diag, 1.2)


def handle_exec(payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Missing non-empty 'code' string")

    if payload.get("reset_namespace"):
        STATE.reset_exec_globals()

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    ok = True
    err_msg = None
    tb_str = None

    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        try:
            compiled = compile(code, "<blender_mcp_exec>", "exec")
            exec(compiled, STATE.exec_globals)
        except Exception as exc:
            ok = False
            err_msg = str(exc)
            tb_str = traceback.format_exc()

    res: dict[str, Any] = {
        "ok": ok,
        "backend": BACKEND_NAME,
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
    }
    if not ok:
        res["error"] = err_msg
        res["traceback"] = tb_str
    if payload.get("return_scene_summary", True):
        res["scene_summary"] = build_scene_summary(include_details=False)
    return res


def handle_scene_info() -> dict[str, Any]:
    info = build_scene_summary(include_details=True)
    info["ok"] = True
    info["backend"] = BACKEND_NAME
    return info


def handle_object_info(name: str) -> dict[str, Any]:
    if not name:
        raise ValueError("Missing object 'name'")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise KeyError(f"Object '{name}' not found")

    world_corners = [vec_to_list(obj.matrix_world @ Vector(c)) for c in obj.bound_box]
    min_b = [round(min(c[i] for c in world_corners), 5) for i in range(3)]
    max_b = [round(max(c[i] for c in world_corners), 5) for i in range(3)]

    info: dict[str, Any] = {
        "ok": True,
        "backend": BACKEND_NAME,
        "name": obj.name,
        "type": obj.type,
        "location": vec_to_list(obj.location),
        "rotation_euler": vec_to_list(obj.rotation_euler),
        "rotation_mode": obj.rotation_mode,
        "scale": vec_to_list(obj.scale),
        "dimensions": vec_to_list(obj.dimensions),
        "world_bounds": {"min": min_b, "max": max_b},
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "parent": obj.parent.name if obj.parent else None,
        "children": [c.name for c in obj.children],
        "collections": [c.name for c in obj.users_collection],
        "modifiers": [{"name": m.name, "type": m.type} for m in obj.modifiers],
        "material_slots": [
            slot.material.name if slot.material else None for slot in obj.material_slots
        ],
    }

    if obj.type == "MESH" and obj.data is not None:
        mesh = obj.data
        info["mesh"] = {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "uv_layers": [uv.name for uv in mesh.uv_layers],
            "shape_keys": (
                [kb.name for kb in mesh.shape_keys.key_blocks] if mesh.shape_keys else []
            ),
        }
    elif obj.type == "CAMERA" and obj.data is not None:
        cam = obj.data
        info["camera"] = {
            "lens": round(float(cam.lens), 3),
            "clip_start": round(float(cam.clip_start), 4),
            "clip_end": round(float(cam.clip_end), 2),
            "dof_enabled": bool(cam.dof.use_dof),
        }
    elif obj.type == "LIGHT" and obj.data is not None:
        lt = obj.data
        info["light"] = {
            "light_type": lt.type,
            "energy": round(float(lt.energy), 4),
            "color": vec_to_list(lt.color),
        }

    if obj.animation_data and obj.animation_data.action:
        act = obj.animation_data.action
        info["animation"] = {
            "action": act.name,
            "fcurve_count": len(act.fcurves),
            "frame_range": [round(float(act.frame_range[0]), 2), round(float(act.frame_range[1]), 2)],
        }
    return info


def handle_render(payload: dict[str, Any]) -> dict[str, Any]:
    scene = bpy.context.scene
    fmt = str(payload.get("format", "PNG")).strip().upper()
    if fmt == "JPG":
        fmt = "JPEG"
    is_video = fmt in ("MP4", "FFMPEG")

    default_ext = ".mp4" if is_video else (".jpg" if fmt == "JPEG" else ".png")
    raw_filename = payload.get("filename")
    if raw_filename:
        fname = sanitize_name(os.path.basename(str(raw_filename)), fallback="preview" + default_ext)
        if not os.path.splitext(fname)[1]:
            fname += default_ext
    else:
        fname = f"preview_{int(time.time())}{default_ext}"

    rel_path = f"renders/{fname}"
    abs_out = safe_workspace_path(rel_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)

    width = int(payload.get("width", 1024))
    height = int(payload.get("height", 1024))
    width = max(64, min(width, 4096))
    height = max(64, min(height, 4096))

    engine_req = payload.get("engine")
    if engine_req:
        engine = normalize_engine_name(str(engine_req))
    else:
        engine = "CYCLES" if STATE.gpu_available else get_eevee_engine_id()

    samples = payload.get("samples")
    if samples is None:
        samples = 48 if (engine == "CYCLES" and STATE.gpu_available) else (24 if engine == "CYCLES" else 32)
    samples = max(1, min(int(samples), 2048))

    # Save previous settings to restore cleanly if needed
    prev_cam = scene.camera
    prev_engine = scene.render.engine
    prev_rx = scene.render.resolution_x
    prev_ry = scene.render.resolution_y
    prev_rp = scene.render.resolution_percentage
    prev_filepath = scene.render.filepath
    prev_file_format = scene.render.image_settings.file_format
    prev_transparent = scene.render.film_transparent

    temp_cam_obj = None
    temp_cam_data = None

    try:
        scene.render.engine = engine
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.resolution_percentage = 100
        scene.render.filepath = abs_out
        scene.render.film_transparent = bool(payload.get("transparent", False))

        if engine == "CYCLES":
            use_gpu = payload.get("use_gpu", STATE.gpu_available)
            scene.cycles.device = "GPU" if (use_gpu and STATE.gpu_available) else "CPU"
            scene.cycles.samples = samples
            try:
                scene.cycles.use_denoising = True
                if scene.cycles.device == "GPU" and STATE.gpu_backend == "OPTIX":
                    scene.cycles.denoiser = "OPTIX"
                else:
                    scene.cycles.denoiser = "OPENIMAGEDENOISE"
            except Exception:
                try:
                    scene.cycles.use_denoising = False
                except Exception:
                    pass
        elif engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
            try:
                scene.eevee.taa_render_samples = samples
            except Exception:
                pass

        cam_arg = payload.get("camera")
        auto_cam = payload.get("auto_camera")
        if cam_arg and str(cam_arg).lower() != "auto":
            cam_obj = bpy.data.objects.get(str(cam_arg))
            if cam_obj is None or cam_obj.type != "CAMERA":
                raise KeyError(f"Camera '{cam_arg}' not found")
            scene.camera = cam_obj
        elif str(cam_arg).lower() == "auto" or (scene.camera is None and auto_cam is not False):
            center, diag = compute_scene_bounds(scene)
            dist = max(diag * 1.45, 2.2)
            temp_cam_data = bpy.data.cameras.new("_MCP_AutoPreviewCam")
            temp_cam_data.lens = 45.0
            temp_cam_data.clip_end = max(1000.0, dist * 10.0)
            temp_cam_obj = bpy.data.objects.new("_MCP_AutoPreviewCam", temp_cam_data)
            scene.collection.objects.link(temp_cam_obj)
            temp_cam_obj.location = center + Vector((dist * 0.72, -dist * 0.82, dist * 0.50))
            point_camera_at(temp_cam_obj, center)
            scene.camera = temp_cam_obj

        if scene.camera is None:
            raise RuntimeError("No active camera in scene and auto_camera disabled")

        t0 = time.monotonic()
        if is_video:
            scene.render.image_settings.file_format = "FFMPEG"
            scene.render.ffmpeg.format = "MPEG4"
            scene.render.ffmpeg.codec = "H264"
            scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
            if payload.get("frame_start") is not None:
                scene.frame_start = int(payload["frame_start"])
            if payload.get("frame_end") is not None:
                scene.frame_end = int(payload["frame_end"])
            bpy.ops.render.render(animation=True)
        else:
            scene.render.image_settings.file_format = "JPEG" if fmt == "JPEG" else "PNG"
            if fmt == "PNG":
                scene.render.image_settings.color_mode = "RGBA" if scene.render.film_transparent else "RGB"
            if payload.get("frame") is not None:
                scene.frame_set(int(payload["frame"]))
            bpy.ops.render.render(write_still=True)

        elapsed = round(time.monotonic() - t0, 3)

        # Blender appends frame number if filepath doesn't match or for some modes; ensure exact output path exists
        if not os.path.exists(abs_out):
            raise RuntimeError(f"Render completed but output file missing at {abs_out}")

        drive_copy = mirror_to_drive(rel_path, abs_out)
        size_bytes = os.path.getsize(abs_out)
        return {
            "ok": True,
            "backend": BACKEND_NAME,
            "rel_path": rel_path,
            "filename": fname,
            "format": "MP4" if is_video else fmt,
            "width": width,
            "height": height,
            "engine": engine,
            "device": getattr(scene.cycles, "device", "CPU") if engine == "CYCLES" else ("GPU" if BACKEND_NAME == "colab" else "CPU"),
            "samples": samples,
            "render_seconds": elapsed,
            "size_bytes": size_bytes,
            "drive_backup": drive_copy,
        }
    finally:
        scene.camera = prev_cam
        scene.render.engine = prev_engine
        scene.render.resolution_x = prev_rx
        scene.render.resolution_y = prev_ry
        scene.render.resolution_percentage = prev_rp
        scene.render.filepath = prev_filepath
        scene.render.image_settings.file_format = prev_file_format
        scene.render.film_transparent = prev_transparent
        if temp_cam_obj is not None:
            bpy.data.objects.remove(temp_cam_obj, do_unlink=True)
        if temp_cam_data is not None:
            bpy.data.cameras.remove(temp_cam_data, do_unlink=True)


def download_to_assets(url: str, ext_hint: str | None = None) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Asset URL must start with http:// or https://")
    base = os.path.basename(parsed.path) or "asset"
    if not os.path.splitext(base)[1] and ext_hint:
        base += "." + ext_hint.lstrip(".")
    safe_base = sanitize_name(base, fallback="asset.glb")
    dest = safe_workspace_path(f"assets/{int(time.time())}_{safe_base}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": "BlenderHybridMCP/1.0"})
    total = 0
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMPORT_BYTES:
                out.close()
                try:
                    os.remove(dest)
                except OSError:
                    pass
                raise ValueError(f"Asset exceeds max download limit ({MAX_IMPORT_BYTES} bytes)")
            out.write(chunk)
    return dest


def handle_import_asset(payload: dict[str, Any]) -> dict[str, Any]:
    url = payload.get("url")
    rel_path = payload.get("rel_path")
    fmt_hint = str(payload.get("format") or "").strip().lower().lstrip(".")

    if url:
        local_file = download_to_assets(str(url), fmt_hint or None)
    elif rel_path:
        local_file = safe_workspace_path(str(rel_path))
        if not os.path.isfile(local_file):
            raise FileNotFoundError(f"Asset file not found: {rel_path}")
    else:
        raise ValueError("Provide either 'url' or 'rel_path'")

    ext = fmt_hint or os.path.splitext(local_file)[1].lower().lstrip(".")
    before = set(bpy.data.objects.keys())

    if ext in ("glb", "gltf"):
        bpy.ops.import_scene.gltf(filepath=local_file)
    elif ext == "obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=local_file)
        else:
            bpy.ops.import_scene.obj(filepath=local_file)
    elif ext == "fbx":
        bpy.ops.import_scene.fbx(filepath=local_file)
    elif ext == "stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=local_file)
        else:
            bpy.ops.import_mesh.stl(filepath=local_file)
    elif ext == "blend":
        with bpy.data.libraries.load(local_file, link=False) as (data_from, data_to):
            data_to.objects = list(data_from.objects)
        for obj in data_to.objects:
            if obj is not None and obj.name not in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.link(obj)
    else:
        raise ValueError(f"Unsupported asset format '.{ext}'. Supported: glb, gltf, obj, fbx, stl, blend")

    added_names = [n for n in bpy.data.objects.keys() if n not in before]
    added_objs = [bpy.data.objects[n] for n in added_names]
    added_set = set(added_names)
    roots = [o for o in added_objs if o.parent is None or o.parent.name not in added_set]

    loc = payload.get("location")
    if isinstance(loc, (list, tuple)) and len(loc) == 3:
        offset = Vector((float(loc[0]), float(loc[1]), float(loc[2])))
        for r in roots:
            r.location = r.location + offset

    scl = payload.get("scale")
    if isinstance(scl, (int, float)):
        sv = Vector((float(scl), float(scl), float(scl)))
        for r in roots:
            r.scale = Vector((r.scale.x * sv.x, r.scale.y * sv.y, r.scale.z * sv.z))
    elif isinstance(scl, (list, tuple)) and len(scl) == 3:
        sv = Vector((float(scl[0]), float(scl[1]), float(scl[2])))
        for r in roots:
            r.scale = Vector((r.scale.x * sv.x, r.scale.y * sv.y, r.scale.z * sv.z))

    prefix = payload.get("name_prefix")
    if prefix:
        pstr = sanitize_name(str(prefix), fallback="asset")
        renamed = []
        for o in added_objs:
            o.name = f"{pstr}_{o.name}"
            renamed.append(o.name)
        added_names = renamed

    return {
        "ok": True,
        "backend": BACKEND_NAME,
        "imported_file": os.path.relpath(local_file, WORKSPACE_DIR),
        "added_objects": added_names,
        "root_objects": [r.name for r in roots],
    }


def setup_studio_scene() -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES" if STATE.gpu_available else get_eevee_engine_id()
    configure_cycles_devices(apply_to_scene=True)

    # Dark studio world
    if scene.world is None:
        scene.world = bpy.data.worlds.new("StudioWorld")
    scene.world.use_nodes = True
    nt = scene.world.node_tree
    bg = nt.nodes.get("Background")
    if bg is None:
        bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs[0].default_value = (0.04, 0.048, 0.068, 1.0)
    bg.inputs[1].default_value = 1.0

    # Ground floor
    bpy.ops.mesh.primitive_plane_add(size=18.0, location=(0.0, 0.0, 0.0))
    floor = bpy.context.active_object
    floor.name = "StudioFloor"
    floor_mat = bpy.data.materials.new("StudioFloorMat")
    floor_mat.use_nodes = True
    bsdf = floor_mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.055, 0.062, 0.08, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.62
    floor.data.materials.append(floor_mat)

    target = Vector((0.0, 0.0, 0.8))

    def add_area_light(name: str, loc: tuple[float, float, float], energy: float, size: float, color: tuple[float, float, float]) -> None:
        ldata = bpy.data.lights.new(name=name, type="AREA")
        ldata.energy = energy
        ldata.size = size
        ldata.color = color
        lobj = bpy.data.objects.new(name=name, object_data=ldata)
        scene.collection.objects.link(lobj)
        lobj.location = Vector(loc)
        point_camera_at(lobj, target)

    add_area_light("KeyLight", (3.6, -3.4, 4.2), 260.0, 2.2, (1.0, 0.96, 0.91))
    add_area_light("FillLight", (-4.2, -2.6, 2.6), 110.0, 3.0, (0.76, 0.86, 1.0))
    add_area_light("RimLight", (-1.5, 4.2, 3.4), 210.0, 2.0, (0.68, 0.88, 1.0))

    cam_data = bpy.data.cameras.new("MainCamera")
    cam_data.lens = 50.0
    cam_obj = bpy.data.objects.new("MainCamera", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = Vector((3.8, -4.4, 2.5))
    point_camera_at(cam_obj, target)
    scene.camera = cam_obj


def handle_scene_reset(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode", "studio")).strip().lower()
    if mode not in ("empty", "studio"):
        raise ValueError("reset mode must be 'empty' or 'studio'")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    STATE.active_project = None
    STATE.reset_exec_globals()
    configure_cycles_devices(apply_to_scene=True)

    if mode == "studio":
        setup_studio_scene()

    return {
        "ok": True,
        "backend": BACKEND_NAME,
        "mode": mode,
        "scene_summary": build_scene_summary(include_details=True),
    }


def handle_scene_save(payload: dict[str, Any]) -> dict[str, Any]:
    raw_name = payload.get("project_name") or STATE.active_project or "untitled"
    proj = sanitize_project_name(str(raw_name))
    rel_path = f"projects/{proj}.blend"
    abs_path = safe_workspace_path(rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    if payload.get("pack_resources", True):
        try:
            bpy.ops.file.pack_all()
        except Exception:
            pass

    bpy.ops.wm.save_as_mainfile(filepath=abs_path)
    STATE.active_project = proj
    drive_copy = mirror_to_drive(rel_path, abs_path)

    return {
        "ok": True,
        "backend": BACKEND_NAME,
        "project_name": proj,
        "rel_path": rel_path,
        "size_bytes": os.path.getsize(abs_path),
        "drive_backup": drive_copy,
    }


def handle_scene_load(payload: dict[str, Any]) -> dict[str, Any]:
    raw_name = payload.get("project_name")
    if not raw_name:
        raise ValueError("Missing 'project_name'")
    proj = sanitize_project_name(str(raw_name))
    rel_path = f"projects/{proj}.blend"
    abs_path = safe_workspace_path(rel_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Project file not found: {rel_path}")

    bpy.ops.wm.open_mainfile(filepath=abs_path)
    STATE.active_project = proj
    configure_cycles_devices(apply_to_scene=True)

    return {
        "ok": True,
        "backend": BACKEND_NAME,
        "project_name": proj,
        "rel_path": rel_path,
        "scene_summary": build_scene_summary(include_details=True),
    }


def handle_files_list() -> dict[str, Any]:
    ensure_workspace_dirs()
    out: dict[str, list[dict[str, Any]]] = {}
    for sub in SUBDIRS:
        items: list[dict[str, Any]] = []
        sub_dir = os.path.join(WORKSPACE_DIR, sub)
        if os.path.isdir(sub_dir):
            for entry in sorted(os.scandir(sub_dir), key=lambda e: e.stat().st_mtime, reverse=True):
                if entry.is_file():
                    st = entry.stat()
                    items.append(
                        {
                            "name": entry.name,
                            "rel_path": f"{sub}/{entry.name}",
                            "size_bytes": st.st_size,
                            "mtime": int(st.st_mtime),
                        }
                    )
        out[sub] = items
    return {"ok": True, "backend": BACKEND_NAME, "files": out}


# Main-thread job queue
JOB_QUEUE: queue.Queue[tuple[Any, threading.Event, dict[str, Any]]] = queue.Queue()


def run_on_main_thread(fn: Any, timeout: float = 600.0) -> Any:
    ev = threading.Event()
    box: dict[str, Any] = {}
    JOB_QUEUE.put((fn, ev, box))
    if not ev.wait(timeout=timeout):
        raise TimeoutError("Timed out waiting for Blender main thread execution")
    if "exc" in box:
        raise box["exc"]
    return box["res"]


class WorkerHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep stdout clean for Blender / systemd journal
        pass

    def send_json(self, status: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_error_json(self, status: int, message: str, detail: str | None = None) -> None:
        payload: dict[str, Any] = {"ok": False, "error": message, "backend": BACKEND_NAME}
        if detail:
            payload["detail"] = detail
        self.send_json(status, payload)

    def check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {API_TOKEN}"
        return hmac.compare_digest(auth.encode("utf-8"), expected.encode("utf-8"))

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        if length > 20 * 1024 * 1024:
            raise ValueError("JSON body too large")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path

        if route == "/health":
            try:
                res = run_on_main_thread(get_health_payload, timeout=15.0)
                self.send_json(200, res)
            except Exception as exc:
                self.send_error_json(500, str(exc))
            return

        if not self.check_auth():
            self.send_error_json(401, "Unauthorized")
            return

        try:
            if route == "/scene_info":
                res = run_on_main_thread(handle_scene_info, timeout=30.0)
                self.send_json(200, res)
            elif route == "/object_info":
                qs = urllib.parse.parse_qs(parsed.query)
                name = (qs.get("name") or [""])[0]
                res = run_on_main_thread(lambda: handle_object_info(name), timeout=30.0)
                self.send_json(200, res)
            elif route == "/files/list":
                res = handle_files_list()
                self.send_json(200, res)
            elif route == "/files/download":
                qs = urllib.parse.parse_qs(parsed.query)
                rel = (qs.get("path") or [""])[0]
                abs_path = safe_workspace_path(rel)
                if not os.path.isfile(abs_path):
                    self.send_error_json(404, f"File not found: {rel}")
                    return
                size = os.path.getsize(abs_path)
                ctype, _ = mimetypes.guess_type(abs_path)
                self.send_response(200)
                self.send_header("Content-Type", ctype or "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with open(abs_path, "rb") as f:
                    while True:
                        chunk = f.read(256 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            else:
                self.send_error_json(404, f"Unknown GET endpoint: {route}")
        except KeyError as exc:
            self.send_error_json(404, str(exc))
        except FileNotFoundError as exc:
            self.send_error_json(404, str(exc))
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:
            self.send_error_json(500, str(exc), traceback.format_exc())

    def do_POST(self) -> None:
        if not self.check_auth():
            self.send_error_json(401, "Unauthorized")
            return

        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path

        try:
            if route == "/files/upload":
                qs = urllib.parse.parse_qs(parsed.query)
                rel = (qs.get("path") or [""])[0]
                abs_path = safe_workspace_path(rel)
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0 or length > MAX_UPLOAD_BYTES:
                    self.send_error_json(400, f"Invalid Content-Length: {length}")
                    return
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                tmp_path = abs_path + f".tmp.{threading.get_ident()}"
                remaining = length
                with open(tmp_path, "wb") as out:
                    while remaining > 0:
                        chunk = self.rfile.read(min(256 * 1024, remaining))
                        if not chunk:
                            raise EOFError("Client disconnected during upload")
                        out.write(chunk)
                        remaining -= len(chunk)
                os.replace(tmp_path, abs_path)
                drive_copy = mirror_to_drive(rel.replace("\\", "/").lstrip("/"), abs_path)
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "backend": BACKEND_NAME,
                        "rel_path": rel,
                        "size_bytes": length,
                        "drive_backup": drive_copy,
                    },
                )
                return

            payload = self.read_json_body()
            if route == "/exec":
                res = run_on_main_thread(lambda: handle_exec(payload), timeout=180.0)
                self.send_json(200, res)
            elif route == "/render":
                res = run_on_main_thread(lambda: handle_render(payload), timeout=600.0)
                self.send_json(200, res)
            elif route == "/import_asset":
                res = run_on_main_thread(lambda: handle_import_asset(payload), timeout=180.0)
                self.send_json(200, res)
            elif route == "/scene/reset":
                res = run_on_main_thread(lambda: handle_scene_reset(payload), timeout=60.0)
                self.send_json(200, res)
            elif route == "/scene/save":
                res = run_on_main_thread(lambda: handle_scene_save(payload), timeout=120.0)
                self.send_json(200, res)
            elif route == "/scene/load":
                res = run_on_main_thread(lambda: handle_scene_load(payload), timeout=120.0)
                self.send_json(200, res)
            else:
                self.send_error_json(404, f"Unknown POST endpoint: {route}")
        except KeyError as exc:
            self.send_error_json(404, str(exc))
        except FileNotFoundError as exc:
            self.send_error_json(404, str(exc))
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:
            self.send_error_json(500, str(exc), traceback.format_exc())


class ReusableThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    ensure_workspace_dirs()
    gpu_info = configure_cycles_devices(apply_to_scene=True)
    # Initialize clean studio scene on boot if scene has just factory startup objects
    try:
        setup_studio_scene_needed = len(bpy.context.scene.objects) <= 3 and "Cube" in bpy.data.objects
        if setup_studio_scene_needed:
            handle_scene_reset({"mode": "studio"})
    except Exception as exc:
        print(f"[blender_worker] Initial studio scene setup warning: {exc}", file=sys.stderr, flush=True)

    server = ReusableThreadingHTTPServer((HOST, PORT), WorkerHandler)
    http_thread = threading.Thread(target=server.serve_forever, daemon=True)
    http_thread.start()

    print(
        f"[blender_worker] Listening on http://{HOST}:{PORT} "
        f"(backend={BACKEND_NAME}, blender={bpy.app.version_string}, arch={platform.machine()}, gpu={gpu_info})",
        flush=True,
    )

    try:
        while True:
            fn, ev, box = JOB_QUEUE.get()
            try:
                box["res"] = fn()
            except BaseException as exc:  # keep main thread alive across any Python/bpy error
                box["exc"] = exc
            finally:
                ev.set()
    except KeyboardInterrupt:
        print("[blender_worker] Shutting down...", flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
