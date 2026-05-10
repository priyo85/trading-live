"""CSV data loader for ETF OHLCV data."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = ("date", "open", "high", "low", "close")


def load_ohlcv_csv(path: str | Path) -> list[dict[str, Any]]:
    """Load OHLCV rows from a CSV file.

    The loader accepts common column capitalization such as Date/Open/Close.
    It returns rows sorted by date.
    """

    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError("CSV file does not contain a header row")

        column_map = {name.lower().strip(): name for name in reader.fieldnames}
        missing = [column for column in REQUIRED_COLUMNS if column not in column_map]
        if missing:
            raise ValueError(f"CSV file is missing required columns: {', '.join(missing)}")

        rows = [_parse_row(row, column_map) for row in reader]

    return sorted(rows, key=lambda row: row["date"])


def _parse_row(row: dict[str, str], column_map: dict[str, str]) -> dict[str, Any]:
    return {
        "date": _parse_date(row[column_map["date"]]),
        "open": float(row[column_map["open"]]),
        "high": float(row[column_map["high"]]),
        "low": float(row[column_map["low"]]),
        "close": float(row[column_map["close"]]),
        "volume": float(row.get(column_map.get("volume", ""), 0) or 0),
    }


def _parse_date(value: str) -> date:
    cleaned = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return datetime.fromisoformat(cleaned).date()
