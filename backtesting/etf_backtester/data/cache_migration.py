"""Migration helpers for moving legacy JSON market data caches into SQLite."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from backtesting.etf_backtester.data.sqlite_cache import CandleCache
from backtesting.etf_backtester.data.yahoo_finance import (
    AVAILABILITY_CACHE_DIR,
    HISTORY_CACHE_DIR,
    MAX_CACHE_END,
    MAX_CACHE_START,
    YAHOO_PROVIDER_NAME,
)


@dataclass(frozen=True)
class MigrationResult:
    files_seen: int
    files_imported: int
    rows_imported: int
    files_failed: int


def migrate_legacy_json_caches(cache: CandleCache | None = None) -> MigrationResult:
    """Import legacy Yahoo JSON history and availability caches into SQLite."""

    store = cache or CandleCache()
    files_seen = 0
    files_imported = 0
    rows_imported = 0
    files_failed = 0

    for path in sorted(HISTORY_CACHE_DIR.glob("*.json")):
        files_seen += 1
        try:
            yahoo_symbol, timeframe = _parse_history_cache_name(path)
            imported = _import_cache_file(store, path, yahoo_symbol, timeframe)
        except Exception as exc:
            files_failed += 1
            print(f"[SQLite Migration] {path.name}: failed: {exc}")
            continue
        files_imported += 1
        rows_imported += imported

    for path in sorted(AVAILABILITY_CACHE_DIR.glob("*.json")):
        files_seen += 1
        try:
            yahoo_symbol = _parse_availability_cache_name(path)
            imported = _import_cache_file(store, path, yahoo_symbol, "max_daily", mark_full_range=True)
        except Exception as exc:
            files_failed += 1
            print(f"[SQLite Migration] {path.name}: failed: {exc}")
            continue
        files_imported += 1
        rows_imported += imported

    return MigrationResult(
        files_seen=files_seen,
        files_imported=files_imported,
        rows_imported=rows_imported,
        files_failed=files_failed,
    )


def _import_cache_file(
    cache: CandleCache,
    path: Path,
    yahoo_symbol: str,
    timeframe: str,
    mark_full_range: bool = False,
) -> int:
    data = _load_json(path)
    rows = [_deserialize_row(row) for row in data.get("rows", []) if isinstance(row, dict)]
    cache.save_rows(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, rows)

    row_dates = [row["date"] for row in rows if isinstance(row.get("date"), date)]
    if mark_full_range and row_dates:
        cache.mark_attempted(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, MAX_CACHE_START, MAX_CACHE_END)
    else:
        _mark_attempted_ranges(cache, yahoo_symbol, timeframe, data.get("attempted_ranges", []), row_dates)

    return len(row_dates)


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("cache file is not a JSON object")
    return data


def _deserialize_row(row: dict) -> dict:
    parsed = dict(row)
    row_date = parsed.get("date")
    if isinstance(row_date, str):
        parsed["date"] = datetime.strptime(row_date, "%Y-%m-%d").date()
    return parsed


def _mark_attempted_ranges(
    cache: CandleCache,
    yahoo_symbol: str,
    timeframe: str,
    attempted_ranges,
    row_dates: list[date],
) -> None:
    marked = False
    if isinstance(attempted_ranges, list):
        for attempted_range in attempted_ranges:
            if not isinstance(attempted_range, dict):
                continue
            try:
                start_date = datetime.strptime(attempted_range["start"], "%Y-%m-%d").date()
                end_date = datetime.strptime(attempted_range["end"], "%Y-%m-%d").date()
            except (KeyError, TypeError, ValueError):
                continue
            cache.mark_attempted(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, start_date, end_date)
            marked = True

    if not marked and row_dates:
        cache.mark_attempted(YAHOO_PROVIDER_NAME, yahoo_symbol, timeframe, min(row_dates), max(row_dates))


def _parse_history_cache_name(path: Path) -> tuple[str, str]:
    stem = path.stem
    if stem.endswith("_daily_close"):
        return stem[: -len("_daily_close")], "daily_close"

    for marker in ("_1m_", "_5m_", "_30m_"):
        if marker in stem:
            symbol, suffix = stem.split(marker, maxsplit=1)
            return symbol, f"{marker.strip('_')}_{suffix.replace('_', ':')}"

    raise ValueError(f"unrecognized history cache filename: {path.name}")


def _parse_availability_cache_name(path: Path) -> str:
    stem = path.stem
    if not stem.endswith("_max_daily"):
        raise ValueError(f"unrecognized availability cache filename: {path.name}")
    return stem[: -len("_max_daily")]


def main() -> None:
    result = migrate_legacy_json_caches()
    print(
        "[SQLite Migration] "
        f"files seen={result.files_seen}, imported={result.files_imported}, "
        f"rows={result.rows_imported}, failed={result.files_failed}"
    )


if __name__ == "__main__":
    main()
