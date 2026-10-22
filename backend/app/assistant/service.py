"""The assistant: parser, pending confirmation, router, reply.

This service is the seam between a spoken sentence and the one execution path.
It does four things and nothing else:

1. Resolve a pending yes or no before parsing anything new, so a confirmation
   cannot be skipped by a differently worded request.
2. Ask the deterministic parser what the user meant.
3. Hand the result to `Router.execute`, which validates, authorizes, audits, and
   writes the trace exactly as it does for Alexa+.
4. Keep the preview token for the next turn and return one reply shape.

It never calls a model, never writes adapter state, and never composes speech for
a tool. The handler composes its own speech, which keeps replies repeatable and
keeps `tell_me_more` consistent with what was said.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.assistant.models import AssistantReply, ParsedIntentView, PendingView, StepView
from app.assistant.parser import (
    INTRO,
    INTRO_SUGGESTIONS,
    Clarification,
    Intent,
    is_affirmative,
    is_greeting,
    is_negative,
    parse_steps,
)
from app.assistant.session import PendingConfirmation, SessionStore
from app.auth import Principal
from app.models import ErrorCode, ToolResponse
from app.router import Router
from app.rules import RULES

logger = logging.getLogger("alexa.assistant")


def _merge(replies: list[AssistantReply]) -> AssistantReply:
    """One reply for a multi-task turn: the speech in order, the last step's status and pending action."""
    steps = [
        StepView(
            tool=reply.intent.tool if reply.intent else None,
            status=reply.status,
            speech=reply.speech,
            audit_id=reply.audit_id,
        )
        for reply in replies
    ]
    last = replies[-1]
    speech = " ".join(reply.speech for reply in replies)
    return last.model_copy(update={"speech": speech, "steps": steps})


@dataclass(frozen=True)
class _Turn:
    """Internal timing record so one log line covers every exit path."""

    started: float

    def elapsed_ms(self) -> int:
        return max(0, int((time.perf_counter() - self.started) * 1000))


