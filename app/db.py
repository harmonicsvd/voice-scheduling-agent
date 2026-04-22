"""SQLite helpers for user profile persistence."""

import sqlite3
from app.config import settings


def get_db():
    """Return SQLite connection configured for row-by-name access."""
    # sqlite Row factory enables dict-like column access (row["default_city"]).
    conn = sqlite3.connect(settings.app_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create required tables if they do not exist."""
    # Startup schema creation for local/dev deployment.
    with get_db() as conn:
        conn.execute(
            """
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
        )
        conn.commit()
