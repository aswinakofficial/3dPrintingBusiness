"""
Image preprocessing and multi-image input handling.
Supports flexible input for both TRELLIS.2 (1-4 images) and Meshroom (10-50+ images).
"""

from pathlib import Path
from typing import Union, List, Optional

import numpy as np
from PIL import Image

from utils.logger import get_logger

logger = get_logger()


class ImageValidator:
    """Validate images before pipeline processing."""

    SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}
    MIN_RESOLUTION = 256
    MAX_RESOLUTION = 16384

    @classmethod
    def validate_single_image(cls, image_path: Union[str, Path]) -> bool:
        """
        Validate single image file.

        Args:
            image_path: Path to image file

        Returns:
            True if valid, False otherwise
        """
        image_path = Path(image_path)

        # Check file exists
        if not image_path.exists():
            logger.error("Image file not found", file=str(image_path))
            return False

        # Check format
        if image_path.suffix.lower() not in cls.SUPPORTED_FORMATS:
            logger.error(
                "Unsupported image format",
                file=image_path.name,
                format=image_path.suffix,
                supported=list(cls.SUPPORTED_FORMATS),
            )
            return False

        # Check readable and get dimensions
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                if width < cls.MIN_RESOLUTION or height < cls.MIN_RESOLUTION:
                    logger.error(
                        "Image too small",
                        file=image_path.name,
                        resolution=f"{width}x{height}",
                        minimum=cls.MIN_RESOLUTION,
                    )
                    return False
                if width > cls.MAX_RESOLUTION or height > cls.MAX_RESOLUTION:
                    logger.error(
                        "Image too large",
                        file=image_path.name,
                        resolution=f"{width}x{height}",
                        maximum=cls.MAX_RESOLUTION,
                    )
                    return False
        except Exception as e:
            logger.error("Failed to read image", file=image_path.name, error=str(e))
            return False

        return True

    @classmethod
    def validate_input_images(
        cls,
        image_paths: Union[str, List[str]],
        allow_directory: bool = False,
    ) -> List[Path]:
        """
        Validate one or more image paths (single file, list, or directory).

        Args:
            image_paths: Single path string, list of paths, or directory path
            allow_directory: If True, allow directory input (returns all images in dir)

        Returns:
            List of validated image paths

        Raises:
            ValueError: If no valid images found or input format invalid
        """
        validated = []

        # Handle single string input
        if isinstance(image_paths, str):
            image_path = Path(image_paths)

            # Directory input
            if image_path.is_dir():
                if not allow_directory:
                    raise ValueError(
                        "Directory input not allowed for this engine. "
                        "Provide individual image files or use Meshroom engine."
                    )
                # Find all images in directory
                for ext in cls.SUPPORTED_FORMATS:
                    validated.extend(sorted(image_path.glob(f"*{ext}")))
                    validated.extend(sorted(image_path.glob(f"*{ext.upper()}")))

            # Single file input
            elif image_path.is_file():
                if cls.validate_single_image(image_path):
                    validated.append(image_path)

            else:
                raise ValueError(f"Path not found: {image_path}")

        # Handle list of paths
        elif isinstance(image_paths, list):
            for path in image_paths:
                path = Path(path)
                if path.is_dir() and allow_directory:
                    # Add all images from directory
                    for ext in cls.SUPPORTED_FORMATS:
                        validated.extend(sorted(path.glob(f"*{ext}")))
                        validated.extend(sorted(path.glob(f"*{ext.upper()}")))
                elif path.is_file() and cls.validate_single_image(path):
                    validated.append(path)

        else:
            raise ValueError(f"Invalid input type: {type(image_paths)}")

        if not validated:
            raise ValueError("No valid images found in input")

        # Remove duplicates while preserving order
        seen = set()
        unique_validated = []
        for path in validated:
            path_str = str(path.resolve())
            if path_str not in seen:
                seen.add(path_str)
                unique_validated.append(path)

        logger.log_input_validation(
            len(unique_validated), [str(p) for p in unique_validated]
        )
        return unique_validated


