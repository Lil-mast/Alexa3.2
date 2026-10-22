"""Voice client tests. No network: the ElevenLabs transport is mocked."""

from __future__ import annotations

import asyncio

import httpx2
import pytest

from app.config import Settings
from app.voice.elevenlabs import ElevenLabsVoice, VoiceUnavailable


def _settings(**overrides) -> Settings:
    values = {
        "tokens_json": '{"test-token":{"subject":"test-user"}}',
        "public_url": "http://localhost:8000",
        "elevenlabs_api_key": "test-key",
        "elevenlabs_voice_id": "test-voice",
        "elevenlabs_model_id": "test-model",
        "elevenlabs_timeout_seconds": 1.0,
        "voice_max_chars": 20,
        "voice_cache_size": 4,
    }
    values.update(overrides)
    return Settings(**values)


def test_synthesize_returns_the_upstream_audio() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            content=b"audio-bytes",
            headers={"content-type": "audio/mpeg; charset=binary"},
        )

    voice = ElevenLabsVoice(_settings(), transport=httpx2.MockTransport(handler))

    clip = asyncio.run(voice.synthesize(" Timer set. "))

    assert clip.content == b"audio-bytes"
    assert clip.media_type == "audio/mpeg"
    assert seen[0].headers["xi-api-key"] == "test-key"
    assert str(seen[0].url).endswith("/test-voice")


def test_identical_text_is_cached() -> None:
    calls = {"count": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["count"] += 1
        return httpx2.Response(200, content=b"audio", headers={"content-type": "audio/mpeg"})

    voice = ElevenLabsVoice(_settings(), transport=httpx2.MockTransport(handler))

    first = asyncio.run(voice.synthesize("Timer set."))
    second = asyncio.run(voice.synthesize("Timer set."))

    assert first.content == second.content
    assert calls["count"] == 1


def test_not_configured_is_a_typed_failure() -> None:
    voice = ElevenLabsVoice(_settings(elevenlabs_api_key=None))

    with pytest.raises(VoiceUnavailable) as caught:
        asyncio.run(voice.synthesize("Timer set."))

    assert caught.value.reason == "not_configured"


def test_text_over_the_cap_is_refused_before_the_call() -> None:
    voice = ElevenLabsVoice(_settings(), transport=httpx2.MockTransport(lambda request: None))

    with pytest.raises(VoiceUnavailable) as caught:
        asyncio.run(voice.synthesize("a" * 21))

    assert caught.value.reason == "text_too_long"


def test_upstream_error_does_not_echo_the_text() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={"detail": "provider said no"})

    voice = ElevenLabsVoice(_settings(), transport=httpx2.MockTransport(handler))

    with pytest.raises(VoiceUnavailable) as caught:
        asyncio.run(voice.synthesize("Sensitive title"))

    assert caught.value.reason == "upstream_status_500"
    assert "Sensitive" not in str(caught.value)
