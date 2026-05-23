"""TripoSG Engine — high-quality single-image to 3D with PBR textures.

Model: vast-ai/TripoSG
Paper: TripoSG: High-Fidelity 3D Shape Synthesis using Large-Scale Rectified Flow Models
Repo:  https://github.com/VAST-AI-Research/TripoSG

TripoSG uses a Flow-Matching DiT trained on a larger, curated 3D dataset than Hunyuan3D.
It produces cleaner topology, better surface detail, and sharper geometry — particularly
for organic figurine shapes — making it the closest open-source alternative to Meshy.ai.
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
from utils.pre_processor import ImagePreprocessor, ImageValidator  # noqa: E402

logger = get_logger()


class TripoSGEngine(Engine):
    """TripoSG image-to-3D engine (VAST-AI).

    Accepts 1 image; returns a textured GLB with PBR materials.
    """

    MODEL_ID = "vast-ai/TripoSG"

    # Inference quality tiers, tried in order on OOM
    _INFER_TIERS = [
        {"steps": 50, "guidance": 7.5, "label": "high"},
        {"steps": 36, "guidance": 7.5, "label": "med"},
        {"steps": 25, "guidance": 7.0, "label": "low"},
    ]

    def __init__(self, config: EngineConfig):
        super().__init__(config)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._pipe = None

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
            raise RuntimeError("CUDA not available — TripoSG requires GPU")

        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        if total_gb < 16:
            raise RuntimeError(f"GPU has {total_gb:.1f}GB; need 16GB+ for TripoSG")
        logger.info(f"GPU memory OK: {total_gb:.1f}GB")

        try:
            from triposg.pipelines import TripoSGPipeline  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(f"triposg package not installed in container: {exc}")

        logger.info("triposg imports OK")
        return True

    def preprocess(self, image_paths: Union[str, List[str]]) -> List[Image.Image]:
        if isinstance(image_paths, str):
            image_paths = [image_paths]

        validated = ImageValidator.validate_input_images(
            image_paths, allow_directory=False
        )
        # TripoSG is optimised for single-image input; use the first image only
        if len(validated) > 1:
            logger.warning(f"TripoSG uses 1 image; got {len(validated)}, using first")
        path = validated[0]

        img = ImagePreprocessor.load_image(path).convert("RGBA")
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
        """Run TripoSG inference. Returns (mesh, timestamp)."""
        from triposg.pipelines import TripoSGPipeline

        image = images[0]
        logger.info(f"Loading TripoSG pipeline: {self.MODEL_ID}")
        if self._pipe is None:
            self._pipe = TripoSGPipeline.from_pretrained(
                self.MODEL_ID,
                torch_dtype=torch.float16,
            ).to(str(self.device))

        for i, tier in enumerate(self._INFER_TIERS):
            label = tier["label"]
            try:
                t0 = time.time()
                logger.info(
                    f"TripoSG inference tier={label}: steps={tier['steps']} "
                    f"guidance={tier['guidance']}"
                )
                result = self._pipe(
                    image,
                    num_inference_steps=tier["steps"],
                    guidance_scale=tier["guidance"],
                )
                mesh = result.mesh[0]
                logger.info(
                    f"Shape done in {time.time()-t0:.1f}s tier={label} — "
                    f"{len(mesh.vertices):,}v {len(mesh.faces):,}f"
                )

                # Offload to CPU to free VRAM
                self._pipe.to("cpu")
                gc.collect()
                torch.cuda.empty_cache()
                logger.info(
                    f"VRAM after offload: {torch.cuda.memory_allocated()/1e9:.1f}GB"
                )

                return mesh, time.strftime("%Y%m%d_%H%M%S")

            except Exception as exc:
                oom = (
                    "out of memory" in str(exc).lower()
                    or "OutOfMemoryError" in type(exc).__name__
                )
                gc.collect()
                torch.cuda.empty_cache()
                if oom and i < len(self._INFER_TIERS) - 1:
                    logger.warning(f"OOM at tier={label}, stepping down")
                    continue
                raise

        raise RuntimeError("TripoSG inference failed at all quality tiers")

    def postprocess(self, infer_output: Any) -> str:
        """Apply Laplacian smoothing and export textured GLB."""
        import trimesh
        import trimesh.smoothing

        mesh, timestamp = infer_output
        output_dir = Path("/app/output/triposg")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Laplacian smoothing to remove any DC staircase artifacts
        try:
            if isinstance(mesh, trimesh.Trimesh):
                t0 = time.time()
                trimesh.smoothing.filter_laplacian(
                    mesh, lamb=0.5, iterations=3, volume_constraint=True
                )
                logger.info(
                    f"Laplacian smoothing → {time.time()-t0:.1f}s, "
                    f"{len(mesh.vertices):,}v {len(mesh.faces):,}f"
                )
        except Exception as exc:
            logger.warning(f"Laplacian smoothing failed ({exc}), skipping")

        out_glb = output_dir / f"triposg_{timestamp}.glb"
        mesh.export(str(out_glb))
        logger.info(
            f"Exported GLB: {len(mesh.vertices):,}v {len(mesh.faces):,}f → {out_glb}"
        )
        return str(out_glb)

    def get_engine_info(self) -> dict:
        info = super().get_engine_info()
        info["model_id"] = self.MODEL_ID
        return info
