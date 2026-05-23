"""
Engine factory and loader for 3D Figurine Lab.
Provides dynamic engine selection and initialization.
"""

from typing import Type, Dict, List
from engines.base_engine import Engine, EngineConfig
from engines.trellis_v2 import TRELLIS2Engine
from engines.meshroom_sfm import MeshroomEngine
from engines.hunyuan3d import Hunyuan3DEngine
from engines.triposg import TripoSGEngine
from engines.sf3d import SF3DEngine
from engines.instantmesh import InstantMeshEngine
from utils.logger import get_logger

logger = get_logger()


# Registry of available engines
ENGINE_REGISTRY: Dict[str, Type[Engine]] = {
    "trellis": TRELLIS2Engine,
    "meshroom": MeshroomEngine,
    "hunyuan3d": Hunyuan3DEngine,
    "triposg": TripoSGEngine,
    "sf3d": SF3DEngine,
    "instantmesh": InstantMeshEngine,
}


def get_available_engines() -> List[str]:
    """
    Get list of available engines.

    Returns:
        List of engine names
    """
    return list(ENGINE_REGISTRY.keys())


def load_engine(
    engine_name: str,
    config: EngineConfig,
) -> Engine:
    """
    Load and initialize an engine.

    Args:
        engine_name: Engine name (e.g., 'trellis', 'meshroom')
        config: EngineConfig instance

    Returns:
        Initialized Engine instance

    Raises:
        ValueError: If engine not found
        RuntimeError: If engine initialization fails
    """
    engine_name = engine_name.lower().strip()

    if engine_name not in ENGINE_REGISTRY:
        available = ", ".join(get_available_engines())
        raise ValueError(
            f"Engine '{engine_name}' not found. Available engines: {available}"
        )

    engine_class = ENGINE_REGISTRY[engine_name]

    try:
        logger.info(f"Initializing engine: {engine_name}")
        engine = engine_class(config)
        logger.info(f"Engine initialized successfully: {engine_name}")
        return engine
    except Exception as e:
        logger.error(f"Failed to initialize engine {engine_name}: {e}")
        raise RuntimeError(f"Engine initialization failed: {e}")


__all__ = [
    "Engine",
    "EngineConfig",
    "load_engine",
    "get_available_engines",
    "ENGINE_REGISTRY",
]
