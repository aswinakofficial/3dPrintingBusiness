"""Meshroom Structure from Motion (SfM) engine for 3D reconstruction."""

import subprocess
import os
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Union
import shutil
from datetime import datetime

import trimesh

from engines.base_engine import Engine, EngineConfig
from utils.logger import get_logger
from utils.pre_processor import ImageValidator, ImagePreprocessor

logger = get_logger()


class MeshroomEngine(Engine):
    """
    Meshroom Structure from Motion engine for multi-view 3D reconstruction.

    Meshroom uses AliceVision algorithms to reconstruct 3D models from multiple
    overlapping 2D images. Suitable for real-world object scanning and photogrammetry.

    Configuration:
        - min_images: Minimum number of images required (default: 10)
        - max_images: Maximum images to process (default: 50)
        - use_gpu: Enable GPU acceleration (default: true)
        - quality: Processing quality level (high, medium, low)
    """

    # Meshroom configuration constants
    MESHROOM_MIN_IMAGES = 10
    MESHROOM_MAX_IMAGES = 50
    MESHROOM_IMAGE_MIN_RESOLUTION = 256
    MESHROOM_IMAGE_MAX_RESOLUTION = 4096

    def __init__(self, config: EngineConfig):
        """
        Initialize Meshroom engine.

        Args:
            config: EngineConfig instance

        Raises:
            RuntimeError: If Meshroom is not installed
        """
        super().__init__(config)
        self.meshroom_path = None
        self.quality = "high"  # high, medium, low
        self.use_gpu = True
        self.graph_file = None
        self.cache_path = None

        logger.info(
            "Initializing MeshroomEngine",
            extra={
                "device": str(self.device),
                "max_images": config.max_images,
                "min_images": self.MESHROOM_MIN_IMAGES,
            },
        )

    def validate_prerequisites(self) -> bool:
        """
        Validate that Meshroom is installed and accessible.

        Checks for:
        - meshroom_photogrammetry or Meshroom command available
        - Required image input directory

        Returns:
            True if prerequisites are met

        Raises:
            RuntimeError: If Meshroom not found or dependencies missing
        """
        logger.info("Validating Meshroom prerequisites...")

        # Check for Meshroom installation
        meshroom_cmd = self._find_meshroom()
        if not meshroom_cmd:
            error_msg = (
                "Meshroom not found. Install via:\n"
                "  conda install meshroom -c conda-forge\n"
                "or download from https://alicevision.org"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        self.meshroom_path = meshroom_cmd
        logger.info(f"Found Meshroom at: {self.meshroom_path}")

        return True

    def _find_meshroom(self) -> Union[str, None]:
        """
        Find Meshroom command in system PATH.

        Returns:
            Path to meshroom_photogrammetry command or None if not found
        """
        # Try common Meshroom command names
        commands = ["meshroom_photogrammetry", "meshroom", "aliceVision"]

        for cmd in commands:
            path = shutil.which(cmd)
            if path:
                logger.debug(f"Found Meshroom at: {path}")
                return path

        # Try environment variable
        meshroom_env = os.environ.get("MESHROOM_EXECUTABLE")
        if meshroom_env and Path(meshroom_env).exists():
            logger.debug(f"Found Meshroom via environment: {meshroom_env}")
            return meshroom_env

        logger.warning("Meshroom not found in PATH or environment")
        return None

    def preprocess(self, image_paths: Union[str, List[str]]) -> List[Any]:
        """
        Preprocess input images for Meshroom SfM pipeline.

        Validates:
        - Number of images (10-50)
        - Image format and resolution
        - Image quality and overlap

        Args:
            image_paths: Single path, list, or directory

        Returns:
            List of validated PIL.Image objects

        Raises:
            ValueError: If image validation fails
        """
        logger.info("Preprocessing images for Meshroom SfM...")

        # Validate inputs
        validator = ImageValidator()
        validated_paths = validator.validate_input_images(
            image_paths, allow_directory=True
        )

        num_images = len(validated_paths)
        if num_images < self.MESHROOM_MIN_IMAGES:
            error_msg = (
                f"Need at least {self.MESHROOM_MIN_IMAGES} images, got {num_images}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        if num_images > self.MESHROOM_MAX_IMAGES:
            warning_msg = (
                f"Limiting to {self.MESHROOM_MAX_IMAGES} images from {num_images}"
            )
            logger.warning(warning_msg)
            validated_paths = validated_paths[: self.MESHROOM_MAX_IMAGES]

        # Load and validate images
        preprocessor = ImagePreprocessor()
        preprocessed_images = []

        for path in validated_paths:
            try:
                img = preprocessor.load_image(path)
                # Validate resolution
                if (
                    img.width < self.MESHROOM_IMAGE_MIN_RESOLUTION
                    or img.height < self.MESHROOM_IMAGE_MIN_RESOLUTION
                ):
                    logger.warning(
                        f"Image {path} below minimum resolution {self.MESHROOM_IMAGE_MIN_RESOLUTION}x{self.MESHROOM_IMAGE_MIN_RESOLUTION}"
                    )
                # Note: Don't resize for Meshroom - preserve full resolution for SfM
                preprocessed_images.append(img)
                logger.debug(f"Loaded image: {path} ({img.width}x{img.height})")
            except Exception as e:
                logger.error(f"Failed to load image {path}: {e}")
                raise ValueError(f"Failed to load image {path}: {e}")

        logger.info(f"Preprocessed {len(preprocessed_images)} images for Meshroom")

        return preprocessed_images

    def infer(self, preprocessed_images: List[Any]) -> Dict[str, Any]:
        """
        Run Meshroom SfM reconstruction pipeline.

        Steps:
        1. Create temporary working directory
        2. Copy images to working directory
        3. Initialize Meshroom graph
        4. Run photogrammetry pipeline
        5. Extract output mesh

        Args:
            preprocessed_images: List of PIL.Image objects from preprocess()

        Returns:
            Dict with mesh and metadata from SfM pipeline

        Raises:
            RuntimeError: If reconstruction fails
        """
        logger.info(
            f"Running Meshroom SfM reconstruction on {len(preprocessed_images)} images..."
        )

        # Create temporary working directory
        with tempfile.TemporaryDirectory(prefix="meshroom_") as tmpdir:
            tmpdir = Path(tmpdir)
            input_dir = tmpdir / "images"
            input_dir.mkdir()

            # Save preprocessed images to disk
            image_paths = []
            for idx, img in enumerate(preprocessed_images):
                img_path = input_dir / f"image_{idx:04d}.jpg"
                img.save(img_path, quality=95)
                image_paths.append(str(img_path))
                logger.debug(f"Saved image: {img_path}")

            # Create output directory
            output_dir = tmpdir / "output"
            output_dir.mkdir()

            try:
                # Run Meshroom photogrammetry
                result = self._run_meshroom_pipeline(
                    input_dir=str(input_dir),
                    output_dir=str(output_dir),
                    gpu_enabled=self.use_gpu,
                )

                if not result.get("success"):
                    error_msg = f"Meshroom pipeline failed: {result.get('error', 'unknown error')}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)

                # Extract output mesh
                mesh_path = result.get("mesh_path")
                if not mesh_path or not Path(mesh_path).exists():
                    error_msg = "Meshroom did not produce mesh output"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)

                # Load mesh
                mesh = trimesh.load(mesh_path)
                logger.info(
                    f"Successfully reconstructed mesh: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces"
                )

                return {
                    "mesh": mesh,
                    "mesh_path": mesh_path,
                    "num_images": len(preprocessed_images),
                    "pipeline": "meshroom_sfm",
                }

            except Exception as e:
                logger.error(f"Meshroom SfM reconstruction failed: {e}")
                raise RuntimeError(f"Meshroom reconstruction failed: {e}")

    def _run_meshroom_pipeline(
        self, input_dir: str, output_dir: str, gpu_enabled: bool = True
    ) -> Dict[str, Any]:
        """
        Execute Meshroom photogrammetry pipeline.

        Runs the complete SfM pipeline:
        - Image matching and feature extraction
        - Structure from Motion (SfM) computation
        - Mesh reconstruction
        - Mesh refinement

        Args:
            input_dir: Directory containing input images
            output_dir: Directory for pipeline output
            gpu_enabled: Use GPU acceleration if available

        Returns:
            Dict with success status and output paths
        """
        logger.info(
            "Running Meshroom photogrammetry pipeline...",
            extra={
                "input_dir": input_dir,
                "output_dir": output_dir,
                "gpu": gpu_enabled,
            },
        )

        try:
            # Build Meshroom command
            cmd = [
                self.meshroom_path,
                "--input",
                input_dir,
                "--output",
                output_dir,
                "--verbose",
            ]

            if gpu_enabled:
                cmd.append("--gpu")

            # Add quality settings
            if self.quality == "high":
                cmd.extend(["--quality", "high"])
            elif self.quality == "medium":
                cmd.extend(["--quality", "medium"])
            else:
                cmd.extend(["--quality", "low"])

            logger.debug(f"Executing: {' '.join(cmd)}")

            # Execute pipeline (this may take several minutes)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
            )

            if result.returncode != 0:
                error_output = result.stderr or result.stdout
                logger.error(f"Meshroom command failed: {error_output}")
                return {"success": False, "error": error_output}

            logger.info("Meshroom pipeline completed successfully")

            # Find output mesh file
            mesh_path = self._find_output_mesh(Path(output_dir))
            if not mesh_path:
                logger.error("No mesh file found in Meshroom output")
                return {"success": False, "error": "No mesh output found"}

            return {"success": True, "mesh_path": str(mesh_path)}

        except subprocess.TimeoutExpired:
            error_msg = "Meshroom pipeline timed out (exceeded 1 hour)"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        except Exception as e:
            logger.error(f"Meshroom pipeline execution failed: {e}")
            return {"success": False, "error": str(e)}

    def _find_output_mesh(self, output_dir: Path) -> Union[Path, None]:
        """
        Find output mesh file from Meshroom pipeline.

        Looks for .obj, .ply, or .fbx files in output directory.

        Args:
            output_dir: Meshroom output directory

        Returns:
            Path to mesh file or None if not found
        """
        mesh_formats = [".obj", ".ply", ".fbx", ".gltf", ".glb"]

        for root, dirs, files in os.walk(output_dir):
            for file in files:
                if Path(file).suffix.lower() in mesh_formats:
                    mesh_path = Path(root) / file
                    logger.debug(f"Found mesh: {mesh_path}")
                    return mesh_path

        logger.warning("No mesh file found in output directory")
        return None

    def postprocess(self, raw_output: Dict[str, Any]) -> str:
        """
        Export Meshroom output to standardized GLB format.

        Args:
            raw_output: Dict from infer() with mesh and metadata

        Returns:
            Path to exported GLB file

        Raises:
            RuntimeError: If export fails
        """
        logger.info("Post-processing Meshroom mesh output...")

        try:
            mesh = raw_output.get("mesh")
            if mesh is None:
                raise ValueError("No mesh in raw_output")

            # Create output directory
            output_dir = Path("output/meshroom")
            output_dir.mkdir(parents=True, exist_ok=True)

            # Generate output filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"{timestamp}_reconstructed.glb"

            # Ensure mesh is valid
            if not mesh.is_valid:
                logger.warning("Mesh has invalid properties, attempting repair...")
                mesh.remove_infinite_values()
                mesh.remove_degenerate_faces()

            # Export to GLB
            mesh.export(str(output_path), file_type="glb")
            logger.info(
                f"Exported mesh to {output_path}",
                extra={
                    "vertices": len(mesh.vertices),
                    "faces": len(mesh.faces),
                    "file_size_mb": output_path.stat().st_size / (1024 * 1024),
                },
            )

            return str(output_path)

        except Exception as e:
            error_msg = f"Post-processing failed: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_engine_info(self) -> Dict[str, Any]:
        """
        Get Meshroom engine information and capabilities.

        Returns:
            Dict with engine metadata
        """
        info = {
            "name": self.get_engine_name(),
            "device": str(self.device),
            "min_images": self.MESHROOM_MIN_IMAGES,
            "max_images": self.MESHROOM_MAX_IMAGES,
            "resolution": self.config.resolution,
            "output_format": self.config.output_format,
            "pipeline": "Structure from Motion (SfM)",
            "use_gpu": self.use_gpu,
            "quality": self.quality,
        }
        return info
