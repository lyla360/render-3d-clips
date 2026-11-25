# 3D Clips Cloud Render Hub (`lyla360/render-3d-clips`)

Single **public** 20-way GitHub Actions **Blender 4.0.2 + Cycles Toon/Freestyle** render hub dedicated exclusively to 3D clips (`InkRoom 3D` Engine v2).

## Repository Layout
```text
engine/
  bru3d_core.py          # InkRoom 3D Engine v2 core (3-Tone Toon + Fresnel Rim + Freestyle + Kinetic Camera)
  polyhaven_loader.py    # Auto CC0 Poly Haven & Rigged GLB/Blend importer (Blend -> glTF fallback)
episodes/
  _template/             # Starter skeleton for new 3D episodes
  grease_fire/           # Production episode: "NEVER Pour Water on a Grease Fire"
    render_short.py
    thumb.html
    assets/audio/master_audio.m4a
.github/workflows/
  render-3d.yml          # Cloud pipeline (chars / preview / thumb / motion / 20x full)
```

## Dispatch Cloud Renders
```bash
# Character / Rig Turnarounds (Gate A)
gh workflow run render-3d.yml -R lyla360/render-3d-clips -f episode=<episode> -f mode=chars

# Storyboard Stills (Gate B)
gh workflow run render-3d.yml -R lyla360/render-3d-clips -f episode=<episode> -f mode=preview

# 3D Thumbnail Views (Stage 7)
gh workflow run render-3d.yml -R lyla360/render-3d-clips -f episode=<episode> -f mode=thumb

# 20-Way Parallel Full Render + Audio Mux (Stage 6)
gh workflow run render-3d.yml -R lyla360/render-3d-clips -f episode=<episode> -f mode=full -f project_slug=<slug>
```
