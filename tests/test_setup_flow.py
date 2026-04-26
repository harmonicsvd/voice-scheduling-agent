"""Tests for onboarding/setup routing behavior."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module


def _init_db(db_path: Path) -> None:
    """Create test DB schema matching the app profile table."""
    with sqlite3.connect(db_path) as conn:
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


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Provide test client with isolated DB and fake authenticated user."""
    db_path = tmp_path / "setup_flow.db"
    _init_db(db_path)

    def _get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(main_module, "get_db", _get_db)
    monkeypatch.setattr(
        main_module,
        "get_current_user_or_401",
        lambda request: (
            {"sub": "user-1", "email": "user@example.com"},
            None,
        ),
    )

    with TestClient(main_module.app) as test_client:
        yield test_client, db_path


def test_assistant_redirects_to_setup_when_profile_incomplete(client) -> None:
    """Users without completed setup should be redirected from /assistant to /setup."""
    test_client, _db_path = client

    response = test_client.get("/assistant", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/setup"


def test_setup_redirects_to_assistant_when_profile_complete(client) -> None:
    """Users with completed setup should not stay on /setup."""
    test_client, db_path = client

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_profiles (
                sub, email, default_city, timezone, role,
                commute_mode, ppe_required, risk_tolerance, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "user-1",
                "user@example.com",
                "Berlin",
                "Europe/Berlin",
                "Architect",
                "Car",
                False,
                "Medium",
                "2026-04-26T10:00:00+00:00",
            ),
        )
        conn.commit()

    response = test_client.get("/setup", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/assistant"
    
def test_profile_reports_incomplete_setup_when_profile_missing(client) -> None:
    """Profile endpoint should mark setup incomplete when no profile exists yet."""
    test_client, _db_path = client

    response = test_client.get("/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["has_profile"] is False
    assert body["is_setup_complete"] is False
    assert body["profile"] is None


def test_profile_reports_complete_setup_when_required_fields_exist(client) -> None:
    """Profile endpoint should mark setup complete when onboarding fields are filled."""
    test_client, db_path = client

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_profiles (
                sub, email, default_city, timezone, role,
                commute_mode, ppe_required, risk_tolerance, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "user-1",
                "user@example.com",
                "Berlin",
                "Europe/Berlin",
                "Architect",
                "Car",
                True,
                "Medium",
                "2026-04-26T10:00:00+00:00",
            ),
        )
        conn.commit()

    response = test_client.get("/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["has_profile"] is True
    assert body["is_setup_complete"] is True
    assert body["profile"]["role"] == "Architect"
    assert body["profile"]["commute_mode"] == "Car"
    assert body["profile"]["risk_tolerance"] == "Medium"


def test_put_profile_saves_onboarding_fields(client) -> None:
    """Profile update should persist all setup fields used by onboarding."""
    test_client, db_path = client

    response = test_client.put(
        "/profile",
        json={
            "role": "Project Manager",
            "default_city": "Munich",
            "timezone": "Europe/Berlin",
            "commute_mode": "Public transport",
            "risk_tolerance": "Low",
            "ppe_required": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT role, default_city, timezone, commute_mode, risk_tolerance, ppe_required
            FROM user_profiles
            WHERE sub = ?
            """,
            ("user-1",),
        ).fetchone()

    assert row is not None
    assert row["role"] == "Project Manager"
    assert row["default_city"] == "Munich"
    assert row["timezone"] == "Europe/Berlin"
    assert row["commute_mode"] == "Public transport"
    assert row["risk_tolerance"] == "Low"
    assert row["ppe_required"] == 1


def test_assistant_is_accessible_when_profile_complete(client) -> None:
    """Users with completed setup should be allowed into /assistant."""
    test_client, db_path = client

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_profiles (
                sub, email, default_city, timezone, role,
                commute_mode, ppe_required, risk_tolerance, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "user-1",
                "user@example.com",
                "Berlin",
                "Europe/Berlin",
                "Architect",
                "Car",
                False,
                "Medium",
                "2026-04-26T10:00:00+00:00",
            ),
        )
        conn.commit()

    response = test_client.get("/assistant", follow_redirects=False)

    assert response.status_code == 200
