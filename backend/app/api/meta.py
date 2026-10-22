"""Public capability document for the console and for a fresh clone.

This route is intentionally unauthenticated. It contains no schema and no
secret: just the versions, the tool count, whether the audit chain was seeded,
and whether a voice provider is configured. That lets the console render its
shell and its token bar before it has a token, without teaching an anonymous
caller anything about the request contract.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.api.voice import VoiceConfig
from app.config import Settings
from app.rules import RULES
from app.state import AppState
from app.tools import REGISTRY, SCOPES


class AssistantConfig(BaseModel):
    # There is no model in this path. The field is explicit so a reviewer does
    # not have to infer it from the absence of a key.
    mode: Literal["deterministic"]
    model: None = None
    endpoint: str
    note: str


class AuthConfig(BaseModel):
    scheme: Literal["bearer"]
    scopes: list[str]
    # Public capability flags, never the client id or secret. The landing page
    # uses `google_enabled` to decide whether to render the sign-in button.
    google_enabled: bool
    frontend_url: str
    session_ttl_seconds: int
    accounts: Literal["database"]


class AuditConfig(BaseModel):
    seeded: bool
    rows: int
    fixture: str | None


class ConfigView(BaseModel):
    name: str
    version: str
    rules_version: str
    tools: int
    persistence: Literal["memory"]
    assistant: AssistantConfig
    voice: VoiceConfig
    auth: AuthConfig
    audit: AuditConfig
    endpoints: dict[str, str]


def build_meta_router(state: AppState, settings: Settings) -> APIRouter:
    api = APIRouter(prefix="/api", tags=["meta"])

    @api.get("/config", response_model=ConfigView)
    async def read_config() -> ConfigView:
        marker = state.audit.seed_marker
        return ConfigView(
            name="Alexa",
            version=__version__,
            rules_version=RULES.version,
            tools=len(REGISTRY),
            persistence="memory",
            assistant=AssistantConfig(
                mode="deterministic",
                endpoint="/api/assistant/turn",
                note="Alexa+ owns intent in production. This endpoint is a demo stand-in.",
            ),
            voice=VoiceConfig(
                enabled=settings.voice_enabled,
                provider="elevenlabs",
                model=settings.elevenlabs_model_id,
                max_chars=settings.voice_max_chars,
                fallback="browser_speech_synthesis",
            ),
            auth=AuthConfig(
                scheme="bearer",
                scopes=SCOPES,
                google_enabled=settings.google_oauth_enabled,
                frontend_url=settings.frontend_origin,
                session_ttl_seconds=settings.session_ttl_seconds,
                accounts="database",
            ),
            audit=AuditConfig(
                seeded=marker is not None,
                rows=len(state.audit),
                fixture=str(marker["fixture"]) if marker else None,
            ),
            endpoints={
                "mcp": "/mcp",
                "health": "/health",
                "docs": "/docs",
                "console": "/console/",
            },
        )

    return api


__all__ = ["AssistantConfig", "AuditConfig", "AuthConfig", "ConfigView", "build_meta_router"]
