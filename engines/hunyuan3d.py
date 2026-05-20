"""Hunyuan3D-2 Engine — single and multi-view image-to-3D with PBR textures."""

import gc
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, List, Union

import torch
from PIL import Image

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# huggingface_hub removed cached_download in ≥ 0.17; hy3dshape imports it at module
# level, so this shim must run before any `import hy3dshape` anywhere in the process.
# Wrapped in try/except so the test environment (no huggingface_hub) can still import.
try:
    import huggingface_hub as _hfhub  # noqa: E402

    if not hasattr(_hfhub, "cached_download"):
        _hfhub.cached_download = _hfhub.hf_hub_download
except ImportError:
    pass

# Model configs on HuggingFace Hub reference the old package name `hy3dgen.*`.
# The Space renamed it to `hy3dshape`. Install a meta-path finder that redirects
# any `hy3dgen` import to the corresponding `hy3dshape` module at runtime.
import importlib as _importlib
import types as _types


class _Hy3dgenFinder:
    # The old hy3dgen package was split: hy3dgen.shapegen → hy3dshape (the whole pkg).
    # Model configs downloaded from HF Hub still reference hy3dgen.shapegen.models.*
    # Mapping: hy3dgen / hy3dgen.shapegen → hy3dshape
    #          hy3dgen.shapegen.X         → hy3dshape.X

    def find_module(self, fullname, path=None):
        if fullname == "hy3dgen" or fullname.startswith("hy3dgen."):
            return self
        return None

    def _to_hy3dshape(self, fullname):
        if fullname in ("hy3dgen", "hy3dgen.shapegen"):
            return "hy3dshape"
        if fullname.startswith("hy3dgen.shapegen."):
            return "hy3dshape." + fullname[len("hy3dgen.shapegen.") :]
        if fullname.startswith("hy3dgen."):
            return "hy3dshape." + fullname[len("hy3dgen.") :]
        return "hy3dshape"

    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
        target = self._to_hy3dshape(fullname)
        try:
            mod = _importlib.import_module(target)
        except ImportError:
            mod = _types.ModuleType(fullname)
        sys.modules[fullname] = mod
        return mod


