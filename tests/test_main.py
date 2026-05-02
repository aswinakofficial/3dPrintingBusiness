"""
Unit tests for main orchestration pipeline.
Tests CLI argument parsing, configuration, and pipeline execution.
"""

import json
import tempfile
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, Mock, patch

import pytest

from main import Config, Pipeline


class TestConfig:
    """Tests for Config class."""

    def test_config_initialization_valid(self, tmp_path):
        """Test config loads successfully from valid YAML."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
paths:
  input: ./input
  output: ./output
  logs: ./logs
runtime:
  local_gpu: false
  cloud_provider: azure
"""
        )

        config = Config(str(config_file))
        assert config.data is not None
        assert "paths" in config.data
        assert "runtime" in config.data

    def test_config_initialization_missing_file(self):
        """Test config fails when file missing."""
        with pytest.raises(FileNotFoundError):
            Config("/nonexistent/config.yaml")

    def test_config_initialization_invalid_yaml(self, tmp_path):
        """Test config fails on invalid YAML."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: content:")

        with pytest.raises(Exception):
            Config(str(config_file))

    def test_config_get_dot_notation(self, tmp_path):
        """Test config.get() with dot notation."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
paths:
  input: ./input
  output: ./output
runtime:
  local_gpu: false
"""
        )

        config = Config(str(config_file))
        assert config.get("paths.input") == "./input"
        assert config.get("paths.output") == "./output"
        assert config.get("runtime.local_gpu") is False

    def test_config_get_default(self, tmp_path):
        """Test config.get() with default value."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("paths:\n  input: ./input\n")

        config = Config(str(config_file))
        assert config.get("nonexistent.key", "default") == "default"

    def test_config_get_output_dir_creates(self, tmp_path):
        """Test config creates output directory."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"paths:\n  output: {tmp_path / 'out'}\nruntime:\n  local_gpu: false")

        config = Config(str(config_file))
        output_dir = config.get_output_dir()
        assert output_dir.exists()

    def test_config_get_logs_dir_creates(self, tmp_path):
        """Test config creates logs directory."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"paths:\n  logs: {tmp_path / 'logs'}\nruntime:\n  local_gpu: false")

        config = Config(str(config_file))
        logs_dir = config.get_logs_dir()
        assert logs_dir.exists()


class TestPipeline:
    """Tests for Pipeline class."""

    @pytest.fixture
    def config_and_temp_dir(self, tmp_path):
        """Create config and temporary directory."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            f"""
paths:
  input: {tmp_path / 'input'}
  output: {tmp_path / 'output'}
  logs: {tmp_path / 'logs'}
runtime:
  local_gpu: false
post_processing:
  auto_repair: true
  mesh_repair:
    max_hole_size: 30
  hollowing:
    enabled: false
    wall_thickness_mm: 2.0
  supports:
    enabled: false
