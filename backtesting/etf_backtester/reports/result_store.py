"""Persist backtest result reports."""

from __future__ import annotations

import json
from hashlib import sha1
from datetime import datetime
from pathlib import Path
from typing import Any

from backtesting.etf_backtester.utils.paths import PACKAGE_ROOT


RESULTS_DIR = PACKAGE_ROOT / "reports" / "results"


def save_backtest_report(report: dict[str, Any], condition_identifier: str) -> Path:
    """Save a backtest report JSON file and return its path."""

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{timestamp}_{_short_report_identifier(condition_identifier)}.json"
    path = RESULTS_DIR / file_name

    with path.open("w", encoding="utf-8") as file:
        json.dump(_serialize(report), file, indent=2)

    return path


def list_backtest_reports() -> list[dict[str, Any]]:
    """Return saved report metadata, newest first."""

    if not RESULTS_DIR.exists():
        return []

    reports: list[dict[str, Any]] = []
    for path in RESULTS_DIR.glob("*.json"):
        try:
            report = load_backtest_report(path.name)
        except (OSError, ValueError, json.JSONDecodeError):
            continue

        config = report.get("config", {})
        equity_curve = report.get("equity_curve", [])
        reports.append(
            {
                "id": path.name,
                "saved_at": report.get("saved_at", ""),
                "condition_identifier": report.get("condition_identifier", ""),
                "start_date": config.get("start_date", ""),
                "end_date": config.get("end_date", ""),
                "symbols_count": len(config.get("symbols", [])),
                "ending_equity": _ending_equity(equity_curve),
                "cagr": report.get("cagr", 0),
                "xirr": report.get("xirr"),
                "price_time": report.get("price_time", ""),
            }
        )

    return sorted(reports, key=lambda row: row["saved_at"], reverse=True)


def load_backtest_report(report_id: str) -> dict[str, Any]:
    """Load a saved report by file name."""

    path = _report_path(report_id)
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _report_path(report_id: str) -> Path:
    path = (RESULTS_DIR / report_id).resolve()
    results_root = RESULTS_DIR.resolve()
    if path.parent != results_root or path.suffix != ".json":
        raise ValueError("Invalid report id")
    return path


def _ending_equity(equity_curve: list[dict]) -> float:
    if not equity_curve:
        return 0.0
    return float(equity_curve[-1].get("equity", 0))


def _safe_identifier(value: str) -> str:
    return "".join(character if character.isalnum() or character in ("-", "_") else "_" for character in value)


def _short_report_identifier(value: str, max_prefix_length: int = 96) -> str:
    safe_value = _safe_identifier(value)
    digest = sha1(safe_value.encode("utf-8")).hexdigest()[:12]
    prefix = safe_value[:max_prefix_length].rstrip("_-")
    return f"{prefix}_{digest}" if prefix else digest


def _serialize(value):
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
