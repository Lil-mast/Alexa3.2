"""Simulated timer adapter. In-memory by design; swap for a real service later."""

from __future__ import annotations

import secrets
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel


class TimerState(BaseModel):
    id: str
    subject: str
    label: str | None
    duration_s: int
    started_at: datetime
    ends_at: datetime


class TimerAdapter:
    """Simulated timer store, keyed by subject.

    The outer key is the authenticated subject, so two callers cannot see or
    cancel each other's timers. A real implementation would keep the same shape
    around a device or database call.
    """

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        # Injectable clock keeps tests deterministic.
        self._now = now or (lambda: datetime.now(UTC))
        self._timers: dict[str, dict[str, TimerState]] = defaultdict(dict)

    def create(self, subject: str, *, duration_s: int, label: str | None = None) -> TimerState:
        started_at = self._now()
        # The short id is safe to speak and will be the audit reference on Day 3.
        # UTC everywhere; the edge formats local time if it ever needs to.
        timer = TimerState(
            id=f"timer_{secrets.token_hex(4)}",
            subject=subject,
            label=label,
            duration_s=duration_s,
            started_at=started_at,
            ends_at=started_at + timedelta(seconds=duration_s),
        )
        self._timers[subject][timer.id] = timer
        return timer

    def get(self, subject: str, timer_id: str) -> TimerState | None:
        return self._timers.get(subject, {}).get(timer_id)

    def list_for(self, subject: str) -> list[TimerState]:
        return sorted(self._timers.get(subject, {}).values(), key=lambda timer: timer.ends_at)

    def cancel(self, subject: str, timer_id: str) -> TimerState | None:
        return self._timers.get(subject, {}).pop(timer_id, None)
