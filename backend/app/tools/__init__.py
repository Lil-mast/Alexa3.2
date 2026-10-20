"""Tool registry: the single source of truth for what the server exposes."""

from __future__ import annotations

from collections.abc import Callable

from app.auth import Principal
from app.models import HandlerResult
from app.state import AppState
from app.tools import lights, timers
from app.tools.specs import ToolSpec

Handler = Callable[[dict, Principal, AppState], HandlerResult]

TOOLS: tuple[ToolSpec, ...] = (timers.SPEC, lights.SPEC)

# Name to manifest and name to handler. The router reads both, and the console
# reads manifests(). Keep registration in one place so a tool cannot be listed
# without a handler, or handled without a manifest.
REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in TOOLS}
HANDLERS: dict[str, Handler] = {timers.SPEC.name: timers.handle, lights.SPEC.name: lights.handle}

# Every scope the server knows about. Published in the RFC 9728 metadata so a
# client can request the right grants up front.
SCOPES: list[str] = sorted({scope for spec in TOOLS for scope in spec.scopes})


def manifests() -> list[dict]:
    return [spec.manifest() for spec in TOOLS]


__all__ = ["HANDLERS", "REGISTRY", "SCOPES", "TOOLS", "Handler", "manifests"]
