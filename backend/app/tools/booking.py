"""`book_room`: a medium-risk, simulated meeting-room booking.

The handler only runs after the confirmation flow in the router. It never sees
the token and cannot tell a preview from a confirmed execution: by the time it is
called, the action is authorized.
"""

from __future__ import annotations

from datetime import date, time

from app.adapters.booking import BOOKING_ROOMS, BookingConflict
from app.auth import Principal
from app.models import ErrorCode, HandlerResult, RuleViolation, ToolError
from app.speech import human_date, human_duration, human_time
from app.state import AppState
from app.tools.specs import ToolSpec

# The description teaches Alexa+ the two-step flow. Without it, a model may call
# once and tell the user the room is booked, which is exactly the failure this
# tool exists to prevent.
SPEC = ToolSpec(
    name="book_room",
    title="Book a meeting room",
    description=(
        "Reserve a meeting room. Use when the user asks to book a room, for example 'book a room "
        "for Friday at two'. Convert the date to YYYY-MM-DD and the time to 24-hour HH:MM yourself. "
        "This is a medium-risk action: the first call returns status confirmation_required, a "
        "preview, and a confirmation_token, and books nothing. Call it again with exactly the same "
        "parameters and that token only after the user confirms. Never tell the user it is booked "
        "before a response with status ok. Rooms are Oak, Cedar, and Maple; if the user does not "
        "name a room or a start time, omit them and the defaults apply. Do not use for cancelling "
        "an existing booking."
    ),
    service="booking",
    scopes=["booking:rooms:write"],
    risk="medium",
    reversible=True,
    compensator="booking_cancel",
    required=["date"],
    optional=["room", "start_time", "duration_minutes", "guests", "title"],
    confirmation_template=(
        "Book the {room} room on {date} at {start_time} for {duration_minutes} minutes, party of {guests}"
    ),
    # A real booking service would be external. The manifest flag means the Day 3
    # privacy gate can refuse this tool when third-party sharing is off.
    external=True,
)


def handle(params: dict, principal: Principal, state: AppState) -> HandlerResult:
    on_date = date.fromisoformat(params["date"])
    room = params["room"]
    start = time.fromisoformat(params["start_time"])
    try:
        booking = state.bookings.create(
            principal.subject,
            room=room,
            on_date=on_date,
            start_time=start,
            duration_minutes=params["duration_minutes"],
            guests=params["guests"],
            title=params.get("title"),
        )
    except BookingConflict as conflict:
        room_name = BOOKING_ROOMS[room]
        raise RuleViolation(
            ToolError.of(
                ErrorCode.INVALID_PARAM,
                f"The {room_name} room is already booked at that time.",
                field="start_time",
                follow_up="Offer a different time or room.",
            )
        ) from conflict

    room_name = BOOKING_ROOMS[room]
    spoken = (
        f"Booked the {room_name} room on {human_date(params['date'])} at "
        f"{human_time(params['start_time'])} for {human_duration(booking.duration_minutes * 60)}."
    )
    named = f" ({booking.title})" if booking.title else ""
    detail = (
        f"Booking {booking.id}{named} for {booking.guests} guests on {human_date(params['date'])}, "
        f"{human_time(params['start_time'])} to {human_time(booking.end().strftime('%H:%M'))}. "
        f"Cancellable with booking_cancel."
    )
    return HandlerResult(speech=spoken, detail=detail)


__all__ = ["SPEC", "handle"]