class ImagePreprocessor:
    """Preprocess images for model input."""

    @staticmethod
    def load_image(image_path: Union[str, Path]) -> Image.Image:
        """
        Load image as PIL Image.

        Args:
            image_path: Path to image

        Returns:
            PIL Image object
        """
        image_path = Path(image_path)
        try:
            img = Image.open(image_path).convert("RGB")
            logger.debug(
                "Loaded image",
                file=image_path.name,
                size=f"{img.width}x{img.height}",
            )
            return img
        except Exception as e:
            raise RuntimeError(f"Failed to load image {image_path}: {e}")

    # Short-edge threshold below which Real-ESRGAN upscaling is applied
    _UPSCALE_THRESHOLD_PX = 512

    @staticmethod
    def maybe_upscale(image: Image.Image) -> Image.Image:
        """Upscale small images 4× with Real-ESRGAN before inference.

        Skipped silently when the short edge already meets the threshold or when
        realesrgan / basicsr are not installed in the container.
        """
        short = min(image.size)
        if short >= ImagePreprocessor._UPSCALE_THRESHOLD_PX:
            return image

        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer

            # Weights are at a well-known path in containers that ship them
            # (Hunyuan3D has them at /opt/hunyuan3d-space/hy3dpaint/ckpt/);
            # for other containers they are downloaded to HF_HOME cache.
            _WEIGHT_CANDIDATES = [
                "/opt/hunyuan3d-space/hy3dpaint/ckpt/RealESRGAN_x4plus.pth",
                Path.home() / ".cache/realesrgan/RealESRGAN_x4plus.pth",
            ]
            weights_path = next(
                (str(p) for p in _WEIGHT_CANDIDATES if Path(p).exists()), None
            )
            if weights_path is None:
                # Download on first use — cached by realesrgan into HF_HOME
                weights_path = "RealESRGAN_x4plus"

            model = RRDBNet(
                num_in_ch=3,
                num_out_ch=3,
                num_feat=64,
                num_block=23,
                num_grow_ch=32,
                scale=4,
            )
            upsampler = RealESRGANer(
                scale=4,
                model_path=weights_path,
                model=model,
                tile=0,
                tile_pad=10,
                pre_pad=0,
                half=True,
            )
            rgb = np.array(image.convert("RGB"))
            out_rgb, _ = upsampler.enhance(rgb, outscale=4)
            result = Image.fromarray(out_rgb)
            logger.info(f"Real-ESRGAN upscale: {image.size} → {result.size}")
            return result
        except ImportError:
            logger.debug("realesrgan not installed, skipping upscale")
            return image
        except Exception as exc:
            logger.warning(f"Real-ESRGAN upscale failed ({exc}), using original")
            return image

    @staticmethod
    def remove_background(image: Image.Image, model_name: str = "u2net") -> Image.Image:
        """
        Remove background from image using rembg.

        Args:
            image: PIL Image
            model_name: rembg model name (u2net, u2netp, etc.)

        Returns:
            PIL Image with transparent background
        """
        try:
            import rembg

            session = rembg.new_session(model_name)
            result = rembg.remove(image, session=session)
            # rembg.remove() returns PIL Image when given PIL Image input
            if isinstance(result, Image.Image):
                return result
            return Image.fromarray(result, "RGBA")
        except ImportError:
            logger.warning("rembg not installed, skipping background removal")
            return image
        except Exception as e:
            logger.warning(
                f"Background removal failed: {e}, continuing without removal"
            )
            return image

    @staticmethod
    def normalize_image(
        image: Image.Image,
        target_size: int = 512,
        remove_bg: bool = True,
    ) -> Image.Image:
        """
        Normalize image: optionally remove background, resize to target.

        Args:
            image: PIL Image
            target_size: Target dimension (square)
            remove_bg: Whether to remove background

        Returns:
            Normalized PIL Image
        """
        # Remove background if requested
        if remove_bg:
            image = ImagePreprocessor.remove_background(image)

        # Resize to target (maintain aspect ratio with padding)
        image.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)

        # Create canvas and paste image centered
        canvas = Image.new("RGB", (target_size, target_size), color=(255, 255, 255))
        offset = ((target_size - image.width) // 2, (target_size - image.height) // 2)
        canvas.paste(image, offset, image if image.mode == "RGBA" else None)

        logger.debug(f"Normalized image to {target_size}x{target_size}")
        return canvas

    @staticmethod
    def extract_exif_focal_length(image_path: Union[str, Path]) -> Optional[float]:
        """
        Extract focal length from image EXIF (useful for Meshroom calibration).

        Args:
            image_path: Path to image

        Returns:
            Focal length in pixels, or None if not found
        """
        try:
            image = Image.open(image_path)
            exif = image.getexif()

            if exif:
                # EXIF tag 37386 is FocalLength
                focal_length_tuple = exif.get(37386)
                if focal_length_tuple:
                    return float(focal_length_tuple[0]) / float(focal_length_tuple[1])
        except Exception as e:
            logger.debug(f"Failed to extract EXIF: {e}")

        return None

    @staticmethod
    def get_images_metadata(image_paths: List[Path]) -> dict:
        """
        Get metadata summary for list of images.

        Args:
            image_paths: List of image paths

        Returns:
            Dictionary with metadata
        """
        metadata = {
            "count": len(image_paths),
            "files": [p.name for p in image_paths],
            "sizes": [],
            "focal_lengths": [],
        }

        for path in image_paths:
            try:
                img = Image.open(path)
                metadata["sizes"].append(f"{img.width}x{img.height}")
                focal = ImagePreprocessor.extract_exif_focal_length(path)
                if focal:
                    metadata["focal_lengths"].append(round(focal, 2))
            except Exception as e:
                logger.debug(f"Failed to get metadata for {path.name}: {e}")

        return metadata


__all__ = ["ImageValidator", "ImagePreprocessor"]
