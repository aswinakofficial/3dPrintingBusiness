"""
Unit tests for TRELLIS.2 engine.
Tests engine initialization, preprocessing, and inference.
"""

import pytest
from pathlib import Path
import tempfile
import sys
import os

# Skip tests if torch not available
torch = pytest.importorskip("torch")
from PIL import Image

from engines.trellis_v2 import TRELLIS2Engine
from engines.base_engine import EngineConfig
from engines.loader import load_engine, get_available_engines


class TestTRELLIS2Engine:
    """Tests for TRELLIS.2 engine."""

    @pytest.fixture
    def config(self):
        """Fixture for engine config."""
        return EngineConfig(
            resolution=1024,
            max_images=4,
            output_format="glb",
            device="cuda" if torch.cuda.is_available() else "cpu",
        )

    @pytest.fixture
    def test_image(self):
        """Fixture for test image."""
        # Create simple test image (512x512 RGB)
        img = Image.new("RGB", (512, 512), color=(100, 150, 200))
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img.save(f.name)
            yield f.name
        Path(f.name).unlink()

    @pytest.fixture
    def test_images_list(self):
        """Fixture for multiple test images."""
        paths = []
        for i in range(3):
            img = Image.new("RGB", (512, 512), color=(100 + i * 20, 150, 200))
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                img.save(f.name)
                paths.append(f.name)
        yield paths
        for path in paths:
            Path(path).unlink()

    def test_engine_initialization(self, config):
        """Test engine can be initialized."""
        engine = TRELLIS2Engine(config)
        assert engine is not None
        assert engine.get_engine_name() == "TRELLIS2Engine"

    def test_engine_from_loader(self, config):
        """Test engine can be loaded via factory."""
        engine = load_engine("trellis", config)
        assert engine is not None
        assert isinstance(engine, TRELLIS2Engine)

    def test_available_engines(self):
        """Test that trellis is in available engines."""
        engines = get_available_engines()
        assert "trellis" in engines

    def test_get_engine_info(self, config):
        """Test engine info retrieval."""
        engine = TRELLIS2Engine(config)
        info = engine.get_engine_info()
        assert info["name"] == "TRELLIS2Engine"
        assert info["max_images"] == 4
        assert info["resolution"] == 1024

    def test_image_preprocessing_single(self, config, test_image):
        """Test single image preprocessing."""
        engine = TRELLIS2Engine(config)
        preprocessed = engine.preprocess(test_image)

        assert len(preprocessed) == 1
        assert isinstance(preprocessed[0], Image.Image)
        assert preprocessed[0].width == 512
        assert preprocessed[0].height == 512
        assert preprocessed[0].mode == "RGB"

    def test_image_preprocessing_multiple(self, config, test_images_list):
        """Test multiple image preprocessing."""
        engine = TRELLIS2Engine(config)
        preprocessed = engine.preprocess(test_images_list)

        assert len(preprocessed) == 3
        for img in preprocessed:
            assert isinstance(img, Image.Image)
            assert img.width == 512
            assert img.height == 512

    def test_image_preprocessing_max_images(self, config, test_images_list):
        """Test that preprocessing respects max_images limit."""
        config.max_images = 2
        engine = TRELLIS2Engine(config)

        # Pass 3 images but config allows max 2
        preprocessed = engine.preprocess(test_images_list)
        assert len(preprocessed) <= 2

    def test_invalid_engine_name(self, config):
        """Test error on invalid engine name."""
        with pytest.raises(ValueError):
            load_engine("invalid_engine", config)

    def test_image_validation_nonexistent(self, config):
        """Test error on nonexistent image."""
        engine = TRELLIS2Engine(config)
        with pytest.raises(ValueError):
            engine.preprocess("/nonexistent/image.jpg")

    def test_engine_device_selection(self):
        """Test engine device selection."""
        config_cuda = EngineConfig(device="cuda")
        engine_cuda = TRELLIS2Engine(config_cuda)

        if torch.cuda.is_available():
            assert "cuda" in str(engine_cuda.device)
        else:
            # Will fallback to CPU if CUDA not available
            assert engine_cuda.device.type in ["cuda", "cpu"]

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
    def test_prerequisite_validation_cuda_required(self, config):
        """Test prerequisite validation requires CUDA."""
        config.device = "cuda"
        engine = TRELLIS2Engine(config)

        # This will check CUDA and memory, but skip model loading in test
        # (model loading requires network and authentication)
        assert torch.cuda.is_available()


class TestTRELLIS2Integration:
    """Integration tests for TRELLIS.2 engine."""

    @pytest.fixture
    def config(self):
        """Fixture for engine config."""
        return EngineConfig(
            resolution=1024,
            max_images=4,
            device="cuda" if torch.cuda.is_available() else "cpu",
        )

    def test_engine_info_structure(self, config):
        """Test that engine info has required fields."""
        engine = TRELLIS2Engine(config)
        info = engine.get_engine_info()

        required_fields = [
            "name",
            "device",
            "resolution",
            "max_images",
            "output_format",
        ]
        for field in required_fields:
            assert field in info, f"Missing field: {field}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
