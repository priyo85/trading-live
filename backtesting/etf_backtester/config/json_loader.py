"""JSON loading helpers for project configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_config(path: str | Path) -> dict[str, Any]:
    """Load a JSON configuration file."""

    config_path = Path(path)
    with config_path.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {config_path}")
    return data
