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
        "_fetch_meetings_summary_from_weather_agent",
        lambda **kwargs: {
            "summary_text": "On 2026-04-10, you have 2 meetings: 1 in-person and 1 online.",
            "counts": {"total": 2, "in_person": 1, "online": 1},
            "risk_summary": [{"event_title": "Client Visit", "risk": "low"}],
            "events": [],
            "recommendations": [],
            "date": "2026-04-10",
            "timezone": "Europe/Berlin",
            "user_sub": kwargs["user_sub"],
        },
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
    monkeypatch.setattr(
        main_module,
        "_fetch_meetings_summary_from_weather_agent",
        lambda **kwargs: {
            "summary_text": "You have no meetings on 2026-04-10.",
            "counts": {"total": 0, "in_person": 0, "online": 0},
            "risk_summary": [],
            "events": [],
            "recommendations": [],
            "date": "2026-04-10",
            "timezone": "Europe/Berlin",
            "user_sub": kwargs["user_sub"],
        },
    )

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
        "_fetch_meetings_summary_from_weather_agent",
        lambda **kwargs: {
            "summary_text": (
                "On 2026-04-10, you have 1 meetings: 1 in-person and 0 online. "
                "Weather guidance: Site Visit at 09:00: Add event city to evaluate weather risk."
            ),
            "counts": {"total": 1, "in_person": 1, "online": 0},
            "risk_summary": [{"event_title": "Site Visit", "risk": "blocked"}],
            "events": [],
            "recommendations": ["Site Visit at 09:00: Add event city to evaluate weather risk."],
            "date": "2026-04-10",
            "timezone": "Europe/Berlin",
            "user_sub": kwargs["user_sub"],
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