class AssistantService:
    """One instance per app, created beside the router in `create_app`."""

    def __init__(
        self,
        router: Router,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._router = router
        self._now = now or (lambda: datetime.now(UTC))
        # The confirmation window is the same reviewed value the token service
        # uses. Two different windows would let the preview expire without the
        # user being told, so there is one source of truth.
        # Steps the user asked for after the one that is waiting for a yes or no.
        self._queues: dict[str, list[Intent]] = {}
        self._sessions = SessionStore(
            ttl_seconds=RULES.confirmation.ttl_seconds,
            now=lambda: self._now().timestamp(),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def turn(self, utterance: str, principal: Principal) -> AssistantReply:
        """Handle one user sentence for one authenticated subject."""
        turn = _Turn(time.perf_counter())
        subject = principal.subject
        pending = self._sessions.get(subject)

        if pending is not None:
            # Context wins over parsing. A user who was asked "should I go
            # ahead?" is answering that question, not starting a new one.
            if is_affirmative(utterance):
                return self._drain(principal, turn, [self._confirm(pending, principal, turn)])
            if is_negative(utterance):
                return self._drain(principal, turn, [self._cancel(pending, principal, turn)])
            return self._repeat(pending, principal, turn)

        # Steps left over from a confirmation that expired must not run now.
        self._queues.pop(subject, None)

        if is_affirmative(utterance):
            return self._clarify(
                "There is nothing waiting for confirmation right now.",
                ("book a room tomorrow at 2 PM",),
                "no_pending_confirmation",
                turn,
                principal,
            )
        if is_negative(utterance):
            return self._clarify(
                "There is nothing to cancel right now.",
                ("set a ten minute timer",),
                "no_pending_action",
                turn,
                principal,
            )
        if is_greeting(utterance):
            return self._clarify(INTRO, INTRO_SUGGESTIONS, "greeting", turn, principal)

        steps = parse_steps(utterance, today=self._now().date())
        if isinstance(steps, Clarification):
            return self._clarify(
                steps.speech,
                steps.suggestions,
                steps.reason,
                turn,
                principal,
            )

        # Run the first step now and keep the rest in order. A step that needs a
        # yes or no stops the queue until the user answers it.
        self._queues[subject] = list(steps[1:])
        first = self._execute(steps[0], principal, turn)
        return self._drain(principal, turn, [first])

    def confirm(self, principal: Principal) -> AssistantReply:
        """Complete the pending action, for a UI button that is not a sentence."""
        turn = _Turn(time.perf_counter())
        pending = self._sessions.get(principal.subject)
        if pending is None:
            return self._clarify(
                "There is nothing waiting for confirmation right now.",
                ("book a room tomorrow at 2 PM",),
                "no_pending_confirmation",
                turn,
                principal,
            )
        return self._drain(principal, turn, [self._confirm(pending, principal, turn)])

    def cancel(self, principal: Principal) -> AssistantReply:
        """Drop the pending action, for a UI button that is not a sentence."""
        turn = _Turn(time.perf_counter())
        pending = self._sessions.get(principal.subject)
        if pending is None:
            return self._clarify(
                "There is nothing waiting to cancel right now.",
                ("set a ten minute timer",),
                "no_pending_action",
                turn,
                principal,
            )
        return self._drain(principal, turn, [self._cancel(pending, principal, turn)])

    def session(self, subject: str) -> PendingView | None:
        """The pending confirmation for the console, without the token."""
        pending = self._sessions.get(subject)
        return pending.view() if pending is not None else None

    def reset(self, subject: str) -> bool:
        """Forget a pending action and the steps queued behind it. A session control, not an audited action."""
        self._queues.pop(subject, None)
        return self._sessions.clear(subject)

    # ------------------------------------------------------------------
    # Confirmation paths
    # ------------------------------------------------------------------

    def _drain(self, principal: Principal, turn: _Turn, replies: list[AssistantReply]) -> AssistantReply:
        """Run queued steps until one needs a yes or no, or the queue is empty."""
        subject = principal.subject
        queue = self._queues.get(subject, [])
        while queue and self._sessions.get(subject) is None:
            replies.append(self._execute(queue.pop(0), principal, turn))
        if not queue:
            self._queues.pop(subject, None)
        return _merge(replies)

    def _execute(self, intent: Intent, principal: Principal, turn: _Turn) -> AssistantReply:
        """One tool call through the router, keeping its preview for the next yes or no."""
        response = self._router.execute(intent.tool, intent.params, principal)
        pending_view = None
        if response.status == "confirmation_required" and response.confirmation_token and response.preview is not None:
            # The router already wrote a `previewed` audit row and issued the
            # token. Keeping the token here is what lets the next "yes" finish
            # the same action without the browser managing a capability.
            issued_at = self._now().timestamp()
            self._sessions.put(
                PendingConfirmation(
                    subject=principal.subject,
                    tool=intent.tool,
                    params=dict(intent.params),
                    token=response.confirmation_token,
                    preview=response.preview,
                    effect=response.preview.effect,
                    created_at=issued_at,
                    expires_at=issued_at + self._sessions.ttl_seconds,
                    ttl_seconds=self._sessions.ttl_seconds,
                )
            )
            pending_view = self._sessions.get(principal.subject)
            pending_view = pending_view.view() if pending_view else None
        return self._reply(intent, response, principal, turn, pending_view)

    def _confirm(self, pending: PendingConfirmation, principal: Principal, turn: _Turn) -> AssistantReply:
        # The router re-verifies subject, tool, and parameter hash, so this is a
        # convenience, not a bypass. The token is consumed only after the
        # adapter succeeds, which is the same rule as a direct MCP call.
        response = self._router.execute(
            pending.tool,
            pending.params,
            principal,
            confirmation_token=pending.token,
        )

        # A transient upstream failure is the one case where keeping the
        # pending action is useful: the user can say "yes" again after the
        # service recovers. Every other outcome is terminal, including an
        # expired or already consumed token.
        transient = response.error is not None and response.error.code in {
            ErrorCode.UPSTREAM_ERROR,
            ErrorCode.UPSTREAM_TIMEOUT,
        }
        if not transient:
            self._sessions.clear(principal.subject)

        intent = Intent(pending.tool, dict(pending.params), "confirmed pending action")
        return self._reply(intent, response, principal, turn, None)

    def _cancel(self, pending: PendingConfirmation, principal: Principal, turn: _Turn) -> AssistantReply:
        self._sessions.clear(principal.subject)
        # A no stops the whole request. Running the steps behind a declined one
        # would act on a plan the user just refused.
        skipped = self._queues.pop(principal.subject, [])
        speech = "Okay, I will not do that."
        if skipped:
            speech += " I also skipped the rest of your request."
        reply = AssistantReply(
            understood=True,
            status="cancelled",
            speech=speech,
            detail="Nothing changed.",
            intent=ParsedIntentView(
                tool=pending.tool,
                params=dict(pending.params),
                rationale="cancelled pending action",
            ),
        )
        self._log(principal, pending.tool, reply.status, True, turn, None)
        return reply

    def _repeat(self, pending: PendingConfirmation, principal: Principal, turn: _Turn) -> AssistantReply:
        # The user said something else while a preview was open. Repeating the
        # question is safer than silently replacing the preview or guessing
        # which request they meant.
        reply = AssistantReply(
            understood=True,
            status="confirmation_required",
            speech=f"{pending.effect.rstrip('.')}. Should I go ahead?",
            detail="Say yes to continue or no to cancel.",
            intent=ParsedIntentView(
                tool=pending.tool,
                params=dict(pending.params),
                rationale="waiting for confirmation",
            ),
            pending=pending.view(),
        )
        self._log(principal, pending.tool, reply.status, True, turn, None)
        return reply

    # ------------------------------------------------------------------
    # Reply construction
    # ------------------------------------------------------------------

    def _reply(
        self,
        intent: Intent,
        response: ToolResponse,
        principal: Principal,
        turn: _Turn,
        pending: PendingView | None,
    ) -> AssistantReply:
        trace_id = response.trace[0].id if response.trace else None
        reply = AssistantReply(
            understood=True,
            status=response.status,
            speech=response.speech,
            detail=response.detail,
            detail_available=response.detail_available,
            intent=ParsedIntentView(
                tool=intent.tool,
                params=dict(intent.params),
                rationale=intent.rationale,
            ),
            response=response,
            pending=pending,
            trace_id=trace_id,
            audit_id=response.audit_id,
        )
        self._log(principal, intent.tool, reply.status, True, turn, response.audit_id)
        return reply

    def _clarify(
        self,
        speech: str,
        suggestions: tuple[str, ...],
        reason: str,
        turn: _Turn,
        principal: Principal,
    ) -> AssistantReply:
        reply = AssistantReply(
            understood=False,
            status="clarification",
            speech=speech,
            suggestions=list(suggestions),
        )
        self._log(principal, None, "clarification", False, turn, None, reason=reason)
        return reply

    def _log(
        self,
        principal: Principal,
        tool: str | None,
        status: str,
        understood: bool,
        turn: _Turn,
        audit_id: str | None,
        *,
        reason: str | None = None,
    ) -> None:
        # The utterance and the parameters are deliberately absent. The subject,
        # the chosen tool, and the outcome are enough to debug a turn, and the
        # audit row already holds the parameter hash.
        logger.info(
            "assistant_turn",
            extra={
                "subject": principal.subject,
                "tool": tool,
                "status": status,
                "understood": understood,
                "reason": reason,
                "ms": turn.elapsed_ms(),
                "audit_id": audit_id,
                "pending": self._sessions.pending_count(),
            },
        )


__all__ = ["AssistantService"]
