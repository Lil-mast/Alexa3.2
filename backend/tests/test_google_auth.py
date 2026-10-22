"""End-to-end tests for Google identity, persisted sessions, and CORS.

The Google transport is mocked, so these tests exercise the real routes, state
handling, PKCE challenge, exchange code, session verifier, and audit subject
without a network call or a real Google project. The store is in memory per app
unless a test explicitly uses a file URL to prove persistence.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.accounts import store as account_store
from app.accounts.google import GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL, GoogleOAuthClient
from app.config import Settings
from app.main import create_app
from tests.conftest import TEST_TOKEN, make_settings


def _settings(public_url: str = "http://localhost:8000", *, database_url: str = "sqlite://") -> Settings:
    return make_settings(public_url).model_copy(
        update={
            "google_client_id": "google-client",
            "google_client_secret": "google-secret",
            "oauth_redirect_uri": f"{public_url}/api/auth/callback/google",
            "database_url": database_url,
            "auth_dev_login": True,
        }
    )


class FakeGoogle:
    """A real GoogleOAuthClient with a mocked transport and a mutable profile."""

    def __init__(self, settings: Settings, profile: dict | None = None) -> None:
        self.profile = profile or {
            "sub": "google-sub-1",
            "email": "ada@example.com",
            "email_verified": True,
            "name": "Ada Lovelace",
        }
        self.client = GoogleOAuthClient(settings, transport=httpx2.MockTransport(self._handle))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == GOOGLE_TOKEN_URL:
            return httpx2.Response(200, json={"access_token": "provider-access-token"})
        if str(request.url) == GOOGLE_USERINFO_URL:
            return httpx2.Response(200, json=self.profile)
        return httpx2.Response(404, json={"error": "unexpected_url"})


def _app(profile: dict | None = None, *, public_url: str = "http://localhost:8000", database_url: str = "sqlite://"):
    settings = _settings(public_url, database_url=database_url)
    google = FakeGoogle(settings, profile)
    return create_app(settings, google=google.client), google


def _start(client: TestClient, redirect_after: str = "/console") -> dict[str, list[str]]:
    response = client.get(
        f"/api/auth/google/start?redirect_after={redirect_after}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    query = parse_qs(urlparse(location).query)
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]
    assert query["redirect_uri"] == ["http://localhost:8000/api/auth/callback/google"]
    return query


def _callback(client: TestClient, state: str, code: str = "provider-code") -> str:
    response = client.get(
        f"/api/auth/callback/google?state={state}&code={code}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    return response.headers["location"]


def _exchange_code(location: str) -> str:
    fragment = urlparse(location).fragment
    assert fragment.startswith("/auth/callback?")
    return parse_qs(fragment.split("?", 1)[1])["code"][0]


def _login(client: TestClient, google: FakeGoogle) -> tuple[str, dict]:
    query = _start(client)
    location = _callback(client, query["state"][0])
    assert location.startswith("http://localhost:5173/#/auth/callback?")
    code = _exchange_code(location)
    response = client.post("/api/auth/exchange", json={"code": code})
    assert response.status_code == 200
    payload = response.json()
    return payload["token"], payload["user"]


def test_auth_config_is_public_and_reports_google(client):
    response = client.get("/api/auth/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["provider"] == "google"
    assert payload["login_url"] == "/api/auth/google/start"
    assert payload["frontend_url"] == "http://localhost:5173"
    assert payload["session_ttl_seconds"] == 604800
    assert payload["dev_login"] is True


def test_google_login_creates_a_user_and_a_session():
    app, google = _app()
    with TestClient(app) as client:
        token, user = _login(client, google)

    assert token.startswith("sess_")
    assert user["subject"].startswith("user_")
    assert user["email"] == "ada@example.com"
    assert user["provider"] == "google"


def test_session_token_works_on_me_whoami_and_a_tool():
    app, google = _app()
    with TestClient(app) as client:
        token, user = _login(client, google)
        auth = {"Authorization": f"Bearer {token}"}

        me = client.get("/api/auth/me", headers=auth)
        assert me.status_code == 200
        assert me.json()["auth_type"] == "session"
        assert me.json()["user"]["subject"] == user["subject"]

        whoami = client.get("/api/whoami", headers=auth)
        assert whoami.status_code == 200
        assert whoami.json()["subject"] == user["subject"]
        assert whoami.json()["email"] == "ada@example.com"

        call = client.post(
            "/api/call/timer_set",
            json={"params": {"duration_seconds": 60}},
            headers=auth,
        )
        assert call.status_code == 200
        assert call.json()["status"] == "ok"

        # The audit row uses the pseudonymous subject, never the Google id or
        # the email. This is the key the rest of the app already uses.
        audit = client.get("/api/audit", headers=auth)
        assert audit.status_code == 200
        assert audit.json()["entries"][0]["subject"] == user["subject"]


def test_email_is_refreshed_but_google_sub_is_the_identity():
    app, google = _app()
    with TestClient(app) as client:
        first_token, first_user = _login(client, google)
        google.profile["email"] = "ada.new@example.com"
        second_token, second_user = _login(client, google)

    assert first_token != second_token
    assert first_user["subject"] == second_user["subject"]
    assert second_user["email"] == "ada.new@example.com"


def test_exchange_code_is_single_use():
    app, _google = _app()
    with TestClient(app) as client:
        query = _start(client)
        location = _callback(client, query["state"][0])
        code = _exchange_code(location)

        first = client.post("/api/auth/exchange", json={"code": code})
        assert first.status_code == 200

        second = client.post("/api/auth/exchange", json={"code": code})
        assert second.status_code == 400
        assert second.json()["detail"]["code"] == "INVALID_EXCHANGE_CODE"


def test_logout_revokes_the_session():
    app, google = _app()
    with TestClient(app) as client:
        token, _ = _login(client, google)
        auth = {"Authorization": f"Bearer {token}"}

        logout = client.post("/api/auth/logout", headers=auth)
        assert logout.status_code == 204

        assert client.get("/api/auth/me", headers=auth).status_code == 401


def test_unverified_google_email_redirects_with_a_reason():
    app, _google = _app({"sub": "google-sub-2", "email": "unverified@example.com", "email_verified": False})
    with TestClient(app) as client:
        query = _start(client)
        location = _callback(client, query["state"][0])

    assert location == "http://localhost:5173/#/login?error=email_unverified"


def test_oauth_denied_and_state_replay_redirect_with_reasons():
    app, _google = _app()
    with TestClient(app) as client:
        denied = client.get(
            "/api/auth/callback/google?error=access_denied",
            follow_redirects=False,
        )
        assert denied.headers["location"] == "http://localhost:5173/#/login?error=oauth_denied"

        query = _start(client)
        _callback(client, query["state"][0])
        replay = client.get(
            f"/api/auth/callback/google?state={query['state'][0]}&code=another-code",
            follow_redirects=False,
        )
        assert replay.headers["location"] == "http://localhost:5173/#/login?error=invalid_state"


def test_expired_session_is_rejected():
    app, google = _app()
    with TestClient(app) as client:
        _, user = _login(client, google)
        store = app.state.accounts
        _session_id, expired_token, _ = store.create_session(user_id=user["id"], ttl_seconds=-1)

        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401


def test_sessions_survive_a_new_app_against_the_same_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'accounts.db'}"
    first_app, google = _app(database_url=database_url)
    with TestClient(first_app) as client:
        token, user = _login(client, google)

    second_app, _ = _app(database_url=database_url)
    with TestClient(second_app) as client:
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["user"]["subject"] == user["subject"]


def test_dev_login_is_local_only():
    app, _ = _app()
    with TestClient(app) as client:
        response = client.post("/api/auth/dev-login")
        assert response.status_code == 200
        assert response.json()["token"].startswith("sess_")

    public_app, _ = _app(public_url="https://alexa-api.onrender.com")
    with TestClient(public_app) as client:
        response = client.post("/api/auth/dev-login")
        assert response.status_code == 404


@pytest.mark.parametrize("origin", ["https://alexa.vercel.app", "http://localhost:5173"])
def test_cors_preflight_allows_authorization_without_credentials(client, origin):
    response = client.options(
        "/api/auth/config",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


def test_disabled_google_reports_no_login_url_and_returns_503():
    settings = make_settings().model_copy(
        update={
            "google_client_id": None,
            "google_client_secret": None,
            "auth_dev_login": False,
        }
    )
    app = create_app(settings)
    with TestClient(app) as client:
        config = client.get("/api/auth/config")
        assert config.status_code == 200
        assert config.json()["enabled"] is False
        assert config.json()["login_url"] is None

        start = client.get("/api/auth/google/start", follow_redirects=False)
        assert start.status_code == 503
        assert start.json()["detail"]["code"] == "AUTH_UNAVAILABLE"


def test_exchange_code_expires(monkeypatch):
    app, _google = _app()
    with TestClient(app) as client:
        query = _start(client)
        location = _callback(client, query["state"][0])
        code = _exchange_code(location)

        real_utcnow = account_store.utcnow
        monkeypatch.setattr(
            account_store,
            "utcnow",
            lambda: real_utcnow() + timedelta(seconds=120),
        )
        response = client.post("/api/auth/exchange", json={"code": code})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_EXCHANGE_CODE"


def test_display_name_update_and_static_token_cannot_edit():
    app, google = _app()
    with TestClient(app) as client:
        token, _ = _login(client, google)
        auth = {"Authorization": f"Bearer {token}"}

        updated = client.patch(
            "/api/auth/me",
            json={"display_name": "  Ada   Byron  "},
            headers=auth,
        )
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "Ada Byron"

        me = client.get("/api/auth/me", headers=auth)
        assert me.json()["user"]["display_name"] == "Ada Byron"

        blank = client.patch(
            "/api/auth/me",
            json={"display_name": "   "},
            headers=auth,
        )
        assert blank.status_code == 400
        assert blank.json()["detail"]["code"] == "INVALID_DISPLAY_NAME"

        static = client.patch(
            "/api/auth/me",
            json={"display_name": "Not allowed"},
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert static.status_code == 403
        assert static.json()["detail"]["code"] == "SESSION_REQUIRED"


def test_redirect_after_cannot_leave_the_frontend():
    app, _google = _app()
    with TestClient(app) as client:
        for target in (
            "https://example.com/steal",
            "//evil.example",
            # Double-encoded so FastAPI decodes one layer and the service still
            # sees the percent escape rather than a plain `///host` path.
            "/%252F%252Fevil.example",
        ):
            query = _start(client, redirect_after=target)
            location = _callback(client, query["state"][0])
            fragment = urlparse(location).fragment
            params = parse_qs(fragment.split("?", 1)[1])
            assert params["next"] == ["/house"]


def test_two_google_accounts_are_isolated():
    app, google = _app()
    with TestClient(app) as client:
        token_a, user_a = _login(client, google)
        google.profile = {
            "sub": "google-sub-2",
            "email": "grace@example.com",
            "email_verified": True,
            "name": "Grace Hopper",
        }
        token_b, user_b = _login(client, google)

        assert user_a["subject"] != user_b["subject"]
        me_a = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        me_b = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_b}"})

    assert me_a.json()["user"]["email"] == "ada@example.com"
    assert me_b.json()["user"]["email"] == "grace@example.com"
    assert me_a.json()["user"]["subject"] != me_b.json()["user"]["subject"]
