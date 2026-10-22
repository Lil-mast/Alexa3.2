"""Simulated lighting adapter. In-memory by design; swap for a real service later."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from app.adapters.rooms import ROOMS

DEFAULT_BRIGHTNESS = 100


class LightState(BaseModel):
    room: str
    on: bool
    brightness: int
    updated_at: datetime


class LightAdapter:
    """Simulated light store, keyed by subject then room."""

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._lights: dict[str, dict[str, LightState]] = defaultdict(dict)

    def get(self, subject: str, room: str) -> LightState:
        # An unseen room reads as off rather than missing. Tools then have one
        # code path and the response can still say "previously off".
        existing = self._lights.get(subject, {}).get(room)
        if existing is not None:
            return existing
        return LightState(room=room, on=False, brightness=0, updated_at=self._now())

    def all_for(self, subject: str) -> list[LightState]:
        return [self.get(subject, room) for room in ROOMS]

    def set(
        self,
        subject: str,
        room: str,
        *,
        on: bool | None = None,
        brightness: int | None = None,
    ) -> tuple[LightState, LightState]:
        previous = self.get(subject, room)
        state = previous.model_copy(deep=True)

        # Brightness 0 is the same as off. Any positive brightness implies on.
        if brightness is not None:
            state.brightness = brightness
            state.on = brightness > 0
        # An explicit power change wins, and turning on an unlit room restores
        # the default brightness instead of leaving it at 0.
        if on is not None:
            state.on = on
            if on and state.brightness == 0:
                state.brightness = DEFAULT_BRIGHTNESS
        # Keep the last brightness while off so "turn it back on" restores it.
        # The contradictory on=False plus brightness>0 case is refused by the
        # tool before it reaches this method.
        if on is False:
            state.brightness = previous.brightness

        state.updated_at = self._now()
        self._lights[subject][room] = state
        return previous, state

    def restore(self, subject: str, room: str, *, on: bool, brightness: int) -> LightState:
        """Write a snapshot back verbatim, for undo.

        `set()` cannot express this: turning a room off keeps whatever brightness
        was last remembered, which is not necessarily the value before the action
        being undone. Undo restores the snapshot, including the remembered
        brightness of a room that was off.
        """
        state = LightState(room=room, on=on, brightness=brightness, updated_at=self._now())
        self._lights[subject][room] = state
        return state
