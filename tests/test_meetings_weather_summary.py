from fastapi.testclient import TestClient
import pytest

from app import main as main_module


@pytest.fixture
def client():
    with TestClient(main_module.app) as c:
        yield c


def test_meetings_weather_summary_with_vapi_wrapper(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setattr(
        main_module,
        "get_current_user_or_401",
        lambda request: ({"sub": "u1", "email": "u1@example.com"}, None),
    )
    monkeypatch.setattr(
        main_module,
        "_list_events_payload",
        lambda _from_iso, _to_iso: {
            "events": [
                {
                    "title": "Client Visit",
                    "start": "2026-04-10T11:00:00+02:00",
                    "end": "2026-04-10T11:30:00+02:00",
                    "location": "Berlin Office",
                    "city": "Berlin",
                    "city_source": "provided",
                    "meeting_mode": "in_person",
                    "is_virtual": False,
                    "user_sub": "u1",
                },
                {
                    "title": "Online Sync",
                    "start": "2026-04-10T13:00:00+02:00",
                    "end": "2026-04-10T13:20:00+02:00",
                    "location": None,
                    "city": None,
                    "city_source": None,
                    "meeting_mode": "online",
                    "is_virtual": True,
                    "user_sub": "u1",
                },
                {
                    "title": "Other User Meeting",
                    "start": "2026-04-10T15:00:00+02:00",
                    "end": "2026-04-10T15:20:00+02:00",
                    "location": None,
                    "city": "Hamburg",
                    "city_source": "provided",
                    "meeting_mode": "in_person",
                    "is_virtual": False,
                    "user_sub": "u2",
                },
            ]
        },
    )
    monkeypatch.setattr(
        main_module,
        "_fetch_current_weather_by_city",
        lambda city: {"temperature_c": 10.4, "wind_speed_kmh": 12.0, "weather_code": 2}
        if city == "Berlin"
        else None,
    )

    response = client.post(
        "/meetings-weather-summary",
        json={
            "message": {
                "toolCalls": [
                    {
                        "id": "tc-1",
                        "function": {
                            "arguments": {
                                "date": "2026-04-10",
                                "timezone": "Europe/Berlin",
                            }
                        },
                    }
                ]
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["toolCallId"] == "tc-1"
    assert "2 meetings: 1 in-person and 1 online" in body["results"][0]["result"]
    assert body["data"]["counts"] == {"total": 2, "in_person": 1, "online": 1}
    assert body["data"]["risk_summary"][0]["risk"] == "low"


def test_meetings_weather_summary_no_meetings(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setattr(
        main_module,
        "get_current_user_or_401",
        lambda request: ({"sub": "u1", "email": "u1@example.com"}, None),
    )
    monkeypatch.setattr(main_module, "_list_events_payload", lambda _from_iso, _to_iso: {"events": []})

    response = client.post(
        "/meetings-weather-summary",
        json={"date": "2026-04-10", "timezone": "Europe/Berlin"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {"total": 0, "in_person": 0, "online": 0}
    assert body["summary_text"] == "You have no meetings on 2026-04-10."


def test_meetings_weather_summary_in_person_missing_city_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_current_user_or_401",
        lambda request: ({"sub": "u1", "email": "u1@example.com"}, None),
    )
    monkeypatch.setattr(
        main_module,
        "_list_events_payload",
        lambda _from_iso, _to_iso: {
            "events": [
                {
                    "title": "Site Visit",
                    "start": "2026-04-10T09:00:00+02:00",
                    "end": "2026-04-10T10:00:00+02:00",
                    "location": "Client HQ",
                    "city": None,
                    "city_source": None,
                    "meeting_mode": "in_person",
                    "is_virtual": False,
                    "user_sub": "u1",
                }
            ]
        },
    )

    response = client.post(
        "/meetings-weather-summary",
        json={"date": "2026-04-10", "timezone": "Europe/Berlin"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {"total": 1, "in_person": 1, "online": 0}
    assert body["risk_summary"][0]["risk"] == "blocked"
    assert "Add event city to evaluate weather risk." in body["recommendations"][0]
