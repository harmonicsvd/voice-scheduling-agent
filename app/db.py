import os
import sqlite3
import logging
from contextlib import contextmanager
from app.config import settings

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USING_POSTGRES = bool(DATABASE_URL)
logger = logging.getLogger("uvicorn.error")


@contextmanager
def get_db():
    if DATABASE_URL:
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is set")
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(settings.app_db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db():
    db_target = "postgres" if USING_POSTGRES else settings.app_db_path
    logger.info("init_db starting | USING_POSTGRES=%s | target=%s", USING_POSTGRES, db_target)
    ddl = """
    CREATE TABLE IF NOT EXISTS user_profiles (
        sub TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        default_city TEXT NOT NULL,
        timezone TEXT NOT NULL DEFAULT 'Europe/Berlin',
        role TEXT,
        commute_mode TEXT,
        ppe_required BOOLEAN DEFAULT FALSE,
        risk_tolerance TEXT,
        updated_at TEXT NOT NULL
    )
    """
    with get_db() as conn:
        conn.execute(ddl)
    logger.info("init_db complete | USING_POSTGRES=%s", USING_POSTGRES)


def adapt_sql(query: str) -> str:
    """Convert Postgres-style placeholders to SQLite placeholders when needed."""
    if USING_POSTGRES:
        return query
    return query.replace("%s", "?")


def db_execute(conn, query: str, params=()):
    """Execute SQL with placeholder style adapted for active DB backend."""
    return conn.execute(adapt_sql(query), params)
