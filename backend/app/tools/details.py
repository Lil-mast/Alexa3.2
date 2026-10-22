"""`tell_me_more`: return the detail that concise mode withheld.

Concise mode is the default, so most responses carry only `speech` and set
`detail_available`. Alexa+ offers the details and calls this tool when the user
says yes. The text comes from the same handler that composed the answer, so it
never disagrees with what was said.

This is a read. It changes no state and reports decision `no_change`.
"""

from __future__ import annotations

from app.auth import Principal
from app.models import ErrorCode, HandlerResult, RuleViolation, ToolError
from app.state import AppState
from app.tools.specs import ToolSpec

SPEC = ToolSpec(
    name="tell_me_more",
    title="Explain the last action",
    description=(
        "Return the longer detail for the last action, or for the action named by audit_id. Use "
        "only after a response had detail_available true and the user said yes to hearing more. "
        "Do not use to repeat the whole request or to read device state. If the user asks about a "
        "specific older action, pass its audit_id."
    ),
    service="details",
    # No scope: the history is keyed by the token's subject, so this cannot read
    # another user's action, and asking about a timer should not need the lights
    # grant or the other way round.
    scopes=[],
    risk="low",
    reversible=True,
    read_only=True,
    idempotent=True,
    required=[],
    optional=["audit_id"],
)


def handle(params: dict, principal: Principal, state: AppState) -> HandlerResult:
    if not state.privacy.get(principal.subject).personalization:
        # The toggle is real: with personalization off the server keeps no
        # per-action history to return.
        raise RuleViolation(
            ToolError.of(
                ErrorCode.NOT_FOUND,
                "Personalization is off, so I do not keep details of past actions.",
                follow_up="Explain that personalization is off and offer to turn it on.",
            )
        )
    entry = state.details.latest(principal.subject, params.get("audit_id"))
    if entry is None:
        raise RuleViolation(
            ToolError.of(
                ErrorCode.NOT_FOUND,
                "There is nothing more to tell about that.",
                follow_up="Say that no details are available for the last action.",
            )
        )
    # The detail is the answer, so it becomes `speech`. `detail` stays empty or
    # `_finish` would offer the same text twice.
    return HandlerResult(speech=entry.detail, decision="no_change")


__all__ = ["SPEC", "handle"]
