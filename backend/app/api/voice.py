"""Voice output proxy for the demo.

The browser sends the `speech` string it already received from a tool response.
The server returns audio bytes, or a structured reason to use the browser's own
speech synthesis. The API key never reaches the client.

Two gates apply before the upstream call:

- Authentication, because speech can contain a booking title or a timer label.
- `third_party_sharing`, because synthesis sends that text to ElevenLabs. A
  user who turned sharing off gets the fallback, not a hidden exception.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.auth import Principal
from app.config import Settings
from app.state import AppState
from app.voice.elevenlabs import ElevenLabsVoice, VoiceUnavailable


class VoiceConfig(BaseModel):
    enabled: bool
    provider: Literal["elevenlabs"]
    model: str
    max_chars: int
    fallback: Literal["browser_speech_synthesis"]


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)


def _unavailable(reason: str) -> HTTPException:
    code = "INVALID_TEXT" if reason in {"empty_text", "text_too_long"} else "VOICE_UNAVAILABLE"
    http_status = status.HTTP_400_BAD_REQUEST if code == "INVALID_TEXT" else status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(
        status_code=http_status,
        detail={
            "code": code,
            "reason": reason,
            "fallback": "browser_speech_synthesis",
        },
    )


def build_voice_router(
    settings: Settings,
    state: AppState,
    voice: ElevenLabsVoice,
    require_principal,
) -> APIRouter:
    api = APIRouter(prefix="/api/voice", tags=["voice"])

    @api.get("/config", response_model=VoiceConfig)
    async def voice_config(_: Principal = Depends(require_principal)) -> VoiceConfig:
        return VoiceConfig(
            enabled=voice.enabled,
            provider="elevenlabs",
            model=settings.elevenlabs_model_id,
            max_chars=settings.voice_max_chars,
            fallback="browser_speech_synthesis",
        )

    @api.post("/speak")
    async def speak(
        payload: SpeakRequest,
        principal: Principal = Depends(require_principal),
    ) -> Response:
        if not state.privacy.get(principal.subject).third_party_sharing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PRIVACY_BLOCKED",
                    "message": "Voice output needs third-party sharing, which is off.",
                    "follow_up": "Use the browser fallback or turn third-party sharing on.",
                    "fallback": "browser_speech_synthesis",
                },
            )
        if len(payload.text) > settings.voice_max_chars:
            raise _unavailable("text_too_long")

        try:
            clip = await voice.synthesize(payload.text)
        except VoiceUnavailable as exc:
            raise _unavailable(exc.reason) from exc

        # The audio is specific to one response and is already cached in memory
        # by exact text. Tell the browser not to keep its own copy.
        return Response(
            content=clip.content,
            media_type=clip.media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Alexa-Voice": "elevenlabs",
            },
        )

    return api


__all__ = ["SpeakRequest", "VoiceConfig", "build_voice_router"]
