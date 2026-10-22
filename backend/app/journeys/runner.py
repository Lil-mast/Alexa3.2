"""Run a journey against a fresh, isolated app state.

The runner uses the same parser, router, rules, confirmation service, and audit
log as the live server, but it never touches the live state. A journey run cannot
set a timer in the house, consume a real confirmation token, or add rows to the
audit chain the operator is showing.

The principal is synthetic and holds every scope the tools declare. A journey is
a test of the contract, not a test of one user's grants. Scope refusal is covered
by the unit suite with a deliberately narrower principal.
"""

from __future__ import annotations

import logging

from app.assistant.models import AssistantReply
from app.assistant.service import AssistantService
from app.auth import Principal
from app.config import Settings
from app.journeys.models import Journey, JourneyResult, Step, StepResult
from app.router import Router
from app.state import AppState
from app.tools import SCOPES

logger = logging.getLogger("alexa.journeys")

JOURNEY_SUBJECT = "journey-runner"


def _principal() -> Principal:
    return Principal(
        subject=JOURNEY_SUBJECT,
        client_id="journey-runner",
        scopes=tuple(SCOPES),
    )


def _check(index: int, step: Step, reply: AssistantReply, state: AppState) -> StepResult:
    """Compare one reply with one expectation and explain every mismatch.

    All comparisons run, not just the first, so the console can show a complete
    diagnosis instead of making the operator replay the journey to find the next
    broken assertion.
    """
    failures: list[str] = []
    expectation = step.expect

    tool = reply.intent.tool if reply.intent is not None else None
    error_code = reply.response.error.code.value if reply.response and reply.response.error else None
    row = state.audit.get(reply.audit_id) if reply.audit_id else None
    decision = row.decision if row is not None else None

    if expectation.tool is not None and tool != expectation.tool:
        failures.append(f"tool: expected {expectation.tool!r}, got {tool!r}")
    if expectation.status is not None and reply.status != expectation.status:
        failures.append(f"status: expected {expectation.status!r}, got {reply.status!r}")
    if expectation.speech is not None and reply.speech != expectation.speech:
        failures.append(f"speech: expected {expectation.speech!r}, got {reply.speech!r}")
    if expectation.error_code is not None and error_code != expectation.error_code:
        failures.append(f"error_code: expected {expectation.error_code!r}, got {error_code!r}")
    if expectation.audit_decision is not None and decision != expectation.audit_decision:
        failures.append(f"audit decision: expected {expectation.audit_decision!r}, got {decision!r}")
    if expectation.detail_available is not None and reply.detail_available != expectation.detail_available:
        failures.append(f"detail_available: expected {expectation.detail_available!r}, got {reply.detail_available!r}")
    if expectation.pending is not None and (reply.pending is not None) != expectation.pending:
        failures.append(f"pending: expected {expectation.pending!r}, got {reply.pending is not None!r}")

    return StepResult(
        index=index,
        say=step.say,
        passed=not failures,
        failures=failures,
        tool=tool,
        status=reply.status,
        speech=reply.speech,
        error_code=error_code,
        audit_id=reply.audit_id,
        audit_decision=decision,
    )


def run_journey(journey: Journey, *, settings: Settings) -> JourneyResult:
    """Execute every step and return a result the console can render."""
    state = AppState(settings=settings)
    assistant = AssistantService(Router(state))
    principal = _principal()

    results: list[StepResult] = []
    for index, step in enumerate(journey.steps, start=1):
        try:
            reply = assistant.turn(step.say, principal)
        except Exception as exc:
            # A runner bug or a fixture that reaches an unexpected path should
            # fail this step, not take down the console endpoint. The exception
            # type is logged; the message is not echoed because it may contain a
            # parameter value.
            logger.exception("journey_step_failed", extra={"journey": journey.name, "step": index})
            results.append(
                StepResult(
                    index=index,
                    say=step.say,
                    passed=False,
                    failures=[f"runner error: {type(exc).__name__}"],
                    status="error",
                    speech="",
                )
            )
            continue
        results.append(_check(index, step, reply, state))

    report = state.audit.verify()
    notes: list[str] = []
    if not report.ok:
        notes.append(f"audit chain broken at {report.first_bad}: {report.reason}")

    return JourneyResult(
        name=journey.name,
        title=journey.title,
        passed=all(result.passed for result in results) and report.ok,
        steps=results,
        audit_ok=report.ok,
        audit_rows=len(state.audit),
        notes=notes,
    )


__all__ = ["JOURNEY_SUBJECT", "run_journey"]
