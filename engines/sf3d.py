"""SF3D Engine — Stability AI Stable Fast 3D, single-image with UV-baked textures.

Model: stabilityai/stable-fast-3d  (GATED — set HF_TOKEN env var)
Repo:  https://github.com/Stability-AI/stable-fast-3d
Paper: SF3D: Stable Fast 3D Mesh Reconstruction with UV-unwrapping and Illumination Disentanglement

SF3D reconstructs a UV-unwrapped, textured mesh from a single image in under 0.5s.
It uses a triplane transformer + multi-resolution grid + baked PBR texture pipeline.
Unlike Hunyuan3D, it outputs clean geometry without Dual Contouring artifacts, and
produces sharper per-texel colour because it bakes from the latent representation
rather than diffusion inpainting.
"""

import gc
import os
import time
from pathlib import Path
from typing import Any, List, Union

import torch
from PIL import Image

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from engines.base_engine import Engine, EngineConfig  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger()

# Bake quality tiers, tried in order on OOM
_BAKE_TIERS = [
    {"bake_resolution": 2048, "remesh": "quad", "label": "high"},
    {"bake_resolution": 1024, "remesh": "quad", "label": "med"},
    {"bake_resolution": 512,  "remesh": "quad", "label": "low"},
]


class SF3DEngine(Engine):
    """Stable Fast 3D single-image engine (Stability AI).

    Accepts 1 image; returns a UV-unwrapped, PBR-textured GLB in <1s inference.
    Requires HF_TOKEN env var — model is gated on HuggingFace.
    """

    MODEL_ID = "stabilityai/stable-fast-3d"

    def __init__(self, config: EngineConfig):
        super().__init__(config)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model = None

    def validate_prerequisites(self) -> bool:
        for attempt in range(6):
            if torch.cuda.is_available():
                break
            wait = 10 * (attempt + 1)
            logger.warning(
                f"CUDA not ready (attempt {attempt + 1}/6), retrying in {wait}s…"
            )
            time.sleep(wait)
        else:
            raise RuntimeError("CUDA not available — SF3D requires GPU")

        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        if total_gb < 8:
            raise RuntimeError(f"GPU has {total_gb:.1f}GB; SF3D needs at least 8GB")
        logger.info(f"GPU memory OK: {total_gb:.1f}GB")

        if not os.getenv("HF_TOKEN"):
            raise RuntimeError(
                "HF_TOKEN env var not set — stabilityai/stable-fast-3d is a gated model. "
                "Accept the license at https://huggingface.co/stabilityai/stable-fast-3d "
                "then set HF_TOKEN."
            )

        try:
            from sf3d.system import SF3D  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(f"sf3d package not installed in container: {exc}")

        logger.info("sf3d imports OK")
        return True

    def preprocess(self, image_paths: Union[str, List[str]]) -> List[Image.Image]:
        if isinstance(image_paths, str):
            image_paths = [image_paths]

        from utils.pre_processor import ImagePreprocessor, ImageValidator

        validated = ImageValidator.validate_input_images(
            image_paths, allow_directory=False
        )
        if len(validated) > 1:
            logger.warning(f"SF3D uses 1 image; got {len(validated)}, using first")
        path = validated[0]

        img = ImagePreprocessor.load_image(path)
        img = ImagePreprocessor.maybe_upscale(img)
        img = img.convert("RGBA")

        # Background removal — SF3D expects RGBA with alpha mask on subject
        try:
            import rembg

            session = rembg.new_session("birefnet-general")
            img = rembg.remove(img, session=session)
            logger.info(f"Background removed (birefnet-general): {Path(path).name}")
        except Exception as e:
            logger.warning(f"Background removal failed ({e}), using original")

        logger.info(f"Preprocessed 1 image: {img.mode} {img.size}")
        return [img]

    def infer(self, images: List[Image.Image]) -> Any:
        """Run SF3D inference. Returns (mesh, timestamp)."""
        from sf3d.system import SF3D

        image = images[0]

        if self._model is None:
            logger.info(f"Loading SF3D model: {self.MODEL_ID}")
            t0 = time.time()
            self._model = SF3D.from_pretrained(
                self.MODEL_ID,
                config_name="config.yaml",
                weight_name="model.safetensors",
            )
            self._model.to(self.device).eval()
            logger.info(f"SF3D loaded in {time.time()-t0:.1f}s")

        for i, tier in enumerate(_BAKE_TIERS):
            label = tier["label"]
            try:
                t0 = time.time()
                logger.info(
                    f"SF3D inference tier={label}: bake_resolution={tier['bake_resolution']} "
                    f"remesh={tier['remesh']}"
                )
                with torch.no_grad():
                    with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                        mesh, _ = self._model.run_image(
                            [image],
                            bake_resolution=tier["bake_resolution"],
                            remesh=tier["remesh"],
                            vertex_count=-1,
                        )
                elapsed = time.time() - t0
                logger.info(
                    f"SF3D done in {elapsed:.1f}s tier={label} — "
                    f"{len(mesh.vertices):,}v {len(mesh.faces):,}f"
                )

                gc.collect()
                torch.cuda.empty_cache()
                return mesh, time.strftime("%Y%m%d_%H%M%S")

            except Exception as exc:
                oom = (
                    "out of memory" in str(exc).lower()
                    or "OutOfMemoryError" in type(exc).__name__
                )
                gc.collect()
                torch.cuda.empty_cache()
                if oom and i < len(_BAKE_TIERS) - 1:
                    logger.warning(f"OOM at tier={label}, stepping down")
                    continue
                raise

        raise RuntimeError("SF3D inference failed at all quality tiers")

    def postprocess(self, infer_output: Any) -> str:
        """Export UV-textured GLB. SF3D textures are already baked — no separate paint step."""
        import trimesh
        import trimesh.repair

        mesh, timestamp = infer_output
        output_dir = Path("/app/output/sf3d")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Mesh repair: fix winding and fill simple holes before export.
        try:
            mesh.fix_normals()
            trimesh.repair.fill_holes(mesh)
            logger.info(
                f"Mesh repair done: {len(mesh.vertices):,}v {len(mesh.faces):,}f"
            )
        except Exception as exc:
            logger.warning(f"Mesh repair skipped ({exc})")

        out_glb = output_dir / f"sf3d_{timestamp}.glb"
        mesh.export(str(out_glb))
        logger.info(
            f"Exported GLB: {len(mesh.vertices):,}v {len(mesh.faces):,}f → {out_glb}"
        )
        return str(out_glb)

    def get_engine_info(self) -> dict:
        info = super().get_engine_info()
        info["model_id"] = self.MODEL_ID
        return info
