"""Shared state for one process. Restarts intentionally clear it (see BUILD_PLAN.md)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.adapters import BookingAdapter, ClimateAdapter, LightAdapter, TimerAdapter
from app.audit import AuditLog
from app.config import Settings
from app.confirm import ConfirmationService
from app.memory import DetailMemory
from app.privacy import PrivacyStore
from app.rules import RULES
from app.trace import TraceBuffer


@dataclass
class AppState:
    """One instance per process, created in create_app().

    Adapters are simulated, so everything here is in memory and disappears on
    restart. On App Runner that means every redeploy starts with no timers, no
    lights on, and no pending confirmations. BUILD_PLAN.md accepts this for the
    demo; the audit log seeds a known chain at startup so the reset is visible
    instead of silent.

    The audit log is the record. The trace buffer is a debugging view, and the
    detail memory exists only so `tell_me_more` can return what concise mode
    withheld.
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
    audit: AuditLog = field(default_factory=AuditLog)
    privacy: PrivacyStore = field(default_factory=PrivacyStore)
    details: DetailMemory = field(default_factory=DetailMemory)

    @property
    def rules_version(self) -> str:
        """The rules version that approved the current state.

        Exposed on the snapshot so the console can show which rule set is live
        without importing the rules package itself.
        """
        return RULES.version
