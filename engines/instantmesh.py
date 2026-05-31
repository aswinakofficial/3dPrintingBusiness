"""InstantMesh Engine — multi-view LRM + FlexiCubes (TencentARC, 2024).

Model:  TencentARC/InstantMesh  (Apache 2.0, open access)
Repo:   https://github.com/TencentARC/InstantMesh
Paper:  InstantMesh: Efficient 3D Mesh Generation from a Single or Multi-View
        Image with Sparse-view Large Reconstruction Models

Pipeline (two modes):
  • 1-image mode: rembg → Zero123++ (6 synthesised views) → LRM → FlexiCubes → GLB
  • 6-image mode: rembg each → direct LRM → FlexiCubes → GLB
        (assumes photos taken at ~60° azimuth intervals, ~30° elevation)

FlexiCubes mesh extraction produces clean, watertight topology without the
Dual-Contouring staircase artifacts seen in Hunyuan3D.
"""

import gc
import os
import sys
import time
from pathlib import Path
from typing import Any, List, Union

import torch
from PIL import Image

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# InstantMesh repo is cloned to /opt/instantmesh in the Docker image.
# We add it to sys.path so `src.*` imports work at inference time.
_IM_ROOT = Path("/opt/instantmesh")
if _IM_ROOT.exists() and str(_IM_ROOT) not in sys.path:
    sys.path.insert(0, str(_IM_ROOT))

from engines.base_engine import Engine, EngineConfig  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger()

# Zero123++ quality tiers (tried in order on OOM)
_Z123_TIERS = [
    {"num_inference_steps": 75, "guidance_scale": 4.0, "label": "high"},
    {"num_inference_steps": 50, "guidance_scale": 4.0, "label": "med"},
    {"num_inference_steps": 36, "guidance_scale": 3.0, "label": "low"},
]

_ZERO123_MODEL = "sudo-ai/zero123plus-v1.1"
_IM_REPO = "TencentARC/InstantMesh"
_IM_CONFIG = "config/instantmesh_large.yaml"
_IM_CKPT = "checkpoints/instantmesh_large.ckpt"


