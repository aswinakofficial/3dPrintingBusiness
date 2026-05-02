"""
Structured logging for 3D Figurine Lab pipeline.
Provides JSON-formatted logs with context, rotation, and GPU metrics.
"""

import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from loguru import logger as loguru_logger
from rich.console import Console

# Remove default handler
loguru_logger.remove()

# Rich console for colored output
console = Console()


class StructuredLogger:
    """
    Centralized logging with structured JSON output, file rotation, and GPU metrics.
    """

    def __init__(
        self,
        name: str = "3dfigurine",
        log_dir: str = "./logs",
        level: str = "INFO",
        file_rotation: str = "daily",
    ):
        """
        Initialize logger with file and console handlers.

        Args:
            name: Logger name
            log_dir: Directory for log files
            level: Logging level (DEBUG, INFO, WARNING, ERROR)
            file_rotation: Rotation frequency (daily, 100 MB, etc.)
        """
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Console handler (colored output)
        loguru_logger.add(
            self._log_console,
            level=level,
            format="{message}",
            colorize=True,
            backtrace=True,
        )

        # File handler (JSON lines format)
        log_file = self.log_dir / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        loguru_logger.add(
            str(log_file),
            level=level,
            format="{message}",
            rotation=file_rotation,
            retention="30 days",
            serialize=True,  # Output JSON
        )

        self.logger = loguru_logger

    def _log_console(self, message):
        """Format console output with styling."""
        record = message.record
        level = record["level"].name
        text = record["message"]
        timestamp = record["time"].strftime("%Y-%m-%d %H:%M:%S")

        # Color by level
        color_map = {
            "DEBUG": "dim",
            "INFO": "cyan",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red bold",
        }
        color = color_map.get(level, "white")

        console.print(f"[{color}]{timestamp}[/{color}] [{level:8}] {text}")

    def info(self, message: str, **context):
        """Log info with context."""
        self.logger.info(f"{message} | {json.dumps(context)}" if context else message)

    def debug(self, message: str, **context):
        """Log debug with context."""
        self.logger.debug(f"{message} | {json.dumps(context)}" if context else message)

    def warning(self, message: str, **context):
        """Log warning with context."""
        self.logger.warning(f"{message} | {json.dumps(context)}" if context else message)

    def error(self, message: str, **context):
        """Log error with context."""
        self.logger.error(f"{message} | {json.dumps(context)}" if context else message)

    def critical(self, message: str, **context):
        """Log critical error with context."""
        self.logger.critical(f"{message} | {json.dumps(context)}" if context else message)

    def log_step(
        self,
        step_name: str,
        duration_ms: int,
        gpu_memory_mb: Optional[float] = None,
        **extra_context,
    ):
        """
        Log pipeline step with timing and GPU metrics.

        Args:
            step_name: Name of pipeline step
            duration_ms: Execution time in milliseconds
            gpu_memory_mb: Peak GPU memory usage in MB
            **extra_context: Additional context (vertices, faces, file size, etc.)
        """
        context = {
            "step": step_name,
            "duration_ms": duration_ms,
            "duration_sec": f"{duration_ms / 1000:.2f}",
        }
        if gpu_memory_mb is not None:
            context["gpu_memory_mb"] = round(gpu_memory_mb, 2)
        context.update(extra_context)

        self.info(f"Step: {step_name}", **context)

    def log_engine_info(self, engine_name: str, config: Dict[str, Any]):
        """Log engine initialization info."""
        self.info(
            f"Engine initialized: {engine_name}",
            engine=engine_name,
            gpu_memory_available=config.get("gpu_memory_available"),
            cuda_device=config.get("cuda_device"),
        )

    def log_input_validation(self, num_images: int, image_paths: list):
        """Log input validation results."""
        self.info(
            f"Input validated: {num_images} image(s)",
            num_images=num_images,
            image_files=[Path(p).name for p in image_paths],
        )

    def log_inference_complete(
        self,
        engine_name: str,
        duration_ms: int,
        output_file: str,
        mesh_stats: Dict[str, Any],
    ):
        """Log inference completion with mesh statistics."""
        self.info(
            f"Inference complete: {engine_name}",
            engine=engine_name,
            duration_ms=duration_ms,
            output_file=Path(output_file).name,
            **mesh_stats,
        )

    def log_post_processing_complete(
        self,
        duration_ms: int,
        input_file: str,
        output_file: str,
        is_watertight: bool,
        volume_mm3: float,
    ):
        """Log post-processing completion."""
        self.info(
            f"Post-processing complete",
            duration_ms=duration_ms,
            input=Path(input_file).name,
            output=Path(output_file).name,
            is_watertight=is_watertight,
            volume_mm3=round(volume_mm3, 2),
        )


# Global logger instance
_logger_instance: Optional[StructuredLogger] = None


def setup_logger(
    log_dir: str = "./logs",
    level: str = "INFO",
    file_rotation: str = "daily",
) -> StructuredLogger:
    """
    Set up and return global logger instance.

    Args:
        log_dir: Directory for log files
        level: Logging level
        file_rotation: Log rotation frequency

    Returns:
        StructuredLogger instance
    """
    global _logger_instance
    _logger_instance = StructuredLogger(
        log_dir=log_dir,
        level=level,
        file_rotation=file_rotation,
    )
    return _logger_instance


def get_logger() -> StructuredLogger:
    """Get global logger instance (initialize if needed)."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = StructuredLogger()
    return _logger_instance
