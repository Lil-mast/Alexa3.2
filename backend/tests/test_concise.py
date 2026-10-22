from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.audit import AuditLog
from app.auth import Principal
from app.models import ErrorCode
from app.router import Router
from app.state import AppState
from tests.conftest import ALL_SCOPES, make_settings


def _setup() -> tuple[Router, AppState]:
    state = AppState(settings=make_settings(), audit=AuditLog(seed_path=None))
    return Router(state), state


def _principal() -> Principal:
    return Principal(subject="test-user", client_id="test-client", scopes=tuple(ALL_SCOPES))


def _booking_date(days: int = 2) -> str:
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


def test_concise_mode_is_the_default_and_withholds_detail():
    router, _ = _setup()

    response = router.execute("timer_set", {"duration_seconds": 600}, _principal())

    assert response.status == "ok"
    assert response.speech == "Timer set for 10 minutes."
    assert response.detail is None
    assert response.detail_available is True


def test_tell_me_more_returns_the_withheld_detail():
    router, state = _setup()
    first = router.execute("timer_set", {"duration_seconds": 600, "label": "pasta"}, _principal())

    response = router.execute("tell_me_more", {}, _principal())

    assert response.status == "ok"
    assert response.speech.startswith("Timer 'pasta' set for 10:00")
    assert "timer_" in response.speech
    # The answer is the detail, so it is not offered a second time.
    assert response.detail is None
    assert response.detail_available is False
    row = state.audit.get(response.audit_id or "")
    assert row is not None
    assert row.tool == "tell_me_more"
    assert row.decision == "no_change"
    assert first.audit_id is not None


def test_tell_me_more_can_target_an_audit_id():
    router, _ = _setup()
    lights = router.execute("lights_set", {"room": "office", "brightness": 30}, _principal())
    router.execute("timer_set", {"duration_seconds": 60}, _principal())

    response = router.execute("tell_me_more", {"audit_id": lights.audit_id}, _principal())

    assert response.status == "ok"
    assert "Office lights are now on at 30 percent" in response.speech


def test_turning_concise_mode_off_includes_detail():
    router, _ = _setup()
    router.execute("privacy_set", {"concise_mode": False}, _principal())

    response = router.execute("thermostat_set", {"zone": "office", "target_c": 22}, _principal())

    assert response.detail is not None
    assert "previously 21" in response.detail
    assert response.detail_available is False


def test_tell_me_more_without_history_is_refused():
    router, _ = _setup()

    response = router.execute("tell_me_more", {}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.NOT_FOUND
    assert response.error.message == "There is nothing more to tell about that."


def test_personalization_off_clears_history_and_refuses_detail():
    router, state = _setup()
    router.execute("timer_set", {"duration_seconds": 600}, _principal())
    router.execute("privacy_set", {"personalization": False}, _principal())

    response = router.execute("tell_me_more", {}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.NOT_FOUND
    assert "Personalization is off" in response.error.message
    assert state.details.latest("test-user") is None


def test_personalization_off_ignores_a_stored_verbose_preference():
    router, _ = _setup()
    # Set the verbose preference first, then turn personalization off. The
    # presented preference must not survive as a way around the default.
    router.execute("privacy_set", {"concise_mode": False}, _principal())
    router.execute("privacy_set", {"personalization": False}, _principal())

    response = router.execute("lights_set", {"room": "office", "on": True}, _principal())

    assert response.detail is None
    assert response.detail_available is True


def test_a_preview_keeps_its_detail_because_it_is_the_confirmation():
    router, _ = _setup()

    response = router.execute("book_room", {"date": _booking_date()}, _principal())

    assert response.status == "confirmation_required"
    assert response.detail is not None
    assert "Nothing has happened yet" in response.detail
    # A preview is not an action, so it is not offered as a detail to fetch.
    assert response.detail_available is False


def test_each_action_keeps_its_own_detail():
    router, _ = _setup()
    first = router.execute("timer_set", {"duration_seconds": 60, "label": "tea"}, _principal())
    second = router.execute("timer_set", {"duration_seconds": 600, "label": "pasta"}, _principal())

    older = router.execute("tell_me_more", {"audit_id": first.audit_id}, _principal())
    newer = router.execute("tell_me_more", {"audit_id": second.audit_id}, _principal())

    assert "Timer 'tea'" in older.speech
    assert "Timer 'pasta'" in newer.speech
