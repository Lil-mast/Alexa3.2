"""`lights_set`: deterministic room lighting."""

from __future__ import annotations

from app.adapters.lights import ROOMS
from app.auth import Principal
from app.models import ErrorCode, HandlerResult, RuleViolation, ToolError
from app.state import AppState
from app.tools.specs import ToolSpec

# Same rule as the timer: the description is prompt text for tool selection. It
# spells out that "on", "brightness", or both are valid, and that rooms are a
# closed set. The accepted values themselves live in rules.yaml.
SPEC = ToolSpec(
    name="lights_set",
    title="Set room lights",
    description=(
        "Set a room's lights: turn them on or off, set a brightness percentage, or both. Use when "
        "the user asks to change lighting, for example 'dim the living room lights to 30 percent'. "
        "Brightness is 0 to 100, where 0 is off. Only these rooms exist: living room, bedroom, "
        "kitchen, office. Do not guess a room the user did not name."
    ),
    service="lights",
    scopes=["home:lights:write"],
    risk="low",
    reversible=True,
    idempotent=True,
    compensator="lights_restore",
    required=["room"],
    optional=["on", "brightness"],
)


def handle(params: dict, principal: Principal, state: AppState) -> HandlerResult:
    # Cross-field rules cannot be expressed as a per-field bound, so they live
    # here. Everything else was already checked by validate_params.
    if params.get("on") is None and params.get("brightness") is None:
        raise RuleViolation(
            ToolError.of(
                ErrorCode.INVALID_PARAM,
                "Say whether to turn the lights on or off, or give a brightness percentage.",
                field="brightness",
            )
        )
    # "Turn off at 40 percent" is contradictory. Refuse it instead of silently
    # dropping one of the two values.
    if params.get("on") is False and (params.get("brightness") or 0) > 0:
        raise RuleViolation(
            ToolError.of(
                ErrorCode.INVALID_PARAM,
                "A brightness cannot be set while turning the lights off.",
                field="brightness",
            )
        )

    room = params["room"]
    previous, current = state.lights.set(
        principal.subject,
        room,
        on=params.get("on"),
        brightness=params.get("brightness"),
    )
    # ROOMS maps the wire enum to the spoken name. Never speak "living_room".
    room_name = ROOMS[room]

    # Keep speech short and factual. Depth goes in detail, which Alexa+ offers
    # as a follow-up instead of saying it up front.
    if not current.on:
        spoken = f"{room_name} lights off."
    elif params.get("brightness") is not None:
        spoken = f"{room_name} lights set to {current.brightness} percent."
    else:
        spoken = f"{room_name} lights on."

    was = f"on at {previous.brightness} percent" if previous.on else "off"
    detail = (
        f"{room_name} lights are now {'on' if current.on else 'off'} at {current.brightness} percent "
        f"(previously {was}). Stored as lights_{room}."
    )
    return HandlerResult(speech=spoken, detail=detail)
