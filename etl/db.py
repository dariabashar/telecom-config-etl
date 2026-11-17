from __future__ import annotations

import os
from pathlib import Path

import psycopg

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
DEFAULT_URL = "postgresql://etl:etl@localhost:5432/etl"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def connect(url: str | None = None) -> psycopg.Connection:
    """Autocommit connection; transactions are opened explicitly with `with conn.transaction()`."""
    return psycopg.connect(url or database_url(), autocommit=True)


def init_db(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