"""
        )
        config = Config(str(config_file))
        return config, tmp_path

    def test_pipeline_initialization(self, config_and_temp_dir):
        """Test pipeline initializes with engine."""
        config, tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        assert pipeline.engine_name == "trellis"
        assert pipeline.config == config
        assert pipeline.session_dir.exists()

    def test_pipeline_session_dir_creation(self, config_and_temp_dir):
        """Test pipeline creates timestamped session directory."""
        config, tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        assert pipeline.session_dir.exists()
        assert "trellis" in str(pipeline.session_dir)
        assert tmp_path / "output" / "trellis" in pipeline.session_dir.parents

    def test_pipeline_custom_output_dir(self, config_and_temp_dir):
        """Test pipeline respects custom output directory."""
        config, tmp_path = config_and_temp_dir
        custom_output = tmp_path / "custom_output"

        pipeline = Pipeline("trellis", config, output_dir=custom_output)
        assert custom_output in pipeline.session_dir.parents

    def test_pipeline_gets_default_post_processing_config(self, config_and_temp_dir):
        """Test pipeline loads post-processing config from YAML."""
        config, tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        assert pipeline.post_processing_config is not None
        assert pipeline.post_processing_config.repair_non_manifold is True
        assert pipeline.post_processing_config.max_hole_size == 30

    def test_pipeline_validate_inputs_no_images(self, config_and_temp_dir):
        """Test validation fails with no images."""
        config, tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        with pytest.raises(ValueError, match="No images provided"):
            pipeline._validate_inputs([])

    def test_pipeline_validate_inputs_file_not_found(self, config_and_temp_dir):
        """Test validation fails with missing file."""
        config, tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        with pytest.raises(FileNotFoundError):
            pipeline._validate_inputs(["/nonexistent/image.jpg"])

    def test_pipeline_validate_inputs_trellis_max_images(self, config_and_temp_dir, tmp_path):
        """Test TRELLIS.2 rejects more than 4 images."""
        config, base_tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        # Create fake image files
        from PIL import Image

        images = []
        for i in range(5):
            img = Image.new("RGB", (100, 100))
            path = tmp_path / f"image_{i}.jpg"
            img.save(path)
            images.append(str(path))

        with pytest.raises(ValueError, match="supports max 4 images"):
            pipeline._validate_inputs(images)

    def test_pipeline_validate_inputs_meshroom_min_images(self, config_and_temp_dir, tmp_path):
        """Test Meshroom requires at least 10 images."""
        config, base_tmp_path = config_and_temp_dir
        pipeline = Pipeline("meshroom", config)

        # Create fake image files
        from PIL import Image

        images = []
        for i in range(5):
            img = Image.new("RGB", (100, 100))
            path = tmp_path / f"image_{i}.jpg"
            img.save(path)
            images.append(str(path))

        with pytest.raises(ValueError, match="requires min 10 images"):
            pipeline._validate_inputs(images)

    def test_pipeline_validate_inputs_meshroom_max_images(self, config_and_temp_dir, tmp_path):
        """Test Meshroom rejects more than 50 images."""
        config, base_tmp_path = config_and_temp_dir
        pipeline = Pipeline("meshroom", config)

        # Create fake image files
        from PIL import Image

        images = []
        for i in range(51):
            img = Image.new("RGB", (100, 100))
            path = tmp_path / f"image_{i}.jpg"
            img.save(path)
            images.append(str(path))

        with pytest.raises(ValueError, match="supports max 50 images"):
            pipeline._validate_inputs(images)

    @patch("main.load_engine")
    def test_pipeline_load_engine_success(self, mock_load, config_and_temp_dir):
        """Test engine loading."""
        config, tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        mock_engine = MagicMock()
        mock_engine.validate_prerequisites.return_value = None
        mock_load.return_value = mock_engine

        engine = pipeline._load_engine()

        assert engine == mock_engine
        mock_load.assert_called_once()
        mock_engine.validate_prerequisites.assert_called_once()

    @patch("main.load_engine")
    def test_pipeline_load_engine_fails_prerequisites(self, mock_load, config_and_temp_dir):
        """Test engine fails on prerequisite check."""
        config, tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        mock_engine = MagicMock()
        mock_engine.validate_prerequisites.side_effect = RuntimeError("CUDA not available")
        mock_load.return_value = mock_engine

        with pytest.raises(RuntimeError):
            pipeline._load_engine()

    @patch("main.ImagePreprocessor")
    def test_pipeline_preprocess_images_single(self, mock_preprocessor_class, config_and_temp_dir, tmp_path):
        """Test preprocessing a single image."""
        config, base_tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        # Create fake image
        from PIL import Image
        img = Image.new("RGB", (512, 512))
        img_path = tmp_path / "test.jpg"
        img.save(img_path)

        # Setup mock preprocessor
        mock_preprocessor = MagicMock()
        mock_preprocessor_class.return_value = mock_preprocessor
        mock_preprocessor.load_image.return_value = img
        mock_preprocessor.remove_background.return_value = img
        mock_preprocessor.normalize_image.return_value = img

        preprocessed = pipeline._preprocess_images([str(img_path)])

        assert len(preprocessed) == 1
        assert Path(preprocessed[0]).exists()

    @patch("main.ImagePreprocessor")
    def test_pipeline_preprocess_images_multiple(self, mock_preprocessor_class, config_and_temp_dir, tmp_path):
        """Test preprocessing multiple images."""
        config, base_tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        # Create fake images
        from PIL import Image
        images = []
        for i in range(3):
            img = Image.new("RGB", (512, 512))
            img_path = tmp_path / f"test_{i}.jpg"
            img.save(img_path)
            images.append(str(img_path))

        # Setup mock preprocessor
        mock_preprocessor = MagicMock()
        mock_preprocessor_class.return_value = mock_preprocessor
        mock_preprocessor.load_image.return_value = Image.new("RGB", (512, 512))
        mock_preprocessor.remove_background.return_value = Image.new("RGB", (512, 512))
        mock_preprocessor.normalize_image.return_value = Image.new("RGB", (512, 512))

        preprocessed = pipeline._preprocess_images(images)

        assert len(preprocessed) == 3

    @patch("main.PostProcessingPipeline")
    def test_pipeline_post_process_mesh_success(self, mock_pp_class, config_and_temp_dir, tmp_path):
        """Test mesh post-processing."""
        config, base_tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        # Setup mock pipeline
        mock_pp = MagicMock()
        mock_pp_class.return_value = mock_pp
        mock_pp.process_mesh.return_value = {
            "mesh_path": str(tmp_path / "final.glb"),
            "vertices": 5000,
            "faces": 10000,
            "has_supports": False,
        }

        raw_mesh = str(tmp_path / "raw.glb")
        results = pipeline._post_process_mesh(raw_mesh)

        assert results["vertices"] == 5000
        assert results["faces"] == 10000
        mock_pp.process_mesh.assert_called_once()

    def test_pipeline_save_metadata_creates_json(self, config_and_temp_dir):
        """Test metadata is saved to JSON."""
        config, tmp_path = config_and_temp_dir
        pipeline = Pipeline("trellis", config)

        results = {
            "mesh_path": str(tmp_path / "final.glb"),
            "support_path": str(tmp_path / "supports.glb"),
            "vertices": 5000,
            "faces": 10000,
            "has_supports": True,
            "overhang_faces": 100,
        }

        pipeline._save_metadata(results, ["image1.jpg", "image2.jpg"])

        metadata_path = pipeline.session_dir / "metadata.json"
        assert metadata_path.exists()

        with open(metadata_path) as f:
            metadata = json.load(f)

        assert metadata["engine"] == "trellis"
        assert len(metadata["input_images"]) == 2
        assert metadata["mesh_stats"]["vertices"] == 5000


class TestPipelineIntegration:
    """Integration tests for full pipeline execution."""

    @pytest.fixture
    def full_test_setup(self, tmp_path):
        """Setup for full pipeline tests."""
        # Create config
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            f"""
paths:
  input: {tmp_path / 'input'}
  output: {tmp_path / 'output'}
  logs: {tmp_path / 'logs'}
