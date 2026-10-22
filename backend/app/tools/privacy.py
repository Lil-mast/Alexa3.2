"""`privacy_get` and `privacy_set`: the four privacy controls plus concise mode.

Every change goes through the router, so it is validated by the versioned rules
and written to the audit chain. `retention_days` is enforced immediately: setting
it tombstones older rows for this subject in the same call, which keeps the
promise visible instead of deferring it to a job that does not exist yet.

`privacy_get` uses the same `privacy:settings:write` scope. The token table has
no separate read grant for this resource, and inventing one here would leave the
advertised scopes disagreeing with the tested ones. Splitting it later is a
one-line change to the manifest and the token table.
"""

from __future__ import annotations

from app.auth import Principal
from app.models import ErrorCode, HandlerResult, RuleViolation, ToolError
from app.privacy import PrivacySettings
from app.state import AppState
from app.tools.specs import ToolSpec

GET_SPEC = ToolSpec(
    name="privacy_get",
    title="Read privacy settings",
    description=(
        "Read the current privacy and verbosity settings. Use when the user asks what is shared, "
        "whether personalization is on, how long details are kept, how listening works, or whether "
        "answers are concise. Do not use to change anything."
    ),
    service="privacy",
    scopes=["privacy:settings:write"],
    risk="low",
    reversible=True,
    read_only=True,
    idempotent=True,
    required=[],
)

SET_SPEC = ToolSpec(
    name="privacy_set",
    title="Change a privacy setting",
    description=(
        "Change one or more privacy or verbosity settings. Use when the user asks to stop or allow "
        "third-party sharing, turn personalization on or off, choose how long details are kept, "
        "choose wake word or continuous listening, or turn concise answers on or off. Supply only "
        "the settings the user actually asked to change. retention_days is 0, 7, 30, or 90. "
        "Turning third-party sharing off blocks room booking. Every change is audited."
    ),
    service="privacy",
    scopes=["privacy:settings:write"],
    risk="low",
    reversible=True,
    required=[],
    optional=["retention_days", "personalization", "microphone_mode", "third_party_sharing", "concise_mode"],
)

_FIELD_LABELS: dict[str, str] = {
    "retention_days": "Retention",
    "personalization": "Personalization",
    "microphone_mode": "Listening",
    "third_party_sharing": "Third-party sharing",
    "concise_mode": "Concise mode",
}


def _value(field: str, value: object) -> str:
    if field == "retention_days":
        return "no history" if value == 0 else f"{value} days"
    if field == "microphone_mode":
        return "wake word only" if value == "wake_word" else "continuous"
    return "on" if value else "off"


def _sentence(field: str, value: object) -> str:
    """One natural sentence per single-field change."""
    if field == "retention_days":
        return "No details will be kept." if value == 0 else f"Details are kept for {value} days."
    if field == "microphone_mode":
        return "Listening uses the wake word only." if value == "wake_word" else "Listening is continuous."
    if field == "third_party_sharing":
        return "Third-party sharing is off." if value is False else "Third-party sharing is on."
    if field == "personalization":
        return "Personalization is off." if value is False else "Personalization is on."
    return "Concise mode is on." if value is True else "Concise mode is off. I will include details."


def _describe(settings: PrivacySettings) -> str:
    sharing = "on" if settings.third_party_sharing else "off"
    personalization = "on" if settings.personalization else "off"
    listening = "wake word only" if settings.microphone_mode == "wake_word" else "continuous"
    retention = (
        "keeps no details" if settings.retention_days == 0 else f"keeps details for {settings.retention_days} days"
    )
    concise = "concise answers" if settings.concise_mode else "full details in every answer"
    return (
        f"Third-party sharing is {sharing}, personalization is {personalization}, "
        f"listening is {listening}, the server {retention}, and it gives {concise}."
    )


def get(params: dict, principal: Principal, state: AppState) -> HandlerResult:
    settings = state.privacy.get(principal.subject)
    return HandlerResult(
        speech=_describe(settings),
        detail=(
            f"Third-party sharing: {'on' if settings.third_party_sharing else 'off'}. "
            f"Personalization: {'on' if settings.personalization else 'off'}. "
            f"Microphone mode: {'wake word' if settings.microphone_mode == 'wake_word' else 'continuous'}. "
            f"Retention: {'no history' if settings.retention_days == 0 else f'{settings.retention_days} days'}. "
            f"Concise mode: {'on' if settings.concise_mode else 'off'}."
        ),
        # A read changes nothing, so it is not an undo candidate.
        decision="no_change",
    )


def set_settings(params: dict, principal: Principal, state: AppState) -> HandlerResult:
    if not params:
        raise RuleViolation(
            ToolError.of(
                ErrorCode.INVALID_PARAM,
                "Say which privacy setting to change.",
                follow_up="Ask which setting the user wants to change.",
            )
        )

    subject = principal.subject
    previous = state.privacy.get(subject)
    # A setting sent with the value it already has is not a change, so the call
    # reads as no_change rather than as an executed update. It also keeps an idle
    # privacy call out of the undo candidates.
    changed = {field: value for field, value in params.items() if getattr(previous, field) != value}
    if not changed:
        return HandlerResult(
            speech="Those settings are already in place.",
            detail="No privacy setting changed.",
            decision="no_change",
        )

    _, current = state.privacy.update(subject, changed)

    if "personalization" in changed and not current.personalization:
        # With personalization off there is no history to return, so drop what
        # was kept instead of leaving it unreadable but present.
        state.details.clear(subject)

    pruned = 0
    if "retention_days" in changed:
        pruned = state.audit.prune(subject, current.retention_days)

    if len(changed) == 1:
        field, value = next(iter(changed.items()))
        speech = _sentence(field, value)
    else:
        speech = f"Updated {len(changed)} privacy settings."

    changes = [
        (
            f"{_FIELD_LABELS[field]}: {_value(field, getattr(previous, field))} "
            f"to {_value(field, getattr(current, field))}."
        )
        for field in changed
    ]
    if pruned:
        changes.append(f"{pruned} older audit entr{'y' if pruned == 1 else 'ies'} replaced with tombstones.")
    return HandlerResult(speech=speech, detail=" ".join(changes))


__all__ = ["GET_SPEC", "SET_SPEC", "get", "set_settings"]
