"""Bearer authentication shared by the MCP endpoint and the REST console API.

Two kinds of bearer token are accepted. A static token from
`ALEXA_TOKENS_JSON` is the inspector, CLI, and Alexa+ path. A Google account
session is an opaque random token stored only as a hash in Postgres or SQLite.
Both resolve to the same `Principal`, so the router, audit, and trace never need
to know which one the caller used.

The MCP SDK's bearer middleware returns the standard 401 with a
`WWW-Authenticate` challenge and resource metadata, and every tool re-checks its
own scopes before it runs.
"""

from __future__ import annotations

import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, Request, status
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url
from pydantic import AnyHttpUrl, BaseModel, ValidationError

from app.config import AMAZON_ID, Settings


class TokenRecord(BaseModel):
    subject: str
    client_id: str = "alexa-client"
    scopes: list[str] = []
    # Unix seconds. None means the token does not expire.
    expires_at: int | None = None


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. Never log the token itself.

    `subject` is the pseudonymous household/user key. Device adapters and the
    audit log use it to keep one user's data separate from another's. A Google
    session also carries its account and session ids, but `subject` is still the
    only key the rest of the app uses.
    """

    subject: str
    client_id: str
    scopes: tuple[str, ...]
    auth_type: Literal["session", "token"] = "token"
    user_id: int | None = None
    session_id: int | None = None
    session_expires_at: datetime | None = None
    email: str | None = None
    display_name: str | None = None
    provider: str | None = None
    email_verified: bool = False


def parse_tokens(raw: str) -> dict[str, TokenRecord]:
    # Fail at startup, not on the first request: a malformed table would
    # otherwise look like an auth outage in the middle of a demo.
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("ALEXA_TOKENS_JSON is not valid JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError("ALEXA_TOKENS_JSON must be a non-empty object mapping token to record")
    try:
        tokens = {token: TokenRecord.model_validate(record) for token, record in payload.items()}
    except ValidationError as exc:
        raise ValueError(f"ALEXA_TOKENS_JSON has an invalid record: {exc}") from exc
    # The subject is the only stable user key the server stores, logs, and later
    # audits. A raw Alexa id there would spread throughout the trace and the
    # audit chain, so refuse it at the boundary and ask for a pseudonym instead.
    for record in tokens.values():
        if not record.subject.strip():
            raise ValueError("ALEXA_TOKENS_JSON records need a non-empty subject")
        if AMAZON_ID.match(record.subject):
            raise ValueError(
                "ALEXA_TOKENS_JSON subject must be a pseudonym, not a raw Alexa id. "
                "Hash the Alexa id before putting it in the token table."
            )
    return tokens


class StaticTokenVerifier(TokenVerifier):
    """Constant-time lookup over a static token table."""

    def __init__(self, tokens: dict[str, TokenRecord]) -> None:
        if not tokens:
            raise ValueError("At least one bearer token must be configured")
        self._tokens = tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        # Compare against every entry with compare_digest. A dict lookup would
        # exit early on a miss and leak which prefix was close. The table is tiny,
        # so the linear scan costs nothing.
        for candidate, record in self._tokens.items():
            if hmac.compare_digest(candidate, token):
                if record.expires_at is not None and record.expires_at < int(time.time()):
                    return None
                return AccessToken(
                    token=token,
                    client_id=record.client_id,
                    scopes=record.scopes,
                    expires_at=record.expires_at,
                    subject=record.subject,
                )
        return None


def build_verifier(settings: Settings) -> StaticTokenVerifier:
    return StaticTokenVerifier(parse_tokens(settings.tokens_json))


def _claim_str(claims: dict | None, key: str) -> str | None:
    value = (claims or {}).get(key)
    return value if isinstance(value, str) else None


def _claim_int(claims: dict | None, key: str) -> int | None:
    value = (claims or {}).get(key)
    return value if isinstance(value, int) else None


def _claim_bool(claims: dict | None, key: str) -> bool:
    return (claims or {}).get(key) is True


def principal_from_access_token(access: AccessToken) -> Principal:
    claims = access.claims or {}
    auth_type = claims.get("auth_type")
    if auth_type not in {"session", "token"}:
        auth_type = "token"
    session_expires_at = None
    if auth_type == "session" and access.expires_at is not None:
        session_expires_at = datetime.fromtimestamp(access.expires_at, UTC)
    return Principal(
        subject=access.subject or access.client_id,
        client_id=access.client_id,
        scopes=tuple(access.scopes),
        auth_type=auth_type,
        user_id=_claim_int(claims, "user_id"),
        session_id=_claim_int(claims, "session_id"),
        session_expires_at=session_expires_at,
        email=_claim_str(claims, "email"),
        display_name=_claim_str(claims, "display_name"),
        provider=_claim_str(claims, "provider"),
        email_verified=_claim_bool(claims, "email_verified"),
    )


def www_authenticate(settings: Settings, *, error: str = "invalid_token") -> str:
    # The MCP SDK sends this same challenge. Reusing it for the console API keeps
    # both surfaces telling clients where the resource metadata lives.
    metadata_url = build_resource_metadata_url(AnyHttpUrl(settings.resource_server_url))
    return (
        f'Bearer realm="alexa", error="{error}", '
        f'error_description="Authentication required", resource_metadata="{metadata_url}"'
    )


def bearer_token(request: Request) -> str | None:
    """The only accepted source of a bearer token. No query strings."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def build_rest_auth(verifier: TokenVerifier, settings: Settings):
    """FastAPI dependency for the operator console API."""

    async def require_principal(request: Request) -> Principal:
        token = bearer_token(request)
        access = await verifier.verify_token(token) if token else None
        if access is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "AUTH_REQUIRED",
                    "message": "A valid bearer token is required.",
                    "follow_up": "Prompt the user to authorize or reconnect.",
                },
                headers={"WWW-Authenticate": www_authenticate(settings)},
            )
        return principal_from_access_token(access)

    return require_principal
