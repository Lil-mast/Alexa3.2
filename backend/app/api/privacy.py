"""Privacy settings for the console.

A read is a plain view: reading a setting should not add noise to the audit
chain, so `GET` returns the stored values without a tool call. A write is an
action. It goes through `Router.execute("privacy_set", ...)` so it gets the same
rule validation, scope check, retention pruning, and audit row as a voice
request. The console never mutates `PrivacyStore` directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import Principal
from app.models import ToolResponse
from app.privacy import PrivacySettings
from app.router import Router
from app.state import AppState


class PrivacyPatch(BaseModel):
    """Only the fields the operator changed are sent.

    The endpoint is a partial update even though it also answers `PUT`, because
    the console toggles one switch at a time and should not have to resend the
    other four values and risk clobbering a change from another tab.

    `retention_days` and `microphone_mode` are deliberately broad types. The
    versioned rules own the allowed values, so a bad value reaches
    `Router.execute` and comes back as an audited `OUT_OF_BOUNDS` or
    `INVALID_PARAM`, not as a FastAPI 422 that bypasses the decision path.
    """

    retention_days: int | None = None
    personalization: bool | None = None
    microphone_mode: str | None = None
    third_party_sharing: bool | None = None
    concise_mode: bool | None = None


def build_privacy_router(state: AppState, router: Router, require_principal) -> APIRouter:
    api = APIRouter(prefix="/api", tags=["privacy"])

    @api.get("/privacy", response_model=PrivacySettings)
    async def read_privacy(principal: Principal = Depends(require_principal)) -> PrivacySettings:
        # A missing subject reads the documented defaults. That is the same view
        # `privacy_get` would return, minus the audit row a read does not need.
        return state.privacy.get(principal.subject)

    @api.api_route("/privacy", methods=["PUT", "PATCH"], response_model=ToolResponse)
    async def write_privacy(
        payload: PrivacyPatch,
        principal: Principal = Depends(require_principal),
    ) -> ToolResponse:
        changes = payload.model_dump(exclude_none=True)
        # Business errors stay in the ToolResponse with HTTP 200, exactly as
        # they do over MCP. A console that treats a refusal as a network failure
        # would hide the rule that caused it.
        return router.execute("privacy_set", changes, principal)

    return api


__all__ = ["PrivacyPatch", "build_privacy_router"]
