"""Small JSON storage helpers for the live dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
INSTANCE_DIR = Path(os.getenv("EMA_SWING_LIVE_INSTANCE_DIR", PACKAGE_ROOT / "instance"))
SETTINGS_PATH = INSTANCE_DIR / "settings.json"


DEFAULT_SETTINGS: dict[str, Any] = {
    "data_provider": "auto",
    "default_quote_symbol": "NSE:GOLDBEES",
}


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    with path.open(encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def save_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
    return path


def load_settings() -> dict[str, Any]:
    settings = DEFAULT_SETTINGS | load_json(SETTINGS_PATH, {})
    provider = str(settings.get("data_provider", "auto")).strip().lower()
    if provider not in {"auto", "dhan", "dhanhq", "icici", "breeze", "icici_breeze", "yahoo"}:
        provider = "auto"
    settings["data_provider"] = "icici" if provider in {"breeze", "icici_breeze"} else provider
    return settings


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    settings.update(updates)
    return load_json(save_json(SETTINGS_PATH, settings), DEFAULT_SETTINGS)


def mask_value(value: str) -> str:
    value = str(value or "")
    if len(value) <= 6:
        return "***" if value else ""
    return f"{value[:3]}...{value[-3:]}"
