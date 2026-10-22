"""`undo`: reverse the most recent action that changed something.

Undo is a normal tool on purpose. It goes through `Router.execute`, so it gets
the same auth, rules, audit, trace, and privacy path as the action it reverses,
and its row links back with `compensator_of`.

Two authorization layers apply. The tool itself declares no scopes, because the
scope that matters depends on what is being undone. The handler resolves the
target row first and then checks the scopes that row recorded, before any adapter
call. A caller without `home:lights:write` cannot undo a light change even though
`undo` is in the tool list.

The compensators are deliberately small and explicit. Each one writes the state
captured in the original audit row, so rummaging through adapter internals is not
required and a restart does not change the outcome.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from app.adapters.booking import BOOKING_ROOMS
from app.adapters.rooms import ROOMS
from app.audit import AuditRow
from app.auth import Principal
from app.models import ErrorCode, HandlerResult, RuleViolation, ToolError
from app.speech import human_date, human_time
from app.state import AppState
from app.tools.specs import ToolSpec

SPEC = ToolSpec(
    name="undo",
    title="Undo the last action",
    description=(
        "Reverse the most recent action that changed something. Use when the user says 'undo "
        "that'. It can cancel a timer, restore lights, restore a thermostat, or cancel a booking. "
        "Reads, previews, refusals, and no-op changes are skipped, so this always targets the last "
        "real change. Pass audit_id only when the user is referring to a specific earlier action "
        "from the console. Undo cannot itself be undone, and a booking cancellation cannot be "
        "reversed. Never claim the action was undone before a response with status ok."
    ),
    service="undo",
    # Scopes are resolved from the target row inside the handler. Declaring one
    # here would either be too broad or force every caller to hold all four.
    scopes=[],
    risk="low",
    reversible=False,
    required=[],
    optional=["audit_id"],
)


def _not_found(message: str, *, follow_up: str) -> RuleViolation:
    return RuleViolation(ToolError.of(ErrorCode.NOT_FOUND, message, follow_up=follow_up))


def _undo_timer(row: AuditRow, subject: str, state: AppState) -> HandlerResult:
    timer_id = (row.compensation or {}).get("timer_id") or row.result_ref
    timer = state.timers.cancel(subject, timer_id) if timer_id else None
    if timer is None:
        raise _not_found(
            "That timer is no longer running.",
            follow_up="Say that the timer has already finished or was cancelled.",
        )
    named = f" '{timer.label}'" if timer.label else ""
    return HandlerResult(
        speech="Timer cancelled.",
        detail=f"Cancelled timer{named} ({timer.id}), set for {timer.duration_s} seconds. Undo of {row.id}.",
        compensator_of=row.id,
    )


def _undo_lights(row: AuditRow, subject: str, state: AppState) -> HandlerResult:
    compensation = row.compensation or {}
    room = str(compensation.get("room", ""))
    if room not in ROOMS:
        raise _not_found(
            "That light change cannot be undone.",
            follow_up="Say that the previous lighting state is no longer available.",
        )
    restored = state.lights.restore(
        subject,
        room,
        on=bool(compensation.get("on", False)),
        brightness=int(compensation.get("brightness", 0)),
    )
    room_name = ROOMS[room]
    speech = (
        f"{room_name} lights back to {restored.brightness} percent."
        if restored.on
        else f"{room_name} lights off again."
    )
    return HandlerResult(
        speech=speech,
        detail=f"{room_name} lights restored to the state before {row.id}.",
        compensator_of=row.id,
    )


def _undo_climate(row: AuditRow, subject: str, state: AppState) -> HandlerResult:
    compensation = row.compensation or {}
    zone = str(compensation.get("zone", ""))
    if zone not in ROOMS:
        raise _not_found(
            "That thermostat change cannot be undone.",
            follow_up="Say that the previous setpoint is no longer available.",
        )
    previous, current, _ = state.climate.set(subject, zone, int(compensation.get("target_c", 21)))
    zone_name = ROOMS[zone]
    return HandlerResult(
        speech=f"{zone_name} thermostat back to {current.target_c} degrees.",
        detail=(
            f"{zone_name} thermostat restored from {previous.target_c} to {current.target_c} degrees. Undo of {row.id}."
        ),
        compensator_of=row.id,
    )


def _undo_booking(row: AuditRow, subject: str, state: AppState) -> HandlerResult:
    compensation = row.compensation or {}
    booking_id = str(compensation.get("booking_id") or row.result_ref or "")
    cancelled = state.bookings.cancel(subject, booking_id) if booking_id else None
    if cancelled is None:
        raise _not_found(
            "That booking is already cancelled.",
            follow_up="Say that there is no active booking to cancel.",
        )
    room_name = BOOKING_ROOMS.get(cancelled.room, cancelled.room.title())
    return HandlerResult(
        speech=(
            f"Cancelled the {room_name} room booking on {human_date(cancelled.date.isoformat())} "
            f"at {human_time(cancelled.start_time.strftime('%H:%M'))}."
        ),
        detail=f"Cancelled booking {cancelled.id}. Undo of {row.id}.",
        compensator_of=row.id,
    )


# Target tool name to the function that reverses one row.
COMPENSATORS: dict[str, Callable[[AuditRow, str, AppState], HandlerResult]] = {
    "timer_set": _undo_timer,
    "lights_set": _undo_lights,
    "thermostat_set": _undo_climate,
    "book_room": _undo_booking,
}


def _resolve(row_id: str | None, subject: str, state: AppState) -> AuditRow:
    if row_id:
        row = state.audit.get(row_id)
        # Another user's row reads as missing. An undo must not confirm that an
        # audit id exists for someone else.
        if row is None or row.subject != subject:
            raise _not_found(
                "I could not find that action.",
                follow_up="Ask the user to repeat the action, or use the console to find the entry.",
            )
        if row.decision != "executed" or row.compensation is None:
            raise _not_found(
                "That action cannot be undone.",
                follow_up="Say that only a completed action can be undone.",
            )
        if row.id in state.audit.compensated_ids():
            raise _not_found(
                "That action was already undone.",
                follow_up="Say that this action has already been reversed.",
            )
        return row

    row = state.audit.last_executed(subject)
    if row is None:
        raise _not_found(
            "There is nothing to undo.",
            follow_up="Tell the user there is no recent action to reverse.",
        )
    if row.tool not in COMPENSATORS or row.compensation is None:
        raise _not_found(
            "The last action cannot be undone.",
            follow_up="Say that this action cannot be reversed.",
        )
    if row.id in state.audit.compensated_ids():
        raise _not_found(
            "That action was already undone.",
            follow_up="Say that this action has already been reversed.",
        )
    return row


def handle(params: dict, principal: Principal, state: AppState) -> HandlerResult:
    subject = principal.subject
    row = _resolve(params.get("audit_id"), subject, state)

    missing = [scope for scope in row.scopes_used if scope not in principal.scopes]
    if missing:
        # Checked before the adapter runs, so a refused undo changes nothing.
        raise RuleViolation(
            ToolError.of(
                ErrorCode.AUTH_REQUIRED,
                "This action requires permission that has not been granted.",
            )
        )

    # Cancelling a booking reaches a service outside the household, so it is
    # gated by the same sharing toggle that blocks the booking itself.
    from app.tools import REGISTRY

    target = REGISTRY.get(row.tool)
    if target is not None and target.external and not state.privacy.get(subject).third_party_sharing:
        raise RuleViolation(
            ToolError.of(
                ErrorCode.PRIVACY_BLOCKED,
                "That action needs third-party sharing, which is off.",
                follow_up="Explain that third-party sharing is off and offer to turn it on.",
            )
        )

    result = COMPENSATORS[row.tool](row, subject, state)
    # The undo row relied on the same grants as the action it reversed. replace()
    # keeps whatever the compensator set, including compensator_of.
    return dataclasses.replace(result, result_ref=row.id, scopes_used=list(row.scopes_used))


__all__ = ["COMPENSATORS", "SPEC", "handle"]
