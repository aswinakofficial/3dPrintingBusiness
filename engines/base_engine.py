"""Base engine abstraction layer for 3D model generation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Union, List, Dict, Any

import torch


@dataclass
class EngineConfig:
    """Configuration for engine."""

    resolution: int = 1024
    max_images: int = 4
    output_format: str = "glb"  # glb or ply
    device: str = "cuda"
    batch_size: int = 1


class Engine(ABC):
    """Abstract base class for all model generation engines."""

    def __init__(self, config: EngineConfig):
        """
        Initialize engine.

        Args:
            config: EngineConfig instance
        """
        self.config = config
        self.device = torch.device(
            config.device if torch.cuda.is_available() else "cpu"
        )

    @abstractmethod
    def validate_prerequisites(self) -> bool:
        """
        Validate that all prerequisites are met.

        Must check:
        - GPU availability and VRAM
        - Model downloads/availability
        - Dependencies

        Returns:
            True if all prerequisites met

        Raises:
            RuntimeError: If prerequisites not met
        """
        pass

    @abstractmethod
    def preprocess(
        self,
        image_paths: Union[str, List[str]],
    ) -> List[Any]:
        """
        Preprocess input image(s) for model.

        Args:
            image_paths: Single path, list of paths, or directory

        Returns:
            List of preprocessed image tensors/objects
        """
        pass

    @abstractmethod
    def infer(self, preprocessed_images: List[Any]) -> Any:
        """
        Run inference on preprocessed images.

        Args:
            preprocessed_images: List from preprocess()

        Returns:
            Raw 3D output (trimesh.Mesh or similar)
        """
        pass

    @abstractmethod
    def postprocess(self, raw_output: Any) -> str:
        """
        Convert raw model output to standardized format.

        Args:
            raw_output: Output from infer()

        Returns:
            Path to standardized output file (GLB or PLY)
        """
        pass

    def get_engine_name(self) -> str:
        """Get human-readable engine name."""
        return self.__class__.__name__

    def get_engine_info(self) -> Dict[str, Any]:
        """Get engine information and capabilities."""
        return {
            "name": self.get_engine_name(),
            "device": str(self.device),
            "resolution": self.config.resolution,
            "max_images": self.config.max_images,
            "output_format": self.config.output_format,
        }


__all__ = ["Engine", "EngineConfig"]
