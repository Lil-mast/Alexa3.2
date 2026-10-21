"""Shared state for one process. Restarts intentionally clear it (see BUILD_PLAN.md)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.adapters import BookingAdapter, ClimateAdapter, LightAdapter, TimerAdapter
from app.config import Settings
from app.confirm import ConfirmationService
from app.rules import RULES
from app.trace import TraceBuffer


@dataclass
class AppState:
    """One instance per process, created in create_app().

    Adapters are simulated, so everything here is in memory and disappears on
    restart. On App Runner that means every redeploy starts with no timers, no
    lights on, and no pending confirmations. BUILD_PLAN.md accepts this for the
    demo and puts the audit seed in place on Day 3 so a reset is visible instead
    of silent.
    """

    settings: Settings
    timers: TimerAdapter = field(default_factory=TimerAdapter)
    lights: LightAdapter = field(default_factory=LightAdapter)
    climate: ClimateAdapter = field(default_factory=ClimateAdapter)
    bookings: BookingAdapter = field(default_factory=BookingAdapter)
    # TTL comes from the versioned rules file, so changing the confirmation
    # window is a reviewed data change, not a code change.
    confirmations: ConfirmationService = field(
        default_factory=lambda: ConfirmationService(ttl_seconds=RULES.confirmation.ttl_seconds)
    )
    trace: TraceBuffer = field(default_factory=TraceBuffer)
