"""Simulated meeting-room booking adapter.

No external service is called. `external=True` in the tool manifest exists so the
privacy gate can be demonstrated later; the adapter itself is deterministic and
local.
"""

from __future__ import annotations

import secrets
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from pydantic import BaseModel

BOOKING_ROOMS: dict[str, str] = {
    # Wire value -> spoken name. Proper names keep the preview readable.
    "oak": "Oak",
    "cedar": "Cedar",
    "maple": "Maple",
}


class Booking(BaseModel):
    id: str
    subject: str
    room: str
    date: date
    start_time: time
    duration_minutes: int
    guests: int
    title: str | None
    created_at: datetime
    cancelled_at: datetime | None = None

    def start(self) -> datetime:
        return datetime.combine(self.date, self.start_time, tzinfo=UTC)

    def end(self) -> datetime:
        return self.start() + timedelta(minutes=self.duration_minutes)


class BookingConflict(Exception):
    """The requested slot overlaps an active booking for the same room."""

    def __init__(self, booking: Booking) -> None:
        super().__init__(f"{booking.room} is already booked at that time")
        self.booking = booking


class BookingAdapter:
    """Simulated booking store, keyed by subject then booking id."""

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._bookings: dict[str, dict[str, Booking]] = defaultdict(dict)

    def create(
        self,
        subject: str,
        *,
        room: str,
        on_date: date,
        start_time: time,
        duration_minutes: int,
        guests: int,
        title: str | None = None,
    ) -> Booking:
        booking = Booking(
            id=f"booking_{secrets.token_hex(4)}",
            subject=subject,
            room=room,
            date=on_date,
            start_time=start_time,
            duration_minutes=duration_minutes,
            guests=guests,
            title=title,
            created_at=self._now(),
        )
        conflict = self._conflict(subject, booking)
        if conflict is not None:
            raise BookingConflict(conflict)
        self._bookings[subject][booking.id] = booking
        return booking

    def get(self, subject: str, booking_id: str) -> Booking | None:
        return self._bookings.get(subject, {}).get(booking_id)

    def list_for(self, subject: str) -> list[Booking]:
        return sorted(
            (booking for booking in self._bookings.get(subject, {}).values() if booking.cancelled_at is None),
            key=lambda booking: booking.start(),
        )

    def cancel(self, subject: str, booking_id: str) -> Booking | None:
        booking = self._bookings.get(subject, {}).get(booking_id)
        if booking is None or booking.cancelled_at is not None:
            return None
        booking.cancelled_at = self._now()
        return booking

    def _conflict(self, subject: str, candidate: Booking) -> Booking | None:
        # Half-open intervals: a booking ending at 10:00 does not conflict with
        # one starting at 10:00.
        start, end = candidate.start(), candidate.end()
        for existing in self._bookings.get(subject, {}).values():
            if existing.cancelled_at is not None or existing.room != candidate.room:
                continue
            if existing.date != candidate.date:
                continue
            if start < existing.end() and end > existing.start():
                return existing
        return None
