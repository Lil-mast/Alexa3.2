"""Text-in assistant endpoints for the demo console.

These endpoints are the demo stand-in for Alexa+'s conversation layer. The real
product turns speech into tool calls inside Alexa+. For a local demo, the
deterministic parser does that job so the operator can type or dictate a phrase
and watch the same router decide.

The confirmation buttons exist because a browser button is not a sentence. Both
`/confirm` and a spoken "yes" go through the same service method, so a button
cannot skip the token check in the router.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.assistant.models import AssistantReply, PendingView
from app.assistant.service import AssistantService
from app.auth import Principal


class TurnRequest(BaseModel):
    """One utterance. The cap is a guard against a pasted transcript."""

    utterance: str = Field(min_length=1, max_length=500)


class SessionView(BaseModel):
    pending: PendingView | None


class ResetView(BaseModel):
    cleared: bool


def build_assistant_router(assistant: AssistantService, require_principal) -> APIRouter:
    api = APIRouter(prefix="/api/assistant", tags=["assistant"])

    @api.post("/turn", response_model=AssistantReply)
    async def turn(
        payload: TurnRequest,
        principal: Principal = Depends(require_principal),
    ) -> AssistantReply:
        return assistant.turn(payload.utterance, principal)

    @api.get("/session", response_model=SessionView)
    async def session(principal: Principal = Depends(require_principal)) -> SessionView:
        return SessionView(pending=assistant.session(principal.subject))

    @api.post("/confirm", response_model=AssistantReply)
    async def confirm(principal: Principal = Depends(require_principal)) -> AssistantReply:
        return assistant.confirm(principal)

    @api.post("/cancel", response_model=AssistantReply)
    async def cancel(principal: Principal = Depends(require_principal)) -> AssistantReply:
        return assistant.cancel(principal)

    @api.post("/reset", response_model=ResetView)
    async def reset(principal: Principal = Depends(require_principal)) -> ResetView:
        # A session control, not an action: there is nothing to audit because
        # no tool ran and no state changed.
        return ResetView(cleared=assistant.reset(principal.subject))

    return api


__all__ = ["ResetView", "SessionView", "TurnRequest", "build_assistant_router"]
