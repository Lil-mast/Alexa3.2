"""The single REST write path for the console.

The console must never re-implement validation, scopes, confirmation, or audit.
This endpoint is deliberately thin: it resolves the caller from the same bearer
token MCP uses, then calls `Router.execute` and returns the same `ToolResponse`
an MCP client would see.

Why not let the browser speak MCP directly? The streamable transport needs a
session handshake and streaming, the SDK is Node-oriented, and the browser would
end up with a second copy of the tool contract. One REST endpoint keeps the
policy in one place.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import Principal
from app.models import ToolResponse
from app.router import Router
from app.tools import REGISTRY


class CallRequest(BaseModel):
    """One tool call from the console.

    `confirmation_token` sits beside the business parameters, not inside them,
    so the parameter hash that binds the token stays about the action only.
    """

    params: dict[str, Any] = Field(default_factory=dict)
    confirmation_token: str | None = None


def build_call_router(router: Router, require_principal) -> APIRouter:
    api = APIRouter(prefix="/api", tags=["console"])

    @api.post("/call/{tool}", response_model=ToolResponse)
    async def call_tool(
        tool: str,
        payload: CallRequest,
        principal: Principal = Depends(require_principal),
    ) -> ToolResponse:
        if tool not in REGISTRY:
            # The router would return a business error, but an unknown path is a
            # client mistake, so it gets a real 404 with the same error shape.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "NOT_FOUND",
                    "message": "That tool is not available.",
                    "follow_up": "Use GET /api/tools to list the available tools.",
                },
            )
        return router.execute(
            tool,
            payload.params,
            principal,
            confirmation_token=payload.confirmation_token,
        )

    return api


__all__ = ["CallRequest", "build_call_router"]
