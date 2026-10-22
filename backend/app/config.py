"""Runtime configuration. Everything is env-overridable with the ALEXA_ prefix."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Amazon user and skill identifiers. A token subject must be a pseudonym, not
# one of these: the server never needs the raw identifier, and keeping it out of
# logs and traces is cheaper than redacting it later.
AMAZON_ID = re.compile(r"^amzn1\.")

DEV_TOKEN_JSON = (
    '{"dev-token":{"subject":"demo-user","client_id":"alexa-demo",'
    '"scopes":["home:timers:write","home:lights:write","home:climate:write",'
    '"booking:rooms:write","privacy:settings:write"]}}'
)
"""Development-only token table.

One token with every demo scope keeps the MCP Inspector usable on a fresh
checkout. `ALEXA_TOKENS_JSON` replaces this before any deployment.
"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALEXA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Tests and callers can pass `database_url=` even though the environment
        # name is DATABASE_URL, not ALEXA_DATABASE_URL.
        populate_by_name=True,
    )

    # Public origin Alexa+ calls. It doubles as the OAuth issuer in the metadata
    # we publish, and as the base for the 401 challenge URL.
    public_url: str = "http://localhost:8000"

    # Accounts and sessions are the only state that survives a redeploy. Render
    # provides DATABASE_URL; local development defaults to a file beside the
    # backend so a restart keeps the same user and session.
    database_url: str = Field(
        default="sqlite:///./data/alexa.db",
        validation_alias=AliasChoices("DATABASE_URL", "ALEXA_DATABASE_URL"),
    )

    # Google OAuth. Both halves are required before /api/auth is enabled. The
    # callback lives on the API origin, never on the frontend origin.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    oauth_redirect_uri: str | None = None
    frontend_url: str = "http://localhost:5173"
    session_ttl_seconds: int = 604800
    # The handoff code is small on purpose. It only needs to survive the redirect
    # from the callback to the SPA, and a short window limits replay if the URL
    # ends up somewhere it should not.
    exchange_code_ttl_seconds: int = 60
    # Local-only shortcut for UI work without a Google project. It is gated by
    # both this flag and `is_local`, so a public Render instance cannot expose it
    # even if the flag is accidentally set.
    auth_dev_login: bool = False

    # A JSON string rather than a secret file keeps the demo to one env var.
    # app.auth parses it into subject, client_id, scopes, and optional expiry.
    tokens_json: str = DEV_TOKEN_JSON

    # Host header allow list for the MCP transport guard. "*" disables the guard,
    # which is fine locally but should be narrowed to the App Runner hostname.
    allowed_hosts: str = "*"

    # The console runs on Vite's dev origin and on Vercel in production. The
    # server is on Render, so both are cross-origin. No cookies, so credentials
    # stay off and the browser only needs to allow the Authorization header.
    cors_origins: str = "https://alexa.vercel.app,http://localhost:5173"

    # JSON logs in App Runner. Uvicorn keeps its own format.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Size of the in-memory console trace. This is not the audit log.
    trace_capacity: int = 200

    # Reserved for the Day 2 adapter timeout budget. Simulated adapters are
    # instant, so nothing reads this yet.
    adapter_timeout_ms: int = 300

    # ElevenLabs is the demo voice. It is optional: without a key the console
    # falls back to the browser's own speech synthesis. The key is read from the
    # environment and never leaves the server, and the voice id is fixed here so
    # a client cannot ask the server to fetch an arbitrary voice.
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model_id: str = "eleven_turbo_v2_5"
    elevenlabs_timeout_seconds: float = 10.0
    # A tool response is one short sentence. The cap protects the upstream call
    # from an accidental paste of a whole transcript.
    voice_max_chars: int = 600
    # Server-composed phrases repeat during a demo. A small cache makes the
    # second playback instant and cuts upstream cost. It is keyed by exact text,
    # cleared on restart, and never contains a subject id.
    voice_cache_size: int = 32

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("session_ttl_seconds", "exchange_code_ttl_seconds")
    @classmethod
    def _positive_ttl(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("TTL values must be positive")
        return value

    @field_validator("database_url")
    @classmethod
    def _non_empty_database(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("DATABASE_URL must not be empty")
        return value.strip()

    @property
    def google_oauth_enabled(self) -> bool:
        """True only when both halves of the Google client exist."""
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def resolved_oauth_redirect_uri(self) -> str:
        """The callback Google is told to use.

        Production sets this explicitly because the public URL is the Render
        origin. Local development derives it from `public_url`, so the default
        works without a second variable.
        """
        value = self.oauth_redirect_uri or f"{self.public_url.rstrip('/')}/api/auth/callback/google"
        return value.rstrip("/")

    @property
    def frontend_origin(self) -> str:
        return self.frontend_url.rstrip("/")

    @property
    def resource_server_url(self) -> str:
        """The URL Alexa+ calls, and the RFC 8707 resource identifier we publish."""
        return f"{self.public_url.rstrip('/')}/mcp"

    @property
    def is_local(self) -> bool:
        """True for the developer origins that are safe to expose as-is."""
        host = (urlparse(self.public_url).hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1", "testserver"}

    @property
    def uses_dev_token(self) -> bool:
        """True when the token table is still the one shipped in the repository."""
        return self.tokens_json.strip() == DEV_TOKEN_JSON

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def voice_enabled(self) -> bool:
        """True only when both halves of the ElevenLabs configuration exist."""
        return bool(self.elevenlabs_api_key and self.elevenlabs_voice_id)


def startup_warnings(settings: Settings) -> list[str]:
    """Configuration that is fine locally and dangerous on a public host.

    These are warnings, not startup errors. A hackathon demo should still boot
    with the shipped token; a deployer should see the warning in the first log
    lines and fix it before real users arrive.
    """
    warnings: list[str] = []

    # A blank client id or secret is the most common reason the sign-in button
    # stays greyed out, and it is invisible from the browser. Say it at boot.
    missing = [
        name
        for name, value in (
            ("ALEXA_GOOGLE_CLIENT_ID", settings.google_client_id),
            ("ALEXA_GOOGLE_CLIENT_SECRET", settings.google_client_secret),
        )
        if not value
    ]
    if missing:
        warnings.append(
            f"Google sign-in is disabled. {', '.join(missing)} {'' if len(missing) == 1 else 'are'} empty on the API."
        )

    if settings.is_local:
        return warnings

    if settings.uses_dev_token:
        warnings.append(
            "ALEXA_TOKENS_JSON still contains the development token. Replace it before exposing the server."
        )
    if "*" in settings.allowed_host_list:
        warnings.append("ALEXA_ALLOWED_HOSTS disables DNS-rebinding protection. Set the public hostname instead.")
    if not settings.public_url.lower().startswith("https://"):
        warnings.append("ALEXA_PUBLIC_URL is not HTTPS. Alexa+ requires a TLS origin in production.")
    return warnings


@lru_cache
def get_settings() -> Settings:
    # Parsed once per process. Tests pass an explicit Settings instead.
    return Settings()
