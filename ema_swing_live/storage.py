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
        stored = _load_sqlite_document(path, default)
        if stored is not None:
            return stored
        return dict(default or {})
    with path.open(encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    _save_sqlite_document(path, data)
    return data


def save_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
    _save_sqlite_document(path, data)
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


def _load_sqlite_document(path: Path, default: dict[str, Any] | None) -> dict[str, Any] | None:
    if _sqlite_disabled(path):
        return None
    try:
        from ema_swing_live import database

        key = database.document_key_for_path(path)
        data = database.load_document(key, default)
        return data if data else None
    except Exception:
        return None


def _save_sqlite_document(path: Path, data: dict[str, Any]) -> None:
    if _sqlite_disabled(path):
        return
    try:
        from ema_swing_live import database

        database.save_document(database.document_key_for_path(path), data)
    except Exception:
        return


def _sqlite_disabled(path: Path) -> bool:
    if os.getenv("EMA_SWING_DISABLE_SQLITE", "").strip().lower() in {"1", "true", "yes"}:
        return True
    try:
        from ema_swing_live import database

        return database.is_secret_path(path)
    except Exception:
        return True
