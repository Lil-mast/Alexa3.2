"""Tool registry: the single source of truth for what the server exposes."""

from __future__ import annotations

from collections.abc import Callable

from app.auth import Principal
from app.models import HandlerResult
from app.state import AppState
from app.tools import booking, lights, thermostat, timers
from app.tools.specs import ToolSpec

Handler = Callable[[dict, Principal, AppState], HandlerResult]

TOOLS: tuple[ToolSpec, ...] = (timers.SPEC, lights.SPEC, thermostat.SPEC, booking.SPEC)

# Name to manifest and name to handler. The router reads both, and the console
# reads manifests(). Keep registration in one place so a tool cannot be listed
# without a handler, or handled without a manifest.
REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in TOOLS}
HANDLERS: dict[str, Handler] = {
    timers.SPEC.name: timers.handle,
    lights.SPEC.name: lights.handle,
    thermostat.SPEC.name: thermostat.handle,
    booking.SPEC.name: booking.handle,
}

# Every scope the server knows about. Published in the RFC 9728 metadata so a
# client can request the right grants up front.
SCOPES: list[str] = sorted({scope for spec in TOOLS for scope in spec.scopes})


def manifests() -> list[dict]:
    """Manifests plus the rules that constrain them.

    Imported inside the function so the rules package and the tool registry
    cannot form an import cycle if either side starts importing the other at
    runtime.
    """
    from app.rules import RULES

    payloads: list[dict] = []
    for spec in TOOLS:
        payload = spec.manifest()
        fields = RULES.for_tool(spec.name).fields
        payload["rules_version"] = RULES.version
        payload["fields"] = {name: rule.model_dump(mode="json", exclude_defaults=True) for name, rule in fields.items()}
        payloads.append(payload)
    return payloads


__all__ = ["HANDLERS", "REGISTRY", "SCOPES", "TOOLS", "Handler", "manifests"]
