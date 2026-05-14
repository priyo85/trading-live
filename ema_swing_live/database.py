"""SQLite persistence for EMA Swing Live local/EC2 instances."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent
INSTANCE_DIR = Path(os.getenv("EMA_SWING_LIVE_INSTANCE_DIR", PACKAGE_ROOT / "instance"))
DB_PATH = Path(os.getenv("EMA_SWING_LIVE_DB_PATH", INSTANCE_DIR / "ema_swing_live.sqlite"))


SCHEMA_VERSION = 1


def connect(path: Path | None = None) -> sqlite3.Connection:
    database_path = path or DB_PATH
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    init_db(connection)
    return connection


def init_db(connection: sqlite3.Connection | None = None) -> None:
    own_connection = connection is None
    db = connection or sqlite3.connect(DB_PATH)
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS broker_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker TEXT NOT NULL,
                snapshot_type TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_broker_snapshots_lookup
                ON broker_snapshots (broker, snapshot_type, created_at);

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        db.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        db.commit()
    finally:
        if own_connection:
            db.close()


def load_document(key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT data FROM documents WHERE key = ?", (key,)).fetchone()
    if row is None:
        return dict(default or {})
    data = json.loads(row["data"])
    if not isinstance(data, dict):
        raise ValueError(f"Expected SQLite document object for {key}")
    return data


def save_document(key: str, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as db:
        db.execute(
            """
            INSERT INTO documents (key, data, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
            """,
            (key, payload, now),
        )
        db.commit()


def save_broker_snapshot(broker: str, snapshot_type: str, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    with connect() as db:
        db.execute(
            """
            INSERT INTO broker_snapshots (broker, snapshot_type, data, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (broker, snapshot_type, payload, datetime.now().isoformat(timespec="seconds")),
        )
        db.commit()


def latest_broker_snapshot(broker: str, snapshot_type: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT data FROM broker_snapshots
            WHERE broker = ? AND snapshot_type = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (broker, snapshot_type),
        ).fetchone()
    if row is None:
        return None
    data = json.loads(row["data"])
    return data if isinstance(data, dict) else {"value": data}


def append_audit(event_type: str, entity_type: str, entity_id: str | None, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    with connect() as db:
        db.execute(
            """
            INSERT INTO audit_log (event_type, entity_type, entity_id, data, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, entity_type, entity_id, payload, datetime.now().isoformat(timespec="seconds")),
        )
        db.commit()


def document_key_for_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PACKAGE_ROOT.parent)).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


def is_secret_path(path: Path) -> bool:
    text = str(path).lower()
    return "credential" in text or text.endswith(".env") or "/.env" in text or "\\.env" in text
