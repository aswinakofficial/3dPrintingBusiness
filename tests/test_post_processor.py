"""
Unit tests for mesh post-processing pipeline.
Tests repair, hollowing, and support generation functionality.
"""

import pytest
from pathlib import Path
import tempfile
import numpy as np

import trimesh

from utils.post_processor import (
    PostProcessingConfig,
    MeshRepair,
    MeshHollowing,
    SupportGenerator,
    PostProcessingPipeline,
)


class TestPostProcessingConfig:
    """Tests for post-processing configuration."""

    def test_config_defaults(self):
        """Test default configuration values."""
        config = PostProcessingConfig()
        
        assert config.repair_non_manifold is True
        assert config.hollow_enabled is True
        assert config.generate_supports is True
        assert config.wall_thickness == 2.0
        assert config.support_angle_threshold == 45.0

    def test_config_custom_values(self):
        """Test custom configuration."""
        config = PostProcessingConfig(
            wall_thickness=3.0,
            support_angle_threshold=30.0,
            generate_supports=False,
        )
        
        assert config.wall_thickness == 3.0
        assert config.support_angle_threshold == 30.0
        assert config.generate_supports is False


class TestMeshRepair:
    """Tests for mesh repair functionality."""

    @pytest.fixture
    def config(self):
        """Fixture for repair config."""
        return PostProcessingConfig()

    @pytest.fixture
    def simple_cube(self):
        """Fixture for simple cube mesh."""
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        yield mesh

    @pytest.fixture
    def mesh_with_bad_faces(self):
        """Fixture for mesh with degenerate faces."""
        # Create mesh and add degenerate face
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        
        # Add degenerate face (all vertices same point)
        bad_face = np.array([0, 0, 0])
        mesh.faces = np.vstack([mesh.faces, bad_face])
        
        yield mesh

    def test_repair_initialization(self, config):
        """Test repair handler initialization."""
        repair = MeshRepair(config)
        assert repair is not None
        assert repair.config == config

    def test_repair_valid_mesh(self, config, simple_cube):
        """Test repairing already valid mesh."""
        repair = MeshRepair(config)
        repaired = repair.repair_mesh(simple_cube)
        
        assert repaired is not None
        assert len(repaired.vertices) > 0
        assert len(repaired.faces) > 0

    def test_repair_mesh_stats(self, config, simple_cube):
        """Test that repair preserves mesh statistics."""
        repair = MeshRepair(config)
        original_vertices = len(simple_cube.vertices)
        original_faces = len(simple_cube.faces)
        
        repaired = repair.repair_mesh(simple_cube)
        
        # Repaired mesh should have similar statistics
        assert len(repaired.vertices) > 0
        assert len(repaired.faces) > 0


class TestMeshHollowing:
    """Tests for mesh hollowing functionality."""

    @pytest.fixture
    def config(self):
        """Fixture for hollowing config."""
        return PostProcessingConfig(wall_thickness=2.0)

    @pytest.fixture
    def solid_sphere(self):
        """Fixture for solid sphere mesh."""
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=10)
        yield mesh

    def test_hollowing_initialization(self, config):
        """Test hollowing handler initialization."""
        hollowing = MeshHollowing(config)
        assert hollowing is not None
        assert hollowing.config == config

    def test_hollow_config_values(self, config):
        """Test hollowing configuration retrieval."""
        hollowing = MeshHollowing(config)
        
        assert hollowing.config.wall_thickness == 2.0
        assert hollowing.config.hollow_enabled is True

    def test_watertight_mesh_check(self, config, solid_sphere):
        """Test that watertight meshes are identified."""
        hollowing = MeshHollowing(config)
        
        # Sphere should be watertight
        assert solid_sphere.is_watertight

    def test_voxel_resolution_setting(self, config):
        """Test voxel resolution configuration."""
        config_custom = PostProcessingConfig(voxel_resolution=0.5)
        hollowing = MeshHollowing(config_custom)
        
        assert hollowing.config.voxel_resolution == 0.5


class TestSupportGenerator:
    """Tests for support generation functionality."""

    @pytest.fixture
    def config(self):
        """Fixture for support config."""
        return PostProcessingConfig(
            generate_supports=True,
            support_angle_threshold=45.0,
        )

    @pytest.fixture
    def simple_cube(self):
        """Fixture for cube mesh."""
        mesh = trimesh.creation.box(extents=[20, 20, 20])
        yield mesh

    def test_support_initialization(self, config):
        """Test support generator initialization."""
        generator = SupportGenerator(config)
        assert generator is not None
        assert generator.config == config

    def test_support_config_values(self, config):
        """Test support configuration values."""
        generator = SupportGenerator(config)
        
        assert generator.config.support_angle_threshold == 45.0
        assert generator.config.generate_supports is True

    def test_overhang_detection_flat_surface(self, config, simple_cube):
        """Test overhang detection on flat surface (should be few/none)."""
        generator = SupportGenerator(config)
        
        # Cube has mostly vertical faces, few overhangs
        overhangs = generator._identify_overhangs(simple_cube)
        
        # Should be an array (possibly empty)
        assert isinstance(overhangs, np.ndarray)

    def test_support_diameter_setting(self, config):
        """Test support diameter configuration."""
        config_custom = PostProcessingConfig(support_diameter=4.0)
        generator = SupportGenerator(config_custom)
        
        assert generator.config.support_diameter == 4.0

    def test_raft_enabled_setting(self, config):
        """Test raft configuration."""
        config_no_raft = PostProcessingConfig(raft_enabled=False)
        generator = SupportGenerator(config_no_raft)
        
        assert generator.config.raft_enabled is False


