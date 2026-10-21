"""MCP server wiring. Tools are thin wrappers over `Router.execute` so MCP and
REST/tests share one decision path.
"""

from __future__ import annotations

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl

from app import __version__
from app.auth import Principal, StaticTokenVerifier, principal_from_access_token
from app.config import Settings
from app.models import ToolResponse
from app.router import Router
from app.tools import booking, lights, thermostat, timers
from app.tools.specs import ToolSpec

# Sent to the model once during initialize. It tells Alexa+ how to read the
# response contract in one paragraph, so the tool descriptions can stay short.
INSTRUCTIONS = (
    "Alexa controls a simulated smart home. Use one tool per user request. Every response "
    "contains `speech`, a short sentence to say to the user, and may contain `detail`, a longer "
    "explanation to offer only if the user asks. If `status` is `error`, read `error.code` and "
    "follow `error.follow_up`; never claim the action succeeded. If `status` is "
    "`confirmation_required`, say the preview `speech`, show the `preview`, and ask the user; call "
    "the same tool again with exactly the same parameters plus `confirmation_token` only after "
    "they confirm. Never claim success before a response with `status` `ok`. Times and durations "
    "are in seconds; booking dates are YYYY-MM-DD and times are 24-hour HH:MM. Prefer asking a "
    "specific follow-up question over repeating the whole request."
)


def annotations_for(spec: ToolSpec) -> ToolAnnotations:
    """MCP hints derived from the same manifest the console sees.

    `open_world_hint` is true only for a tool that reaches a service outside the
    household, which is the same flag the privacy gate will use. `idempotent_hint`
    tells a client whether a retry after a timeout is safe without asking again.
    """
    return ToolAnnotations(
        title=spec.title,
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=spec.idempotent,
        open_world_hint=spec.external,
    )


async def principal_from_context(ctx: Context, verifier: StaticTokenVerifier) -> Principal | None:
    """Re-verify the bearer token from the current request.

    The MCP middleware already rejected a bad token at the HTTP layer. Tool
    handlers may run in a session task, though, so a context variable could carry
    the identity from the initialize call instead of the call being served. The
    current request headers keep the two tied together. Re-verification is one
    dictionary scan, and it means a revoked or expired token stops working even
    inside an open session.
    """
    headers = ctx.headers or {}
    authorization = next((value for key, value in headers.items() if key.lower() == "authorization"), "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    access = await verifier.verify_token(token.strip())
    return principal_from_access_token(access) if access else None


def build_mcp_server(settings: Settings, router: Router, verifier: StaticTokenVerifier) -> MCPServer:
    # This is the resource server we advertise in the protected-resource
    # metadata; there is no token endpoint yet. Static dev tokens have no RFC
    # 8707 audience, so the audience check stays off until tokens carry a
    # resource value.
    auth = AuthSettings(
        issuer_url=AnyHttpUrl(settings.public_url),
        resource_server_url=AnyHttpUrl(settings.resource_server_url),
        # Scopes are checked per tool in the router, not globally on the endpoint.
        required_scopes=None,
        validate_token_resource=False,
    )
    mcp = MCPServer(
        name="Alexa",
        title="Alexa+ Smart Home",
        version=__version__,
        instructions=INSTRUCTIONS,
        auth=auth,
        token_verifier=verifier,
        log_level=settings.log_level,
    )

    # Tool signatures stay flat on purpose. Alexa+ fills a small JSON object, and
    # the SDK turns these arguments into the input schema. The Context parameter
    # is injected by the SDK and never appears in that schema.
    @mcp.tool(
        name=timers.SPEC.name,
        title=timers.SPEC.title,
        description=timers.SPEC.description,
        annotations=annotations_for(timers.SPEC),
    )
    async def timer_set(
        ctx: Context,
        duration_seconds: int,
        label: str | None = None,
    ) -> ToolResponse:
        # The wrapper does no business logic. It resolves the caller and hands
        # the raw parameters to the same router the tests use.
        principal = await principal_from_context(ctx, verifier)
        return router.execute(
            timers.SPEC.name,
            {"duration_seconds": duration_seconds, "label": label},
            principal,
        )

    @mcp.tool(
        name=lights.SPEC.name,
        title=lights.SPEC.title,
        description=lights.SPEC.description,
        annotations=annotations_for(lights.SPEC),
    )
    async def lights_set(
        ctx: Context,
        room: str,
        on: bool | None = None,
        brightness: int | None = None,
    ) -> ToolResponse:
        principal = await principal_from_context(ctx, verifier)
        return router.execute(
            lights.SPEC.name,
            {"room": room, "on": on, "brightness": brightness},
            principal,
        )

    @mcp.tool(
        name=thermostat.SPEC.name,
        title=thermostat.SPEC.title,
        description=thermostat.SPEC.description,
        annotations=annotations_for(thermostat.SPEC),
    )
    async def thermostat_set(
        ctx: Context,
        zone: str,
        target_c: int,
    ) -> ToolResponse:
        principal = await principal_from_context(ctx, verifier)
        return router.execute(
            thermostat.SPEC.name,
            {"zone": zone, "target_c": target_c},
            principal,
        )

    @mcp.tool(
        name=booking.SPEC.name,
        title=booking.SPEC.title,
        description=booking.SPEC.description,
        annotations=annotations_for(booking.SPEC),
    )
    async def book_room(
        ctx: Context,
        date: str,
        room: str | None = None,
        start_time: str | None = None,
        duration_minutes: int | None = None,
        guests: int | None = None,
        title: str | None = None,
        confirmation_token: str | None = None,
    ) -> ToolResponse:
        principal = await principal_from_context(ctx, verifier)
        # The token travels beside the business parameters, never inside them.
        # That keeps the parameter hash, and therefore the token binding, about
        # the action only.
        return router.execute(
            booking.SPEC.name,
            {
                "date": date,
                "room": room,
                "start_time": start_time,
                "duration_minutes": duration_minutes,
                "guests": guests,
                "title": title,
            },
            principal,
            confirmation_token=confirmation_token,
        )

    return mcp
