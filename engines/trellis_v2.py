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

        # Remove background ourselves so TRELLIS.2 receives an RGBA image with real
        # alpha.  preprocess_image() checks `not np.all(alpha == 255)` and skips its
        # internal BiRefNet call when has_alpha=True — this avoids the trust_remote_code
        # model-load crash (BiRefNet inherits nn.Module, not PreTrainedModel, so
        # transformers attributes like all_tied_weights_keys are missing).
        try:
            import rembg as _rembg

            _session = _rembg.new_session("u2net")
            image = _rembg.remove(image, session=_session)
            logger.info(
                f"Background removed (rembg/u2net); image is now {image.mode} "
                f"{image.size[0]}x{image.size[1]}"
            )
        except Exception as _bg_err:
            logger.warning(
                f"Background removal failed ({_bg_err}); passing raw RGB image to pipeline"
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
        """Export Trellis2Mesh as a watertight GLB using Open3D Poisson reconstruction.

        TRELLIS.2's marching-cubes output is non-watertight: the sparse voxel grid
        produces many disconnected face patches separated by gaps.  The correct fix
        is o_voxel.postprocess.to_glb(remesh=True) (Dual Contouring), but DC remesh
        at 1024^3 times out.  Instead we run Poisson surface reconstruction on the
        full set of marching-cubes vertex positions — they are dense surface samples
        even when not connected by faces — to produce a watertight, print-ready mesh.
        Falls back to direct trimesh export if Open3D is unavailable.
        """
        raw_mesh, res = infer_output  # noqa: F841
        output_dir = Path("/app/output/trellis")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"trellis_{timestamp}_print.glb"

        # ALL raw_mesh vertices (including isolated ones) are surface samples from
        # the SLAT marching-cubes — use them as the Poisson point cloud.
        all_verts = raw_mesh.vertices.cpu().float().numpy().copy()
        logger.info(f"Raw mesh: {all_verts.shape[0]:,} surface points")

        # Swap Y/Z for GLTF Y-up convention (TRELLIS.2 internal space is Z-up)
        all_verts[:, 1], all_verts[:, 2] = (
            all_verts[:, 2].copy(),
            -all_verts[:, 1].copy(),
        )

        try:
            import open3d as o3d

            logger.info(
                f"Poisson reconstruction (depth=9) on {all_verts.shape[0]:,} points..."
            )
            t0 = time.time()

            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(all_verts)
            pcd.estimate_normals(
                search_param=o3d.geometry.KDTreeSearchParamHybrid(
                    radius=0.02, max_nn=30
                )
            )
            pcd.orient_normals_consistent_tangent_plane(100)

            (
                mesh_o3d,
                densities,
            ) = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
                pcd, depth=9, scale=1.1, linear_fit=False
            )

            # Remove low-density vertices — Poisson extrapolates slightly outside the
            # real surface; clipping the bottom 5% by density removes those artifacts.
            dens = np.asarray(densities)
            mesh_o3d.remove_vertices_by_mask(dens < np.percentile(dens, 5))
            mesh_o3d.remove_degenerate_triangles()
            mesh_o3d.remove_unreferenced_vertices()

            n_v = len(mesh_o3d.vertices)
            n_f = len(mesh_o3d.triangles)
            logger.info(
                f"Poisson mesh: {n_v:,} vertices, {n_f:,} faces ({time.time()-t0:.1f}s)"
            )

            # Decimate to a count manageable by slicer software
            target = 300_000
            if n_f > target:
                mesh_o3d = mesh_o3d.simplify_quadric_decimation(target)
                logger.info(f"Decimated to {len(mesh_o3d.triangles):,} faces")

            verts_out = np.asarray(mesh_o3d.vertices, dtype=np.float32)
            faces_out = np.asarray(mesh_o3d.triangles, dtype=np.int32)
            mesh_out = trimesh.Trimesh(
                vertices=verts_out, faces=faces_out, process=False
            )
            mesh_out.export(str(output_file))
            logger.info(
                f"Exported watertight GLB: {len(mesh_out.vertices):,} v, "
                f"{len(mesh_out.faces):,} f → {output_file}"
            )
            return str(output_file)

        except Exception as exc:
            logger.warning(
                f"Poisson reconstruction failed ({exc}); falling back to direct trimesh export"
            )

        # ── Fallback: direct trimesh export (non-watertight, vertex-color) ──────
        output_file = output_dir / f"trellis_{timestamp}_raw.glb"
        unique_idx, inverse = torch.unique(
            raw_mesh.faces.reshape(-1), return_inverse=True
        )
        vert_t = raw_mesh.vertices[unique_idx]
        face_t = inverse.reshape(raw_mesh.faces.shape).to(torch.int64)
        logger.info(
            f"Fallback mesh: {vert_t.shape[0]:,} vertices, {face_t.shape[0]:,} faces"
        )
        verts = vert_t.cpu().float().numpy().copy()
        verts[:, 1], verts[:, 2] = verts[:, 2].copy(), -verts[:, 1].copy()
        faces = face_t.cpu().numpy().astype(np.int32)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        mesh.export(str(output_file))
        logger.info(
            f"Exported GLB (fallback): {len(mesh.vertices):,} v, "
            f"{len(mesh.faces):,} f → {output_file}"
        )
        return str(output_file)

    def get_engine_info(self) -> dict:
        info = super().get_engine_info()
        info["model_id"] = self.MODEL_ID
        return info
