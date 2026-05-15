"""SQLite-backed market data cache."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from backtesting.etf_backtester.utils.paths import PACKAGE_ROOT


MARKET_DATA_CACHE_PATH = PACKAGE_ROOT / "data" / "cache" / "market_data.sqlite"


class CandleCache:
    """Persist provider candle rows and attempted fetch ranges."""

    def __init__(self, path: str | Path = MARKET_DATA_CACHE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def rows(self, provider: str, source_symbol: str, timeframe: str, start_date: date, end_date: date) -> list[dict]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT trade_date, trade_time, open, high, low, close, volume
                FROM candles
                WHERE provider = ?
                  AND source_symbol = ?
                  AND timeframe = ?
                  AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date, trade_time
                """,
                (provider, source_symbol, timeframe, start_date.isoformat(), end_date.isoformat()),
            )
            return [_row_from_record(record) for record in cursor.fetchall()]

    def save_rows(self, provider: str, source_symbol: str, timeframe: str, rows: list[dict]) -> None:
        if not rows:
            return

        records = []
        for row in rows:
            row_date = row.get("date")
            if not isinstance(row_date, date):
                continue
            row_time = str(row.get("time") or "")
            timestamp_key = f"{row_date.isoformat()}T{row_time or '00:00'}"
            records.append(
                (
                    provider,
                    source_symbol,
                    timeframe,
                    timestamp_key,
                    row_date.isoformat(),
                    row_time,
                    _float_or_zero(row.get("open")),
                    _float_or_zero(row.get("high")),
                    _float_or_zero(row.get("low")),
                    _float_or_zero(row.get("close")),
                    _float_or_zero(row.get("volume")),
                )
            )

        if not records:
            return

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO candles (
                    provider, source_symbol, timeframe, timestamp_key, trade_date, trade_time,
                    open, high, low, close, volume
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )

    def mark_attempted(self, provider: str, source_symbol: str, timeframe: str, start_date: date, end_date: date) -> None:
        if start_date > end_date:
            return

        ranges = self.attempted_ranges(provider, source_symbol, timeframe)
        ranges.append((start_date, end_date))
        merged = _merge_ranges(ranges)

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM attempted_ranges WHERE provider = ? AND source_symbol = ? AND timeframe = ?",
                (provider, source_symbol, timeframe),
            )
            connection.executemany(
                """
                INSERT INTO attempted_ranges (provider, source_symbol, timeframe, start_date, end_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (provider, source_symbol, timeframe, range_start.isoformat(), range_end.isoformat())
                    for range_start, range_end in merged
                ],
            )

    def attempted_ranges(self, provider: str, source_symbol: str, timeframe: str) -> list[tuple[date, date]]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT start_date, end_date
                FROM attempted_ranges
                WHERE provider = ? AND source_symbol = ? AND timeframe = ?
                ORDER BY start_date, end_date
                """,
                (provider, source_symbol, timeframe),
            )
            ranges = []
            for start_value, end_value in cursor.fetchall():
                try:
                    ranges.append((date.fromisoformat(start_value), date.fromisoformat(end_value)))
                except ValueError:
                    continue
            return _merge_ranges(ranges)

    def missing_ranges(self, provider: str, source_symbol: str, timeframe: str, start_date: date, end_date: date) -> list[tuple[date, date]]:
        return _missing_ranges(start_date, end_date, self.attempted_ranges(provider, source_symbol, timeframe))

    def get_metadata(self, key: str) -> str | None:
        with self._connect() as connection:
            cursor = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,))
            row = cursor.fetchone()
            return str(row[0]) if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS candles (
                    provider TEXT NOT NULL,
                    source_symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp_key TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    trade_time TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY (provider, source_symbol, timeframe, timestamp_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attempted_ranges (
                    provider TEXT NOT NULL,
                    source_symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    PRIMARY KEY (provider, source_symbol, timeframe, start_date, end_date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )


def _row_from_record(record: tuple) -> dict:
    trade_date, trade_time, open_price, high, low, close, volume = record
    row = {
        "date": date.fromisoformat(trade_date),
        "open": float(open_price),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
    }
    if trade_time:
        row["time"] = trade_time
    return row


def _float_or_zero(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _missing_ranges(start_date: date, end_date: date, attempted_ranges: list[tuple[date, date]]) -> list[tuple[date, date]]:
    if start_date > end_date:
        return []
    if not attempted_ranges:
        return [(start_date, end_date)]

    missing: list[tuple[date, date]] = []
    cursor = start_date
    for range_start, range_end in _merge_ranges(attempted_ranges):
        clipped_start = max(start_date, range_start)
        clipped_end = min(end_date, range_end)
        if clipped_start > end_date or clipped_end < start_date:
            continue
        if cursor < clipped_start:
            missing.append((cursor, clipped_start - timedelta(days=1)))
        cursor = max(cursor, _next_day(clipped_end))

    if cursor <= end_date:
        missing.append((cursor, end_date))
    return missing


def _merge_ranges(ranges: list[tuple[date, date]]) -> list[tuple[date, date]]:
    parsed = sorted((start, end) for start, end in ranges if start <= end)
    if not parsed:
        return []

    merged = [parsed[0]]
    for range_start, range_end in parsed[1:]:
        previous_start, previous_end = merged[-1]
        if range_start > _next_day(previous_end):
            merged.append((range_start, range_end))
        else:
            merged[-1] = (previous_start, max(previous_end, range_end))
    return merged


def _next_day(value: date) -> date:
    if value >= date.max:
        return date.max
    return value + timedelta(days=1)
