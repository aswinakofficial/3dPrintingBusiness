"""TRELLIS.2 Engine - Image-to-3D using the official Microsoft TRELLIS.2-4B pipeline."""

import os

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import time
from pathlib import Path
from typing import Any, List, Union

import torch
import trimesh
from PIL import Image

from engines.base_engine import Engine, EngineConfig
from utils.logger import get_logger
from utils.pre_processor import ImagePreprocessor, ImageValidator

logger = get_logger()


class TRELLIS2Engine(Engine):
    """TRELLIS.2-4B image-to-3D engine using the official Microsoft pipeline."""

    MODEL_ID = "microsoft/TRELLIS.2-4B"

    def __init__(self, config: EngineConfig):
        super().__init__(config)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.pipeline = None
        self.pipeline_loaded = False

    def validate_prerequisites(self) -> bool:
        logger.info("Validating TRELLIS.2 prerequisites")

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available — TRELLIS.2 requires NVIDIA GPU")

        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        if total_gb < 14:
            raise RuntimeError(f"GPU has only {total_gb:.1f}GB, need 14GB+ for TRELLIS.2")
        if total_gb < 24:
            logger.warning(
                f"GPU has {total_gb:.1f}GB — running at minimum VRAM, may OOM on complex scenes"
            )
        else:
            logger.info(f"GPU memory OK: {total_gb:.1f}GB")

        try:
            from trellis2.pipelines import Trellis2ImageTo3DPipeline  # noqa: F401
            import o_voxel  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                f"trellis2/o_voxel package not installed in container: {exc}"
            )
        logger.info("trellis2 + o_voxel imports OK")
        return True

    def _load_pipeline(self):
        if self.pipeline_loaded:
            return
        from trellis2.pipelines import Trellis2ImageTo3DPipeline

        logger.info(f"Loading {self.MODEL_ID} from HuggingFace (multi-GB download)...")
        start = time.time()
        self.pipeline = Trellis2ImageTo3DPipeline.from_pretrained(self.MODEL_ID)
        self.pipeline.cuda()
        self.pipeline_loaded = True
        logger.info(f"TRELLIS.2 pipeline ready in {time.time() - start:.1f}s")

    def preprocess(self, image_paths: Union[str, List[str]]) -> List[Image.Image]:
        if isinstance(image_paths, str):
            image_paths = [image_paths]

        validated = ImageValidator.validate_input_images(image_paths, allow_directory=False)
        if len(validated) > self.config.max_images:
            logger.warning(
                f"Got {len(validated)} images, using first {self.config.max_images}"
            )
            validated = validated[: self.config.max_images]

        images = []
        for path in validated:
            img = ImagePreprocessor.load_image(path)
            img = ImagePreprocessor.remove_background(img)
            images.append(img)
        logger.info(f"Preprocessed {len(images)} image(s)")
        return images

    def infer(self, preprocessed_images: List[Image.Image]) -> Any:
        """Run TRELLIS.2 — returns a native Trellis2Mesh (NOT trimesh.Trimesh)."""
        if not preprocessed_images:
            raise ValueError("No preprocessed images supplied")

        self._load_pipeline()

        image = preprocessed_images[0]
        logger.info(
            f"Running TRELLIS.2 inference on {image.size[0]}x{image.size[1]} image..."
        )
        start = time.time()
        try:
            # Mixed fp16/bf16 models require autocast so float32 tensors
            # (e.g. DINOv3 output) are promoted to match each layer's dtype.
            logger.info("Starting pipeline.run()...")
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                result = self.pipeline.run(
                    image,
                    preprocess_image=False,
                    pipeline_type="512",
                    sparse_structure_sampler_params={"steps": 6},
                    shape_slat_sampler_params={"steps": 6},
                    tex_slat_sampler_params={"steps": 6},
                )
            logger.info(f"pipeline.run() done in {time.time() - start:.1f}s")
            mesh = result[0]
            # attrs come out of autocast as fp16; grid_sample_3d inside simplify()
            # creates a float32 buffer and index-puts into it → dtype mismatch.
            mesh.attrs = mesh.attrs.float()
            logger.info("Starting mesh.simplify()...")
            t_simplify = time.time()
            mesh.simplify(16777216)
            logger.info(f"mesh.simplify() done in {time.time() - t_simplify:.1f}s")
        except Exception as exc:
            torch.cuda.empty_cache()
            raise RuntimeError(f"TRELLIS.2 inference failed: {exc}")

        vram_used = torch.cuda.memory_allocated() / 1e9
        vram_reserved = torch.cuda.memory_reserved() / 1e9
        logger.info(f"VRAM after inference: {vram_used:.1f}GB allocated, {vram_reserved:.1f}GB reserved")

        # Move the pipeline off GPU before texture baking — nvdiffrast needs VRAM too.
        # The 4B model keeps ~8 GB in VRAM after empty_cache(); moving to CPU frees it.
        try:
            self.pipeline.cpu()
            logger.info("Pipeline moved to CPU")
        except Exception as e:
            logger.warning(f"Could not offload pipeline to CPU: {e}")
        import gc; gc.collect()
        torch.cuda.empty_cache()
        vram_used = torch.cuda.memory_allocated() / 1e9
        logger.info(f"VRAM after pipeline offload: {vram_used:.1f}GB allocated")
        logger.info(f"Inference complete in {time.time() - start:.1f}s")
        return mesh

    def postprocess(self, raw_mesh: Any) -> str:
        """Export Trellis2Mesh to GLB via o_voxel.postprocess.to_glb."""
        import o_voxel

        output_dir = Path("/app/output/trellis")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"trellis_{timestamp}_raw.glb"

        # texture_size=1024 and remesh=False for fast export on T4.
        # 4096 + remesh took >16 min (baking scales with texel count).
        logger.info(f"Exporting GLB via o_voxel (VRAM: {torch.cuda.memory_allocated()/1e9:.1f}GB)...")
        t_glb = time.time()
        glb = o_voxel.postprocess.to_glb(
            vertices=raw_mesh.vertices,
            faces=raw_mesh.faces,
            attr_volume=raw_mesh.attrs,
            coords=raw_mesh.coords,
            attr_layout=raw_mesh.layout,
            voxel_size=raw_mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=200000,
            texture_size=1024,
            remesh=False,
            verbose=True,
        )
        logger.info(f"to_glb() done in {time.time() - t_glb:.1f}s (VRAM: {torch.cuda.memory_allocated()/1e9:.1f}GB)")
        glb.export(str(output_file), extension_webp=True)
        logger.info(f"Exported TRELLIS.2 output to {output_file}")
        return str(output_file)

    def get_engine_info(self) -> dict:
        return {
            "name": "TRELLIS.2",
            "model_id": self.MODEL_ID,
            "max_images": self.config.max_images,
            "device": str(self.device),
        }
