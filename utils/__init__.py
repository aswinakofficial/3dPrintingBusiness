"""Utilities package for 3D Figurine Lab.

Intentionally empty -- importing this package must NOT transitively pull in
heavy ML/3D libraries (cv2, trimesh, etc.). Submodules are imported directly:

    from utils.logger import get_logger, setup_logger        # client-safe
    from utils.pre_processor import ImageValidator           # container only
    from utils.post_processor import PostProcessingPipeline  # container only

The trigger script (scripts/run_job.py) imports only utils.logger, which has
no heavy dependencies. main.py (which runs inside the container) imports the
heavier submodules where they're needed.
"""
