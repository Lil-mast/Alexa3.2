"""Runtime configuration. Everything is env-overridable with the ALEXA_ prefix."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @property
    def resource_server_url(self) -> str:
        """The URL Alexa+ calls, and the RFC 8707 resource identifier we publish."""
        return f"{self.public_url.rstrip('/')}/mcp"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    # Parsed once per process. Tests pass an explicit Settings instead.
    return Settings()
