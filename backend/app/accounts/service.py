"""Account policy between the HTTP routes, Google, and the account store.

The service owns the decisions that should not live in a route handler:

- validate the post-login path so a crafted `redirect_after` cannot leave the
  app,
- burn the OAuth state before the network call,
- reject an unverified Google email,
- put a single-use exchange code in the frontend redirect instead of a session
  token,
- create the session only when the SPA redeems that code.

The routes stay thin: they translate `AuthFlowError` into a JSON error or a
redirect with a stable reason.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from app.accounts.google import (
    GoogleAuthError,
    GoogleIdentityClient,
    code_challenge_for,
    new_code_verifier,
)
from app.accounts.models import UserRecord
from app.accounts.store import AccountStore
from app.auth import Principal
from app.config import Settings

logger = logging.getLogger("alexa.accounts")

HOUSE_NOTICE = "Your house resets after inactivity or a redeploy. Your account and sign-in stay."

# The state only lives for the trip through Google's consent screen. Ten minutes
# is long enough to sign in, short enough that abandoned rows do not accumulate.
OAUTH_STATE_TTL_SECONDS = 600
DEFAULT_REDIRECT_AFTER = "/house"

# A relative SPA route without a scheme or host. The frontend uses hash routing,
# so this value is the part after `#`: `/house`, `/console/audit`, and so on.
_REDIRECT_RE = re.compile(r"^/[A-Za-z0-9/?#=&._~%-]{0,199}$")


def normalize_redirect_after(raw: str | None) -> str:
    """Return an in-app path, defaulting rather than failing.

    A bad value should still let the user sign in; it must never become an open
    redirect after a successful consent. The silent fallback is deliberate.
    """
    if not raw:
        return DEFAULT_REDIRECT_AFTER
    value = raw.strip()
    # Accept the full hash form too, so a caller can pass `/#/house` without
    # producing `/#/#/house` after the callback composes the URL.
    if value.startswith("/#"):
        value = value[1:]
    if value.startswith("#/"):
        value = value[1:]
    if not value.startswith("/") or value.startswith("//"):
        return DEFAULT_REDIRECT_AFTER
    # Reject percent-encoding. The only encoded form that matters here is
    # `/%2F%2Fhost`, which some clients decode into `///host`; an in-app route
    # never needs it. This keeps the check closed even if the SPA later decodes
    # `next` once more before navigating.
    if "%" in value:
        return DEFAULT_REDIRECT_AFTER
    if "\\" in value or "\r" in value or "\n" in value or not _REDIRECT_RE.fullmatch(value):
        return DEFAULT_REDIRECT_AFTER
    return value


@dataclass(frozen=True)
class CompleteResult:
    """The one-time code and the safe path to resume after exchange."""

    code: str
    redirect_after: str


@dataclass(frozen=True)
class ExchangeResult:
    """A freshly created session token and the account it belongs to."""

    token: str
    expires_at: datetime
    user: UserRecord


class AuthFlowError(Exception):
    """A browser-auth outcome with a stable, lowercase reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthService:
    def __init__(
        self,
        settings: Settings,
        store: AccountStore,
        google: GoogleIdentityClient,
    ) -> None:
        self.settings = settings
        self.store = store
        self.google = google

    @property
    def google_enabled(self) -> bool:
        return self.settings.google_oauth_enabled

    @property
    def dev_login_enabled(self) -> bool:
        # A development shortcut must never be reachable from a public origin,
        # even if an environment flag is accidentally left on.
        return self.settings.auth_dev_login and self.settings.is_local

    def start(self, redirect_after: str | None) -> str:
        if not self.google_enabled:
            raise AuthFlowError("auth_unavailable", "Google sign-in is not configured on this server.")

        verifier = new_code_verifier()
        state = self.store.create_oauth_state(
            provider="google",
            code_verifier=verifier,
            redirect_after=normalize_redirect_after(redirect_after),
            ttl_seconds=OAUTH_STATE_TTL_SECONDS,
        )
        try:
            return self.google.authorization_url(
                state=state,
                code_challenge=code_challenge_for(verifier),
            )
        except GoogleAuthError as exc:
            logger.warning("google_authorize_failed", extra={"reason": exc.reason})
            raise AuthFlowError("auth_unavailable", "Google sign-in could not be started.") from exc

    def complete(self, *, state: str | None, code: str | None, error: str | None) -> CompleteResult:
        """Consume the callback, create the account, and return a handoff code.

        The state is consumed before Google is called. A failed exchange
        therefore cannot be replayed with the same callback URL.
        """
        if error:
            raise AuthFlowError("oauth_denied", "Google sign-in was cancelled.")
        if not state or not code:
            raise AuthFlowError("invalid_callback", "The sign-in callback is incomplete.")

        stored = self.store.consume_oauth_state(state, provider="google")
        if stored is None:
            raise AuthFlowError("invalid_state", "The sign-in request expired or was already used.")

        try:
            identity = self.google.exchange(code=code, code_verifier=stored.code_verifier)
        except GoogleAuthError as exc:
            if exc.reason == "email_unverified":
                raise AuthFlowError(
                    "email_unverified",
                    "Verify the email address with Google, then try again.",
                ) from exc
            if exc.reason == "not_configured":
                raise AuthFlowError("auth_unavailable", "Google sign-in is not configured on this server.") from exc
            # The reason is safe to log; the authorization code and provider
            # response are not in it.
            logger.warning("google_exchange_failed", extra={"reason": exc.reason})
            raise AuthFlowError("oauth_failed", "Google sign-in could not be completed.") from exc

        # The provider client already enforces this. Repeating the policy here
        # means an injected or future identity client cannot create an account
        # from an unverified address by accident.
        if not identity.email_verified:
            raise AuthFlowError(
                "email_unverified",
                "Verify the email address with Google, then try again.",
            )

        user = self.store.upsert_google_user(
            provider_account_id=identity.subject,
            email=identity.email,
            display_name=identity.display_name or identity.email.split("@", 1)[0],
            email_verified=identity.email_verified,
        )

        # Create the session now, but throw away its first token. The exchange
        # rotates the hash, so the raw bearer never exists until the SPA redeems
        # the code, and the code itself is never a bearer.
        session_id, _discarded, _ = self.store.create_session(
            user_id=user.id,
            ttl_seconds=self.settings.session_ttl_seconds,
        )
        raw_code = self.store.create_exchange_code(
            session_id=session_id,
            ttl_seconds=self.settings.exchange_code_ttl_seconds,
        )
        logger.info("account_login", extra={"subject": user.subject, "provider": "google"})
        return CompleteResult(code=raw_code, redirect_after=stored.redirect_after or DEFAULT_REDIRECT_AFTER)

    def exchange(self, code: str) -> ExchangeResult:
        if not code:
            raise AuthFlowError("invalid_exchange_code", "The sign-in code is missing.")
        session_id = self.store.consume_exchange_code(code)
        if session_id is None:
            raise AuthFlowError(
                "invalid_exchange_code",
                "The sign-in code is invalid, expired, or already used.",
            )
        rotated = self.store.rotate_session(
            session_id,
            ttl_seconds=self.settings.session_ttl_seconds,
        )
        if rotated is None:
            raise AuthFlowError("account_not_found", "The session is no longer usable. Start again.")
        token, expires_at, user = rotated
        logger.info("session_created", extra={"subject": user.subject})
        return ExchangeResult(token=token, expires_at=expires_at, user=user)

    def dev_login(self) -> ExchangeResult:
        if not self.dev_login_enabled:
            raise AuthFlowError("not_found", "Not found.")
        user = self.store.find_or_create_dev_user()
        _session_id, token, expires_at = self.store.create_session(
            user_id=user.id,
            ttl_seconds=self.settings.session_ttl_seconds,
        )
        logger.warning("dev_session_created", extra={"subject": user.subject})
        return ExchangeResult(token=token, expires_at=expires_at, user=user)

    def update_display_name(self, principal: Principal, display_name: str) -> UserRecord:
        if principal.auth_type != "session" or principal.user_id is None:
            raise AuthFlowError("session_required", "Changing a display name requires a signed-in browser session.")
        # The request model rejects an empty string, but a value made only of
        # whitespace would otherwise overwrite the name with blank space.
        cleaned = " ".join(display_name.split())
        if not cleaned:
            raise AuthFlowError("invalid_display_name", "Display name cannot be empty.")
        user = self.store.update_display_name(principal.user_id, cleaned[:80])
        logger.info("display_name_updated", extra={"subject": user.subject})
        return user

    def logout(self, principal: Principal) -> bool:
        if principal.auth_type != "session" or principal.session_id is None:
            # A static token cannot be revoked by the server. The caller should
            # still get a successful logout so the UI can clear its copy.
            return False
        revoked = self.store.revoke_session(principal.session_id)
        if revoked:
            logger.info("session_revoked", extra={"subject": principal.subject})
        return revoked

    def login_url(
        self,
        *,
        code: str | None = None,
        next_path: str | None = None,
        error: str | None = None,
    ) -> str:
        base = self.settings.frontend_origin
        if error:
            return f"{base}/#/login?{urlencode({'error': error})}"
        query = urlencode(
            {
                "code": code or "",
                "next": normalize_redirect_after(next_path),
            }
        )
        return f"{base}/#/auth/callback?{query}"


__all__ = [
    "DEFAULT_REDIRECT_AFTER",
    "HOUSE_NOTICE",
    "OAUTH_STATE_TTL_SECONDS",
    "AuthFlowError",
    "AuthService",
    "CompleteResult",
    "ExchangeResult",
    "normalize_redirect_after",
]
