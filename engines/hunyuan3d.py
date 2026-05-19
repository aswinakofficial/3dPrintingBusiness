"""Hunyuan3D-2 Engine — multi-view image-to-3D from Tencent."""

import gc
import os
import time
from pathlib import Path
from typing import Any, List, Union

import torch
from PIL import Image

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from engines.base_engine import Engine, EngineConfig
from utils.logger import get_logger
from utils.pre_processor import ImagePreprocessor, ImageValidator

logger = get_logger()

# Ordered view labels: front is always first (used as texture reference image).
# Additional views are assigned in clockwise order around the subject.
_VIEW_LABELS = ["front", "right", "back", "left", "front_left", "front_right"]


class Hunyuan3DEngine(Engine):
    """Hunyuan3D-2 multi-view image-to-3D engine (shape + PBR texture)."""

    SHAPEGEN_MODEL_ID = "tencent/Hunyuan3D-2mv"
    TEXGEN_MODEL_ID = "tencent/Hunyuan3D-2"

    def __init__(self, config: EngineConfig):
        super().__init__(config)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.shapegen = None
        self.texgen = None

    def validate_prerequisites(self) -> bool:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available — Hunyuan3D-2 requires GPU")
        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        if total_gb < 14:
            raise RuntimeError(
                f"GPU has only {total_gb:.1f}GB; Hunyuan3D-2 needs 14GB+ VRAM"
            )
        logger.info(f"GPU memory OK: {total_gb:.1f}GB")
        try:
            from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # noqa: F401
            from hy3dgen.texgen import Hunyuan3DPaintPipeline  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(f"hy3dgen not installed in container: {exc}")
        logger.info("hy3dgen imports OK")
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
            img = ImagePreprocessor.load_image(path)
            try:
                import rembg

                session = rembg.new_session("u2net")
                img = rembg.remove(img, session=session)
                logger.info(
                    f"Background removed: {Path(path).name} → {img.mode} {img.size}"
                )
            except Exception as e:
                logger.warning(f"Background removal failed ({e}), using original")
            images.append(img)

        logger.info(f"Preprocessed {len(images)} image(s)")
        return images

    def infer(self, images: List[Image.Image]) -> Any:
        """Run shape generation then texture generation. Returns a trimesh.Trimesh."""
        if not images:
            raise ValueError("No preprocessed images supplied")

        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
        from hy3dgen.texgen import Hunyuan3DPaintPipeline

        n = len(images)
        view_dict = {_VIEW_LABELS[i]: images[i] for i in range(n)}
        logger.info(f"View mapping: {list(view_dict.keys())}")

        # ── Shape generation ──────────────────────────────────────────────────
        logger.info(f"Loading shape pipeline: {self.SHAPEGEN_MODEL_ID}")
        self.shapegen = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            self.SHAPEGEN_MODEL_ID, subfolder="hunyuan3d-dit-v2-mv"
        ).to(self.device)

        t0 = time.time()
        logger.info("Running shape generation (num_inference_steps=30, octree_res=380)...")
        sm = torch.cuda.get_device_capability()
        dtype = torch.bfloat16 if sm[0] >= 8 else torch.float16
        logger.info(f"GPU sm_{sm[0]}{sm[1]}: using {dtype} autocast")
        with torch.autocast(device_type="cuda", dtype=dtype):
            mesh = self.shapegen(
                image=view_dict,
                num_inference_steps=30,
                octree_resolution=380,
                output_type="trimesh",
            )[0]
        logger.info(
            f"Shape done in {time.time()-t0:.1f}s — "
            f"{len(mesh.vertices):,}v {len(mesh.faces):,}f"
        )

        # Offload shape pipeline before texture pass to free VRAM
        self.shapegen.to("cpu")
        gc.collect()
        torch.cuda.empty_cache()
        logger.info(
            f"VRAM after shapegen offload: {torch.cuda.memory_allocated()/1e9:.1f}GB allocated"
        )

        # ── Texture generation ────────────────────────────────────────────────
        # Use the front image (first supplied) as the texture reference.
        front_image = images[0]
        logger.info(f"Loading texture pipeline: {self.TEXGEN_MODEL_ID}")
        self.texgen = Hunyuan3DPaintPipeline.from_pretrained(
            self.TEXGEN_MODEL_ID
        ).to(self.device)
        t1 = time.time()
        logger.info("Running texture generation...")
        mesh = self.texgen(mesh, image=front_image)
        logger.info(f"Texture done in {time.time()-t1:.1f}s")

        return mesh

    def postprocess(self, mesh: Any) -> str:
        output_dir = Path("/app/output/hunyuan3d")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"hunyuan3d_{timestamp}.glb"
        mesh.export(str(output_file))
        logger.info(
            f"Exported GLB: {len(mesh.vertices):,}v {len(mesh.faces):,}f → {output_file}"
        )
        return str(output_file)

    def get_engine_info(self) -> dict:
        info = super().get_engine_info()
        info["model_id"] = self.SHAPEGEN_MODEL_ID
        return info
