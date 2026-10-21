"""`thermostat_set`: deterministic climate control.

Low risk and reversible, so it executes immediately. It is also the demo's
out-of-bounds example: the bounds (16 to 28 degrees Celsius) live in rules.yaml,
not in this file.
"""

from __future__ import annotations

from app.adapters.rooms import ROOMS
from app.auth import Principal
from app.models import HandlerResult
from app.state import AppState
from app.tools.specs import ToolSpec

SPEC = ToolSpec(
    name="thermostat_set",
    title="Set a thermostat",
    description=(
        "Set the target temperature for one thermostat zone. Use when the user asks to change "
        "heating or cooling, for example 'set the living room to 22 degrees'. The temperature is "
        "in whole degrees Celsius. Zones are living room, bedroom, kitchen, and office. Do not use "
        "to read the current temperature, and do not guess a zone the user did not name."
    ),
    service="climate",
    scopes=["home:climate:write"],
    risk="low",
    reversible=True,
    idempotent=True,
    compensator="thermostat_restore",
    required=["zone", "target_c"],
)


def handle(params: dict, principal: Principal, state: AppState) -> HandlerResult:
    zone = params["zone"]
    target = params["target_c"]
    previous, current, changed = state.climate.set(principal.subject, zone, target)
    # ROOMS maps the wire enum to the spoken name. Never speak "living_room".
    zone_name = ROOMS[zone]

    if not changed:
        # A valid request that changes nothing is not an error. STANDARD.md asks
        # for NO_CHANGE to be visible instead of a fake success.
        return HandlerResult(
            speech=f"{zone_name} is already at {current.target_c} degrees.",
            detail=(
                f"{zone_name} thermostat was already set to {current.target_c} degrees Celsius. "
                f"Stored as climate_{zone}."
            ),
            decision="no_change",
        )

    spoken = f"{zone_name} set to {current.target_c} degrees."
    detail = (
        f"{zone_name} thermostat set to {current.target_c} degrees Celsius "
        f"(previously {previous.target_c}). Stored as climate_{zone}."
    )
    return HandlerResult(speech=spoken, detail=detail)


__all__ = ["SPEC", "handle"]
