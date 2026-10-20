"""One execution path for MCP calls and tests: auth, rules, adapter, response, trace."""

from __future__ import annotations

import logging
import time
from typing import Literal

from app.auth import Principal
from app.canonical import params_hash
from app.models import ErrorCode, RuleViolation, ToolError, ToolResponse
from app.rules import validate_params
from app.state import AppState
from app.tools import HANDLERS, REGISTRY
from app.tools.specs import ToolSpec

logger = logging.getLogger("alexa.calls")


class Router:
    """The only path from a tool call to an adapter.

    Order matters: identity, then scope, then parameters, then execution, then
    trace. Auth comes before validation so an unauthenticated caller cannot use
    error messages to learn the schema.
    """

    def __init__(self, state: AppState) -> None:
        self._state = state

    def execute(self, tool_name: str, params: dict, principal: Principal | None) -> ToolResponse:
        # One timer for the whole path; the trace reports the wall time Alexa+
        # experiences, including validation but not network time.
        started = time.perf_counter()
        spec = REGISTRY.get(tool_name)
        if spec is None:
            # MCP itself rejects unknown tools; this guards direct router use.
            return ToolResponse(
                status="error",
                speech="That tool is not available.",
                error=ToolError.of(ErrorCode.NOT_FOUND, "That tool is not available."),
            )

        if principal is None:
            return self._refuse(
                spec,
                principal=None,
                params=params,
                error=ToolError.of(ErrorCode.AUTH_REQUIRED, "This action requires authorization."),
                started=started,
            )

        # The MCP endpoint proves the token is valid. This proves the token may
        # use this specific tool. A read-only token should not set timers.
        missing = [scope for scope in spec.scopes if scope not in principal.scopes]
        if missing:
            logger.warning(
                "scope_denied",
                extra={"tool": tool_name, "subject": principal.subject, "missing_scopes": missing},
            )
            return self._refuse(
                spec,
                principal=principal,
                params=params,
                error=ToolError.of(
                    ErrorCode.AUTH_REQUIRED,
                    "This action requires permission that has not been granted.",
                ),
                started=started,
            )

        try:
            clean = validate_params(spec, params)
        except RuleViolation as violation:
            # A refused request never reaches the adapter, so device state is
            # untouched and the refusal is still visible in the trace.
            return self._refuse(spec, principal, params, violation.error, started)

        try:
            # Handlers receive only validated, authorized, normalised parameters.
            # They own the state change and the wording; the router owns the rest.
            result = HANDLERS[spec.name](clean, principal, self._state)
        except RuleViolation as violation:
            return self._refuse(spec, principal, params, violation.error, started)
        except Exception:
            # Adapter failures map to one stable code. The exception text stays in
            # the log; Alexa+ is told the service failed, never that it worked.
            logger.exception("adapter_error", extra={"tool": spec.name, "subject": principal.subject})
            return self._refuse(
                spec,
                principal,
                params,
                ToolError.of(ErrorCode.UPSTREAM_ERROR, "The service did not respond correctly."),
                started,
            )

        response = ToolResponse(status="ok", speech=result.speech, detail=result.detail)
        return self._finish(spec, principal, params, response, started, decision="executed")

    def _refuse(
        self,
        spec: ToolSpec,
        principal: Principal | None,
        params: dict,
        error: ToolError,
        started: float,
    ) -> ToolResponse:
        # A refusal is an outcome worth tracing. The console must be able to show
        # what was attempted and why it did not run.
        response = ToolResponse(status="error", speech=error.message, error=error)
        return self._finish(spec, principal, params, response, started, decision="refused")

    def _finish(
        self,
        spec: ToolSpec,
        principal: Principal | None,
        params: dict,
        response: ToolResponse,
        started: float,
        *,
        decision: Literal["executed", "previewed", "refused", "no_change"],
    ) -> ToolResponse:
        elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
        # The trace stores the parameter hash, not the parameters. Raw values stay
        # in the request and, on Day 3, in the access-controlled audit row.
        event = self._state.trace.record(
            subject=principal.subject if principal else "anonymous",
            tool=spec.name,
            service=spec.service,
            params_hash=params_hash(params),
            status=response.status,
            decision=decision,
            ms=elapsed_ms,
            speech=response.speech,
        )
        # Embed the event in the response so Alexa+ and the console see the same
        # account of what happened.
        response.trace = [event]
        # One JSON line per call. No token, no raw parameters.
        logger.info(
            "tool_call",
            extra={
                "tool": spec.name,
                "service": spec.service,
                "subject": event.subject,
                "status": response.status,
                "decision": decision,
                "ok": event.ok,
                "ms": elapsed_ms,
                "params_hash": event.params_hash,
                "error_code": response.error.code if response.error else None,
                "trace_id": event.id,
            },
        )
        return response
