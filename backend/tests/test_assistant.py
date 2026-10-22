"""Parser and assistant service tests.

These are the contract tests for the deterministic brain. They do not call a
model or the network. A parser change that quietly maps a new phrase to the
wrong tool should fail here before it reaches the console or a journey.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.assistant.parser import Clarification, Intent, is_affirmative, is_negative, parse
from app.assistant.service import AssistantService
from app.auth import Principal
from app.router import Router
from app.rules import RULES
from app.state import AppState
from tests.conftest import ALL_SCOPES, make_settings

TODAY = date(2026, 10, 21)


def _principal(subject: str = "test-user") -> Principal:
    return Principal(subject=subject, client_id="test-client", scopes=tuple(ALL_SCOPES))


def _assistant() -> tuple[AppState, AssistantService]:
    state = AppState(settings=make_settings())
    return state, AssistantService(Router(state))


@pytest.mark.parametrize(
    ("utterance", "tool", "params"),
    [
        ("set a ten minute timer", "timer_set", {"duration_seconds": 600}),
        ("set a 10-minute timer", "timer_set", {"duration_seconds": 600}),
        ("set a timer for an hour and a half", "timer_set", {"duration_seconds": 5400}),
        ("set a timer for the pasta", "timer_set", {"label": "pasta"}),
        (
            "dim the living room lights to 30 percent",
            "lights_set",
            {"room": "living_room", "brightness": 30, "on": True},
        ),
        (
            "dim the office lights to 30%",
            "lights_set",
            {"room": "office", "brightness": 30, "on": True},
        ),
        ("turn off the bedroom lights", "lights_set", {"room": "bedroom", "on": False}),
        ("set the thermostat to 35", "thermostat_set", {"zone": "living_room", "target_c": 35}),
        ("set the thermostat to 22\u00b0", "thermostat_set", {"zone": "living_room", "target_c": 22}),
        (
            "book the cedar room tomorrow at 1pm for 4 guests",
            "book_room",
            {"date": "2026-10-22", "room": "cedar", "start_time": "13:00", "guests": 4},
        ),
        ("turn off third party sharing", "privacy_set", {"third_party_sharing": False}),
        ("keep details for 7 days", "privacy_set", {"retention_days": 7}),
        ("what are my privacy settings", "privacy_get", {}),
        ("undo that", "undo", {}),
        ("tell me more", "tell_me_more", {}),
    ],
)
def test_parser_maps_example_phrases(utterance: str, tool: str, params: dict) -> None:
    result = parse(utterance, today=TODAY)

    assert isinstance(result, Intent)
    assert result.tool == tool
    assert result.params == params


@pytest.mark.parametrize(
    ("utterance", "reason"),
    [
        ("", "empty"),
        ("make me a sandwich", "unrecognised"),
        ("turn on the lights and set a timer", "multiple_intents"),
        ("turn on all the lights", "multiple_rooms"),
        ("what can you do", "help"),
    ],
)
def test_parser_asks_instead_of_guessing(utterance: str, reason: str) -> None:
    result = parse(utterance, today=TODAY)

    assert isinstance(result, Clarification)
    assert result.reason == reason
    assert result.speech


def test_affirmative_must_be_a_full_confirmation() -> None:
    assert is_affirmative("yes")
    assert is_affirmative("go ahead")
    assert is_affirmative("yes please")
    # A sentence that starts with yes and adds a new request is not a
    # confirmation. Confirming the wrong thing is worse than asking again.
    assert not is_affirmative("yes, set a timer")


def test_negative_must_be_a_full_refusal() -> None:
    assert is_negative("no")
    assert is_negative("cancel that")
    assert is_negative("no thanks")
    assert not is_negative("no, set a timer")


def test_booking_preview_then_confirm_is_audited() -> None:
    state, assistant = _assistant()
    principal = _principal()

    preview = assistant.turn("book the cedar room tomorrow at 1pm for 4 guests", principal)

    assert preview.status == "confirmation_required"
    assert preview.pending is not None
    assert preview.pending.tool == "book_room"
    assert preview.response is not None
    assert preview.response.confirmation_token
    assert state.audit.get(preview.audit_id).decision == "previewed"

    confirmed = assistant.turn("yes", principal)

    assert confirmed.status == "ok"
    assert confirmed.intent is not None and confirmed.intent.tool == "book_room"
    assert state.audit.get(confirmed.audit_id).decision == "executed"
    assert assistant.session(principal.subject) is None
    assert len(state.bookings.list_for(principal.subject)) == 1


def test_pending_action_blocks_a_new_command() -> None:
    state, assistant = _assistant()
    principal = _principal()

    preview = assistant.turn("book a room tomorrow", principal)
    assert preview.status == "confirmation_required"

    # A different request while the preview is open must not run. It repeats the
    # pending question so the user cannot accidentally book and set a timer.
    repeated = assistant.turn("set a timer for five minutes", principal)

    assert repeated.status == "confirmation_required"
    assert "Should I go ahead" in repeated.speech
    assert state.timers.list_for(principal.subject) == []


def test_cancel_drops_the_pending_action_without_an_audit_row() -> None:
    state, assistant = _assistant()
    principal = _principal()

    assistant.turn("book a room tomorrow", principal)
    rows_before = len(state.audit)

    cancelled = assistant.turn("no", principal)

    assert cancelled.status == "cancelled"
    assert assistant.session(principal.subject) is None
    # The preview row already exists. A cancellation is not a tool call, so it
    # does not invent a second decision.
    assert len(state.audit) == rows_before


def test_a_clarification_does_not_write_an_audit_row() -> None:
    state, assistant = _assistant()
    rows_before = len(state.audit)

    reply = assistant.turn("make me a sandwich", _principal())

    assert reply.status == "clarification"
    assert reply.audit_id is None
    assert len(state.audit) == rows_before


def test_expired_pending_action_is_forgotten() -> None:
    state = AppState(settings=make_settings())
    clock = {"now": datetime(2026, 10, 21, 12, 0, tzinfo=UTC)}
    assistant = AssistantService(Router(state), now=lambda: clock["now"])
    principal = _principal()

    preview = assistant.turn("book a room tomorrow", principal)
    assert preview.status == "confirmation_required"
    # The session store reads the same clock as the parser, so moving the clock
    # forward is enough to expire the pending action.
    clock["now"] = clock["now"] + timedelta(seconds=RULES.confirmation.ttl_seconds + 1)

    assert assistant.session(principal.subject) is None
    reply = assistant.turn("yes", principal)
    assert reply.status == "clarification"


def test_privacy_gate_refuses_booking_before_a_preview() -> None:
    state, assistant = _assistant()
    principal = _principal()

    assistant.turn("turn off third party sharing", principal)
    refused = assistant.turn("book a room tomorrow", principal)

    assert refused.status == "error"
    assert refused.response is not None
    assert refused.response.error is not None
    assert refused.response.error.code == "PRIVACY_BLOCKED"
    assert refused.response.confirmation_token is None
    assert state.bookings.list_for(principal.subject) == []


def test_confirm_and_cancel_methods_share_the_same_flow() -> None:
    state, assistant = _assistant()
    principal = _principal()

    preview = assistant.turn("book a room tomorrow", principal)
    assert preview.status == "confirmation_required"

    confirmed = assistant.confirm(principal)
    assert confirmed.status == "ok"
    assert assistant.session(principal.subject) is None

    assistant.turn("book a room tomorrow", principal)
    cancelled = assistant.cancel(principal)
    assert cancelled.status == "cancelled"
    assert assistant.session(principal.subject) is None
    assert len(state.bookings.list_for(principal.subject)) == 1
