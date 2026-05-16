"""
Unit tests for Meshroom Structure from Motion engine.
Tests engine initialization, preprocessing, and validation.
"""

import pytest
from pathlib import Path
import tempfile
from PIL import Image

from engines.meshroom_sfm import MeshroomEngine
from engines.base_engine import EngineConfig
from engines.loader import load_engine, get_available_engines


class TestMeshroomEngine:
    """Tests for Meshroom SfM engine."""

    @pytest.fixture
    def config(self):
        """Fixture for engine config."""
        return EngineConfig(
            resolution=1024,
            max_images=50,
            output_format="glb",
            device="cpu",  # Meshroom works on CPU
        )

    @pytest.fixture
    def test_images(self):
        """Fixture for multiple test images."""
        paths = []
        for i in range(12):  # Create 12 images (above min of 10)
            img = Image.new("RGB", (512, 512), color=(100 + i * 5, 150, 200))
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                img.save(f.name)
                paths.append(f.name)
        yield paths
        for path in paths:
            Path(path).unlink()

    @pytest.fixture
    def insufficient_images(self):
        """Fixture for insufficient test images."""
        paths = []
        for i in range(5):  # Only 5 images (below min of 10)
            img = Image.new("RGB", (512, 512), color=(100 + i * 20, 150, 200))
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                img.save(f.name)
                paths.append(f.name)
        yield paths
        for path in paths:
            Path(path).unlink()

    def test_engine_initialization(self, config):
        """Test engine can be initialized."""
        engine = MeshroomEngine(config)
        assert engine is not None
        assert engine.get_engine_name() == "MeshroomEngine"

    def test_engine_from_loader(self, config):
        """Test engine can be loaded via factory."""
        engine = load_engine("meshroom", config)
        assert engine is not None
        assert isinstance(engine, MeshroomEngine)

    def test_available_engines_includes_meshroom(self):
        """Test that meshroom is in available engines."""
        engines = get_available_engines()
        assert "meshroom" in engines

    def test_both_engines_available(self):
        """Test both trellis and meshroom are available."""
        engines = get_available_engines()
        assert "trellis" in engines
        assert "meshroom" in engines

    def test_get_engine_info(self, config):
        """Test engine info retrieval."""
        engine = MeshroomEngine(config)
        info = engine.get_engine_info()

        assert info["name"] == "MeshroomEngine"
        assert info["min_images"] == 10
        assert info["max_images"] == 50
        assert info["pipeline"] == "Structure from Motion (SfM)"
        assert "use_gpu" in info
        assert "quality" in info

    def test_minimum_images_requirement(self, config, insufficient_images):
        """Test that preprocessing validates minimum image count."""
        engine = MeshroomEngine(config)

        with pytest.raises(ValueError) as exc_info:
            engine.preprocess(insufficient_images)

        assert "at least" in str(exc_info.value).lower()

    def test_maximum_images_limit(self, config):
        """Test that preprocessing respects maximum image count."""
        config.max_images = 15
        engine = MeshroomEngine(config)

        # Create 25 images
        paths = []
        for i in range(25):
            img = Image.new("RGB", (512, 512), color=(100, 150, 200))
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                img.save(f.name)
                paths.append(f.name)

        try:
            preprocessed = engine.preprocess(paths)
            # Should be limited to max_images
            assert len(preprocessed) <= config.max_images
        finally:
            for path in paths:
                Path(path).unlink()

    def test_image_preprocessing_multiple(self, config, test_images):
        """Test preprocessing multiple images."""
        engine = MeshroomEngine(config)
        preprocessed = engine.preprocess(test_images)

        # Should preprocess all test images (12)
        assert len(preprocessed) == 12
        for img in preprocessed:
            assert isinstance(img, Image.Image)

    def test_invalid_engine_name(self, config):
        """Test error on invalid engine name."""
        with pytest.raises(ValueError):
            load_engine("invalid_engine_xyz", config)

    def test_image_validation_nonexistent(self, config):
        """Test error on nonexistent image."""
        engine = MeshroomEngine(config)
        with pytest.raises(ValueError):
            engine.preprocess("/nonexistent/image.jpg")

    def test_meshroom_constants(self):
        """Test Meshroom engine constants."""
        assert MeshroomEngine.MESHROOM_MIN_IMAGES == 10
        assert MeshroomEngine.MESHROOM_MAX_IMAGES == 50
        assert MeshroomEngine.MESHROOM_IMAGE_MIN_RESOLUTION == 256
        assert MeshroomEngine.MESHROOM_IMAGE_MAX_RESOLUTION == 4096

    def test_engine_config_inherits_base(self, config):
        """Test that Meshroom engine inherits from base correctly."""
        engine = MeshroomEngine(config)

        # Should have base class attributes
        assert hasattr(engine, "device")
        assert hasattr(engine, "config")
        assert hasattr(engine, "get_engine_name")
        assert hasattr(engine, "get_engine_info")


class TestMeshroomIntegration:
    """Integration tests for Meshroom engine."""

    @pytest.fixture
    def config(self):
        """Fixture for engine config."""
        return EngineConfig(
            resolution=1024,
            max_images=50,
            device="cpu",
        )

    def test_engine_info_structure(self, config):
        """Test that engine info has all required fields."""
        engine = MeshroomEngine(config)
        info = engine.get_engine_info()

        required_fields = [
            "name",
            "device",
            "min_images",
            "max_images",
            "resolution",
            "output_format",
            "pipeline",
        ]
        for field in required_fields:
            assert field in info, f"Missing field: {field}"

    def test_quality_settings(self, config):
        """Test quality setting options."""
        engine = MeshroomEngine(config)

        # Test setting different quality levels
        engine.quality = "high"
        assert engine.quality == "high"

        engine.quality = "medium"
        assert engine.quality == "medium"

        engine.quality = "low"
        assert engine.quality == "low"

    def test_gpu_settings(self, config):
        """Test GPU setting configuration."""
        engine = MeshroomEngine(config)

        # Test enabling/disabling GPU
        engine.use_gpu = True
        assert engine.use_gpu is True

        engine.use_gpu = False
        assert engine.use_gpu is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
