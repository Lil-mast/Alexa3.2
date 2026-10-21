from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def test_health_is_open(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["tools"] == 4
    assert response.json()["rules_version"] == "2"


def test_console_api_requires_a_token(client):
    response = client.get("/api/tools")

    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]


def test_console_api_lists_manifests(client):
    response = client.get("/api/tools", headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["rules_version"] == "2"
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
                assert set(by_name) == {"timer_set", "lights_set", "thermostat_set", "book_room"}
                # The MCP manifest carries the same title and hints as the
                # console manifest. A client can render a picker and decide
                # whether a retry is safe without guessing.
                assert by_name["timer_set"].title == "Set a timer"
                assert by_name["timer_set"].annotations.idempotent_hint is False
                assert by_name["lights_set"].annotations.idempotent_hint is True
                assert by_name["book_room"].annotations.open_world_hint is True
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
                assert payload["audit_id"] is None
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
