import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from ema_swing_live import database


class DatabaseTests(unittest.TestCase):
    def test_sqlite_document_roundtrip(self):
        tmp_path = Path.cwd() / ".tmp" / f"ema_swing_db_{uuid4().hex}"
        tmp_path.mkdir(parents=True, exist_ok=True)
        db_path = tmp_path / "ema_swing_live.sqlite"
        key = "example/state.json"

        with database.connect(db_path):
            pass

        original_path = database.DB_PATH
        try:
            database.DB_PATH = db_path
            database.save_document(key, {"cash": 123, "holdings": {"NSE:ABC": {"shares": 1}}})

            loaded = database.load_document(key)
        finally:
            database.DB_PATH = original_path
            shutil.rmtree(tmp_path, ignore_errors=True)

        self.assertEqual(loaded["cash"], 123)
        self.assertEqual(loaded["holdings"]["NSE:ABC"]["shares"], 1)

    def test_secret_paths_are_not_database_documents(self):
        self.assertTrue(database.is_secret_path(Path("ema_swing_live/instance/icici_breeze_credentials.json")))
        self.assertTrue(database.is_secret_path(Path(".env")))
        self.assertFalse(database.is_secret_path(Path("ema_swing_live/instance/settings.json")))
