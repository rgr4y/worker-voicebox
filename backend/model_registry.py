"""
Single source of truth for all TTS model definitions.

Both backends (PyTorch, MLX) and the API layer import from here.
Adding a new model or changing a HuggingFace repo ID should only
require editing this file.
"""

from __future__ import annotations

from typing import Literal


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------

TTS_MODELS: dict[str, dict] = {
    "1.7B": {
        "model_name": "qwen-tts-1.7B",
        "display_name": "Qwen TTS 1.7B",
        "description": "Higher quality",
        "hf_repo": {
            "pytorch": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            "mlx": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit",
        },
    },
    "0.6B": {
        "model_name": "qwen-tts-0.6B",
        "display_name": "Qwen TTS 0.6B",
        "description": "Faster",
        "hf_repo": {
            "pytorch": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            "mlx": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit",
        },
    },
}

DEFAULT_MODEL_SIZE = "1.7B"

BackendType = Literal["pytorch", "mlx"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_tts_sizes() -> list[str]:
    """Return all valid TTS model size keys, e.g. ["1.7B", "0.6B"]."""
    return list(TTS_MODELS.keys())


def get_model_name(size: str) -> str:
    """Map a size key to the API model name, e.g. "1.7B" -> "qwen-tts-1.7B"."""
    return TTS_MODELS[size]["model_name"]


def get_display_name(size: str) -> str:
    """Map a size key to its human-readable label."""
    return TTS_MODELS[size]["display_name"]


def get_description(size: str) -> str:
    """Map a size key to its short description."""
    return TTS_MODELS[size]["description"]


def get_hf_repo(size: str, backend: BackendType) -> str:
    """Resolve the HuggingFace repo ID for a given size + backend."""
    return TTS_MODELS[size]["hf_repo"][backend]


def get_size_from_model_name(model_name: str) -> str | None:
    """Reverse-lookup: "qwen-tts-1.7B" -> "1.7B". Returns None if not found."""
    for size, info in TTS_MODELS.items():
        if info["model_name"] == model_name:
            return size
    return None


def is_valid_size(size: str) -> bool:
    return size in TTS_MODELS


def valid_sizes_pattern() -> str:
    """Return a regex pattern matching all valid sizes, e.g. "^(1\\.7B|0\\.6B)$"."""
    import re
    escaped = [re.escape(s) for s in TTS_MODELS]
    return f"^({'|'.join(escaped)})$"
