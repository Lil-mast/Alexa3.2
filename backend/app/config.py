"""Runtime configuration. Everything is env-overridable with the ALEXA_ prefix."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import field_validator
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
    )

    # Public origin Alexa+ calls. It doubles as the OAuth issuer in the metadata
    # we publish, and as the base for the 401 challenge URL.
    public_url: str = "http://localhost:8000"

    # A JSON string rather than a secret file keeps the demo to one env var.
    # app.auth parses it into subject, client_id, scopes, and optional expiry.
    tokens_json: str = DEV_TOKEN_JSON

    # Host header allow list for the MCP transport guard. "*" disables the guard,
    # which is fine locally but should be narrowed to the App Runner hostname.
    allowed_hosts: str = "*"

    # The console runs on Vite's dev origin, not on this server's origin.
    cors_origins: str = "http://localhost:5173"

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
    if settings.is_local:
        return []
    warnings: list[str] = []
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
