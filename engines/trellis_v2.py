"""TRELLIS.2 Engine - Image-to-3D using the official Microsoft TRELLIS.2-4B pipeline."""

import os

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import time
from pathlib import Path
from typing import Any, List, Union

import numpy as np
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

        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        if total_gb < 14:
            raise RuntimeError(
                f"GPU has only {total_gb:.1f}GB, need 14GB+ for TRELLIS.2"
            )
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
        # torch.batch_norm requires float32 weight even under fp16/bfloat16 autocast.
        # Cast ONLY BatchNorm layers to float32; everything else (linear, conv,
        # sparse-conv) stays in its native fp16/bfloat16 so bfloat16 autocast works.
        # BFS to reach nn.Modules stored in the pipeline's nested dicts/lists.
        _bn_types = (
            torch.nn.BatchNorm1d,
            torch.nn.BatchNorm2d,
            torch.nn.BatchNorm3d,
        )
        seen: set = set()
        queue = [self.pipeline]
        n_bn = 0
        while queue:
            obj = queue.pop()
            oid = id(obj)
            if oid in seen:
                continue
            seen.add(oid)
            if isinstance(obj, torch.nn.Module):
                for m in obj.modules():
                    if isinstance(m, _bn_types):
                        m.float()
                        n_bn += 1
                continue  # .modules() already walked all sub-modules
            if isinstance(obj, dict):
                queue.extend(obj.values())
            elif isinstance(obj, (list, tuple)):
                queue.extend(obj)
            if hasattr(obj, "__dict__"):
                queue.extend(vars(obj).values())
        logger.info(
            f"Cast {n_bn} BatchNorm layer(s) to float32, rest stays in native dtype"
        )
        self.pipeline.cuda()
        self.pipeline_loaded = True
        logger.info(f"TRELLIS.2 pipeline ready in {time.time() - start:.1f}s")

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
            images.append(img)
        logger.info(f"Preprocessed {len(images)} image(s)")
        return images

    def infer(self, preprocessed_images: List[Image.Image]) -> Any:
        """Run TRELLIS.2 — returns a native Trellis2Mesh (NOT trimesh.Trimesh)."""
        if not preprocessed_images:
            raise ValueError("No preprocessed images supplied")

        self._load_pipeline()

        # pipeline.run() accepts a single PIL Image; pick the view with the most
        # non-background content (largest subject area) — typically the frontal view.
        import numpy as np

        def _content_pixels(img: Image.Image) -> int:
            arr = np.array(img.convert("RGB"))
            return int(np.sum(np.any(arr < 240, axis=2)))

        image = max(preprocessed_images, key=_content_pixels)
        idx = preprocessed_images.index(image) + 1
        logger.info(
            f"Selected image {idx}/{len(preprocessed_images)} as primary view "
            f"({image.size[0]}x{image.size[1]}, highest content area)"
        )
        start = time.time()
        try:
            sm = torch.cuda.get_device_capability()
            dtype = torch.bfloat16 if sm[0] >= 8 else torch.float16
            logger.info(
                f"GPU sm_{sm[0]}{sm[1]}: using {dtype} autocast, preprocess_image=True"
            )
            logger.info("Starting pipeline.run()...")
            # bfloat16 autocast: lets the pipeline run in its native mixed-precision
            # mode. BatchNorm layers were pre-cast to float32 (autocast keeps
            # batch_norm in float32, and weight/input must match).
            with torch.autocast(device_type="cuda", dtype=dtype):
                result, latents = self.pipeline.run(
                    image,
                    preprocess_image=True,
                    pipeline_type="1024_cascade",
                    return_latent=True,
                )
            logger.info(f"pipeline.run() done in {time.time() - start:.1f}s")
            # Unpack res before freeing latents — needed for to_glb(grid_size=res)
            _, _, res = latents
            del latents
            mesh = result[0]
            mesh.attrs = mesh.attrs.float()
            n_active = mesh.coords.shape[0] if hasattr(mesh, "coords") else "unknown"
            logger.info(f"SLAT active voxels: {n_active}, grid_size={res}")
            logger.info(
                f"Mesh before simplify: {mesh.vertices.shape[0]} vertices, {mesh.faces.shape[0]} faces"
            )
            mesh.simplify(16777216)
            logger.info(
                f"Mesh after simplify: {mesh.vertices.shape[0]} vertices, {mesh.faces.shape[0]} faces"
            )
        except Exception as exc:
            torch.cuda.empty_cache()
            raise RuntimeError(f"TRELLIS.2 inference failed: {exc}")

        vram_used = torch.cuda.memory_allocated() / 1e9
        vram_reserved = torch.cuda.memory_reserved() / 1e9
        logger.info(
            f"VRAM after inference: {vram_used:.1f}GB allocated, {vram_reserved:.1f}GB reserved"
        )

        # Move the pipeline off GPU before texture baking — nvdiffrast needs VRAM too.
        # The 4B model keeps ~8 GB in VRAM after empty_cache(); moving to CPU frees it.
        try:
            self.pipeline.cpu()
            logger.info("Pipeline moved to CPU")
        except Exception as e:
            logger.warning(f"Could not offload pipeline to CPU: {e}")
        import gc

        gc.collect()
        torch.cuda.empty_cache()
        vram_used = torch.cuda.memory_allocated() / 1e9
        logger.info(f"VRAM after pipeline offload: {vram_used:.1f}GB allocated")
        logger.info(f"Inference complete in {time.time() - start:.1f}s")
        return mesh, res

    def postprocess(self, infer_output: Any) -> str:
        """Export Trellis2Mesh to GLB using trimesh with per-vertex SLAT colors.

        Bypasses o_voxel.postprocess.to_glb() entirely: that function's remesh=False
        path destroys the fragmented marching-cubes mesh via
        remove_small_connected_components(), and remesh=True at resolution=1024
        runs DC remeshing over a 1024^3 grid which takes >36 minutes.  Direct
        trimesh export with nearest-voxel color sampling takes <5 seconds.
        """
        raw_mesh, res = infer_output  # noqa: F841  (res reserved for future to_glb())
        output_dir = Path("/app/output/trellis")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"trellis_{timestamp}_raw.glb"

        # Remove isolated vertices (not referenced by any face)
        unique_idx, inverse = torch.unique(
            raw_mesh.faces.reshape(-1), return_inverse=True
        )
        n_isolated = raw_mesh.vertices.shape[0] - unique_idx.shape[0]
        if n_isolated > 0:
            logger.info(
                f"Removing {n_isolated:,} isolated vertices "
                f"({raw_mesh.vertices.shape[0]:,} → {unique_idx.shape[0]:,})"
            )
        vert_t = raw_mesh.vertices[unique_idx]  # (V, 3) GPU float
        face_t = inverse.reshape(raw_mesh.faces.shape).to(torch.int64)
        logger.info(
            f"Mesh for export: {vert_t.shape[0]:,} vertices, {face_t.shape[0]:,} faces"
        )

        # Sample per-vertex base color from SLAT attr volume via nearest-voxel lookup.
        # coords: (K, 3) int voxel indices;  attrs: (K, C) float [0,1].
        vertex_colors = None
        try:
            t0 = time.time()
            gs = round(1.0 / raw_mesh.voxel_size)  # grid resolution (e.g. 1024)
            origin = torch.tensor(
                [-0.5, -0.5, -0.5], dtype=torch.float32, device=vert_t.device
            )
            # Vertex world pos → integer voxel coordinate
            vert_vox = (
                ((vert_t - origin) / raw_mesh.voxel_size)
                .floor()
                .clamp(0, gs - 1)
                .to(torch.int64)
            )
            # Encode 3D coords as scalar keys for binary search

            def _enc(c):
                return c[:, 0] * gs * gs + c[:, 1] * gs + c[:, 2]

            vox_keys = _enc(raw_mesh.coords.to(torch.int64))
            vert_keys = _enc(vert_vox)

            sorted_idx = torch.argsort(vox_keys)
            sorted_keys = vox_keys[sorted_idx]
            pos = torch.searchsorted(sorted_keys, vert_keys).clamp(
                0, len(sorted_keys) - 1
            )
            hit = sorted_keys[pos] == vert_keys

            base_color_s = raw_mesh.layout.get("base_color", slice(0, 3))
            colors_f = raw_mesh.attrs[sorted_idx[pos], base_color_s].clone()
            colors_f[~hit] = 0.5  # gray fallback for unmatched vertices
            rgb = (colors_f.clamp(0, 1).cpu().float().numpy() * 255).astype(np.uint8)
            alpha = np.full((rgb.shape[0], 1), 255, dtype=np.uint8)
            vertex_colors = np.concatenate([rgb, alpha], axis=1)
            logger.info(f"Vertex color sampling: {time.time() - t0:.2f}s")
        except Exception as e:
            logger.warning(f"Vertex color sampling failed ({e}), exporting plain mesh")

        # Convert to numpy — swap Y/Z for GLTF Y-up coordinate convention
        # (TRELLIS.2 is Z-up internally; matches what to_glb() does)
        verts = vert_t.cpu().float().numpy().copy()
        verts[:, 1], verts[:, 2] = verts[:, 2].copy(), -verts[:, 1].copy()
        faces = face_t.cpu().numpy().astype(np.int32)

        mesh = trimesh.Trimesh(
            vertices=verts,
            faces=faces,
            vertex_colors=vertex_colors,
            process=False,
        )
        mesh.export(str(output_file))
        logger.info(
            f"Exported GLB: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces → {output_file}"
        )
        return str(output_file)

    def get_engine_info(self) -> dict:
        info = super().get_engine_info()
        info["model_id"] = self.MODEL_ID
        return info
