"""FastAPI dependency injection for the web dashboard."""
from typing import Generator
import sqlite3
from fastapi import Cookie, Request
from src.storage.database import get_db as _get_db


def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Yield a DB connection. Commits on success, rolls back on error."""
    with _get_db() as conn:
        yield conn


def get_perspective(perspective: str = Cookie(default="legal")) -> str:
    """Return the current perspective from cookie. Defaults to 'legal'."""
    return perspective if perspective in ("legal", "book") else "legal"
