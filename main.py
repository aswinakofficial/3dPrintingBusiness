#!/usr/bin/env python3
"""
Main orchestration for 3D Figurine Lab.
Unified CLI for running the 3D model generation pipeline with pluggable engines.
"""

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

from engines.base_engine import EngineConfig
from engines.loader import load_engine, get_available_engines
from utils.logger import setup_logger, get_logger
from utils.pre_processor import ImagePreprocessor, ImageValidator
from utils.post_processor import PostProcessingConfig, PostProcessingPipeline

logger = get_logger()


class Config:
    """Runtime configuration from YAML and CLI arguments."""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize configuration from YAML file.

        Args:
            config_path: Path to config.yaml file

        Raises:
            FileNotFoundError: If config file not found
            yaml.YAMLError: If YAML parsing fails
        """
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(self.config_path, "r") as f:
            self.data = yaml.safe_load(f)

        self._validate_config()

    def _validate_config(self):
        """Validate required config sections."""
        required_sections = ["paths", "runtime"]
        for section in required_sections:
            if section not in self.data:
                raise ValueError(f"Missing required config section: {section}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value by dot-notation key."""
        keys = key.split(".")
        value = self.data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        return value

    def get_output_dir(self) -> Path:
        """Get configured output directory."""
        output_dir = Path(self.get("paths.output", "./output"))
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_input_dir(self) -> Path:
        """Get configured input directory."""
        return Path(self.get("paths.input", "./input"))

    def get_logs_dir(self) -> Path:
        """Get configured logs directory."""
        logs_dir = Path(self.get("paths.logs", "./logs"))
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir


