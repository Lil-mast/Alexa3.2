from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters.booking import Booking
from app.audit import AuditLog
from app.auth import Principal
from app.models import ErrorCode
from app.router import Router
from app.state import AppState
from tests.conftest import ALL_SCOPES, make_settings


def _setup() -> tuple[Router, AppState]:
    state = AppState(settings=make_settings(), audit=AuditLog(seed_path=None))
    return Router(state), state


def _principal(*scopes: str, subject: str = "test-user") -> Principal:
    return Principal(subject=subject, client_id="test-client", scopes=tuple(scopes or ALL_SCOPES))


def _booking_date(days: int = 2) -> str:
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


def test_undo_cancels_the_last_timer():
    router, state = _setup()
    set_response = router.execute("timer_set", {"duration_seconds": 600}, _principal())
    assert len(state.timers.list_for("test-user")) == 1

    response = router.execute("undo", {}, _principal())

    assert response.status == "ok"
    assert response.speech == "Timer cancelled."
    assert state.timers.list_for("test-user") == []
    row = state.audit.get(response.audit_id or "")
    assert row is not None
    assert row.compensator_of == set_response.audit_id
    assert row.tool == "undo"
    # The undo relied on the same grant as the action it reversed.
    assert row.scopes_used == ["home:timers:write"]
    assert state.audit.verify().ok is True


def test_undo_restores_the_previous_light_state():
    router, state = _setup()
    router.execute("lights_set", {"room": "bedroom", "brightness": 80}, _principal())
    router.execute("lights_set", {"room": "bedroom", "brightness": 10}, _principal())

    response = router.execute("undo", {}, _principal())

    assert response.status == "ok"
    assert response.speech == "Bedroom lights back to 80 percent."
    assert state.lights.get("test-user", "bedroom").brightness == 80


def test_undo_restores_a_room_that_was_off():
    router, state = _setup()
    router.execute("lights_set", {"room": "kitchen", "brightness": 45}, _principal())
    router.execute("lights_set", {"room": "kitchen", "on": False}, _principal())

    response = router.execute("undo", {}, _principal())

    assert response.status == "ok"
    assert response.speech == "Kitchen lights back to 45 percent."
    assert state.lights.get("test-user", "kitchen").on is True


def test_undo_restores_the_previous_thermostat_setpoint():
    router, state = _setup()
    router.execute("thermostat_set", {"zone": "office", "target_c": 23}, _principal())
    router.execute("thermostat_set", {"zone": "office", "target_c": 26}, _principal())

    response = router.execute("undo", {}, _principal())

    assert response.status == "ok"
    assert response.speech == "Office thermostat back to 23 degrees."
    assert state.climate.get("test-user", "office").target_c == 23


def test_undo_cancels_a_booking():
    router, state = _setup()
    params = {"date": _booking_date(), "guests": 4}
    preview = router.execute("book_room", params, _principal())
    confirmed = router.execute(
        "book_room",
        params,
        _principal(),
        confirmation_token=preview.confirmation_token,
    )
    assert confirmed.status == "ok"

    response = router.execute("undo", {}, _principal())

    assert response.status == "ok"
    assert response.speech.startswith("Cancelled the Oak room booking on")
    assert state.bookings.list_for("test-user") == []
    row = state.audit.get(response.audit_id or "")
    assert row is not None
    assert row.compensator_of == confirmed.audit_id


def test_undo_skips_reads_and_refusals():
    router, _ = _setup()
    router.execute("lights_set", {"room": "office", "brightness": 60}, _principal())
    # Neither of these changes state, so neither is the action to reverse.
    router.execute("tell_me_more", {}, _principal())
    router.execute("privacy_get", {}, _principal())
    router.execute("thermostat_set", {"zone": "office", "target_c": 35}, _principal())

    response = router.execute("undo", {}, _principal())

    assert response.status == "ok"
    assert response.speech == "Office lights off again."


def test_undo_with_nothing_to_reverse_is_refused():
    router, _ = _setup()

    response = router.execute("undo", {}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.NOT_FOUND
    assert response.error.message == "There is nothing to undo."
    assert response.trace[0].decision == "refused"


def test_undo_twice_does_not_reverse_two_actions():
    router, state = _setup()
    router.execute("lights_set", {"room": "office", "brightness": 60}, _principal())
    router.execute("lights_set", {"room": "office", "brightness": 20}, _principal())

    first = router.execute("undo", {}, _principal())
    second = router.execute("undo", {}, _principal())

    assert first.status == "ok"
    assert state.lights.get("test-user", "office").brightness == 60
    assert second.status == "error"
    assert second.error is not None
    assert second.error.message == "The last action cannot be undone."
    # The older light change stays untouched.
    assert state.lights.get("test-user", "office").brightness == 60


def test_undo_targets_an_explicit_audit_id():
    router, state = _setup()
    first = router.execute("lights_set", {"room": "office", "brightness": 60}, _principal())
    router.execute("lights_set", {"room": "office", "brightness": 20}, _principal())

    response = router.execute("undo", {"audit_id": first.audit_id}, _principal())

    assert response.status == "ok"
    assert response.speech == "Office lights off again."
    assert state.lights.get("test-user", "office").on is False


def test_undo_rejects_another_users_audit_id():
    router, state = _setup()
    alice = _principal(subject="alice")
    response = router.execute("lights_set", {"room": "office", "brightness": 40}, alice)

    refused = router.execute("undo", {"audit_id": response.audit_id}, _principal(subject="bob"))

    assert refused.status == "error"
    assert refused.error is not None
    assert refused.error.code is ErrorCode.NOT_FOUND
    assert state.lights.get("alice", "office").brightness == 40


def test_undo_without_the_original_scope_changes_nothing():
    router, state = _setup()
    router.execute("lights_set", {"room": "office", "brightness": 70}, _principal())

    response = router.execute("undo", {}, _principal("home:timers:write"))

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.AUTH_REQUIRED
    assert state.lights.get("test-user", "office").brightness == 70


def test_undo_of_a_timer_that_already_finished_is_refused():
    router, state = _setup()
    created = router.execute("timer_set", {"duration_seconds": 60}, _principal())
    timer_id = state.timers.list_for("test-user")[0].id
    state.timers.cancel("test-user", timer_id)

    response = router.execute("undo", {"audit_id": created.audit_id}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.NOT_FOUND
    assert "no longer running" in response.error.message


def test_undo_of_a_booking_is_gated_by_third_party_sharing():
    router, state = _setup()
    params = {"date": _booking_date()}
    preview = router.execute("book_room", params, _principal())
    confirmed = router.execute(
        "book_room",
        params,
        _principal(),
        confirmation_token=preview.confirmation_token,
    )
    router.execute("privacy_set", {"third_party_sharing": False}, _principal())

    response = router.execute("undo", {"audit_id": confirmed.audit_id}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.PRIVACY_BLOCKED
    active: list[Booking] = state.bookings.list_for("test-user")
    assert len(active) == 1


def test_a_read_alone_leaves_nothing_to_undo():
    router, _ = _setup()
    router.execute("privacy_get", {}, _principal())

    response = router.execute("undo", {}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.message == "There is nothing to undo."
