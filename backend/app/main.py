"""FastAPI app: MCP Streamable HTTP at /mcp, operator REST API at /api."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from app import __version__
from app.auth import Principal, build_rest_auth, build_verifier
from app.config import Settings, get_settings, startup_warnings
from app.logging_config import setup_logging
from app.mcp_server import build_mcp_server
from app.router import Router
from app.rules import RULES
from app.state import AppState
from app.tools import REGISTRY, SCOPES, TOOLS, manifests
from app.trace import TraceBuffer


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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fresh app and its runtime state.

    Tests call this with explicit settings so tokens and URLs do not leak
    between cases. Production uses the module-level `app` below.
    """
    settings = settings or get_settings()
    # A tool without a rule, or a rule without a tool, is a configuration bug.
    # Fail at startup, not on the first voice request.
    RULES.check_tools(TOOLS)
    verifier = build_verifier(settings)
    # One state object per app. Adapters and the trace buffer live here, so a
    # test app never shares timers or lights with the running server.
    state = AppState(settings=settings, trace=TraceBuffer(settings.trace_capacity))
    router = Router(state)
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
        # Public deployments fail closed only for config that is definitely
        # wrong. These warnings cover config that is valid but unsafe, so the
        # first log lines tell a deployer what to change.
        startup_logger = logging.getLogger("alexa.startup")
        for message in startup_warnings(settings):
            startup_logger.warning("startup_warning", extra={"detail": message})
        # A mounted app's lifespan does not run automatically, and the streamable
        # session manager needs it. Start it here so sessions have a manager.
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(
        title="Alexa",
        version=__version__,
        description="Deterministic rules and audit layer for Alexa+.",
        lifespan=lifespan,
    )
    # Exposed for tests and for future console handlers that need runtime state.
    app.state.alexa = state

    # The console is a separate dev origin. Credentials are off because auth is
    # a bearer header, not a cookie.
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
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
        }

    @app.get("/api/whoami", tags=["console"])
    async def whoami(principal: Principal = Depends(require_principal)) -> dict:
        # Debugging aid for the console and the Alexa+ connection.
        return {"subject": principal.subject, "client_id": principal.client_id, "scopes": list(principal.scopes)}

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

    # Mounted last so it only sees paths no other route claimed. This keeps
    # /health, /api, /docs, and the metadata route outside the MCP session code.
    app.mount("/", mcp_app)

    return app


app = create_app()
