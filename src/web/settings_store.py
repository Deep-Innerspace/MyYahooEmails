"""Key-value access to the app_settings table."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return row["value"] if hasattr(row, "keys") else row[0]


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO app_settings(key, value, updated_at)
           VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP""",
        (key, value),
    )


def get_bool(conn: sqlite3.Connection, key: str, default: bool = False) -> bool:
    raw = get_setting(conn, key, "1" if default else "0")
    return raw == "1"


def set_bool(conn: sqlite3.Connection, key: str, value: bool) -> None:
    set_setting(conn, key, "1" if value else "0")


def get_timestamp(conn: sqlite3.Connection, key: str) -> Optional[str]:
    raw = get_setting(conn, key, "")
    return raw or None


def set_timestamp_now(conn: sqlite3.Connection, key: str) -> str:
    ts = datetime.now().isoformat()
    set_setting(conn, key, ts)
    return ts
