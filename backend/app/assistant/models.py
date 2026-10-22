"""Wire models for the assistant turn endpoint.

The assistant reply is a thin envelope around the normal `ToolResponse`. The
console gets one shape for every turn, including a clarification that never
reached a tool, while the raw response stays available for the Trace and Audit
screens.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import Preview, ToolResponse


class ParsedIntentView(BaseModel):
    """What the deterministic parser understood.

    `params` are the raw values that were sent to the router. They are returned
    for transparency in the console, not because the client should validate
    them. The router and the versioned rules remain the authority.
    """

    tool: str
    params: dict[str, Any]
    rationale: str


class PendingView(BaseModel):
    """A preview waiting for the user's yes or no.

    The confirmation token is deliberately absent. The server holds it for the
    next turn. A client that needs the raw token can read it from the first
    `response.confirmation_token`, which is the same contract Alexa+ sees.
    """

    tool: str
    effect: str
    preview: Preview
    expires_at: str
    ttl_seconds: int


class StepView(BaseModel):
    """One tool call inside a multi-task turn, in the order the user asked for it."""

    tool: str | None
    status: str
    speech: str
    audit_id: str | None = None


class AssistantReply(BaseModel):
    """One assistant turn, whether it executed, previewed, refused, or asked.

    `status` adds `clarification` and `cancelled` to the tool statuses. Every
    reply has `speech`, so a voice client can always speak something. `response`
    is present only when the turn reached `Router.execute`.
    """

    understood: bool
    status: Literal["ok", "confirmation_required", "error", "clarification", "cancelled"]
    speech: str
    detail: str | None = None
    detail_available: bool = False
    intent: ParsedIntentView | None = None
    response: ToolResponse | None = None
    pending: PendingView | None = None
    suggestions: list[str] = Field(default_factory=list)
    steps: list[StepView] = Field(default_factory=list)
    trace_id: str | None = None
    audit_id: str | None = None


__all__ = ["AssistantReply", "ParsedIntentView", "PendingView", "StepView"]
