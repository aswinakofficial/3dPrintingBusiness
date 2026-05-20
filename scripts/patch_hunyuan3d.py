#!/usr/bin/env python3
"""
Patch Hunyuan3D-2.1 HuggingFace Space for Docker compatibility.

Patch A: Replace hy3dpaint/DifferentiableRenderer/mesh_utils.py
  — removes bpy (Blender Python) dependency; replaces with trimesh + cv2.

Patch B: Fix basicsr torchvision import
  — torchvision.transforms.functional_tensor.rgb_to_grayscale was removed
    in torchvision 0.17+; adds try/except fallback.

Patch C: Fix hy3dshape cached_download import
  — huggingface_hub removed cached_download in ≥ 0.17; hy3dshape source
    imports it directly, so we replace with hf_hub_download alias.
"""
import glob
import importlib.util
import pathlib

SPACE = pathlib.Path("/opt/hunyuan3d-space")


def patch_mesh_utils():
    target = SPACE / "hy3dpaint/DifferentiableRenderer/mesh_utils.py"
    if not target.exists():
        print(f"[SKIP] mesh_utils.py not found at {target}")
        return
    content = target.read_text()
    if "import bpy" not in content and "from bpy" not in content:
        print(
            "[SKIP] mesh_utils: no bpy import found (already patched or changed upstream)"
        )
        return
    target.write_text(_MESH_UTILS_PATCHED)
    print(f"[OK] mesh_utils.py: replaced bpy implementation with trimesh → {target}")


def patch_basicsr():
    candidates = glob.glob(
        str(SPACE / "**" / "basicsr" / "data" / "degradations.py"), recursive=True
    )
    # Also check system-installed basicsr
    spec = importlib.util.find_spec("basicsr")
    if spec and spec.origin:
        candidates.append(
            str(pathlib.Path(spec.origin).parent / "data" / "degradations.py")
        )
    found = False
    for f in candidates:
        p = pathlib.Path(f)
        if not p.exists():
            continue
        content = p.read_text()
        old = "from torchvision.transforms.functional_tensor import rgb_to_grayscale"
        if old not in content:
            print(f"[SKIP] basicsr patch: pattern not found in {p}")
            continue
        new = (
            "try:\n"
            "    from torchvision.transforms.functional_tensor import rgb_to_grayscale\n"
            "except (ModuleNotFoundError, ImportError):\n"
            "    from torchvision.transforms.functional import rgb_to_grayscale"
        )
        p.write_text(content.replace(old, new))
        print(f"[OK] basicsr: patched torchvision rgb_to_grayscale import → {p}")
        found = True
    if not found:
        print("[WARN] basicsr degradations.py not found — skipping")


_MESH_UTILS_PATCHED = '''\
"""mesh_utils.py — bpy-free replacement using trimesh + cv2."""
import numpy as np
import cv2
import trimesh
from pathlib import Path


def load_mesh(mesh):
    vtx_pos = np.float32(mesh.vertices)
    pos_idx = np.int32(mesh.faces)
    has_uv = (
        hasattr(mesh.visual, "uv")
        and mesh.visual.uv is not None
        and len(mesh.visual.uv) > 0
    )
    vtx_uv = np.float32(mesh.visual.uv) if has_uv else np.zeros(
        (len(vtx_pos), 2), dtype=np.float32
    )
    uv_idx = pos_idx
    return vtx_pos, pos_idx, vtx_uv, uv_idx, None


def _save_texture_map(tex, base_path, suffix="", is_normal=False):
    if tex is None:
        return None
    out_path = str(base_path) + suffix + (".png" if is_normal else ".jpg")
    img = np.array(tex) if not isinstance(tex, np.ndarray) else tex
    if img.dtype != np.uint8:
        img = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    if img.ndim == 2:
        cv2.imwrite(out_path, img)
    else:
        cv2.imwrite(out_path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return out_path


def save_obj_mesh(mesh_path, vtx_pos, pos_idx, vtx_uv, uv_idx, texture,
                  metallic=None, roughness=None, normal=None):
    base = Path(mesh_path).with_suffix("")
    mtl_path = str(base) + ".mtl"

    diffuse_path = _save_texture_map(texture, base)
    metallic_path = _save_texture_map(metallic, base, "_metallic", is_normal=True)
    roughness_path = _save_texture_map(roughness, base, "_roughness", is_normal=True)
    normal_path = _save_texture_map(normal, base, "_normal", is_normal=True)

    with open(mtl_path, "w") as f:
        f.write("newmtl material0\\n")
        if diffuse_path:
            f.write(f"map_Kd {Path(diffuse_path).name}\\n")
        if metallic_path:
            f.write(f"map_Pm {Path(metallic_path).name}\\n")
        if roughness_path:
            f.write(f"map_Pr {Path(roughness_path).name}\\n")
        if normal_path:
            f.write(f"map_Bump {Path(normal_path).name}\\n")

    with open(str(mesh_path), "w") as f:
        f.write(f"mtllib {Path(mtl_path).name}\\n")
        for v in vtx_pos:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\\n")
        for uv in vtx_uv:
            f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\\n")
        f.write("usemtl material0\\n")
        for fi, face in enumerate(pos_idx):
            uv_face = uv_idx[fi]
            f.write(
                f"f {face[0]+1}/{uv_face[0]+1} "
                f"{face[1]+1}/{uv_face[1]+1} "
                f"{face[2]+1}/{uv_face[2]+1}\\n"
            )


def save_mesh(mesh_path, vtx_pos, pos_idx, vtx_uv, uv_idx, texture,
              metallic=None, roughness=None, normal=None):
    return save_obj_mesh(
        mesh_path, vtx_pos, pos_idx, vtx_uv, uv_idx, texture,
        metallic, roughness, normal
    )


def convert_obj_to_glb(obj_path, glb_path, **kwargs):
    scene = trimesh.load(str(obj_path), process=False)
    scene.export(str(glb_path), file_type="glb")
    return glb_path
'''


