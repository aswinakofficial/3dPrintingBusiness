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
        """Export Trellis2Mesh via o_voxel.postprocess.to_glb() with DC remesh.

        DC remesh resolution is capped at 512^3 by scripts/patch_trellis2.py so the
        operation completes in ~2 min instead of timing out at 1024^3.  The patch also
        adds post-remesh cleanup (remove_duplicate_faces, fill_holes, etc.) to produce
        a watertight, slicer-ready GLB with UV-baked PBR textures.
        Falls back to a direct vertex-color trimesh export if to_glb() raises.
        """
        import o_voxel

        raw_mesh, res = infer_output  # noqa: F841
        output_dir = Path("/app/output/trellis")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"trellis_{timestamp}_print.glb"

        try:
            logger.info(
                "Running to_glb() — DC remesh capped at 512^3, "
                "decimation_target=300K, texture_size=1024"
            )
            t0 = time.time()
            glb = o_voxel.postprocess.to_glb(
                vertices=raw_mesh.vertices,
                faces=raw_mesh.faces,
                attr_volume=raw_mesh.attrs,
                coords=raw_mesh.coords,
                attr_layout=self.pipeline.pbr_attr_layout,
                grid_size=res,
                aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
                decimation_target=300_000,
                texture_size=1024,
                remesh=True,
                remesh_band=1,
                remesh_project=0,
                verbose=True,
            )
            glb.export(str(output_file))
            logger.info(f"to_glb() done in {time.time() - t0:.1f}s → {output_file}")

            # Safety net: remove fragments that are <0.5% of total face count.
            # These appear as floating dots in viewers. o_voxel's post-remesh cleanup
            # (Patch B in patch_trellis2.py) should handle this at the source, but we
            # apply a trimesh pass here in case the patch didn't match the installed file.
            try:
                _scene = trimesh.load(str(output_file), force="scene")
                _geoms = (
                    list(_scene.geometry.values())
                    if isinstance(_scene, trimesh.Scene)
                    else [_scene]
                )
                if _geoms:
                    _tm = _geoms[0]
                    _comps = _tm.split(only_watertight=False)
                    if len(_comps) > 1:
                        _total = sum(len(c.faces) for c in _comps)
                        _keep = [c for c in _comps if len(c.faces) / _total > 0.005]
                        logger.info(
                            f"Fragment cleanup: {len(_comps)} components, "
                            f"keeping {len(_keep)} (>0.5% of {_total:,} faces)"
                        )
                        if len(_keep) < len(_comps):
                            _clean = trimesh.util.concatenate(_keep)
                            _clean.export(str(output_file))
                            logger.info(
                                f"Re-exported after cleanup: "
                                f"{len(_clean.vertices):,} v, {len(_clean.faces):,} f"
                            )
                    else:
                        logger.info(
                            f"Single-component mesh ({len(_comps[0].faces):,} faces)"
                        )
            except Exception as _ce:
                logger.warning(
                    f"Fragment cleanup skipped ({_ce}); keeping original GLB"
                )

            return str(output_file)

        except Exception as exc:
            logger.warning(
                f"to_glb() failed ({exc}); falling back to direct trimesh export"
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
