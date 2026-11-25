"""Template InkRoom 3D Engine v2 production script for `lyla360/render-3d-clips`.

Copy `episodes/_template/` to `episodes/<new_episode>/` and implement your
3D scene, CC0 Poly Haven / GLB prop & rig loaders, kinetic camera segments,
and audio-locked keyframes matching `assets/audio/master_audio.m4a`.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ENGINE = os.path.abspath(os.path.join(HERE, "..", "..", "engine"))
for p in (HERE, REPO_ENGINE):
    if p not in sys.path:
        sys.path.insert(0, p)

import bpy  # noqa: E402
from bru3d_core import (  # noqa: E402
    add_box,
    add_sphere,
    clear_scene,
    keyframe_kinetic_camera,
    make_toon_v2_mat,
    parse_args,
    render_chunk,
    render_named_views,
    render_preview_frames,
    setup_bru3d_render_v2,
    setup_vertical_camera,
)

FPS = 30
TOTAL_FRAMES = 60
PREVIEW_FRAMES = [1, 30, 60]


def build_scene():
    clear_scene()
    scene = setup_bru3d_render_v2(width=1080, height=1920, fps=FPS, total_frames=TOTAL_FRAMES)
    col_world = bpy.data.collections.new("World")
    col_props = bpy.data.collections.new("Props")
    scene.collection.children.link(col_world)
    scene.collection.children.link(col_props)

    floor_mat = make_toon_v2_mat("Floor", (0.85, 0.87, 0.90), specular=0.10, rim_strength=0.10)
    hero_mat = make_toon_v2_mat("HeroAccent", (0.95, 0.42, 0.20), specular=0.35, rim_strength=0.32)

    add_box("Floor", (4.0, 4.0, 0.1), (0.0, 0.0, -0.05), col_world, floor_mat)
    hero = add_sphere("HeroSphere", 0.35, (0.0, 0.0, 0.40), col_props, hero_mat)
    hero.keyframe_insert(data_path="location", frame=1)
    hero.location = (0.0, 0.0, 0.85)
    hero.keyframe_insert(data_path="location", frame=30)
    hero.location = (0.0, 0.0, 0.40)
    hero.keyframe_insert(data_path="location", frame=TOTAL_FRAMES)

    cam_obj, cam_tgt = setup_vertical_camera((0.0, -2.6, 1.0), (0.0, 0.0, 0.55), lens=34.0)
    keyframe_kinetic_camera(
        cam_obj,
        cam_tgt,
        [{"start": 1, "end": TOTAL_FRAMES, "type": "orbit", "center": (0.0, 0.0), "r0": 2.6, "r1": 2.2, "az0": -18.0, "az1": 18.0, "z0": 1.0, "z1": 1.2, "tgt0": (0.0, 0.0, 0.55), "tgt1": (0.0, 0.0, 0.65), "l0": 34.0, "l1": 38.0}],
        TOTAL_FRAMES,
    )
    return scene


def main():
    args = [a for a in sys.argv[sys.argv.index("--") + 1:]] if "--" in sys.argv else []
    mode_token = args[0] if args else "preview"
    build_scene()
    if mode_token == "chars":
        render_named_views([{"filename": "char_hero.png", "frame": 1, "cam_loc": (0.8, -2.0, 0.9), "cam_target": (0.0, 0.0, 0.5), "lens": 36.0}], out_dir="out/chars")
    elif mode_token == "preview":
        render_preview_frames(PREVIEW_FRAMES, out_dir="out/preview")
    elif mode_token == "thumb":
        render_named_views([{"filename": "thumb_hero.png", "frame": 30, "cam_loc": (0.4, -1.8, 1.0), "cam_target": (0.0, 0.0, 0.65), "lens": 35.0}], out_dir="out/thumb")
    elif mode_token == "motion":
        render_chunk(0, 1, min(60, TOTAL_FRAMES), fps=FPS, out_prefix="motion")
        os.makedirs("out/motion", exist_ok=True)
        src_mp4 = "out/ci_chunks/motion_00.mp4"
        if os.path.exists(src_mp4):
            os.replace(src_mp4, "out/motion/motion_test.mp4")
    else:
        _, c_idx, n_chunks = parse_args()
        render_chunk(c_idx, n_chunks, TOTAL_FRAMES, fps=FPS, out_prefix="chunk")


if __name__ == "__main__":
    main()
