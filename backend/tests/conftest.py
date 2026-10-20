from __future__ import annotations

import json
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TEST_TOKEN = "test-token"
# One token with every demo scope. Scope-denial tests build a narrower principal
# directly instead of adding another token to the table.
ALL_SCOPES = [
    "home:timers:write",
    "home:lights:write",
    "home:climate:write",
    "booking:rooms:write",
    "privacy:settings:write",
]


def make_settings(public_url: str = "http://localhost:8000") -> Settings:
    # Explicit values win over the environment, so a developer's .env cannot make
    # the suite pass or fail differently.
    tokens = {
        TEST_TOKEN: {
            "subject": "test-user",
            "client_id": "test-client",
            "scopes": ALL_SCOPES,
        }
    }
    return Settings(
        public_url=public_url,
        tokens_json=json.dumps(tokens),
        log_level="WARNING",
        allowed_hosts="*",
    )


@pytest.fixture
def client():
    # TestClient runs the lifespan, which starts the MCP session manager.
    app = create_app(make_settings())
    with TestClient(app) as test_client:
        yield test_client


def _free_port() -> int:
    # Bind and release a port so uvicorn can take it. Good enough for a test run.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_server():
    """Run the real app over TCP for MCP client tests.

    The SDK's streamable client needs real streaming and session headers, so an
    in-process ASGI transport would not exercise the same path Alexa+ uses.
    """
    port = _free_port()
    app = create_app(make_settings(f"http://127.0.0.1:{port}"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("uvicorn did not start")

    yield f"http://127.0.0.1:{port}/mcp"

    server.should_exit = True
    thread.join(timeout=10)
