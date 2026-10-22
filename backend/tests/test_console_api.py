"""HTTP tests for the console, assistant, voice, and journey endpoints.

The console contract is tested over HTTP, not by calling the builders directly,
because the frontend sees status codes, headers, and JSON. A change that only
breaks the wire shape should fail here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def test_config_is_public_and_names_the_deterministic_path(client):
    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Alexa"
    assert payload["rules_version"] == "3"
    assert payload["tools"] == 8
    assert payload["persistence"] == "memory"
    assert payload["assistant"]["mode"] == "deterministic"
    assert payload["assistant"]["model"] is None
    assert payload["voice"]["enabled"] is False
    assert payload["voice"]["fallback"] == "browser_speech_synthesis"
    assert payload["audit"]["seeded"] is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/state",
        "/api/privacy",
        "/api/assistant/session",
        "/api/journeys",
        "/api/voice/config",
    ],
)
def test_new_api_paths_require_a_token(client, path):
    response = client.get(path)

    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]


def test_assistant_turn_runs_the_router_and_updates_state(client):
    response = client.post(
        "/api/assistant/turn",
        json={"utterance": "set a ten minute timer"},
        headers=AUTH,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["understood"] is True
    assert payload["status"] == "ok"
    assert payload["intent"]["tool"] == "timer_set"
    assert payload["intent"]["params"] == {"duration_seconds": 600}
    assert payload["speech"] == "Timer set for 10 minutes."
    assert payload["audit_id"].startswith("a_")
    assert payload["response"]["trace"][0]["decision"] == "executed"

    state = client.get("/api/state", headers=AUTH)
    assert state.status_code == 200
    assert len(state.json()["timers"]) == 1


def test_assistant_confirmation_flow_over_http(client):
    preview = client.post(
        "/api/assistant/turn",
        json={"utterance": "book the cedar room tomorrow at 1pm for 4 guests"},
        headers=AUTH,
    )

    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["status"] == "confirmation_required"
    assert preview_payload["pending"]["tool"] == "book_room"
    assert "token" not in preview_payload["pending"]

    session = client.get("/api/assistant/session", headers=AUTH)
    assert session.json()["pending"]["tool"] == "book_room"

    confirmed = client.post("/api/assistant/confirm", headers=AUTH)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "ok"

    cleared = client.get("/api/assistant/session", headers=AUTH)
    assert cleared.json()["pending"] is None


def test_call_endpoint_is_the_console_write_path(client):
    lights = client.post(
        "/api/call/lights_set",
        json={"params": {"room": "office", "brightness": 40}},
        headers=AUTH,
    )

    assert lights.status_code == 200
    assert lights.json()["status"] == "ok"
    assert lights.json()["speech"] == "Office lights set to 40 percent."

    unknown = client.post("/api/call/not_a_tool", json={"params": {}}, headers=AUTH)
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "NOT_FOUND"


def test_call_endpoint_keeps_the_confirmation_contract(client):
    booking_date = (datetime.now(UTC).date() + timedelta(days=3)).isoformat()
    params = {"date": booking_date, "room": "maple", "start_time": "10:00"}

    preview = client.post("/api/call/book_room", json={"params": params}, headers=AUTH)
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["status"] == "confirmation_required"
    token = preview_payload["confirmation_token"]

    confirmed = client.post(
        "/api/call/book_room",
        json={"params": params, "confirmation_token": token},
        headers=AUTH,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "ok"

    replay = client.post(
        "/api/call/book_room",
        json={"params": params, "confirmation_token": token},
        headers=AUTH,
    )
    assert replay.status_code == 200
    assert replay.json()["error"]["code"] == "TOKEN_CONSUMED"


def test_privacy_put_and_get_share_the_router(client):
    updated = client.put(
        "/api/privacy",
        json={"third_party_sharing": False},
        headers=AUTH,
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["status"] == "ok"
    assert payload["speech"] == "Third-party sharing is off."
    assert payload["audit_id"].startswith("a_")

    current = client.get("/api/privacy", headers=AUTH)
    assert current.status_code == 200
    assert current.json()["third_party_sharing"] is False

    audit = client.get("/api/audit", headers=AUTH).json()["entries"]
    assert audit[0]["tool"] == "privacy_set"
    assert audit[0]["decision"] == "executed"


def test_privacy_bad_value_is_a_tool_result_not_a_422(client):
    response = client.put(
        "/api/privacy",
        json={"retention_days": 14},
        headers=AUTH,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] in {"OUT_OF_BOUNDS", "INVALID_PARAM"}
    assert payload["audit_id"].startswith("a_")


def test_journeys_list_and_run_are_isolated(client):
    listing = client.get("/api/journeys", headers=AUTH)

    assert listing.status_code == 200
    names = [journey["name"] for journey in listing.json()["journeys"]]
    assert names == ["booking", "lights-and-rules", "privacy", "timer"]

    before = len(client.get("/api/audit", headers=AUTH).json()["entries"])

    run = client.post("/api/journeys/timer/run", headers=AUTH)

    assert run.status_code == 200
    result = run.json()
    assert result["passed"] is True
    assert result["audit_ok"] is True
    assert len(result["steps"]) == 2

    # The live audit chain did not gain the journey's rows.
    after = len(client.get("/api/audit", headers=AUTH).json()["entries"])
    assert after == before

    missing = client.post("/api/journeys/nope/run", headers=AUTH)
    assert missing.status_code == 404


def test_voice_falls_back_when_no_provider_is_configured(client):
    config = client.get("/api/voice/config", headers=AUTH)
    assert config.status_code == 200
    assert config.json()["enabled"] is False

    spoken = client.post("/api/voice/speak", json={"text": "Timer set."}, headers=AUTH)
    assert spoken.status_code == 503
    assert spoken.json()["detail"]["code"] == "VOICE_UNAVAILABLE"
    assert spoken.json()["detail"]["fallback"] == "browser_speech_synthesis"

    too_long = client.post("/api/voice/speak", json={"text": "a" * 601}, headers=AUTH)
    assert too_long.status_code == 400
    assert too_long.json()["detail"]["code"] == "INVALID_TEXT"


def test_voice_honors_third_party_sharing(client):
    client.put("/api/privacy", json={"third_party_sharing": False}, headers=AUTH)

    spoken = client.post("/api/voice/speak", json={"text": "Timer set."}, headers=AUTH)

    assert spoken.status_code == 403
    assert spoken.json()["detail"]["code"] == "PRIVACY_BLOCKED"
    assert spoken.json()["detail"]["fallback"] == "browser_speech_synthesis"
