"""FastAPI app: MCP Streamable HTTP at /mcp, operator REST API at /api."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.accounts.google import GoogleIdentityClient, GoogleOAuthClient
from app.accounts.service import AuthService
from app.accounts.store import AccountStore
from app.accounts.verifier import build_session_verifier
from app.api import (
    build_assistant_router,
    build_auth_router,
    build_call_router,
    build_journeys_router,
    build_meta_router,
    build_privacy_router,
    build_state_router,
    build_voice_router,
)
from app.assistant.service import AssistantService
from app.auth import Principal, build_rest_auth, build_verifier
from app.config import Settings, get_settings, startup_warnings
from app.logging_config import setup_logging
from app.mcp_server import build_mcp_server
from app.router import Router
from app.rules import RULES
from app.state import AppState
from app.tools import REGISTRY, SCOPES, TOOLS, manifests
from app.trace import TraceBuffer
from app.voice.elevenlabs import ElevenLabsVoice


def _transport_security(settings: Settings) -> TransportSecuritySettings:
    # Host header allow list for the MCP transport. The SDK's middleware has no
    # "*" wildcard, so a wildcard means disabling the guard. A real deployment
    # should set the App Runner hostname and leave protection on.
    hosts = settings.allowed_host_list
    if "*" in hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[settings.public_url.rstrip("/"), *settings.cors_origin_list],
    )


def create_app(settings: Settings | None = None, google: GoogleIdentityClient | None = None) -> FastAPI:
    """Build a fresh app and its runtime state.

    Tests call this with explicit settings so tokens and URLs do not leak
    between cases. Production uses the module-level `app` below.

    `google` is injectable so the auth suite can exercise the callback without
    network access or a real Google project.
    """
    settings = settings or get_settings()
    # A tool without a rule, or a rule without a tool, is a configuration bug.
    # Fail at startup, not on the first voice request.
    RULES.check_tools(TOOLS)
    # Accounts and sessions are persistent. The house, audit, and trace below are
    # not: a redeploy signs nobody out but resets the house.
    accounts = AccountStore(settings.database_url)
    auth_service = AuthService(settings, accounts, google or GoogleOAuthClient(settings))
    verifier = build_session_verifier(build_verifier(settings), accounts, SCOPES)
    # One state object per app. Adapters and the trace buffer live here, so a
    # test app never shares timers or lights with the running server.
    state = AppState(settings=settings, trace=TraceBuffer(settings.trace_capacity))
    router = Router(state)
    # The assistant is a client of the router, not a second execution path.
    # It owns the parser and the pending confirmation, and every action still
    # goes through Router.execute.
    assistant = AssistantService(router)
    # The voice client is per app so tests can inject a transport and the cache
    # cannot leak between two app instances.
    voice = ElevenLabsVoice(settings)
    mcp = build_mcp_server(settings, router, verifier)

    # Mount the MCP app at the root and let it own /mcp. Older Starlette versions
    # rewrote the path when mounting at /mcp, so an inner route of "/" produced a
    # 307 to /mcp/. Starlette 1.x keeps the full path, and that redirect breaks
    # MCP clients. Mounting at "/" with the MCP route at "/mcp" avoids it.
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=_transport_security(settings),
        host="0.0.0.0",
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        setup_logging(settings.log_level)
        # The store creates its four tables in __init__. A real service would
        # run Alembic migrations before the new process takes traffic; until
        # then, adding a column means recreating the account tables.
        await run_in_threadpool(accounts.prune)
        # Public deployments fail closed only for config that is definitely
        # wrong. These warnings cover config that is valid but unsafe, so the
        # first log lines tell a deployer what to change.
        startup_logger = logging.getLogger("alexa.startup")
        for message in startup_warnings(settings):
            startup_logger.warning("startup_warning", extra={"detail": message})
        # A mounted app's lifespan does not run automatically, and the streamable
        # session manager needs it. Start it here so sessions have a manager.
        try:
            async with mcp_app.router.lifespan_context(mcp_app):
                # A redeploy clears the containers. Say so once, in the log, with
                # the number of seeded rows the console will show.
                marker = state.audit.seed_marker
                if marker:
                    startup_logger.info("audit_seeded", extra=marker)
                yield
        finally:
            accounts.close()

    app = FastAPI(
        title="Alexa",
        version=__version__,
        description="Deterministic rules and audit layer for Alexa+.",
        lifespan=lifespan,
    )
    # Exposed for tests and for future console handlers that need runtime state.
    app.state.alexa = state
    app.state.assistant = assistant
    app.state.voice = voice
    app.state.accounts = accounts
    app.state.auth = auth_service

    # The console runs on a different origin in development (Vite) and in
    # production (Vercel). Auth is a bearer header, not a cookie, so credentials
    # stay off. The browser still sends a preflight for Authorization, which the
    # explicit header list answers without opening the endpoint to any header.
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )

    # RFC 9728 metadata must live at the origin root, not under /mcp. Register it
    # before the catch-all mount below so this path wins over the MCP app.
    for route in create_protected_resource_routes(
        resource_url=AnyHttpUrl(settings.resource_server_url),
        authorization_servers=[AnyHttpUrl(settings.public_url)],
        scopes_supported=SCOPES,
        resource_name="Alexa MCP",
    ):
        app.router.routes.append(route)

    # The console API uses the same verifier as MCP, so one token works on both
    # surfaces and scope changes cannot drift between them.
    require_principal = build_rest_auth(verifier, settings)

    @app.get("/", tags=["ops"])
    async def root() -> dict:
        return {
            "name": "Alexa",
            "version": __version__,
            "mcp": "/mcp",
            "health": "/health",
            "docs": "/docs",
        }

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        # Unauthenticated on purpose: App Runner's health check has no token.
        return {
            "status": "ok",
            "service": "alexa",
            "version": __version__,
            "rules_version": RULES.version,
            "tools": len(REGISTRY),
            "audit_rows": len(state.audit),
            # Present after startup seeding. A reset then reads as intentional
            # instead of looking like lost data.
            "audit_seeded": state.audit.seed_marker is not None,
        }

    @app.get("/api/whoami", tags=["console"])
    async def whoami(principal: Principal = Depends(require_principal)) -> dict:
        # Debugging aid for the console and the Alexa+ connection. Profile fields
        # are null for a static token and populated for a Google session.
        return {
            "subject": principal.subject,
            "client_id": principal.client_id,
            "scopes": list(principal.scopes),
            "email": principal.email,
            "display_name": principal.display_name,
            "provider": principal.provider,
            "user_id": principal.user_id,
            "auth_type": principal.auth_type,
            "session_expires_at": principal.session_expires_at,
        }

    @app.get("/api/tools", tags=["console"])
    async def list_tools(_: Principal = Depends(require_principal)) -> dict:
        # Manifests only, never handlers. The console renders risk, scopes, and
        # bounds from this payload. The rules version is part of the response so
        # reviewers can see which rule set approved an action.
        return {
            "rules_version": RULES.version,
            "confirmation_ttl_seconds": RULES.confirmation.ttl_seconds,
            "tools": manifests(),
        }

    @app.get("/api/trace", tags=["console"])
    async def get_trace(
        limit: int = Query(default=50, ge=1, le=200),
        _: Principal = Depends(require_principal),
    ) -> dict:
        # snapshot() is newest first, which is the order the console expects.
        return {"entries": [event.model_dump(mode="json") for event in state.trace.snapshot()[:limit]]}

    @app.get("/api/audit", tags=["console"])
    async def get_audit(
        limit: int = Query(default=50, ge=1, le=200),
        principal: Principal = Depends(require_principal),
    ) -> dict:
        # The chain is global, but a caller only sees their own rows. The seed
        # marker is shared metadata, not another user's data.
        rows = [row for row in state.audit.snapshot() if row.subject == principal.subject and not row.tombstone]
        return {
            "seeded": state.audit.seed_marker,
            "entries": [row.model_dump(mode="json") for row in rows[:limit]],
        }

    @app.get("/api/audit/verify", tags=["console"])
    async def verify_audit(_: Principal = Depends(require_principal)) -> dict:
        # Counts and the first broken id only. Verifying the chain is a global
        # safety property; reading other subjects' rows is not part of it.
        return state.audit.verify().model_dump(mode="json")

    # The console, assistant, voice, and journey routes are built in app/api/ so
    # each domain owns its request models and its comments. They all resolve the
    # caller from the same verifier, and every write funnels through the router.
    for api_router in (
        build_meta_router(state, settings),
        build_auth_router(settings, auth_service, require_principal),
        build_state_router(state, assistant, require_principal),
        build_privacy_router(state, router, require_principal),
        build_call_router(router, require_principal),
        build_assistant_router(assistant, require_principal),
        build_voice_router(settings, state, voice, require_principal),
        build_journeys_router(settings, require_principal),
    ):
        app.include_router(api_router)

    # Mounted last so it only sees paths no other route claimed. This keeps
    # /health, /api, /docs, and the metadata route outside the MCP session code.
    app.mount("/", mcp_app)

    return app


app = create_app()
