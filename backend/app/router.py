"""One execution path for MCP calls and tests: auth, rules, privacy,
confirmation, adapter, audit, response, trace.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from app.auth import Principal
from app.canonical import params_hash
from app.confirm import TokenStatus
from app.memory import Remembered
from app.models import ErrorCode, HandlerResult, Preview, RuleViolation, ToolError, ToolResponse
from app.rules import RULES, validate_params
from app.state import AppState
from app.tools import HANDLERS, REGISTRY
from app.tools.specs import ToolSpec

logger = logging.getLogger("alexa.calls")


class Router:
    """The only path from a tool call to an adapter.

    Order matters: identity, then scope, then parameters, then privacy, then
    confirmation, then execution, then audit and trace. Auth comes before
    validation so an unauthenticated caller cannot use error messages to learn the
    schema. Privacy comes before confirmation so a blocked external action never
    shows a preview the server would refuse to run. Confirmation comes after
    validation so a preview always describes a request that passed the rules.
    """

    def __init__(self, state: AppState) -> None:
        self._state = state

    def execute(
        self,
        tool_name: str,
        params: dict,
        principal: Principal | None,
        confirmation_token: str | None = None,
    ) -> ToolResponse:
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
        # use this specific tool. A read-only token should not set timers, and a
        # confirmation must not bypass the scope check.
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

        # Privacy comes after validation and before risk, per BUILD_PLAN.md
        # section 2. An external tool is refused before a preview is issued, so
        # a user with sharing off never sees a confirmation for an action the
        # server will not perform.
        if spec.external and not self._state.privacy.get(principal.subject).third_party_sharing:
            logger.warning(
                "privacy_blocked",
                extra={"tool": spec.name, "subject": principal.subject},
            )
            return self._refuse(
                spec,
                principal,
                clean,
                ToolError.of(
                    ErrorCode.PRIVACY_BLOCKED,
                    "That action needs third-party sharing, which is off.",
                    follow_up="Explain that third-party sharing is off and offer to turn it on.",
                ),
                started,
            )

        # Medium and high risk actions split into two calls: preview, then
        # execute with the token issued by that preview. Nothing below the token
        # check runs on the first call.
        requires_confirmation = spec.risk in {"medium", "high"}
        if requires_confirmation:
            if not confirmation_token or not confirmation_token.strip():
                return self._preview(spec, principal, clean, started)
            status = self._state.confirmations.verify(
                confirmation_token.strip(),
                subject=principal.subject,
                tool=spec.name,
                params_hash=params_hash(clean),
            )
            if status is not TokenStatus.OK:
                logger.warning(
                    "confirmation_rejected",
                    extra={
                        "tool": spec.name,
                        "subject": principal.subject,
                        "reason": status.value,
                        "params_hash": params_hash(clean),
                    },
                )
                return self._refuse(spec, principal, clean, self._token_error(status), started)

        try:
            # Handlers receive only validated, authorized, normalised parameters.
            # They own the state change and the wording; the router owns the rest.
            result = HANDLERS[spec.name](clean, principal, self._state)
        except RuleViolation as violation:
            return self._refuse(spec, principal, clean, violation.error, started)
        except Exception:
            # Adapter failures map to one stable code. The exception text stays in
            # the log; Alexa+ is told the service failed, never that it worked.
            logger.exception("adapter_error", extra={"tool": spec.name, "subject": principal.subject})
            return self._refuse(
                spec,
                principal,
                clean,
                ToolError.of(ErrorCode.UPSTREAM_ERROR, "The service did not respond correctly."),
                started,
            )

        if requires_confirmation:
            # Consume only after the adapter ran. A failed execution leaves the
            # token usable for a retry instead of forcing a new preview.
            self._state.confirmations.consume(confirmation_token or "")

        response = ToolResponse(status="ok", speech=result.speech, detail=result.detail)
        return self._finish(spec, principal, clean, response, started, decision=result.decision, result=result)

    def _preview(
        self,
        spec: ToolSpec,
        principal: Principal,
        clean: dict,
        started: float,
    ) -> ToolResponse:
        """Issue a token and describe the action without running it."""
        clean_hash = params_hash(clean)
        record = self._state.confirmations.issue(
            subject=principal.subject,
            tool=spec.name,
            params_hash=clean_hash,
        )
        effect = self._effect(spec, clean)
        response = ToolResponse(
            status="confirmation_required",
            speech=f"{effect}. Should I go ahead?",
            detail=(
                "Nothing has happened yet. This action is reversible."
                if spec.reversible
                else "Nothing has happened yet. This action cannot be undone."
            ),
            preview=Preview(
                service=spec.service,
                tool=spec.name,
                params=clean,
                effect=effect,
                irreversible=not spec.reversible,
            ),
            confirmation_token=record.token,
        )
        return self._finish(spec, principal, clean, response, started, decision="previewed")

    def _effect(self, spec: ToolSpec, clean: dict) -> str:
        # Enum labels and human dates make the preview speakable. If a template
        # does not match the parameters, fall back to a plain description rather
        # than failing the call.
        if not spec.confirmation_template:
            return f"Run {spec.name}"
        values = RULES.display_params(spec.name, clean)
        try:
            return spec.confirmation_template.format(**values).rstrip(".")
        except (KeyError, IndexError):
            return f"Run {spec.name}"

    def _token_error(self, status: TokenStatus) -> ToolError:
        # Each failure maps to a taxonomy code so Alexa+ knows whether to start
        # over or ask a different question.
        if status is TokenStatus.CONSUMED:
            return ToolError.of(
                ErrorCode.TOKEN_CONSUMED,
                "That confirmation was already used. Start a new request.",
            )
        if status is TokenStatus.MISMATCH:
            return ToolError.of(
                ErrorCode.INVALID_PARAM,
                "The request changed since it was previewed.",
                follow_up="Start the action again so the user can confirm the new details.",
            )
        return ToolError.of(
            ErrorCode.TOKEN_EXPIRED,
            "That confirmation has expired or is no longer valid. Start a new request.",
        )

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
        result: HandlerResult | None = None,
    ) -> ToolResponse:
        elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
        subject = principal.subject if principal else "anonymous"
        params_hash_value = params_hash(params)

        # Every decision, including a refusal and a preview, gets one audit row.
        # The row keeps the parameter hash and the minimal compensation state,
        # never the raw request. `compensator_of` links an undo to what it
        # reversed, so the record is a chain of actions, not just a log.
        row = self._state.audit.append(
            subject=subject,
            tool=spec.name,
            tool_version=spec.version,
            rules_version=RULES.version,
            service=spec.service,
            scopes_used=(result.scopes_used if result and result.scopes_used is not None else list(spec.scopes)),
            params_hash=params_hash_value,
            decision=decision,
            status=response.status,
            error_code=response.error.code.value if response.error else None,
            compensator_of=result.compensator_of if result else None,
            result_ref=result.result_ref if result else None,
            compensation=result.compensation if result else None,
        )
        response.audit_id = row.id

        # Concise mode is a server decision: the response carries the short
        # sentence and a flag that a longer detail exists. `tell_me_more` reads
        # the same text from memory, so Alexa+ can offer it without the server
        # repeating the work or the client inventing an answer.
        #
        # Only a handler result can be withheld. A preview's detail explains that
        # nothing has happened yet, and it is part of the confirmation contract
        # rather than an extra, so it is never replaced by a flag that points at
        # memory holding nothing.
        detail = result.detail if result else None
        if detail:
            if self._state.privacy.get(subject).personalization:
                self._state.details.remember(subject, Remembered(audit_id=row.id, tool=spec.name, detail=detail))
            if self._state.privacy.concise(subject):
                response.detail = None
                response.detail_available = True

        # The trace stores the parameter hash, not the parameters. Raw values stay
        # in the request and in the access-controlled audit row's compensation,
        # which is device state rather than user speech.
        event = self._state.trace.record(
            subject=subject,
            tool=spec.name,
            service=spec.service,
            params_hash=params_hash_value,
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
                "risk": spec.risk,
                "subject": event.subject,
                "status": response.status,
                "decision": decision,
                "ok": event.ok,
                "ms": elapsed_ms,
                "params_hash": event.params_hash,
                "error_code": response.error.code if response.error else None,
                "trace_id": event.id,
                "audit_id": row.id,
            },
        )
        return response
