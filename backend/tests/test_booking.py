from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.auth import Principal
from app.confirm import ConfirmationService
from app.models import ErrorCode
from app.router import Router
from app.speech import human_date
from app.state import AppState
from tests.conftest import ALL_SCOPES, make_settings


def _setup() -> tuple[Router, AppState]:
    state = AppState(settings=make_settings())
    return Router(state), state


def _principal(subject: str = "test-user") -> Principal:
    return Principal(subject=subject, client_id="test-client", scopes=tuple(ALL_SCOPES))


def _booking_date(days: int = 2) -> str:
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


def _preview(router: Router, params: dict, principal: Principal | None = None):
    return router.execute("book_room", params, principal or _principal())


def test_preview_returns_a_token_and_books_nothing():
    router, state = _setup()
    target = _booking_date()
    response = _preview(router, {"date": target, "guests": 4})

    assert response.status == "confirmation_required"
    assert response.error is None
    assert response.preview is not None
    assert response.preview.service == "booking"
    assert response.preview.tool == "book_room"
    assert response.preview.irreversible is False
    # Defaults are part of the preview, so the user sees the exact action.
    assert response.preview.params == {
        "date": target,
        "guests": 4,
        "room": "oak",
        "start_time": "09:00",
        "duration_minutes": 60,
    }
    assert response.preview.effect.startswith("Book the Oak room on")
    assert response.confirmation_token
    assert response.trace[0].decision == "previewed"
    assert response.trace[0].ok is False
    assert state.bookings.list_for("test-user") == []


def test_confirm_executes_once():
    router, state = _setup()
    params = {"date": _booking_date(), "guests": 4}
    preview = _preview(router, params)

    response = router.execute("book_room", params, _principal(), confirmation_token=preview.confirmation_token)

    assert response.status == "ok"
    assert response.error is None
    assert response.preview is None
    assert response.confirmation_token is None
    assert response.speech == f"Booked the Oak room on {human_date(params['date'])} at 9 AM for 1 hour."
    assert response.trace[0].decision == "executed"
    bookings = state.bookings.list_for("test-user")
    assert len(bookings) == 1
    assert bookings[0].guests == 4
    assert bookings[0].room == "oak"


def test_replay_is_refused():
    router, state = _setup()
    params = {"date": _booking_date(), "guests": 2}
    preview = _preview(router, params)
    token = preview.confirmation_token
    assert token

    first = router.execute("book_room", params, _principal(), confirmation_token=token)
    replay = router.execute("book_room", params, _principal(), confirmation_token=token)

    assert first.status == "ok"
    assert replay.status == "error"
    assert replay.error is not None
    assert replay.error.code is ErrorCode.TOKEN_CONSUMED
    assert replay.trace[0].decision == "refused"
    assert len(state.bookings.list_for("test-user")) == 1


def test_changed_parameters_are_refused_and_do_not_burn_the_token():
    router, state = _setup()
    params = {"date": _booking_date(), "guests": 2}
    preview = _preview(router, params)
    token = preview.confirmation_token
    assert token

    changed = router.execute(
        "book_room",
        {"date": params["date"], "guests": 6},
        _principal(),
        confirmation_token=token,
    )

    assert changed.status == "error"
    assert changed.error is not None
    assert changed.error.code is ErrorCode.INVALID_PARAM
    assert "changed since it was previewed" in changed.error.message
    assert state.bookings.list_for("test-user") == []

    # The original preview is still the action the user agreed to.
    original = router.execute("book_room", params, _principal(), confirmation_token=token)
    assert original.status == "ok"
    assert len(state.bookings.list_for("test-user")) == 1


def test_expired_token_is_refused():
    router, state = _setup()
    state.confirmations = ConfirmationService(ttl_seconds=0)
    target = _booking_date()
    preview = _preview(router, {"date": target})
    assert preview.confirmation_token

    response = router.execute(
        "book_room",
        {"date": target},
        _principal(),
        confirmation_token=preview.confirmation_token,
    )

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.TOKEN_EXPIRED
    assert state.bookings.list_for("test-user") == []


def test_unknown_token_is_refused():
    router, state = _setup()

    response = router.execute(
        "book_room",
        {"date": _booking_date()},
        _principal(),
        confirmation_token="not-a-real-token",
    )

    assert response.error is not None
    assert response.error.code is ErrorCode.TOKEN_EXPIRED
    assert state.bookings.list_for("test-user") == []


def test_another_users_token_cannot_confirm():
    router, state = _setup()
    target = _booking_date()
    preview = _preview(router, {"date": target}, _principal("alice"))
    assert preview.confirmation_token

    response = router.execute(
        "book_room",
        {"date": target},
        _principal("bob"),
        confirmation_token=preview.confirmation_token,
    )

    assert response.error is not None
    assert response.error.code is ErrorCode.TOKEN_EXPIRED
    assert state.bookings.list_for("bob") == []
    assert state.bookings.list_for("alice") == []


def test_a_failed_execution_does_not_consume_the_token():
    router, state = _setup()
    params = {"date": _booking_date(), "start_time": "10:00", "duration_minutes": 60}
    token = _preview(router, params).confirmation_token
    assert token

    first = router.execute("book_room", params, _principal(), confirmation_token=token)
    assert first.status == "ok"

    # The same slot is now taken. A second preview is issued, then confirmation
    # fails on the conflict, which must leave the token usable.
    retry_preview = _preview(router, params)
    conflict = router.execute(
        "book_room",
        params,
        _principal(),
        confirmation_token=retry_preview.confirmation_token,
    )
    assert conflict.status == "error"
    assert conflict.error is not None
    assert conflict.error.code is ErrorCode.INVALID_PARAM
    assert "already booked" in conflict.error.message

    booking = state.bookings.list_for("test-user")[0]
    state.bookings.cancel("test-user", booking.id)
    retry = router.execute(
        "book_room",
        params,
        _principal(),
        confirmation_token=retry_preview.confirmation_token,
    )
    assert retry.status == "ok"


def test_past_date_is_refused():
    router, state = _setup()
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()

    response = router.execute("book_room", {"date": yesterday}, _principal())

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.INVALID_PARAM
    assert response.error.field == "date"
    assert state.bookings.list_for("test-user") == []


def test_title_appears_in_detail():
    state = AppState(settings=make_settings())
    state.privacy.update("test-user", {"concise_mode": False})
    router = Router(state)
    params = {"date": _booking_date(), "title": "Design review"}
    preview = _preview(router, params)
    response = router.execute("book_room", params, _principal(), confirmation_token=preview.confirmation_token)

    assert response.status == "ok"
    assert "Design review" in (response.detail or "")
    assert "booking_" in (response.detail or "")


@pytest.mark.parametrize("start_time", ["09:00", "13:30"])
def test_booking_accepts_valid_times(start_time):
    router, _ = _setup()
    params = {"date": _booking_date(), "start_time": start_time}
    preview = _preview(router, params)

    assert preview.status == "confirmation_required"
    assert preview.error is None
