"""Shared state for one process. Restarts intentionally clear it (see BUILD_PLAN.md)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.adapters import LightAdapter, TimerAdapter
from app.config import Settings
from app.trace import TraceBuffer


@dataclass
class AppState:
    """One instance per process, created in create_app().

    Adapters are simulated, so everything here is in memory and disappears on
    restart. On App Runner that means every redeploy starts with no timers and
    no lights on. BUILD_PLAN.md accepts this for the demo and puts the audit seed
    in place on Day 3 so a reset is visible instead of silent.
    """

    settings: Settings
    timers: TimerAdapter = field(default_factory=TimerAdapter)
    lights: LightAdapter = field(default_factory=LightAdapter)
    trace: TraceBuffer = field(default_factory=TraceBuffer)
