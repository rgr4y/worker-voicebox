"""
Configuration module for voicebox backend.

Handles data directory configuration for production bundling.
"""

import logging
from pathlib import Path

from .constants import (
    CACHE_SUBDIR,
    DATABASE_FILENAME,
    DATA_DIR,
    GENERATIONS_SUBDIR,
    MODELS_SUBDIR,
    PROFILES_SUBDIR,
)

logger = logging.getLogger(__name__)

# Default data directory
_data_dir = Path(DATA_DIR)

def set_data_dir(path: str | Path):
    """
    Set the data directory path.

    Args:
        path: Path to the data directory
    """
    global _data_dir
    _data_dir = Path(path)
    _data_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Data directory set to: {_data_dir.absolute()}")

def get_data_dir() -> Path:
    """
    Get the data directory path.

    Returns:
        Path to the data directory
    """
    return _data_dir

def get_db_path() -> Path:
    """Get database file path."""
    return _data_dir / DATABASE_FILENAME

def get_profiles_dir() -> Path:
    """Get profiles directory path."""
    path = _data_dir / PROFILES_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_generations_dir() -> Path:
    """Get generations directory path."""
    path = _data_dir / GENERATIONS_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_cache_dir() -> Path:
    """Get cache directory path."""
    path = _data_dir / CACHE_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_models_dir() -> Path:
    """Get models directory path."""
    path = _data_dir / MODELS_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path
