"""Session-token verification for the console and MCP.

The static token table is checked first, so the inspector and the CLI never pay
for a database round trip. A browser session token is an opaque random string;
the store looks it up by hash and returns the account it belongs to. The store
call runs in a threadpool because the driver is synchronous and both the REST and
MCP paths are async.
"""

from __future__ import annotations

from collections.abc import Iterable

from mcp.server.auth.provider import AccessToken, TokenVerifier
from starlette.concurrency import run_in_threadpool

from app.accounts.store import AccountStore
from app.auth import StaticTokenVerifier


class SessionTokenVerifier(TokenVerifier):
    def __init__(self, static: StaticTokenVerifier, store: AccountStore, scopes: Iterable[str]) -> None:
        self._static = static
        self._store = store
        self._scopes = tuple(scopes)

    async def verify_token(self, token: str) -> AccessToken | None:
        access = await self._static.verify_token(token)
        if access is not None:
            return access

        session = await run_in_threadpool(self._store.resolve_session, token)
        if session is None:
            return None
        user = session.user
        return AccessToken(
            token=token,
            client_id="alexa-console",
            scopes=list(self._scopes),
            expires_at=int(session.expires_at.timestamp()),
            subject=user.subject,
            claims={
                "auth_type": "session",
                "user_id": user.id,
                "session_id": session.session_id,
                "email": user.email,
                "display_name": user.display_name,
                "provider": user.provider,
                "email_verified": user.email_verified,
            },
        )


def build_session_verifier(
    static: StaticTokenVerifier,
    store: AccountStore,
    scopes: Iterable[str],
) -> SessionTokenVerifier:
    return SessionTokenVerifier(static, store, scopes)


__all__ = ["SessionTokenVerifier", "build_session_verifier"]
