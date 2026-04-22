"""Endpoint tests for `/create-event` tool webhook behavior."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app import main as main_module


def _init_db(db_path: Path) -> None:
    """Create minimal test DB schema used by create-event endpoint tests."""
    with sqlite3.connect(db_path) as conn:
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


def _payload(
    *,
    meeting_mode: str = "in_person",
    city: str | None = None,
    location: str | None = None,
) -> dict:
    """Build VAPI-style tool-call payload with optional city/location fields."""
    arguments = {
        "name": "Varad",
        "date": "2026-04-08",
        "time": "16:00",
        "title": "Client Visit",
        "duration": "30 min",
        "meeting_mode": meeting_mode,
    }
    if city is not None:
        arguments["city"] = city
    if location is not None:
        arguments["location"] = location

    return {
        "message": {
            "toolCalls": [
                {
                    "id": "tc-1",
                    "function": {
                        "arguments": arguments,
                    },
                }
            ]
        }
    }


@pytest.fixture
def test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Shared fixture: isolated DB + mocked auth + mocked Google Calendar insert."""
    db_path = tmp_path / "test_app.db"
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
            {"sub": "104659023322141767006", "email": "varadwork56@gmail.com"},
            None,
        ),
    )

    created_payloads: list[dict] = []

    class _FakeInsertCall:
        def __init__(self, payload: dict):
            self._payload = payload

        def execute(self):
            created_payloads.append(self._payload)
            return {"htmlLink": "https://example.com/event"}

    class _FakeEventsAPI:
        def insert(self, calendarId: str, body: dict):
            return _FakeInsertCall({"calendarId": calendarId, "body": body})

    class _FakeCalendarService:
        def events(self):
            return _FakeEventsAPI()

    monkeypatch.setattr(main_module, "get_calendar_service", lambda: _FakeCalendarService())

    with TestClient(main_module.app) as client:
        yield client, db_path, created_payloads


def test_create_event_uses_provided_city(test_context) -> None:
    """When city is provided, metadata should mark `city_source:provided`."""
    client, _db_path, created_payloads = test_context

    response = client.post(
        "/create-event",
        json=_payload(meeting_mode="in_person", city="Berlin", location="Berlin Office"),
    )

    assert response.status_code == 200
    assert len(created_payloads) == 1

    event_body = created_payloads[0]["body"]
    description = event_body["description"]
    assert "weather_city:Berlin" in description
    assert "city_source:provided" in description
    assert event_body["location"] == "Berlin Office"


def test_create_event_falls_back_to_profile_default_city(test_context) -> None:
    """Missing city should fall back to user profile default city when available."""
    client, db_path, created_payloads = test_context

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_profiles (sub, email, default_city, timezone, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "104659023322141767006",
                "varadwork56@gmail.com",
                "Frankfurt",
                "Europe/Berlin",
                "2026-04-08T10:00:00+00:00",
            ),
        )
        conn.commit()

    response = client.post("/create-event", json=_payload(meeting_mode="in_person"))

    assert response.status_code == 200
    assert len(created_payloads) == 1

    event_body = created_payloads[0]["body"]
    description = event_body["description"]
    assert "weather_city:Frankfurt" in description
    assert "city_source:profile_default" in description
    assert "location" not in event_body


def test_create_event_uses_profile_city_even_when_location_present(test_context) -> None:
    """Free-form location should not override profile city when explicit city missing."""
    client, db_path, created_payloads = test_context

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_profiles (sub, email, default_city, timezone, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "104659023322141767006",
                "varadwork56@gmail.com",
                "Frankfurt",
                "Europe/Berlin",
                "2026-04-08T10:00:00+00:00",
            ),
        )
        conn.commit()

    response = client.post(
        "/create-event",
        json=_payload(meeting_mode="in_person", location="Berlin Office"),
    )

    assert response.status_code == 200
    assert len(created_payloads) == 1

    event_body = created_payloads[0]["body"]
    description = event_body["description"]
    assert "weather_city:Frankfurt" in description
    assert "city_source:profile_default" in description
    assert event_body["location"] == "Berlin Office"
    assert "weather_city:Berlin" not in description


def test_create_event_returns_400_when_city_and_profile_missing(test_context) -> None:
    """In-person create-event must fail when neither explicit nor profile city exists."""
    client, _db_path, _created_payloads = test_context

    response = client.post("/create-event", json=_payload(meeting_mode="in_person"))

    assert response.status_code == 400
    assert (
        response.json()["error"]
        == "city is required for in-person meetings (or set default city in profile)"
    )


def test_create_event_requires_user_sub_for_server_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Server-to-server calls must provide user_sub when session auth is absent."""
    db_path = tmp_path / "test_app.db"
    _init_db(db_path)

    def _get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(main_module, "get_db", _get_db)
    monkeypatch.setattr(
        main_module,
        "get_current_user_or_401",
        lambda request: (None, None),
    )
    monkeypatch.setattr(main_module, "require_internal_api_key", lambda _key: None)

    class _FakeInsertCall:
        def execute(self):
            return {"htmlLink": "https://example.com/event"}

    class _FakeEventsAPI:
        def insert(self, calendarId: str, body: dict):
            return _FakeInsertCall()

    class _FakeCalendarService:
        def events(self):
            return _FakeEventsAPI()

    monkeypatch.setattr(main_module, "get_calendar_service", lambda: _FakeCalendarService())

    payload = _payload(meeting_mode="online")
    # Simulate VAPI missing user_sub in server-to-server call.
    payload["message"]["toolCalls"][0]["function"]["arguments"].pop("user_sub", None)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/create-event",
            json=payload,
        )

    assert response.status_code == 400
    assert response.json()["error"] == "user_sub is required for server-to-server calls"


def test_create_event_extracts_user_sub_from_assistant_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Extractor should resolve user_sub from assistantOverrides when arg is absent."""
    db_path = tmp_path / "test_app.db"
    _init_db(db_path)

    def _get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(main_module, "get_db", _get_db)
    monkeypatch.setattr(
        main_module,
        "get_current_user_or_401",
        lambda request: (None, None),
    )
    monkeypatch.setattr(main_module, "require_internal_api_key", lambda _key: None)

    created_payloads: list[dict] = []

    class _FakeInsertCall:
        def __init__(self, payload: dict):
            self._payload = payload

        def execute(self):
            created_payloads.append(self._payload)
            return {"htmlLink": "https://example.com/event"}

    class _FakeEventsAPI:
        def insert(self, calendarId: str, body: dict):
            return _FakeInsertCall({"calendarId": calendarId, "body": body})

    class _FakeCalendarService:
        def events(self):
            return _FakeEventsAPI()

    monkeypatch.setattr(main_module, "get_calendar_service", lambda: _FakeCalendarService())

    payload = _payload(meeting_mode="online")
    payload["message"]["toolCalls"][0]["function"]["arguments"].pop("user_sub", None)
    payload["assistantOverrides"] = {"variableValues": {"user_sub": "104659023322141767006"}}

    with TestClient(main_module.app) as client:
        response = client.post("/create-event", json=payload)

    assert response.status_code == 200
    assert len(created_payloads) == 1
    description = created_payloads[0]["body"]["description"]
    assert "user_sub:104659023322141767006" in description