class InstantMeshEngine(Engine):
    """Multi-view LRM reconstruction engine (TencentARC InstantMesh).

    Accepts 1 or 6 images.
    - 1 image  → Zero123++ synthesises 6 consistent views → LRM → FlexiCubes mesh.
    - 6 images → direct multi-view input → LRM → FlexiCubes mesh.
      (Shoot at 0°/60°/120°/180°/240°/300° azimuth, ~30° elevation.)
    """

    def __init__(self, config: EngineConfig):
        super().__init__(config)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._zero123_pipe = None
        self._model = None
        self._infer_config = None

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
            raise RuntimeError("CUDA not available — InstantMesh requires GPU")

        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        if total_gb < 16:
            raise RuntimeError(
                f"GPU has {total_gb:.1f}GB; InstantMesh needs 16GB+ "
                "(Zero123++ + LRM together)"
            )
        logger.info(f"GPU memory OK: {total_gb:.1f}GB")

        if not _IM_ROOT.exists():
            raise RuntimeError(
                f"InstantMesh repo not found at {_IM_ROOT}. "
                "Ensure the Dockerfile cloned it to /opt/instantmesh."
            )

        try:
            from diffusers import DiffusionPipeline  # noqa: F401
            from src.utils.train_util import instantiate_from_config  # noqa: F401
            from src.utils.camera_util import (  # noqa: F401
                get_zero123plus_input_cameras,
            )
        except ImportError as exc:
            raise RuntimeError(f"InstantMesh dependencies not installed: {exc}")

        logger.info("InstantMesh imports OK")
        return True

    # ── Preprocess ────────────────────────────────────────────────────────────

    def preprocess(self, image_paths: Union[str, List[str]]) -> List[Image.Image]:
        if isinstance(image_paths, str):
            image_paths = [image_paths]

        from utils.pre_processor import ImagePreprocessor, ImageValidator  # noqa: E402

        validated = ImageValidator.validate_input_images(
            image_paths, allow_directory=False
        )
        if len(validated) not in (1, 6):
            logger.warning(
                f"InstantMesh works best with 1 or 6 images; "
                f"got {len(validated)} — using first image in Zero123++ mode"
            )
            validated = [validated[0]]

        images = []
        for i, path in enumerate(validated, 1):
            img = ImagePreprocessor.load_image(path)
            img = ImagePreprocessor.maybe_upscale(img)
            img = img.convert("RGBA")
            try:
                import rembg

                session = rembg.new_session("birefnet-general")
                img = rembg.remove(img, session=session)
                logger.info(
                    f"Background removed ({i}/{len(validated)}): {Path(path).name}"
                )
            except Exception as e:
                logger.warning(f"Background removal failed ({e}), using original")
            img = img.resize((320, 320), Image.LANCZOS)
            images.append(img)

        logger.info(
            f"Preprocessed {len(images)} image(s) — "
            f"mode={'direct-6' if len(images) == 6 else 'zero123++'}"
        )
        return images

    # ── Infer ─────────────────────────────────────────────────────────────────

    def infer(self, images: List[Image.Image]) -> Any:
        if len(images) == 6:
            logger.info("Direct 6-image mode — skipping Zero123++")
            views_tensor = self._stack_user_views(images)
        else:
            logger.info("Single-image mode — generating 6 views with Zero123++")
            mv_grid = self._run_zero123plus(images[0])
            views_tensor = self._parse_mv_grid(mv_grid)

        mesh_out = self._run_lrm(views_tensor)
        return mesh_out, time.strftime("%Y%m%d_%H%M%S")

    def _stack_user_views(self, images: List[Image.Image]) -> torch.Tensor:
        """Normalise 6 user-provided RGBA views into a (1,6,3,320,320) tensor."""
        import numpy as np

        frames = []
        for img in images:
            arr = (
                torch.from_numpy(np.array(img.convert("RGB"))).permute(2, 0, 1).float()
                / 255.0
            )
            arr = arr * 2.0 - 1.0  # [-1, 1]
            frames.append(arr)
        return torch.stack(frames).unsqueeze(0).to(self.device)  # (1,6,3,320,320)

    def _run_zero123plus(self, image: Image.Image) -> Image.Image:
        """Zero123++ single-image → 960×640 2×3 multi-view grid."""
        from diffusers import DiffusionPipeline, EulerAncestralDiscreteScheduler

        if self._zero123_pipe is None:
            logger.info(f"Loading Zero123++ pipeline: {_ZERO123_MODEL}")
            t0 = time.time()
            pipe = DiffusionPipeline.from_pretrained(
                _ZERO123_MODEL,
                custom_pipeline="sudo-ai/zero123plus-pipeline",
                torch_dtype=torch.float16,
            )
            pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(
                pipe.scheduler.config, timestep_spacing="trailing"
            )
            pipe.to(self.device)
            self._zero123_pipe = pipe
            logger.info(f"Zero123++ loaded in {time.time()-t0:.1f}s")

        for i, tier in enumerate(_Z123_TIERS):
            try:
                t0 = time.time()
                logger.info(
                    f"Zero123++ tier={tier['label']}: "
                    f"steps={tier['num_inference_steps']}"
                )
                result = self._zero123_pipe(
                    image,
                    num_inference_steps=tier["num_inference_steps"],
                    guidance_scale=tier["guidance_scale"],
                ).images[0]
                logger.info(
                    f"Zero123++ done in {time.time()-t0:.1f}s tier={tier['label']}"
                )
                return result
            except Exception as exc:
                oom = "out of memory" in str(exc).lower()
                gc.collect()
                torch.cuda.empty_cache()
                if oom and i < len(_Z123_TIERS) - 1:
                    logger.warning(f"OOM at tier={tier['label']}, stepping down")
                    continue
                raise

        raise RuntimeError("Zero123++ failed at all quality tiers")

    def _parse_mv_grid(self, mv_image: Image.Image) -> torch.Tensor:
        """Parse 2-row × 3-col 960×640 grid → (1,6,3,320,320) normalised tensor."""
        import numpy as np
        from einops import rearrange

        grid_np = np.array(mv_image.convert("RGB"))  # (640, 960, 3)
        grid_t = (
            torch.from_numpy(grid_np).permute(2, 0, 1).float() / 255.0
        )  # (3, 640, 960)
        grid_t = grid_t * 2.0 - 1.0  # [-1, 1]
        # n=2 rows, m=3 cols → (6, 3, 320, 320)
        views = rearrange(grid_t, "c (n h) (m w) -> (n m) c h w", n=2, m=3)
        return views.unsqueeze(0).to(self.device)  # (1,6,3,320,320)

    def _run_lrm(self, views_tensor: torch.Tensor) -> tuple:
        """Forward through InstantMesh LRM and extract FlexiCubes mesh."""
        from huggingface_hub import hf_hub_download
        from omegaconf import OmegaConf
        from src.utils.camera_util import get_zero123plus_input_cameras
        from src.utils.train_util import instantiate_from_config

        # Lazy-load model (only once per container lifetime)
        if self._model is None:
            logger.info(f"Loading InstantMesh model: {_IM_REPO}")
            t0 = time.time()
            config_path = hf_hub_download(repo_id=_IM_REPO, filename=_IM_CONFIG)
            ckpt_path = hf_hub_download(repo_id=_IM_REPO, filename=_IM_CKPT)
            config = OmegaConf.load(config_path)
            self._infer_config = config.infer_config
            model = instantiate_from_config(config.model_config)
            state_dict = torch.load(ckpt_path, map_location="cpu")["state_dict"]
            state_dict = {
                k[14:]: v
                for k, v in state_dict.items()
                if k.startswith("lrm_generator.")
            }
            model.lrm_generator.load_state_dict(state_dict, strict=True)
            model = model.to(self.device)
            model.eval()
            self._model = model
            logger.info(f"InstantMesh loaded in {time.time()-t0:.1f}s")

        # Offload Zero123++ to CPU to reclaim VRAM before LRM
        if self._zero123_pipe is not None:
            self._zero123_pipe.to("cpu")
            gc.collect()
            torch.cuda.empty_cache()
            logger.info(
                f"VRAM after Z123++ offload: "
                f"{torch.cuda.memory_allocated()/1e9:.1f}GB"
            )

        input_cameras = get_zero123plus_input_cameras(batch_size=1, radius=4.0).to(
            self.device
        )

        logger.info("Running InstantMesh LRM + FlexiCubes extraction")
        t0 = time.time()
        with torch.no_grad():
            planes = self._model.forward_planes(views_tensor, input_cameras)
            mesh_out = self._model.extract_mesh(
                planes,
                use_texture_map=True,
                **self._infer_config,
            )
        logger.info(f"LRM + mesh extraction done in {time.time()-t0:.1f}s")
        return mesh_out  # (vertices, faces, uvs, mesh_tex_idx, texture_map)

    # ── Postprocess ───────────────────────────────────────────────────────────

    def postprocess(self, infer_output: Any) -> str:
        """Export UV-textured GLB from InstantMesh mesh output."""
        import numpy as np
        import trimesh
        from src.utils.mesh_util import save_obj_with_mtl

        (vertices, faces, uvs, mesh_tex_idx, texture_map), timestamp = infer_output

        output_dir = Path("/app/output/instantmesh")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Convert tensors → numpy
        verts_np = vertices.cpu().numpy().astype(np.float32)
        faces_np = faces.cpu().numpy().astype(np.uint32)
        uvs_np = uvs.cpu().numpy().astype(np.float32)
        tex_idx_np = mesh_tex_idx.cpu().numpy().astype(np.uint32)
        # texture_map: (3, H, W) float32 [0,1] → (H, W, 3) uint8
        tex_np = (
            (texture_map.cpu().permute(1, 2, 0).numpy() * 255)
            .clip(0, 255)
            .astype(np.uint8)
        )

        obj_path = output_dir / f"instantmesh_{timestamp}.obj"
        glb_path = output_dir / f"instantmesh_{timestamp}.glb"

        # Write OBJ + MTL + texture PNG
        save_obj_with_mtl(verts_np, uvs_np, faces_np, tex_idx_np, tex_np, str(obj_path))

        # Convert OBJ → GLB via trimesh
        scene = trimesh.load(str(obj_path), process=False)

        # Repair each mesh component: fix winding and fill open holes
        try:
            import trimesh.repair
            meshes = (
                list(scene.geometry.values())
                if isinstance(scene, trimesh.Scene)
                else [scene]
            )
            for m in meshes:
                if isinstance(m, trimesh.Trimesh):
                    m.fix_normals()
                    trimesh.repair.fill_holes(m)
            logger.info("Mesh repair done")
        except Exception as exc:
            logger.warning(f"Mesh repair skipped ({exc})")

        scene.export(str(glb_path))

        logger.info(f"Exported GLB: {len(verts_np):,}v {len(faces_np):,}f → {glb_path}")
        return str(glb_path)

    def get_engine_info(self) -> dict:
        info = super().get_engine_info()
        info["model_id"] = _IM_REPO
        return info
