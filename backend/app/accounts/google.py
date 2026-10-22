"""Google OAuth 2.0 authorization-code flow with PKCE.

The browser is redirected to Google, Google redirects back to the API, and the
server makes exactly two upstream calls: exchange the authorization code, then
read the OpenID userinfo. The provider access token stays in this function and is
never stored. No refresh token is requested.

`GoogleIdentityClient` is a small protocol so the auth tests can inject a fake
without network access, while production uses `GoogleOAuthClient`.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx2

from app.config import Settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class GoogleIdentity:
    """The only Google profile fields this server keeps.

    `subject` is Google's stable `sub`. The email is descriptive and may change,
    so it is never the account lookup key.
    """

    subject: str
    email: str
    display_name: str | None
    email_verified: bool


class GoogleAuthError(Exception):
    """A provider failure with a short, non-secret reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GoogleIdentityClient(Protocol):
    """The seam used by `AuthService` and by the test suite."""

    def authorization_url(self, *, state: str, code_challenge: str) -> str: ...

    def exchange(self, *, code: str, code_verifier: str) -> GoogleIdentity: ...


def new_code_verifier() -> str:
    # RFC 7636 allows 43 to 128 characters. token_urlsafe(64) yields 86.
    return secrets.token_urlsafe(64)


def code_challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verified(raw: object) -> bool:
    # Google returns a JSON boolean. Accepting the string form keeps a mocked or
    # slightly different OIDC response from silently becoming a verified user.
    return raw is True or (isinstance(raw, str) and raw.lower() == "true")


def _display_name(raw: object, *, email: str) -> str:
    candidate = str(raw).strip() if raw is not None else ""
    if not candidate:
        candidate = email.split("@", 1)[0]
    # Collapse whitespace and cap the value at the column limit. React escapes
    # text, but the header should not be pushed out of shape by a 10 KB name.
    candidate = " ".join(candidate.split())
    return (candidate or "Demo user")[:80]


class GoogleOAuthClient:
    """Synchronous Google client used by the threadpool auth routes."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return self._settings.google_oauth_enabled

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        if not self.enabled:
            raise GoogleAuthError("not_configured")
        query = urlencode(
            {
                "client_id": self._settings.google_client_id,
                "redirect_uri": self._settings.resolved_oauth_redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                # Online access is enough for one profile read. Offline access
                # would create a refresh token this server does not want.
                "access_type": "online",
                "prompt": "select_account",
            }
        )
        return f"{GOOGLE_AUTH_URL}?{query}"

    def exchange(self, *, code: str, code_verifier: str) -> GoogleIdentity:
        if not self.enabled:
            raise GoogleAuthError("not_configured")

        try:
            with httpx2.Client(timeout=GOOGLE_TIMEOUT_SECONDS, transport=self._transport) as client:
                token_response = client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": self._settings.google_client_id,
                        "client_secret": self._settings.google_client_secret,
                        "redirect_uri": self._settings.resolved_oauth_redirect_uri,
                        "grant_type": "authorization_code",
                        "code_verifier": code_verifier,
                    },
                    headers={"Accept": "application/json"},
                )
                if token_response.status_code != 200:
                    # Do not include the body: it can echo the authorization
                    # code or a provider error detail.
                    raise GoogleAuthError(f"token_status_{token_response.status_code}")

                token_payload = token_response.json()
                access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
                if not isinstance(access_token, str) or not access_token:
                    raise GoogleAuthError("missing_access_token")

                profile_response = client.get(
                    GOOGLE_USERINFO_URL,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )
                if profile_response.status_code != 200:
                    raise GoogleAuthError(f"userinfo_status_{profile_response.status_code}")
                profile = profile_response.json()
        except httpx2.TimeoutException as exc:
            raise GoogleAuthError("timeout") from exc
        except httpx2.HTTPError as exc:
            raise GoogleAuthError("upstream_unreachable") from exc
        except ValueError as exc:
            # A non-JSON body from either endpoint. The body is not logged.
            raise GoogleAuthError("invalid_provider_response") from exc

        if not isinstance(profile, dict):
            raise GoogleAuthError("invalid_provider_response")

        subject = profile.get("sub")
        email = profile.get("email")
        if not isinstance(subject, str) or not subject.strip():
            raise GoogleAuthError("missing_subject")
        if not isinstance(email, str) or "@" not in email:
            raise GoogleAuthError("missing_email")
        normalized_email = email.strip().lower()
        if not _verified(profile.get("email_verified")):
            raise GoogleAuthError("email_unverified")

        return GoogleIdentity(
            subject=subject.strip(),
            email=normalized_email,
            display_name=_display_name(profile.get("name"), email=normalized_email),
            email_verified=True,
        )


__all__ = [
    "GOOGLE_AUTH_URL",
    "GOOGLE_TIMEOUT_SECONDS",
    "GOOGLE_TOKEN_URL",
    "GOOGLE_USERINFO_URL",
    "GoogleAuthError",
    "GoogleIdentity",
    "GoogleIdentityClient",
    "GoogleOAuthClient",
    "code_challenge_for",
    "new_code_verifier",
]
