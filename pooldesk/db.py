"""SQLite connection and helper utilities for PoolDesk."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd

import config


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with foreign keys enabled.

    Used as a context manager so connections are always closed and the
    transaction is committed on clean exit.
    """
    path = db_path or config.DB_PATH
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def run_script(sql: str, db_path: Path | None = None) -> None:
    """Execute a multi-statement SQL script (e.g. schema DDL)."""
    with get_connection(db_path) as conn:
        conn.executescript(sql)


def query(sql: str, params: tuple = (), db_path: Path | None = None) -> pd.DataFrame:
    """Run a SELECT statement and return the result as a DataFrame."""
    with get_connection(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def table_exists(name: str, db_path: Path | None = None) -> bool:
    """True if a table with the given name exists in the database."""
    rows = query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
        db_path,
    )
    return not rows.empty
