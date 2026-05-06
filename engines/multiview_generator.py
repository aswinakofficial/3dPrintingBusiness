"""
Multi-view image generation using Zero123++.

Generates novel views from a single background-removed image to improve 3D
reconstruction accuracy. Model: sudo-ai/zero123plus-v1.1 (~2.5 GB, downloaded
from HuggingFace on first run and cached in MODEL_CACHE_DIR on Azure Files).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class MultiViewGenerator:
    """Generates novel views from input images using Zero123++."""

    MODEL_ID = "sudo-ai/zero123plus-v1.1"
    _GRID_ROWS = 2
    _GRID_COLS = 3

    def __init__(self, device: str = "cuda", num_inference_steps: int = 75) -> None:
        self.device = device
        self.num_inference_steps = num_inference_steps
        self._pipe = None  # Lazy-loaded on first call

    def _load_pipeline(self) -> None:
        if self._pipe is not None:
            return
        import torch
        from diffusers import DiffusionPipeline

        logger.info(f"Loading Zero123++ ({self.MODEL_ID})...")
        self._pipe = DiffusionPipeline.from_pretrained(
            self.MODEL_ID,
            custom_pipeline="sudo-ai/zero123plus-pipeline",
            torch_dtype=torch.float16,
        ).to(self.device)
        logger.info("Zero123++ loaded.")

    def generate_views(self, image: Image.Image) -> list[Image.Image]:
        """Return 6 novel views from a single background-removed image."""
        self._load_pipeline()
        result = self._pipe(image, num_inference_steps=self.num_inference_steps).images[0]
        return self._split_grid(result)

    def _split_grid(self, grid: Image.Image) -> list[Image.Image]:
        """Split Zero123++ 2×3 output grid into 6 individual view images."""
        w, h = grid.size
        cell_w = w // self._GRID_COLS
        cell_h = h // self._GRID_ROWS
        views = []
        for row in range(self._GRID_ROWS):
            for col in range(self._GRID_COLS):
                box = (col * cell_w, row * cell_h, (col + 1) * cell_w, (row + 1) * cell_h)
                views.append(grid.crop(box))
        return views

    def augment_image_paths(
        self,
        image_paths: list[str],
        target_count: int,
        session_dir: Path,
    ) -> list[str]:
        """
        Generate novel views from each source image and save to session_dir/generated_views/.

        Real photos are always returned first and are preferred. Generated views
        only fill the remaining slots up to target_count.

        Returns original paths + generated view paths (total ≤ target_count).
        """
        real_paths = list(image_paths)
        if len(real_paths) >= target_count:
            return real_paths[:target_count]

        slots_remaining = target_count - len(real_paths)
        generated_paths: list[str] = []
        gen_dir = session_dir / "generated_views"
        gen_dir.mkdir(parents=True, exist_ok=True)

        for src_idx, src_path in enumerate(real_paths):
            if slots_remaining <= 0:
                break
            try:
                source_image = Image.open(src_path).convert("RGB")
                views = self.generate_views(source_image)
                logger.info(f"Generated {len(views)} views from {Path(src_path).name}")
                for view_idx, view in enumerate(views):
                    if slots_remaining <= 0:
                        break
                    out_path = gen_dir / f"view_{src_idx:02d}_{view_idx:02d}.png"
                    view.save(out_path)
                    generated_paths.append(str(out_path))
                    slots_remaining -= 1
            except Exception as exc:
                logger.warning(f"View generation failed for {src_path}: {exc}")

        all_paths = real_paths + generated_paths
        logger.info(
            f"Multi-view augmentation: {len(real_paths)} real + "
            f"{len(generated_paths)} generated = {len(all_paths)} total"
        )
        return all_paths