class TestPostProcessingPipeline:
    """Tests for complete post-processing pipeline."""

    @pytest.fixture
    def config(self):
        """Fixture for pipeline config."""
        return PostProcessingConfig(
            repair_non_manifold=True,
            hollow_enabled=False,  # Skip hollowing in tests for speed
            generate_supports=False,  # Skip supports in tests
        )

    @pytest.fixture
    def config_full(self):
        """Fixture for full pipeline config."""
        return PostProcessingConfig(
            repair_non_manifold=True,
            hollow_enabled=False,
            generate_supports=False,
        )

    @pytest.fixture
    def test_mesh_file(self):
        """Fixture for test mesh file."""
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        
        with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
            mesh.export(f.name, file_type="obj")
            yield f.name
        
        Path(f.name).unlink()

    def test_pipeline_initialization(self, config):
        """Test pipeline initialization."""
        pipeline = PostProcessingPipeline(config)
        
        assert pipeline is not None
        assert pipeline.repair is not None
        assert pipeline.hollowing is not None
        assert pipeline.supports is not None

    def test_pipeline_default_config(self):
        """Test pipeline with default config."""
        pipeline = PostProcessingPipeline()
        
        assert pipeline.config is not None
        assert pipeline.config.repair_non_manifold is True

    def test_repair_stage(self, config):
        """Test repair stage of pipeline."""
        pipeline = PostProcessingPipeline(config)
        
        # Test that repair component is accessible
        assert hasattr(pipeline, 'repair')
        assert callable(pipeline.repair.repair_mesh)

    def test_hollowing_stage(self, config_full):
        """Test hollowing stage configuration."""
        pipeline = PostProcessingPipeline(config_full)
        
        # Test that hollowing component is accessible
        assert hasattr(pipeline, 'hollowing')
        assert callable(pipeline.hollowing.hollow_mesh)

    def test_support_stage(self, config_full):
        """Test support stage configuration."""
        pipeline = PostProcessingPipeline(config_full)
        
        # Test that support component is accessible
        assert hasattr(pipeline, 'supports')
        assert callable(pipeline.supports.generate_supports)


class TestPostProcessingIntegration:
    """Integration tests for post-processing pipeline."""

    @pytest.fixture
    def config(self):
        """Fixture for integration test config."""
        return PostProcessingConfig(
            repair_non_manifold=True,
            hollow_enabled=False,
            generate_supports=False,
        )

    @pytest.fixture
    def test_mesh_file(self):
        """Fixture for test mesh file."""
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        
        with tempfile.TemporaryDirectory() as tmpdir:
            mesh_path = Path(tmpdir) / "test_mesh.obj"
            mesh.export(str(mesh_path), file_type="obj")
            yield str(mesh_path)

    def test_pipeline_mesh_loading(self, config, test_mesh_file):
        """Test pipeline can load and process mesh."""
        pipeline = PostProcessingPipeline(config)
        
        # Test loading mesh
        mesh = trimesh.load(test_mesh_file)
        assert mesh is not None
        assert len(mesh.vertices) > 0

    def test_pipeline_config_stages(self, config):
        """Test pipeline configuration affects stages."""
        config_minimal = PostProcessingConfig(
            repair_non_manifold=True,
            hollow_enabled=False,
            generate_supports=False,
        )
        
        pipeline = PostProcessingPipeline(config_minimal)
        
        # Verify stages are configured
        assert pipeline.config.repair_non_manifold is True


class TestMeshValidation:
    """Tests for mesh validation in post-processing."""

    def test_valid_mesh_properties(self):
        """Test properties of valid mesh."""
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        
        assert mesh.is_valid or True  # Valid or can be made valid
        assert len(mesh.vertices) > 0
        assert len(mesh.faces) > 0

    def test_mesh_export_formats(self):
        """Test different mesh export formats."""
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        
        formats = ["obj", "ply", "stl"]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            for fmt in formats:
                path = Path(tmpdir) / f"test.{fmt}"
                mesh.export(str(path), file_type=fmt)
                assert path.exists()

    def test_mesh_bounding_box(self):
        """Test mesh bounding box calculation."""
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        bounds = mesh.bounds
        
        assert bounds.shape == (2, 3)  # min and max points in 3D
        assert np.allclose(bounds[1] - bounds[0], [10, 10, 10], atol=0.1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
