from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.auth import Principal
from app.router import Router
from tests.conftest import ALL_SCOPES, TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _principal(subject: str = "test-user") -> Principal:
    return Principal(subject=subject, client_id="test-client", scopes=tuple(ALL_SCOPES))


def test_health_is_open(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["tools"] == 8
    assert response.json()["rules_version"] == "3"
    assert response.json()["audit_seeded"] is True


def test_console_api_requires_a_token(client):
    response = client.get("/api/tools")

    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]


def test_console_api_lists_manifests(client):
    response = client.get("/api/tools", headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["rules_version"] == "3"
    assert payload["confirmation_ttl_seconds"] == 300
    tools = {tool["name"]: tool for tool in payload["tools"]}
    assert tools["timer_set"]["risk"] == "low"
    assert tools["timer_set"]["title"] == "Set a timer"
    assert tools["timer_set"]["scopes"] == ["home:timers:write"]
    assert tools["lights_set"]["compensator"] == "lights_restore"
    assert tools["lights_set"]["idempotent"] is True
    assert tools["book_room"]["risk"] == "medium"
    assert tools["book_room"]["external"] is True
    # Bounds are data now, and the console gets them with the manifest.
    assert tools["thermostat_set"]["fields"]["target_c"]["min"] == 16
    assert tools["thermostat_set"]["fields"]["target_c"]["max"] == 28
    assert tools["book_room"]["fields"]["date"]["format"] == "date"


def test_whoami_reflects_the_token(client):
    response = client.get("/api/whoami", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["subject"] == "test-user"


def test_mcp_rejects_unauthenticated_requests(client):
    # The challenge must point at the RFC 9728 metadata, not just say 401, or an
    # MCP client cannot discover how to authenticate.
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )

    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer")
    assert "/.well-known/oauth-protected-resource/mcp" in challenge


def test_mcp_rejects_an_unknown_token(client):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={**AUTH, "Authorization": "Bearer wrong", "Accept": "application/json, text/event-stream"},
    )

    assert response.status_code == 401


def test_protected_resource_metadata(client):
    response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resource"] == "http://localhost:8000/mcp"
    assert "home:timers:write" in payload["scopes_supported"]


