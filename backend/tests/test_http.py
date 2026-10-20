from __future__ import annotations

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
    assert response.json()["tools"] == 2


def test_console_api_requires_a_token(client):
    response = client.get("/api/tools")

    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]


def test_console_api_lists_manifests(client):
    response = client.get("/api/tools", headers=AUTH)

    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in response.json()["tools"]}
    assert tools["timer_set"]["risk"] == "low"
    assert tools["timer_set"]["scopes"] == ["home:timers:write"]
    assert tools["lights_set"]["compensator"] == "lights_restore"


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
    # This is the Day 1 exit check in code: a real client initializes, lists the
    # tools, and calls both of them over the same transport Alexa+ will use.
    async with httpx2.AsyncClient(headers=AUTH, timeout=15.0) as http_client:
        async with streamable_http_client(live_server, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                by_name = {tool.name: tool for tool in tools.tools}
                assert set(by_name) == {"timer_set", "lights_set"}
                # The injected Context parameter must not appear in the tool schema.
                assert set(by_name["timer_set"].input_schema["properties"]) == {"duration_seconds", "label"}
                assert set(by_name["lights_set"].input_schema["properties"]) == {"room", "on", "brightness"}

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
