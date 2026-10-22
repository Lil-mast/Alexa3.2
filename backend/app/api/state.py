"""Read-only device state for the console.

This is a view, not a tool. It never changes an adapter and it never writes an
audit row, so polling it every few seconds cannot pollute the record. Every write
still goes through `Router.execute` via `/api/call/{tool}` or the privacy route.

The snapshot is scoped to the caller's subject. There is no query parameter for
another user, because the subject is the household key and a console must not be
able to read across it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.adapters.booking import BOOKING_ROOMS
from app.adapters.rooms import ROOMS
from app.assistant.models import PendingView
from app.assistant.service import AssistantService
from app.auth import Principal
from app.privacy import PrivacySettings
from app.state import AppState


class TimerSnapshot(BaseModel):
    id: str
    label: str | None
    duration_s: int
    started_at: datetime
    ends_at: datetime
    remaining_s: int


class LightSnapshot(BaseModel):
    room: str
    room_name: str
    on: bool
    brightness: int
    updated_at: datetime


class ClimateSnapshot(BaseModel):
    zone: str
    zone_name: str
    target_c: int
    updated_at: datetime


class BookingSnapshot(BaseModel):
    id: str
    room: str
    room_name: str
    date: str
    start_time: str
    end_time: str
    duration_minutes: int
    guests: int
    title: str | None


class StateSnapshot(BaseModel):
    """Everything the console needs to draw the current household state."""

    subject: str
    server_time: datetime
    rules_version: str
    timers: list[TimerSnapshot]
    lights: list[LightSnapshot]
    climate: list[ClimateSnapshot]
    bookings: list[BookingSnapshot]
    privacy: PrivacySettings
    pending: PendingView | None


def build_state_router(state: AppState, assistant: AssistantService, require_principal) -> APIRouter:
    api = APIRouter(prefix="/api", tags=["state"])

    @api.get("/state", response_model=StateSnapshot)
    async def read_state(principal: Principal = Depends(require_principal)) -> StateSnapshot:
        subject = principal.subject
        now = datetime.now(UTC)

        # Expired timers are filtered here rather than by a background job. The
        # The house has no scheduler, and a timer that has ended should disappear from
        # the operator view even if the adapter still holds its last row.
        timers = [
            TimerSnapshot(
                id=timer.id,
                label=timer.label,
                duration_s=timer.duration_s,
                started_at=timer.started_at,
                ends_at=timer.ends_at,
                remaining_s=max(0, int((timer.ends_at - now).total_seconds())),
            )
            for timer in state.timers.list_for(subject)
            if timer.ends_at > now
        ]

        lights = [
            LightSnapshot(
                room=light.room,
                room_name=ROOMS.get(light.room, light.room),
                on=light.on,
                brightness=light.brightness,
                updated_at=light.updated_at,
            )
            for light in state.lights.all_for(subject)
        ]

        climate = [
            ClimateSnapshot(
                zone=zone.zone,
                zone_name=ROOMS.get(zone.zone, zone.zone),
                target_c=zone.target_c,
                updated_at=zone.updated_at,
            )
            for zone in state.climate.all_for(subject)
        ]

        bookings = [
            BookingSnapshot(
                id=booking.id,
                room=booking.room,
                room_name=BOOKING_ROOMS.get(booking.room, booking.room.title()),
                date=booking.date.isoformat(),
                start_time=booking.start_time.strftime("%H:%M"),
                end_time=booking.end().strftime("%H:%M"),
                duration_minutes=booking.duration_minutes,
                guests=booking.guests,
                title=booking.title,
            )
            for booking in state.bookings.list_for(subject)
        ]

        return StateSnapshot(
            subject=subject,
            server_time=now,
            rules_version=state.rules_version,
            timers=timers,
            lights=lights,
            climate=climate,
            bookings=bookings,
            privacy=state.privacy.get(subject),
            pending=assistant.session(subject),
        )

    return api


__all__ = [
    "BookingSnapshot",
    "ClimateSnapshot",
    "LightSnapshot",
    "StateSnapshot",
    "TimerSnapshot",
    "build_state_router",
]
