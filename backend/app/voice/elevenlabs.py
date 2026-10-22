"""ElevenLabs text to speech, behind a small server-side proxy.

The browser never sees the API key. It asks the backend to speak a `speech`
string, and the backend either returns audio or a structured reason why it
cannot. That keeps the demo voice replaceable: a different provider only has to
implement the same `synthesize` method.

This module is not in the decision path. It does not choose tools, change state,
or write audit rows. The text it speaks is the same sentence the server already
composed, which is why the transcript stays truthful even when the voice fails.

Privacy note: synthesizing sends the speech text to ElevenLabs. The API endpoint
checks the caller's `third_party_sharing` setting before calling this class, so a
user who turned sharing off gets the browser fallback instead.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass

import httpx2

from app.config import Settings

logger = logging.getLogger("alexa.voice")

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1/text-to-speech"


class VoiceUnavailable(Exception):
    """A speech request that cannot be served.

    `reason` is a short machine code. It never includes the text, because the
    text may contain a booking title or a timer label.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AudioClip:
    content: bytes
    media_type: str


class ElevenLabsVoice:
    """Async ElevenLabs client with a bounded, text-keyed cache."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._cache: OrderedDict[str, AudioClip] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self._settings.voice_enabled

    async def synthesize(self, text: str) -> AudioClip:
        """Return audio for one short sentence.

        Raises VoiceUnavailable for configuration, length, transport, and
        upstream failures. The caller turns that into a 503 with a browser
        fallback, never into a silent success.
        """
        cleaned = text.strip()
        if not cleaned:
            raise VoiceUnavailable("empty_text")
        if len(cleaned) > self._settings.voice_max_chars:
            raise VoiceUnavailable("text_too_long")
        if not self.enabled:
            raise VoiceUnavailable("not_configured")

        if self._settings.voice_cache_size > 0:
            cached = self._cache.get(cleaned)
            if cached is not None:
                # move_to_end makes this a real LRU rather than a FIFO.
                self._cache.move_to_end(cleaned)
                return cached

        clip = await self._request(cleaned)
        if self._settings.voice_cache_size > 0:
            self._cache[cleaned] = clip
            self._cache.move_to_end(cleaned)
            while len(self._cache) > self._settings.voice_cache_size:
                self._cache.popitem(last=False)
        return clip

    async def _request(self, text: str) -> AudioClip:
        url = f"{ELEVENLABS_BASE}/{self._settings.elevenlabs_voice_id}"
        payload = {
            "text": text,
            "model_id": self._settings.elevenlabs_model_id,
            # These values are a neutral, readable demo voice. They are not
            # per-user preferences, so there is no reason to expose them.
            "voice_settings": {
                "stability": 0.4,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }
        headers = {
            "xi-api-key": self._settings.elevenlabs_api_key or "",
            "Accept": "audio/mpeg",
        }

        try:
            async with httpx2.AsyncClient(
                timeout=self._settings.elevenlabs_timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx2.TimeoutException as exc:
            # The demo should fall back quickly instead of making the operator
            # wait for a long upstream timeout.
            raise VoiceUnavailable("timeout") from exc
        except httpx2.HTTPError as exc:
            raise VoiceUnavailable("upstream_unreachable") from exc

        if response.status_code != 200:
            # The status is useful. The body is not logged: an error response can
            # echo the request text.
            logger.warning("voice_upstream_error", extra={"status": response.status_code})
            raise VoiceUnavailable(f"upstream_status_{response.status_code}")

        audio = response.content
        if not audio:
            raise VoiceUnavailable("empty_audio")

        content_type = response.headers.get("content-type", "audio/mpeg")
        media_type = content_type.split(";")[0].strip() or "audio/mpeg"
        return AudioClip(content=audio, media_type=media_type)


__all__ = ["AudioClip", "ElevenLabsVoice", "VoiceUnavailable"]