class Pipeline:
    """Main orchestration pipeline for 3D model generation."""

    def __init__(
        self,
        engine_name: str,
        config: Config,
        output_dir: Optional[Path] = None,
        post_processing_config: Optional[PostProcessingConfig] = None,
        generate_views: bool = False,
    ):
        """
        Initialize pipeline.

        Args:
            engine_name: Engine to use (trellis, meshroom)
            config: Runtime configuration
            output_dir: Output directory (overrides config)
            post_processing_config: Post-processing settings
        """
        self.engine_name = engine_name
        self.config = config
        self.output_dir = output_dir or config.get_output_dir()
        self.post_processing_config = (
            post_processing_config or self._get_default_post_processing_config()
        )
        self.generate_views = generate_views
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = self.output_dir / engine_name / self.timestamp
        self.session_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"Pipeline initialized: engine={engine_name}, session={self.session_dir}"
        )

    def _get_default_post_processing_config(self) -> PostProcessingConfig:
        """Load post-processing config from YAML."""
        cfg = self.config
        return PostProcessingConfig(
            repair_non_manifold=cfg.get("post_processing.auto_repair", True),
            max_hole_size=cfg.get("post_processing.mesh_repair.max_hole_size", 30),
            hollow_enabled=cfg.get("post_processing.hollowing.enabled", False),
            wall_thickness=cfg.get("post_processing.hollowing.wall_thickness_mm", 2.0),
            voxel_resolution=cfg.get(
                "post_processing.hollowing.voxel_resolution_mm", 1.0
            ),
            generate_supports=cfg.get("post_processing.supports.enabled", False),
            support_angle_threshold=cfg.get(
                "post_processing.supports.angle_threshold_degrees", 45
            ),
            support_diameter=cfg.get("post_processing.supports.diameter_mm", 4.0),
        )

    def run(self, image_paths: List[str]) -> Dict[str, Any]:
        """
        Run complete pipeline: preprocess → infer → post-process → export.

        Args:
            image_paths: List of input image file paths

        Returns:
            Dictionary with results metadata

        Raises:
            ValueError: If inputs invalid
            RuntimeError: If pipeline execution fails
        """
        try:
            # Stage 1: Validation
            logger.info("=" * 60)
            logger.info("STAGE 1: VALIDATION")
            logger.info("=" * 60)
            image_paths = self._validate_inputs(image_paths)

            # Stage 2: Load engine
            logger.info("=" * 60)
            logger.info("STAGE 2: ENGINE LOADING")
            logger.info("=" * 60)
            engine = self._load_engine()

            # Stage 3: Preprocess images
            logger.info("=" * 60)
            logger.info("STAGE 3: IMAGE PREPROCESSING")
            logger.info("=" * 60)
            preprocessed = self._preprocess_images(image_paths)

            # Stage 3.5: Multi-view generation (optional)
            if self.generate_views:
                logger.info("=" * 60)
                logger.info("STAGE 3.5: MULTI-VIEW GENERATION")
                logger.info("=" * 60)
                preprocessed = self._generate_views(preprocessed)

            # Stage 4: Run inference
            logger.info("=" * 60)
            logger.info("STAGE 4: MODEL INFERENCE")
            logger.info("=" * 60)
            raw_mesh_path = self._run_inference(engine, preprocessed)

            # Stage 5: Post-process mesh
            logger.info("=" * 60)
            logger.info("STAGE 5: MESH POST-PROCESSING")
            logger.info("=" * 60)
            final_results = self._post_process_mesh(raw_mesh_path)

            # Stage 6: Save metadata
            logger.info("=" * 60)
            logger.info("STAGE 6: RESULTS EXPORT")
            logger.info("=" * 60)
            self._save_metadata(final_results, image_paths)

            logger.info("=" * 60)
            logger.info("PIPELINE COMPLETE")
            logger.info("=" * 60)

            return final_results

        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            logger.error(traceback.format_exc())
            raise

    def _validate_inputs(self, image_paths: List[str]) -> List[str]:
        """
        Validate input image paths.

        Args:
            image_paths: List of image file paths

        Returns:
            Validated list of absolute paths

        Raises:
            ValueError: If inputs invalid
        """
        if not image_paths:
            raise ValueError("No images provided")

        validator = ImageValidator()
        validated_paths = []

        for image_path in image_paths:
            path = Path(image_path)
            if not path.exists():
                raise FileNotFoundError(f"Image not found: {image_path}")

            # Validate format
            try:
                validator.validate_input_images([str(path)])
                validated_paths.append(str(path.absolute()))
                logger.info(f"✓ Valid image: {path.name}")
            except ValueError as e:
                raise ValueError(f"Invalid image {image_path}: {e}")

        # Engine-specific validation
        if self.engine_name == "trellis":
            if not self.generate_views and len(validated_paths) > 4:
                raise ValueError(
                    f"TRELLIS.2 supports max 4 images, got {len(validated_paths)}. "
                    "Tip: use --generate-views to auto-select the best 4."
                )
            if self.generate_views:
                logger.info(
                    f"✓ TRELLIS.2: {len(validated_paths)} source image(s) "
                    "(will be reduced to 4 after view generation)"
                )
            else:
                logger.info(f"✓ TRELLIS.2: {len(validated_paths)} images (max 4)")
        elif self.engine_name == "meshroom":
            if len(validated_paths) > 50:
                raise ValueError(
                    f"Meshroom supports max 50 images, got {len(validated_paths)}"
                )
            if self.generate_views:
                logger.info(
                    f"✓ Meshroom: {len(validated_paths)} source image(s) "
                    "(additional views will be generated)"
                )
            else:
                if len(validated_paths) < 10:
                    raise ValueError(
                        f"Meshroom requires min 10 images, got {len(validated_paths)}. "
                        "Tip: use --generate-views to synthesise the remaining views automatically."
                    )
                logger.info(f"✓ Meshroom: {len(validated_paths)} images (10-50 range)")
        elif self.engine_name == "hunyuan3d":
            if len(validated_paths) > 6:
                raise ValueError(
                    f"Hunyuan3D-2 supports max 6 images, got {len(validated_paths)}"
                )
            logger.info(
                f"✓ Hunyuan3D-2: {len(validated_paths)} image(s) "
                "(1–6 views, assigned front→right→back→left order)"
            )

        return validated_paths

    def _load_engine(self):
        """
        Load and initialize the selected engine.

        Returns:
            Initialized Engine instance

        Raises:
            RuntimeError: If engine initialization fails
        """
        logger.info(f"Loading engine: {self.engine_name}")

        max_images = {
            "trellis": 4,
            "meshroom": 50,
            "hunyuan3d": 6,
            "triposg": 1,
            "sf3d": 1,
            "spar3d": 1,
            "instantmesh": 6,
        }.get(self.engine_name, 4)
        engine_config = EngineConfig(max_images=max_images)

        engine = load_engine(self.engine_name, engine_config)

        # Check prerequisites
        logger.info("Checking prerequisites...")
        engine.validate_prerequisites()
        logger.info(f"✓ Prerequisites validated for {self.engine_name}")

        return engine

    def _preprocess_images(self, image_paths: List[str]) -> List[str]:
        """
        Preprocess input images.

        Args:
            image_paths: List of image file paths

        Returns:
            List of preprocessed image paths

        Raises:
            RuntimeError: If preprocessing fails
        """
        logger.info(f"Preprocessing {len(image_paths)} image(s)...")

        preprocessor = ImagePreprocessor()
        preprocessed_paths = []

        for idx, image_path in enumerate(image_paths, 1):
            try:
                logger.info(
                    f"Processing image {idx}/{len(image_paths)}: {Path(image_path).name}"
                )

                image = preprocessor.load_image(image_path)
                logger.info(f"  ✓ Loaded: {image.size}")

                # Remove background
                try:
                    image = preprocessor.remove_background(image)
                    logger.info("  ✓ Background removed")
                except Exception as e:
                    logger.warning(f"  ⚠ Background removal failed: {e}")
                    logger.warning("  ➜ Continuing with original image")

                # Normalize
                image = preprocessor.normalize_image(image)
                logger.info("  ✓ Normalized to RGB")

                # Save preprocessed image
                output_path = self.session_dir / f"preprocessed_{idx:02d}.png"
                image.save(output_path)
                preprocessed_paths.append(str(output_path))
                logger.info(f"  ✓ Saved: {output_path.name}")

            except Exception as e:
                logger.error(f"Failed to preprocess image {idx}: {e}")
                raise RuntimeError(f"Image preprocessing failed: {e}")

        logger.info(f"✓ Preprocessed {len(preprocessed_paths)} images")
        return preprocessed_paths

    def _generate_views(self, image_paths: List[str]) -> List[str]:
        """Generate novel views using Zero123++ to augment the input image set."""
        from engines.multiview_generator import MultiViewGenerator

        target_count = 4 if self.engine_name == "trellis" else 50
        logger.info(
            f"Generating novel views (source: {len(image_paths)}, target: {target_count})..."
        )
        gen = MultiViewGenerator()
        augmented = gen.augment_image_paths(image_paths, target_count, self.session_dir)
        logger.info(f"✓ Multi-view generation complete: {len(augmented)} images total")
        return augmented

    def _run_inference(self, engine, image_paths: List[str]) -> str:
        """
        Run model inference.

        Args:
            engine: Initialized Engine instance
            image_paths: List of preprocessed image paths

        Returns:
            Path to raw mesh output

        Raises:
            RuntimeError: If inference fails
        """
        logger.info(f"Running {self.engine_name} inference...")

        try:
            start_time = time.time()

            # Preprocess (engine-specific)
            logger.info("Pre-processing for model...")
            preprocessed = engine.preprocess(image_paths)

            # Infer
            logger.info("Running inference...")
            output = engine.infer(preprocessed)

            # Post-process (engine-specific)
            logger.info("Post-processing output...")
            raw_mesh_path = engine.postprocess(output)

            elapsed = time.time() - start_time
            logger.info(f"✓ Inference complete ({elapsed:.1f}s)")
            logger.info(f"✓ Raw mesh saved to: {raw_mesh_path}")

            return raw_mesh_path

        except Exception as e:
            logger.error(f"Inference failed: {e}")
            raise RuntimeError(f"Model inference failed: {e}")

    def _post_process_mesh(self, raw_mesh_path: str) -> Dict[str, Any]:
        """
        Post-process mesh (repair, hollow, supports).

        Args:
            raw_mesh_path: Path to raw mesh from engine

        Returns:
            Dictionary with post-processing results

        Raises:
            RuntimeError: If post-processing fails
        """
        try:
            logger.info("Starting mesh post-processing...")

            pipeline = PostProcessingPipeline(self.post_processing_config)
            output_mesh_path = str(self.session_dir / "final_mesh.glb")

            results = pipeline.process_mesh(
                raw_mesh_path, output_mesh_path, engine_name=self.engine_name
            )

            logger.info("✓ Mesh post-processing complete")
            logger.info(f"  Final mesh: {results['mesh_path']}")
            logger.info(
                f"  Vertices: {results['vertices']:,} | Faces: {results['faces']:,}"
            )

            if results["has_supports"]:
                logger.info(f"  Support mesh: {results['support_path']}")
                logger.info(f"  Overhangs detected: {results['overhang_faces']}")

            return results

        except Exception as e:
            logger.error(f"Post-processing failed: {e}")
            raise RuntimeError(f"Mesh post-processing failed: {e}")

    def _save_metadata(self, results: Dict[str, Any], input_images: List[str]):
        """
        Save pipeline metadata and results.

        Args:
            results: Post-processing results
            input_images: Original input image paths
        """
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "engine": self.engine_name,
            "session_id": self.timestamp,
            "input_images": input_images,
            "mesh_stats": {
                "vertices": results.get("vertices", 0),
                "faces": results.get("faces", 0),
            },
            "post_processing": {
                "repair_enabled": self.post_processing_config.repair_non_manifold,
                "hollow_enabled": self.post_processing_config.hollow_enabled,
                "wall_thickness_mm": self.post_processing_config.wall_thickness,
                "supports_enabled": self.post_processing_config.generate_supports,
                "support_angle_threshold": self.post_processing_config.support_angle_threshold,
                "has_supports": results.get("has_supports", False),
                "overhang_faces": results.get("overhang_faces", 0),
            },
            "output_files": {
                "mesh": results["mesh_path"],
                "support_mesh": results.get("support_path", None),
            },
        }

        metadata_path = self.session_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"✓ Metadata saved: {metadata_path}")

        # Also print to console
        print("\n" + "=" * 60)
        print("PIPELINE RESULTS")
        print("=" * 60)
        print(f"Engine: {metadata['engine']}")
        print(f"Input Images: {len(metadata['input_images'])}")
        print(f"Output Mesh: {metadata['output_files']['mesh']}")
        print(
            f"Mesh Stats: {metadata['mesh_stats']['vertices']:,} vertices, "
            f"{metadata['mesh_stats']['faces']:,} faces"
        )
        if metadata["post_processing"]["has_supports"]:
            print(
                f"Supports: Yes ({metadata['post_processing']['overhang_faces']} faces)"
            )
        print(f"Session: {self.session_dir}")
        print("=" * 60 + "\n")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="3D Figurine Lab - 3D Model Generation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # TRELLIS.2 with single image (default post-processing)
  python main.py --engine trellis --images photo.jpg

  # TRELLIS.2 with multi-image and supports
  python main.py --engine trellis --images photo1.jpg photo2.jpg --supports

  # Meshroom SfM with 20 images and hollowing
  python main.py --engine meshroom --directory ./photos --hollow --wall-thickness 3.0

  # Custom post-processing settings
  python main.py --engine trellis --images photo.jpg \\
    --repair --hollow --wall-thickness 2.5 --supports --support-angle 50

  # Use custom config file
  python main.py --engine trellis --images photo.jpg --config ./custom_config.yaml
        """,
    )

    # Core arguments
    parser.add_argument(
        "--engine",
        choices=get_available_engines(),
        default="trellis",
        help="3D generation engine (default: trellis)",
    )

    # Input handling
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--images",
        nargs="+",
        help="Image file(s) to process",
    )
    input_group.add_argument(
        "--directory",
        type=str,
        help="Directory containing images (*.jpg, *.png, etc.)",
    )

    # Configuration
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Config file (default: config.yaml)",
    )

    # Output
    parser.add_argument(
        "--output",
        type=str,
        help="Output directory (overrides config)",
    )

    # Post-processing options
    pp_group = parser.add_argument_group("Post-Processing")
    pp_group.add_argument(
        "--repair",
        action="store_true",
        help="Enable mesh repair (fill holes, remove degenerates)",
    )
    pp_group.add_argument(
        "--hollow",
        action="store_true",
        help="Enable mesh hollowing",
    )
    pp_group.add_argument(
        "--wall-thickness",
        type=float,
        default=2.0,
        help="Hollow wall thickness in mm (default: 2.0)",
    )
    pp_group.add_argument(
        "--supports",
        action="store_true",
        help="Generate support structures",
    )
    pp_group.add_argument(
        "--support-angle",
        type=float,
        default=45,
        help="Overhang detection angle threshold (default: 45°)",
    )
    pp_group.add_argument(
        "--support-diameter",
        type=float,
        default=4.0,
        help="Support diameter in mm (default: 4.0)",
    )

    # Multi-view generation
    parser.add_argument(
        "--generate-views",
        action="store_true",
        help=(
            "Generate additional viewing angles using Zero123++ before 3D reconstruction. "
            "TRELLIS: augments to 4 views. Meshroom: augments to 50 views, enabling "
            "photogrammetry from as few as 1 source photo."
        ),
    )

    # Verbose
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    try:
        # Setup logging — write to output dir when set (Azure Files share, persists after container exit)
        if args.output:
            logs_dir = Path(args.output) / "logs"
        else:
            logs_dir = Path(args.config).parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        setup_logger(
            level="DEBUG" if args.verbose else "INFO",
            log_dir=str(logs_dir),
        )

        logger.info("Starting 3D Figurine Lab Pipeline")
        logger.info(f"Command: {' '.join(sys.argv)}")

        # Load configuration
        config = Config(args.config)
        logger.info(f"Configuration loaded from: {args.config}")

        # Resolve image paths
        image_paths = []
        if args.images:
            image_paths = args.images
        elif args.directory:
            input_dir = Path(args.directory)
            if not input_dir.exists():
                raise FileNotFoundError(f"Directory not found: {args.directory}")
            # Find all image files
            image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
            image_paths = [
                str(p)
                for p in input_dir.rglob("*")
                if p.suffix.lower() in image_extensions
            ]
            if not image_paths:
                raise ValueError(f"No images found in {args.directory}")
            logger.info(f"Found {len(image_paths)} images in {args.directory}")

        pp_config = PostProcessingConfig(
            repair_non_manifold=True,
            remove_degenerate_faces=True,
            remove_infinite_values=True,
            max_hole_size=30,
            enable_optimizer=True,
            hollow_enabled=args.hollow,
            wall_thickness=args.wall_thickness,
            generate_supports=args.supports,
            support_angle_threshold=args.support_angle,
            support_diameter=args.support_diameter,
        )

        # Resolve output directory
        output_dir = Path(args.output) if args.output else None

        # Run pipeline
        pipeline = Pipeline(
            args.engine,
            config,
            output_dir,
            pp_config,
            generate_views=args.generate_views,
        )
        pipeline.run(image_paths)

        logger.info("✓ Pipeline completed successfully")
        return 0

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return 1
    except ValueError as e:
        logger.error(f"Invalid input: {e}")
        return 1
    except RuntimeError as e:
        logger.error(f"Runtime error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
