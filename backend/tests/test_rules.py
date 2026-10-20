from __future__ import annotations

import pytest

from app.models import ErrorCode, RuleViolation
from app.rules import validate_params
from app.tools import lights, timers


def _violation(spec, params) -> RuleViolation:
    with pytest.raises(RuleViolation) as caught:
        validate_params(spec, params)
    return caught.value


def test_timer_params_pass_through():
    assert validate_params(timers.SPEC, {"duration_seconds": 600, "label": "pasta"}) == {
        "duration_seconds": 600,
        "label": "pasta",
    }


def test_timer_optional_label_is_omitted():
    assert validate_params(timers.SPEC, {"duration_seconds": 60, "label": None}) == {"duration_seconds": 60}


def test_timer_missing_duration_is_invalid():
    violation = _violation(timers.SPEC, {})
    assert violation.error.code is ErrorCode.INVALID_PARAM
    assert violation.error.field == "duration_seconds"


def test_timer_zero_is_out_of_bounds():
    violation = _violation(timers.SPEC, {"duration_seconds": 0})
    assert violation.error.code is ErrorCode.OUT_OF_BOUNDS
    assert "between 1 second and 24 hours" in violation.error.message


def test_timer_over_a_day_is_out_of_bounds():
    violation = _violation(timers.SPEC, {"duration_seconds": 86_401})
    assert violation.error.code is ErrorCode.OUT_OF_BOUNDS
    assert violation.error.allowed == [1, 86_400]


def test_timer_rejects_float_and_bool():
    # bool is an int subclass in Python, so this is the check most likely to
    # regress if someone simplifies the type validation.
    assert _violation(timers.SPEC, {"duration_seconds": 1.5}).error.code is ErrorCode.INVALID_PARAM
    assert _violation(timers.SPEC, {"duration_seconds": True}).error.code is ErrorCode.INVALID_PARAM


def test_timer_rejects_long_label():
    violation = _violation(timers.SPEC, {"duration_seconds": 60, "label": "x" * 65})
    assert violation.error.code is ErrorCode.INVALID_PARAM
    assert violation.error.field == "label"


def test_unknown_parameter_is_invalid():
    violation = _violation(timers.SPEC, {"duration_seconds": 60, "minutes": 10})
    assert violation.error.code is ErrorCode.INVALID_PARAM


def test_lights_room_enum():
    violation = _violation(lights.SPEC, {"room": "garage", "on": True})
    assert violation.error.code is ErrorCode.OUT_OF_BOUNDS
    assert "living room" in violation.error.message


def test_lights_brightness_bounds():
    assert validate_params(lights.SPEC, {"room": "office", "brightness": 0})["brightness"] == 0
    assert validate_params(lights.SPEC, {"room": "office", "brightness": 100})["brightness"] == 100
    violation = _violation(lights.SPEC, {"room": "office", "brightness": 101})
    assert violation.error.code is ErrorCode.OUT_OF_BOUNDS
