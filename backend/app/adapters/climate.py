"""Simulated thermostat adapter. In-memory by design; swap for a real service later."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

DEFAULT_TARGET_C = 21


class ClimateState(BaseModel):
    zone: str
    target_c: int
    updated_at: datetime


class ClimateAdapter:
    """Simulated thermostat store, keyed by subject then zone."""

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._zones: dict[str, dict[str, ClimateState]] = defaultdict(dict)

    def get(self, subject: str, zone: str) -> ClimateState:
        # An unseen zone has the default setpoint rather than no value, so the
        # response can still say what it changed from.
        existing = self._zones.get(subject, {}).get(zone)
        if existing is not None:
            return existing
        return ClimateState(zone=zone, target_c=DEFAULT_TARGET_C, updated_at=self._now())

    def set(self, subject: str, zone: str, target_c: int) -> tuple[ClimateState, ClimateState, bool]:
        previous = self.get(subject, zone)
        if target_c == previous.target_c:
            # Nothing to write. The router reports NO_CHANGE rather than
            # pretending the thermostat accepted a new value.
            return previous, previous, False
        current = previous.model_copy(deep=True)
        current.target_c = target_c
        current.updated_at = self._now()
        self._zones[subject][zone] = current
        return previous, current, True
