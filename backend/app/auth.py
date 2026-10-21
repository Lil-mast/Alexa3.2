"""Bearer authentication shared by the MCP endpoint and the REST console API.

Production would use an OAuth 2.1 authorization server. For the hackathon the
server is a resource server with a static token table: each token maps to a
subject and the scopes granted to that subject. The MCP SDK's bearer middleware
returns the standard 401 with a `WWW-Authenticate` challenge and resource
metadata, and every tool re-checks its own scopes before it runs.
"""

from __future__ import annotations

import hmac
import json
import time
from dataclasses import dataclass

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

    `subject` is the pseudonymous household/user key. Device adapters and,
    later, the audit log use it to keep one user's data separate from another's.
    """

    subject: str
    client_id: str
    scopes: tuple[str, ...]


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


def principal_from_access_token(access: AccessToken) -> Principal:
    return Principal(
        subject=access.subject or access.client_id,
        client_id=access.client_id,
        scopes=tuple(access.scopes),
    )


def www_authenticate(settings: Settings, *, error: str = "invalid_token") -> str:
    # The MCP SDK sends this same challenge. Reusing it for the console API keeps
    # both surfaces telling clients where the resource metadata lives.
    metadata_url = build_resource_metadata_url(AnyHttpUrl(settings.resource_server_url))
    return (
        f'Bearer realm="alexa", error="{error}", '
        f'error_description="Authentication required", resource_metadata="{metadata_url}"'
    )


def build_rest_auth(verifier: StaticTokenVerifier, settings: Settings):
    """FastAPI dependency for the operator console API."""

    async def require_principal(request: Request) -> Principal:
        # The header is the only accepted source. No query-string tokens, because
        # those end up in access logs and browser history.
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        access = None
        if scheme.lower() == "bearer" and token:
            access = await verifier.verify_token(token.strip())
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