if not any(isinstance(f, _Hy3dgenFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _Hy3dgenFinder())

from engines.base_engine import Engine, EngineConfig
from utils.logger import get_logger
from utils.pre_processor import ImagePreprocessor, ImageValidator

logger = get_logger()

# HuggingFace Space clone location (set in Dockerfile)
_SPACE_DIR = Path("/opt/hunyuan3d-space")

# Hunyuan3D-2mv view2idx only supports the 4 cardinal directions.
# front_left / front_right are not in preprocessors.view2idx → KeyError.
_VIEW_LABELS = ["front", "right", "back", "left"]

# Texture quality tiers — tried in order, stepped down on CUDA OOM
_PAINT_TIERS = [
    {
        "views": 8,
        "resolution": 512,
        "render_size": 1024,
        "texture_size": 1024,
        "label": "high",
    },
    {
        "views": 6,
        "resolution": 512,
        "render_size": 1024,
        "texture_size": 1024,
        "label": "med",
    },
    {
        "views": 4,
        "resolution": 512,
        "render_size": 512,
        "texture_size": 1024,
        "label": "low",
    },
]


class Hunyuan3DEngine(Engine):
    """Hunyuan3D-2 image-to-3D.

    1 image  → Hunyuan3D-2.1 (tencent/Hunyuan3D-2.1, single-view DiT)
    2–6 imgs → Hunyuan3D-2mv (tencent/Hunyuan3D-2mv, multi-view DiT)

    Texture: Hunyuan3DPaint pipeline from cloned HF Space (file-path based API).
    """

    SINGLE_MODEL_ID = "tencent/Hunyuan3D-2.1"
    SINGLE_SUBFOLDER = "hunyuan3d-dit-v2-1"
    MULTI_MODEL_ID = "tencent/Hunyuan3D-2mv"
    MULTI_SUBFOLDER = "hunyuan3d-dit-v2-mv"

    def __init__(self, config: EngineConfig):
        super().__init__(config)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.shapegen = None

    def validate_prerequisites(self) -> bool:
        # GPU attachment can lag by a few seconds on freshly provisioned
        # Container Apps nodes — retry rather than fail immediately.
        for attempt in range(6):
            if torch.cuda.is_available():
                break
            wait = 10 * (attempt + 1)
            logger.warning(
                f"CUDA not ready (attempt {attempt + 1}/6), retrying in {wait}s…"
            )
            time.sleep(wait)
        else:
            raise RuntimeError("CUDA not available — Hunyuan3D-2 requires GPU")
        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        if total_gb < 14:
            raise RuntimeError(f"GPU has {total_gb:.1f}GB; need 14GB+ for Hunyuan3D-2")
        logger.info(f"GPU memory OK: {total_gb:.1f}GB")

        try:
            import hy3dshape  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(f"hy3dshape not installed in container: {exc}")

        realesr_ckpt = _SPACE_DIR / "hy3dpaint/ckpt/RealESRGAN_x4plus.pth"
        if not realesr_ckpt.exists():
            raise RuntimeError(
                f"RealESRGAN checkpoint missing: {realesr_ckpt} — "
                "Space clone incomplete or git-lfs pull failed"
            )
        logger.info("hy3dshape imports OK, RealESRGAN checkpoint present")
        return True

    def preprocess(self, image_paths: Union[str, List[str]]) -> List[Image.Image]:
        if isinstance(image_paths, str):
            image_paths = [image_paths]

        validated = ImageValidator.validate_input_images(
            image_paths, allow_directory=False
        )
        if len(validated) > self.config.max_images:
            logger.warning(
                f"Got {len(validated)} images, using first {self.config.max_images}"
            )
            validated = validated[: self.config.max_images]

        images = []
        for path in validated:
            img = ImagePreprocessor.load_image(path).convert("RGBA")
            try:
                import rembg

                session = rembg.new_session("birefnet-general")
                img = rembg.remove(img, session=session)
                logger.info(
                    f"Background removed (birefnet-general): {Path(path).name} "
                    f"→ {img.mode} {img.size}"
                )
            except Exception as e:
                logger.warning(f"Background removal failed ({e}), using original")
            images.append(img)

        logger.info(f"Preprocessed {len(images)} image(s)")
        return images

    def infer(self, images: List[Image.Image]) -> Any:
        """Shape generation. Returns (mesh, tmp_dir, front_img_path)."""
        if not images:
            raise ValueError("No preprocessed images supplied")

        from hy3dshape import Hunyuan3DDiTFlowMatchingPipeline

        # Cap at supported view count (2mv only knows front/right/back/left)
        n = min(len(images), len(_VIEW_LABELS))
        images = images[:n]
        is_multi = n > 1
        model_id = self.MULTI_MODEL_ID if is_multi else self.SINGLE_MODEL_ID
        subfolder = self.MULTI_SUBFOLDER if is_multi else self.SINGLE_SUBFOLDER

        logger.info(
            f"Loading shape pipeline: {model_id}/{subfolder} ({n} input image(s))"
        )
        self.shapegen = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            model_id,
            subfolder=subfolder,
            use_safetensors=False,
            device=str(self.device),
        )

        if is_multi:
            view_dict = {_VIEW_LABELS[i]: images[i] for i in range(n)}
            logger.info(f"Multi-view shape gen: {list(view_dict.keys())}")
            shape_input = {"image": view_dict}
        else:
            logger.info("Single-view shape gen")
            shape_input = {"image": images[0]}

        t0 = time.time()
        logger.info(
            "Running shape generation (num_inference_steps=50, octree_resolution=384)..."
        )
        mesh = self.shapegen(
            **shape_input,
            num_inference_steps=50,
            octree_resolution=384,
        )[0]
        logger.info(
            f"Shape done in {time.time()-t0:.1f}s — "
            f"{len(mesh.vertices):,}v {len(mesh.faces):,}f"
        )

        # Offload shape pipeline to free VRAM for texture generation
        self.shapegen.to("cpu")
        gc.collect()
        torch.cuda.empty_cache()
        logger.info(
            f"VRAM after shape offload: {torch.cuda.memory_allocated()/1e9:.1f}GB allocated"
        )

        # Save front (first) image for texture reference
        tmp_dir = Path(tempfile.mkdtemp())
        front_img_path = tmp_dir / "front.png"
        images[0].save(str(front_img_path))

        return mesh, tmp_dir, front_img_path

    def postprocess(self, infer_output: Any) -> str:
        """Texture generation then GLB export. Falls back to untextured GLB on failure."""
        mesh, tmp_dir, front_img_path = infer_output
        output_dir = Path("/app/output/hunyuan3d")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # Export shape to OBJ — paint pipeline is file-path based, not trimesh-based
        obj_path = tmp_dir / "shape.obj"
        mesh.export(str(obj_path))
        logger.info(
            f"Shape OBJ: {len(mesh.vertices):,}v {len(mesh.faces):,}f → {obj_path}"
        )

        textured_glb = self._run_texture_with_fallback(
            obj_path, front_img_path, tmp_dir, timestamp, output_dir
        )
        if textured_glb:
            return textured_glb

        # Final fallback: untextured GLB
        logger.warning("Texture pipeline failed entirely; exporting untextured GLB")
        fallback_glb = output_dir / f"hunyuan3d_{timestamp}_raw.glb"
        mesh.export(str(fallback_glb))
        logger.info(
            f"Exported untextured GLB: {len(mesh.vertices):,}v "
            f"{len(mesh.faces):,}f → {fallback_glb}"
        )
        return str(fallback_glb)

    def _run_texture_with_fallback(
        self,
        obj_path: Path,
        img_path: Path,
        tmp_dir: Path,
        timestamp: str,
        output_dir: Path,
    ) -> str | None:
        # Force hy3dpaint to sys.path[0] — it may already be present (from PYTHONPATH)
        # but after /app, so /app/utils would win over hy3dpaint/utils on a fresh search.
        hy3dpaint = str(_SPACE_DIR / "hy3dpaint")
        if hy3dpaint in sys.path:
            sys.path.remove(hy3dpaint)
        sys.path.insert(0, hy3dpaint)

        # /app/utils is already cached in sys.modules (our engine imported it at startup).
        # sys.path ordering alone can't fix this — Python finds the cached module before
        # searching the path. Evict all utils.* entries so textureGenPipeline's
        # `from utils.simplify_mesh_utils import ...` finds hy3dpaint/utils/ instead.
        # Also evict textureGenPipeline itself to force a clean re-import.
        _utils_saved = {
            k: sys.modules.pop(k)
            for k in list(sys.modules)
            if k == "utils" or k.startswith("utils.")
        }
        sys.modules.pop("textureGenPipeline", None)

        # cached_download was removed from huggingface_hub ≥ 0.17; patch before
        # textureGenPipeline (or basicsr/realesrgan) tries to import it.
        import huggingface_hub as _hfhub

        if not hasattr(_hfhub, "cached_download"):
            _hfhub.cached_download = _hfhub.hf_hub_download

        out_glb = output_dir / f"hunyuan3d_{timestamp}.glb"

        try:
            for i, tier in enumerate(_PAINT_TIERS):
                label = tier["label"]
                try:
                    from textureGenPipeline import (  # type: ignore[import]
                        Hunyuan3DPaintConfig,
                        Hunyuan3DPaintPipeline,
                    )

                    conf = Hunyuan3DPaintConfig(tier["views"], tier["resolution"])
                    conf.realesrgan_ckpt_path = str(
                        _SPACE_DIR / "hy3dpaint/ckpt/RealESRGAN_x4plus.pth"
                    )
                    conf.multiview_cfg_path = str(
                        _SPACE_DIR / "hy3dpaint/cfgs/hunyuan-paint-pbr.yaml"
                    )
                    conf.custom_pipeline = str(_SPACE_DIR / "hy3dpaint/hunyuanpaintpbr")
                    conf.render_size = tier["render_size"]
                    conf.texture_size = tier["texture_size"]
                    paint = Hunyuan3DPaintPipeline(conf)

                    out_obj = tmp_dir / f"textured_{label}.obj"
                    t0 = time.time()
                    logger.info(
                        f"Texture tier={label}: views={tier['views']} "
                        f"res={tier['resolution']} tex_size={tier['texture_size']}"
                    )
                    paint(
                        mesh_path=str(obj_path),
                        image_path=str(img_path),
                        output_mesh_path=str(out_obj),
                        save_glb=True,
                    )
                    # Pipeline writes <name>.glb alongside the OBJ
                    candidate_glb = out_obj.with_suffix(".glb")
                    if candidate_glb.exists():
                        shutil.move(str(candidate_glb), str(out_glb))
                        logger.info(
                            f"Texture done in {time.time()-t0:.1f}s "
                            f"(tier={label}) → {out_glb}"
                        )
                        return str(out_glb)
                    logger.warning(
                        f"Texture tier={label}: GLB not found at {candidate_glb}"
                    )

                except Exception as exc:
                    oom = (
                        "out of memory" in str(exc).lower()
                        or "OutOfMemoryError" in type(exc).__name__
                    )
                    gc.collect()
                    torch.cuda.empty_cache()
                    if oom and i < len(_PAINT_TIERS) - 1:
                        logger.warning(
                            f"Texture OOM at tier={label}, stepping down to "
                            f"tier={_PAINT_TIERS[i+1]['label']}"
                        )
                        continue
                    logger.warning(f"Texture failed at tier={label} ({exc})")
                    return None

            return None
        finally:
            # Restore /app/utils so the rest of the engine (logger, post-processor)
            # keeps working after textureGenPipeline loaded hy3dpaint/utils/ instead.
            sys.modules.update(_utils_saved)

    def get_engine_info(self) -> dict:
        info = super().get_engine_info()
        info["model_id"] = f"{self.SINGLE_MODEL_ID} / {self.MULTI_MODEL_ID}"
        return info
