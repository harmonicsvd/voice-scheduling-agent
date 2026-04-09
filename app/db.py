import sqlite3
from app.config import settings


def get_db():
    conn = sqlite3.connect(settings.app_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                sub TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                default_city TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Europe/Berlin',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