@pytest.mark.asyncio
async def test_mcp_lists_and_calls_tools(live_server):
    # The Day 1 transport check, now covering all four tools: a real client
    # initializes, lists the tools, and calls the low-risk ones over the same
    # transport Alexa+ will use.
    async with httpx2.AsyncClient(headers=AUTH, timeout=15.0) as http_client:
        async with streamable_http_client(live_server, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                by_name = {tool.name: tool for tool in tools.tools}
                assert set(by_name) == {
                    "timer_set",
                    "lights_set",
                    "thermostat_set",
                    "book_room",
                    "undo",
                    "tell_me_more",
                    "privacy_get",
                    "privacy_set",
                }
                # The MCP manifest carries the same title and hints as the
                # console manifest. A client can render a picker and decide
                # whether a retry is safe without guessing.
                assert by_name["timer_set"].title == "Set a timer"
                assert by_name["timer_set"].annotations.idempotent_hint is False
                assert by_name["lights_set"].annotations.idempotent_hint is True
                assert by_name["book_room"].annotations.open_world_hint is True
                # Read tools advertise the hint, so a client does not treat a
                # detail lookup with the same caution as a write.
                assert by_name["tell_me_more"].annotations.read_only_hint is True
                assert by_name["privacy_set"].annotations.read_only_hint is False
                assert by_name["timer_set"].output_schema is not None
                assert "properties" in by_name["timer_set"].output_schema
                # The injected Context parameter must not appear in the tool schema.
                assert set(by_name["timer_set"].input_schema["properties"]) == {"duration_seconds", "label"}
                assert set(by_name["lights_set"].input_schema["properties"]) == {"room", "on", "brightness"}
                assert set(by_name["thermostat_set"].input_schema["properties"]) == {"zone", "target_c"}
                # A medium-risk tool exposes the token as a parameter, so Alexa+
                # can send it back on the second call.
                assert "confirmation_token" in by_name["book_room"].input_schema["properties"]

                timer = await session.call_tool("timer_set", {"duration_seconds": 600})
                payload = timer.structured_content
                assert payload is not None
                assert payload["status"] == "ok"
                assert payload["speech"] == "Timer set for 10 minutes."
                # Every decision now points at an audit row, including a preview
                # or a refusal. The id is stable and appears in the console.
                assert payload["audit_id"].startswith("a_")
                # Concise mode is the default, so the detail is withheld and
                # flagged instead of sent.
                assert payload["detail"] is None
                assert payload["detail_available"] is True
                assert payload["trace"][0]["service"] == "timers"

                lights = await session.call_tool("lights_set", {"room": "living_room", "brightness": 30})
                assert lights.structured_content is not None
                assert lights.structured_content["speech"] == "Living room lights set to 30 percent."


@pytest.mark.asyncio
async def test_mcp_booking_preview_then_confirm(live_server):
    # Day 2 exit check over the real transport: preview, confirm, replay refused.
    booking_date = (datetime.now(UTC).date() + timedelta(days=3)).isoformat()
    params = {"date": booking_date, "room": "cedar", "start_time": "13:00", "guests": 4}

    async with httpx2.AsyncClient(headers=AUTH, timeout=15.0) as http_client:
        async with streamable_http_client(live_server, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                preview = await session.call_tool("book_room", params)
                payload = preview.structured_content
                assert payload is not None
                assert payload["status"] == "confirmation_required"
                assert payload["error"] is None
                assert payload["preview"]["service"] == "booking"
                assert payload["preview"]["irreversible"] is False
                assert payload["preview"]["params"]["room"] == "cedar"
                token = payload["confirmation_token"]
                assert token

                confirmed = await session.call_tool("book_room", {**params, "confirmation_token": token})
                result = confirmed.structured_content
                assert result is not None
                assert result["status"] == "ok"
                assert result["speech"].startswith("Booked the Cedar room")

                replay = await session.call_tool("book_room", {**params, "confirmation_token": token})
                assert replay.structured_content is not None
                assert replay.structured_content["error"]["code"] == "TOKEN_CONSUMED"

                trace = await http_client.get(live_server.replace("/mcp", "/api/trace"))
                assert trace.status_code == 200
                entries = [entry for entry in trace.json()["entries"] if entry["tool"] == "book_room"]
                assert [entry["decision"] for entry in entries[:3]] == ["refused", "executed", "previewed"]


@pytest.mark.asyncio
async def test_mcp_returns_structured_business_errors(live_server):
    async with httpx2.AsyncClient(headers=AUTH, timeout=15.0) as http_client:
        async with streamable_http_client(live_server, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool("timer_set", {"duration_seconds": 0})

                assert result.is_error is not True
                payload = result.structured_content
                assert payload is not None
                assert payload["status"] == "error"
                assert payload["error"]["code"] == "OUT_OF_BOUNDS"
                assert payload["error"]["follow_up"] == "State the allowed range or choices."
                assert payload["trace"][0]["decision"] == "refused"


@pytest.mark.asyncio
async def test_mcp_traces_appear_in_the_console(live_server):
    async with httpx2.AsyncClient(headers=AUTH, timeout=15.0) as http_client:
        async with streamable_http_client(live_server, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("lights_set", {"room": "kitchen", "on": True})

                trace = await http_client.get(live_server.replace("/mcp", "/api/trace"))

    assert trace.status_code == 200
    entries = trace.json()["entries"]
    assert entries[0]["tool"] == "lights_set"
    assert entries[0]["status"] == "ok"


def test_audit_endpoint_lists_only_the_callers_rows(client):
    state = client.app.state.alexa
    router = Router(state)
    router.execute("timer_set", {"duration_seconds": 60}, _principal())
    router.execute("timer_set", {"duration_seconds": 60}, _principal(subject="someone-else"))

    response = client.get("/api/audit", headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    # The seed marker is shared metadata so a reset reads as intentional.
    assert payload["seeded"]["seeded"] is True
    assert payload["seeded"]["rows"] == 3
    entries = payload["entries"]
    assert len(entries) == 1
    assert entries[0]["subject"] == "test-user"
    assert entries[0]["tool"] == "timer_set"
    assert entries[0]["decision"] == "executed"
    assert entries[0]["rules_version"] == "3"


def test_audit_verify_reports_a_healthy_chain(client):
    response = client.get("/api/audit/verify", headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["rows"] >= 3
    assert payload["first_bad"] is None


@pytest.mark.asyncio
async def test_mcp_undo_is_linked_in_the_audit(live_server):
    # The Day 3 exit check over the real transport: an action, an undo, a chain
    # that verifies, and an undo row that points at what it reversed.
    async with httpx2.AsyncClient(headers=AUTH, timeout=15.0) as http_client:
        async with streamable_http_client(live_server, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # The server is module scoped, so establish a known light state
                # before the action under test instead of assuming a fresh one.
                await session.call_tool("lights_set", {"room": "kitchen", "on": False})
                action = await session.call_tool("lights_set", {"room": "kitchen", "brightness": 20})
                assert action.structured_content is not None
                assert action.structured_content["status"] == "ok"

                undone = await session.call_tool("undo", {})
                payload = undone.structured_content
                assert payload is not None
                assert payload["status"] == "ok"
                assert payload["speech"] == "Kitchen lights off again."

                audit = await http_client.get(live_server.replace("/mcp", "/api/audit"))
                verify = await http_client.get(live_server.replace("/mcp", "/api/audit/verify"))

    assert verify.status_code == 200
    assert verify.json()["ok"] is True

    entries = audit.json()["entries"]
    undo_row = next(entry for entry in entries if entry["tool"] == "undo")
    action_row = next(entry for entry in entries if entry["tool"] == "lights_set")
    assert undo_row["compensator_of"] == action_row["id"]
    assert undo_row["result_ref"] == action_row["id"]


@pytest.mark.asyncio
async def test_mcp_privacy_gate_refuses_booking(live_server):
    booking_date = (datetime.now(UTC).date() + timedelta(days=4)).isoformat()

    async with httpx2.AsyncClient(headers=AUTH, timeout=15.0) as http_client:
        async with streamable_http_client(live_server, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("privacy_set", {"third_party_sharing": False})

                result = await session.call_tool("book_room", {"date": booking_date})

                payload = result.structured_content
                assert payload is not None
                assert payload["status"] == "error"
                assert payload["error"]["code"] == "PRIVACY_BLOCKED"
                assert payload["confirmation_token"] is None

                # Leave the shared module-scoped server as it was found.
                await session.call_tool("privacy_set", {"third_party_sharing": True})
