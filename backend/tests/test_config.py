from __future__ import annotations

import json

import pytest

from app.auth import parse_tokens
from app.config import DEV_TOKEN_JSON, Settings, startup_warnings
from tests.conftest import TEST_TOKEN, make_settings


def test_local_settings_have_no_startup_warnings():
    # The shipped development setup is allowed to be unsafe on localhost.
    assert startup_warnings(make_settings()) == []


def test_public_server_refuses_the_shipped_development_token():
    with pytest.raises(ValueError, match="development token"):
        Settings(
            public_url="https://alexa.example.com",
            tokens_json=DEV_TOKEN_JSON,
            allowed_hosts="alexa.example.com",
        )


def test_public_server_warns_about_wildcard_hosts_and_plain_http():
    settings = Settings(
        public_url="http://alexa.example.com",
        tokens_json=json.dumps({TEST_TOKEN: {"subject": "household-7f3a", "scopes": ["home:lights:write"]}}),
        allowed_hosts="*",
    )

    warnings = startup_warnings(settings)

    assert any("DNS-rebinding" in warning for warning in warnings)
    assert any("HTTPS" in warning for warning in warnings)


def test_public_server_with_real_settings_is_quiet():
    tokens = json.dumps({TEST_TOKEN: {"subject": "household-7f3a", "scopes": ["home:lights:write"]}})
    settings = Settings(
        public_url="https://alexa.example.com",
        tokens_json=tokens,
        allowed_hosts="alexa.example.com",
        google_client_id="real-client-id",
        google_client_secret="real-client-secret",
    )

    assert startup_warnings(settings) == []


def test_uses_dev_token_is_exact():
    assert Settings(tokens_json=DEV_TOKEN_JSON).uses_dev_token is True
    assert Settings(tokens_json=make_settings().tokens_json).uses_dev_token is False


def test_parse_tokens_rejects_a_raw_alexa_id_as_subject():
    raw = json.dumps(
        {
            TEST_TOKEN: {
                "subject": "amzn1.ask.account.AFakeIdentifier",
                "scopes": ["home:timers:write"],
            }
        }
    )

    try:
        parse_tokens(raw)
    except ValueError as exc:
        assert "pseudonym" in str(exc)
    else:
        raise AssertionError("a raw Alexa id must be refused at the token boundary")


def test_parse_tokens_rejects_an_empty_subject():
    raw = json.dumps({TEST_TOKEN: {"subject": "  ", "scopes": []}})

    try:
        parse_tokens(raw)
    except ValueError as exc:
        assert "non-empty subject" in str(exc)
    else:
        raise AssertionError("an empty subject must be refused at the token boundary")
