"""The wire contract shared by MCP tools and the REST console."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    """Stable codes from STANDARD.md section 5.

    Clients branch on these strings, so renaming one is a contract change.
    """

    INVALID_PARAM = "INVALID_PARAM"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    NOT_FOUND = "NOT_FOUND"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PRIVACY_BLOCKED = "PRIVACY_BLOCKED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    TOKEN_CONSUMED = "TOKEN_CONSUMED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"


# Each code maps to the follow-up Alexa+ should give (STANDARD.md, section 5).
FOLLOW_UP: dict[ErrorCode, str] = {
    ErrorCode.INVALID_PARAM: "Ask about the specific invalid field.",
    ErrorCode.OUT_OF_BOUNDS: "State the allowed range or choices.",
    ErrorCode.NOT_FOUND: "Ask which item the user intended.",
    ErrorCode.AUTH_REQUIRED: "Prompt the user to authorize or reconnect.",
    ErrorCode.PRIVACY_BLOCKED: "Explain which setting prevented the action.",
    ErrorCode.CONFIRMATION_REQUIRED: "Present the preview and request confirmation.",
    ErrorCode.TOKEN_CONSUMED: "Start a new action and confirmation flow.",
    ErrorCode.TOKEN_EXPIRED: "Start a new action and confirmation flow.",
    ErrorCode.UPSTREAM_TIMEOUT: "Report the timeout and offer a retry.",
    ErrorCode.UPSTREAM_ERROR: "Report the failure; do not claim success or guess the result.",
}


class ToolError(BaseModel):
    code: ErrorCode
    message: str
    field: str | None = None
    allowed: list[int | str] | None = None
    follow_up: str = ""

    @classmethod
    def of(
        cls,
        code: ErrorCode,
        message: str,
        *,
        field: str | None = None,
        allowed: list[int | str] | None = None,
        follow_up: str | None = None,
    ) -> ToolError:
        # follow_up defaults to the taxonomy in STANDARD.md. A tool may narrow it
        # when the generic instruction would be unhelpful, for example when a
        # confirmation token no longer matches the parameters.
        return cls(
            code=code,
            message=message,
            field=field,
            allowed=allowed,
            follow_up=follow_up or FOLLOW_UP[code],
        )


class TraceEvent(BaseModel):
    id: str
    ts: str
    subject: str
    tool: str
    service: str
    # Only the hash of the parameters is shown here. The audit log stores the
    # full record; the console does not need a second copy of user data.
    params_hash: str
    status: Literal["ok", "confirmation_required", "error"]
    # executed: adapter ran. previewed: waiting for confirmation. refused: a rule
    # or a scope stopped it. no_change: valid request with no state difference.
    decision: Literal["executed", "previewed", "refused", "no_change"]
    ok: bool
    ms: int
    speech: str


class Preview(BaseModel):
    """What a medium or high risk action would do, rendered by Alexa+.

    The token is deliberately separate from the preview: the preview is safe to
    show the user, while the token is the capability that authorizes execution.
    """

    service: str
    tool: str
    params: dict[str, Any]
    effect: str
    irreversible: bool


class ToolResponse(BaseModel):
    """The single response shape for MCP tools and the console.

    `confirmation_required` is deliberately not an error: nothing has executed
    yet and the client should present the preview and ask the user.

    `audit_id` points at the hash-chained row for this call, for every decision.
    `detail` is present only when the user has concise mode off; otherwise
    `detail_available` is true and `tell_me_more` can fetch the text later.
    """

    status: Literal["ok", "confirmation_required", "error"]
    speech: str
    detail: str | None = None
    detail_available: bool = False
    trace: list[TraceEvent] = Field(default_factory=list)
    audit_id: str | None = None
    error: ToolError | None = None
    preview: Preview | None = None
    confirmation_token: str | None = None


@dataclass(frozen=True)
class HandlerResult:
    """What a tool handler returns before the router adds trace, audit, and status.

    `no_change` is an outcome, not a failure: the request was valid, and the
    state already matched it. STANDARD.md asks for that to be visible. A
    read-only tool also reports `no_change`, because a read changes no state.

    `compensation` is the minimal inverse state an undo needs, and is recorded in
    the audit row, not in the trace. `compensator_of` is set only by an undo.
    """

    speech: str
    detail: str | None = None
    decision: Literal["executed", "no_change"] = "executed"
    # A stable adapter reference such as `timer_7f3a`. Safe to speak and to log.
    result_ref: str | None = None
    compensation: dict[str, Any] | None = None
    compensator_of: str | None = None
    # Which scopes this call actually relied on. The router falls back to the
    # tool's declared scopes when a handler does not narrow them.
    scopes_used: list[str] | None = None


class RuleViolation(Exception):
    """Raised by rules or tools before an adapter runs. Carries the wire error."""

    def __init__(self, error: ToolError) -> None:
        super().__init__(error.message)
        self.error = error
