"""Device profile loader.

Profiles are JSON files that map semantic names to MIoT siid/piid/aiid values
for specific device models. The loader finds profiles by model string.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROFILES_DIR = Path(__file__).parent


def load_profile(model: str) -> dict[str, Any]:
    """Load a device profile by model string.

    Tries exact match first (e.g. "xiaomi.vacuum.d102gl.json"),
    then tries prefix matches (e.g. "xiaomi.vacuum.json").

    Args:
        model: Device model string from the MIoT API.

    Returns:
        Profile dict.

    Raises:
        FileNotFoundError: If no matching profile exists.
    """
    # Exact match
    path = _PROFILES_DIR / f"{model}.json"
    if path.exists():
        return json.loads(path.read_text())

    # Prefix match (e.g. "xiaomi.vacuum" matches any xiaomi vacuum)
    parts = model.split(".")
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        path = _PROFILES_DIR / f"{prefix}.json"
        if path.exists():
            logger.info("No exact profile for %s, using %s", model, prefix)
            return json.loads(path.read_text())

    raise FileNotFoundError(
        f"No device profile found for model '{model}'. "
        f"Create one at {_PROFILES_DIR / (model + '.json')}"
    )


def list_profiles() -> list[str]:
    """List all available profile model names."""
    return [p.stem for p in _PROFILES_DIR.glob("*.json")]