def patch_hy3dshape_cached_download():
    """Replace `from huggingface_hub import cached_download` in hy3dshape source."""
    hy3dshape_dir = SPACE / "hy3dshape"
    if not hy3dshape_dir.exists():
        print(f"[SKIP] hy3dshape dir not found: {hy3dshape_dir}")
        return
    old = "from huggingface_hub import cached_download"
    new = (
        "try:\n"
        "    from huggingface_hub import cached_download\n"
        "except ImportError:\n"
        "    from huggingface_hub import hf_hub_download as cached_download"
    )
    patched = 0
    for py_file in hy3dshape_dir.rglob("*.py"):
        content = py_file.read_text()
        if old not in content:
            continue
        py_file.write_text(content.replace(old, new))
        print(f"[OK] hy3dshape cached_download: patched {py_file}")
        patched += 1
    if patched == 0:
        print("[SKIP] hy3dshape: no cached_download imports found (already clean)")


def patch_texture_gen_pipeline_utils():
    """Add self-path insertion to textureGenPipeline.py so utils.* resolves locally.

    textureGenPipeline does `from utils.simplify_mesh_utils import ...` which
    normally resolves to /app/utils/ (script dir is sys.path[0] at startup).
    Prepending the file's own directory at the top of the module guarantees the
    right utils/ is found regardless of the outer sys.path order.
    """
    target = SPACE / "hy3dpaint/textureGenPipeline.py"
    if not target.exists():
        print(f"[SKIP] textureGenPipeline.py not found at {target}")
        return
    content = target.read_text()
    sentinel = "# _PATCH_SYSPATH_"
    if sentinel in content:
        print("[SKIP] textureGenPipeline: sys.path patch already applied")
        return
    injection = (
        f"{sentinel}\n"
        "import sys as _sys, os as _os\n"
        "_hy3d = _os.path.dirname(_os.path.abspath(__file__))\n"
        "if _hy3d in _sys.path: _sys.path.remove(_hy3d)\n"
        "_sys.path.insert(0, _hy3d)\n"
        "del _hy3d\n"
    )
    target.write_text(injection + content)
    print(f"[OK] textureGenPipeline: sys.path self-insertion patched → {target}")


def patch_hunyuanpaintpbr_attn():
    """Ensure unet.attn_processor.py exists in hy3dpaint/hunyuanpaintpbr/.

    textureGenPipeline (or a diffusers helper it calls) opens this file directly.
    If the Space clone didn't include it, search the rest of the clone first,
    then fall back to a stub that re-exports standard diffusers attention processors.
    """
    import shutil
    target = SPACE / "hy3dpaint/hunyuanpaintpbr/unet.attn_processor.py"
    if target.exists():
        print(f"[SKIP] {target} already exists")
        return
    # Look elsewhere in the Space
    candidates = [p for p in SPACE.rglob("unet.attn_processor.py") if p != target]
    if candidates:
        shutil.copy(str(candidates[0]), str(target))
        print(f"[OK] hunyuanpaintpbr: copied {candidates[0]} → {target}")
        return
    # Create minimal stub — re-exports all standard diffusers attention processors
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '"""unet.attn_processor — diffusers attention processors (auto-generated stub)."""\n'
        "from diffusers.models.attention_processor import *  # noqa: F401,F403\n"
    )
    print(f"[OK] hunyuanpaintpbr: created stub unet.attn_processor.py → {target}")


if __name__ == "__main__":
    patch_mesh_utils()
    patch_basicsr()
    patch_hy3dshape_cached_download()
    patch_texture_gen_pipeline_utils()
    patch_hunyuanpaintpbr_attn()
    print("[DONE] Hunyuan3D-2.1 patches applied")
