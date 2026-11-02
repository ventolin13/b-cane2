"""SQLite: история чата и выбранная модель."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def default_db_path() -> Path:
    return ROOT / "data" / "bot.sqlite"


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                model TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_chat
                ON messages (chat_id, id);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_model(self, chat_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT model FROM chat_settings WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        model = str(row[0]).strip()
        return model or None

    def set_model(self, chat_id: int, model: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO chat_settings (chat_id, model)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET model = excluded.model
                """,
                (chat_id, model),
            )
            self._conn.commit()

    def history(self, chat_id: int) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT role, content FROM messages
                WHERE chat_id = ?
                ORDER BY id
                """,
                (chat_id,),
            ).fetchall()
        return [{"role": role, "content": content} for role, content in rows]

    def history_length(self, chat_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def append_exchange(
        self, chat_id: int, user_text: str, assistant_text: str
    ) -> None:
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO messages (chat_id, role, content)
                VALUES (?, ?, ?)
                """,
                (
                    (chat_id, "user", user_text),
                    (chat_id, "assistant", assistant_text),
                ),
            )
            self._conn.commit()

    def clear_history(self, chat_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM messages WHERE chat_id = ?",
                (chat_id,),
            )
            self._conn.commit()