runtime:
  local_gpu: false
post_processing:
  auto_repair: true
  hollowing:
    enabled: false
"""
        )

        # Create test image
        from PIL import Image
        img = Image.new("RGB", (512, 512), color="white")
        img_path = tmp_path / "test.jpg"
        img.save(img_path)

        config = Config(str(config_file))
        return config, tmp_path, str(img_path)

    @patch("main.PostProcessingPipeline")
    @patch("main.load_engine")
    def test_pipeline_run_complete(self, mock_load_engine, mock_pp_class, full_test_setup):
        """Test complete pipeline execution."""
        config, tmp_path, img_path = full_test_setup

        # Mock engine
        mock_engine = MagicMock()
        mock_engine.validate_prerequisites.return_value = None
        mock_engine.preprocess.return_value = [img_path]
        mock_engine.infer.return_value = MagicMock()

        # Create mock raw mesh
        raw_mesh_path = str(tmp_path / "raw.glb")
        Path(raw_mesh_path).touch()
        mock_engine.postprocess.return_value = raw_mesh_path
        mock_load_engine.return_value = mock_engine

        # Mock post-processing
        mock_pp = MagicMock()
        mock_pp.process_mesh.return_value = {
            "mesh_path": str(tmp_path / "final.glb"),
            "vertices": 5000,
            "faces": 10000,
            "has_supports": False,
        }
        mock_pp_class.return_value = mock_pp

        pipeline = Pipeline("trellis", config)
        results = pipeline.run([img_path])

        assert "mesh_path" in results
        assert results["vertices"] == 5000
        assert (pipeline.session_dir / "metadata.json").exists()
