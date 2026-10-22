from __future__ import annotations

from app.auth import Principal
from app.models import ErrorCode
from app.router import Router
from app.state import AppState
from tests.conftest import ALL_SCOPES, make_settings


def _router(*, verbose: bool = False) -> Router:
    state = AppState(settings=make_settings())
    if verbose:
        # Detail is omitted under the default concise mode; turn it off when the
        # test is about the longer explanation rather than the spoken sentence.
        state.privacy.update("test-user", {"concise_mode": False})
    return Router(state)


def _principal(*scopes: str, subject: str = "test-user") -> Principal:
    return Principal(subject=subject, client_id="test-client", scopes=tuple(scopes))


def test_timer_set_executes_and_traces():
    router = _router(verbose=True)
    response = router.execute("timer_set", {"duration_seconds": 600}, _principal(*ALL_SCOPES))

    assert response.status == "ok"
    assert response.speech == "Timer set for 10 minutes."
    assert "timer_" in (response.detail or "")
    assert response.error is None
    assert len(response.trace) == 1
    event = response.trace[0]
    assert event.tool == "timer_set"
    assert event.service == "timers"
    assert event.decision == "executed"
    assert event.ok is True
    assert len(event.params_hash) == 64


def test_lights_dim():
    router = _router(verbose=True)
    response = router.execute("lights_set", {"room": "living_room", "brightness": 30}, _principal(*ALL_SCOPES))

    assert response.status == "ok"
    assert response.speech == "Living room lights set to 30 percent."
    assert "previously off" in (response.detail or "")


def test_lights_off_via_zero_brightness():
    router = _router()
    router.execute("lights_set", {"room": "office", "brightness": 80}, _principal(*ALL_SCOPES))
    response = router.execute("lights_set", {"room": "office", "brightness": 0}, _principal(*ALL_SCOPES))

    assert response.status == "ok"
    assert response.speech == "Office lights off."


def test_lights_requires_power_or_brightness():
    router = _router()
    response = router.execute("lights_set", {"room": "kitchen"}, _principal(*ALL_SCOPES))

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.INVALID_PARAM
    assert response.trace[0].decision == "refused"


def test_lights_rejects_off_with_brightness():
    response = _router().execute(
        "lights_set", {"room": "kitchen", "on": False, "brightness": 40}, _principal(*ALL_SCOPES)
    )

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.INVALID_PARAM


def test_missing_scope_refuses_without_side_effect():
    state = AppState(settings=make_settings())
    router = Router(state)
    response = router.execute("timer_set", {"duration_seconds": 60}, _principal("home:lights:write"))

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.AUTH_REQUIRED
    # The important half: a refused call must not create a timer.
    assert state.timers.list_for("test-user") == []


def test_unauthenticated_call_refuses():
    response = _router().execute("timer_set", {"duration_seconds": 60}, None)

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.AUTH_REQUIRED
    assert response.trace[0].subject == "anonymous"


def test_users_do_not_share_device_state():
    state = AppState(settings=make_settings())
    state.privacy.update("bob", {"concise_mode": False})
    router = Router(state)
    alice = _principal(*ALL_SCOPES, subject="alice")
    bob = _principal(*ALL_SCOPES, subject="bob")

    router.execute("lights_set", {"room": "bedroom", "brightness": 10}, alice)
    response = router.execute("lights_set", {"room": "bedroom", "on": True}, bob)

    assert response.detail is not None
    assert "previously off" in response.detail


def test_unknown_tool():
    response = _router().execute("door_unlock", {"door": "front"}, _principal(*ALL_SCOPES))

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.NOT_FOUND
    assert response.trace == []


def test_thermostat_set_executes():
    state = AppState(settings=make_settings())
    state.privacy.update("test-user", {"concise_mode": False})
    response = Router(state).execute("thermostat_set", {"zone": "office", "target_c": 22}, _principal(*ALL_SCOPES))

    assert response.status == "ok"
    assert response.speech == "Office set to 22 degrees."
    assert "previously 21" in (response.detail or "")
    assert response.trace[0].decision == "executed"


def test_thermostat_unchanged_is_no_change():
    response = _router().execute("thermostat_set", {"zone": "office", "target_c": 21}, _principal(*ALL_SCOPES))

    assert response.status == "ok"
    assert response.speech == "Office is already at 21 degrees."
    assert response.trace[0].decision == "no_change"


def test_thermostat_out_of_bounds():
    response = _router().execute("thermostat_set", {"zone": "office", "target_c": 35}, _principal(*ALL_SCOPES))

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code is ErrorCode.OUT_OF_BOUNDS
    assert "between 16 and 28 degrees Celsius" in response.error.message
