"""
Database access layer for Viva Part B.

Responsibilities (spec section 18):
- open SQLite connections
- enable foreign key enforcement
- provide a transaction context manager (commit/rollback)
- close connections cleanly

No adaptive/business logic lives here — see mastery.py and sessions.py.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Default DB location: viva-backend/viva.db (sibling of the app/ package).
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "viva.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Open a new SQLite connection with foreign keys enforced and
    row access by column name.

    Callers are responsible for closing the connection (use `transaction()`
    or a `with` block) — this module keeps no global/persistent cursor.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Create the database file and all tables/indexes if they don't exist."""
    schema_sql = SCHEMA_PATH.read_text()
    conn = get_connection(db_path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(db_path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """
    Context manager providing a connection with proper transaction handling.

    Commits on success, rolls back on any exception, and always closes
    the connection afterward.

    Usage:
        with transaction() as conn:
            conn.execute("INSERT INTO ...", (...))
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
