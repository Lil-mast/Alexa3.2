from __future__ import annotations

import json
import time

import pytest

from app.auth import StaticTokenVerifier, parse_tokens
from app.config import Settings
from tests.conftest import TEST_TOKEN, make_settings


def test_parse_tokens_rejects_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_tokens("{nope")


def test_parse_tokens_rejects_empty_table():
    with pytest.raises(ValueError, match="non-empty"):
        parse_tokens("{}")


@pytest.mark.asyncio
async def test_valid_token_verifies():
    verifier = StaticTokenVerifier(parse_tokens(make_settings().tokens_json))
    access = await verifier.verify_token(TEST_TOKEN)

    assert access is not None
    assert access.subject == "test-user"
    assert "home:timers:write" in access.scopes


@pytest.mark.asyncio
async def test_unknown_token_is_rejected():
    verifier = StaticTokenVerifier(parse_tokens(make_settings().tokens_json))
    assert await verifier.verify_token("wrong") is None


@pytest.mark.asyncio
async def test_expired_token_is_rejected():
    raw = json.dumps(
        {
            TEST_TOKEN: {
                "subject": "old-user",
                "scopes": ["home:timers:write"],
                "expires_at": int(time.time()) - 1,
            }
        }
    )
    verifier = StaticTokenVerifier(parse_tokens(raw))
    assert await verifier.verify_token(TEST_TOKEN) is None


def test_default_public_url_builds_expected_resource():
    settings = Settings(tokens_json=make_settings().tokens_json)
    assert settings.resource_server_url == "http://localhost:8000/mcp"
