"""`timer_set`: deterministic countdown timers."""

from __future__ import annotations

from app.auth import Principal
from app.models import Bounds, HandlerResult
from app.speech import clock, human_duration
from app.state import AppState
from app.tools.specs import ToolSpec

# Alexa+ chooses tools from this description, so it names the unit conversion
# (seconds) and the cases this tool must not handle (alarms, cancelling).
SPEC = ToolSpec(
    name="timer_set",
    description=(
        "Set a countdown timer for the user. Use when the user asks to time something, for example "
        "'set a ten-minute timer' or 'timer for the pasta'. The duration is in seconds, so convert "
        "minutes and hours yourself. Do not use for alarms or reminders at a specific clock time, "
        "and do not use to cancel or inspect an existing timer."
    ),
    service="timers",
    scopes=["home:timers:write"],
    risk="low",
    reversible=True,
    compensator="timer_cancel",
    required=["duration_seconds"],
    optional=["label"],
    bounds={"duration_seconds": Bounds(min=1, max=86_400)},
    field_labels={"duration_seconds": "Timer duration", "label": "Timer label"},
    bounds_display={"duration_seconds": "between 1 second and 24 hours"},
)


def handle(params: dict, principal: Principal, state: AppState) -> HandlerResult:
    # The adapter owns the data change. This handler only turns the validated
    # parameters and the new state into speech and detail.
    timer = state.timers.create(
        principal.subject,
        duration_s=params["duration_seconds"],
        label=params.get("label"),
    )
    # Speech is composed here, not by the model. The same inputs produce the
    # same sentence, which is what makes the demo repeatable.
    spoken = f"Timer set for {human_duration(timer.duration_s)}."
    # Detail is the payload `tell_me_more` will return on Day 3. It carries the
    # stable id and the end time, not the adapter's internals.
    named = f"Timer '{timer.label}'" if timer.label else "Timer"
    detail = (
        f"{named} set for {clock(timer.duration_s)}, ending at "
        f"{timer.ends_at.strftime('%H:%M:%S')} UTC. Stored as {timer.id}."
    )
    return HandlerResult(speech=spoken, detail=detail)


__all__ = ["SPEC", "handle"]
