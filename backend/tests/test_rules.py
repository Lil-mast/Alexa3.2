from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.booking import BOOKING_ROOMS
from app.adapters.rooms import ROOMS
from app.models import ErrorCode, RuleViolation
from app.rules import RULES, validate_params
from app.tools import booking, lights, thermostat, timers

FUTURE_DATE = (datetime.now(UTC).date() + timedelta(days=5)).isoformat()


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


def test_rules_are_versioned_data():
    # The rules are in YAML, loaded once, and versioned independently of code.
    assert RULES.version == "3"
    assert RULES.confirmation.ttl_seconds == 300
    assert RULES.for_tool("thermostat_set").fields["target_c"].min == 16


def test_retention_days_is_a_closed_integer_set():
    # Day 3 adds the first integer enum. A range check would accept 1 day.
    from app.tools import privacy

    assert validate_params(privacy.SET_SPEC, {"retention_days": 7}) == {"retention_days": 7}
    violation = _violation(privacy.SET_SPEC, {"retention_days": 1})
    assert violation.error.code is ErrorCode.OUT_OF_BOUNDS
    assert "0, 7, 30, or 90 days" in violation.error.message
    assert violation.error.allowed == [0, 7, 30, 90]


def test_yaml_enums_match_the_adapters():
    # Drift between a reviewed rule and a simulated device is a silent bug. This
    # turns it into a failing test.
    assert set(RULES.for_tool("lights_set").fields["room"].enum or []) == set(ROOMS)
    assert set(RULES.for_tool("thermostat_set").fields["zone"].enum or []) == set(ROOMS)
    assert set(RULES.for_tool("book_room").fields["room"].enum or []) == set(BOOKING_ROOMS)


def test_thermostat_bounds_come_from_yaml():
    assert validate_params(thermostat.SPEC, {"zone": "office", "target_c": 16})["target_c"] == 16
    assert validate_params(thermostat.SPEC, {"zone": "office", "target_c": 28})["target_c"] == 28
    violation = _violation(thermostat.SPEC, {"zone": "office", "target_c": 35})
    assert violation.error.code is ErrorCode.OUT_OF_BOUNDS
    assert "between 16 and 28 degrees Celsius" in violation.error.message


def test_booking_optional_defaults_are_applied_before_hashing():
    # Defaults are part of the effective action, so the preview and the
    # confirmation hash the same parameter set.
    assert validate_params(booking.SPEC, {"date": FUTURE_DATE}) == {
        "date": FUTURE_DATE,
        "room": "oak",
        "start_time": "09:00",
        "duration_minutes": 60,
        "guests": 1,
    }


def test_booking_rejects_malformed_date_and_time():
    date_violation = _violation(booking.SPEC, {"date": "Friday"})
    assert date_violation.error.code is ErrorCode.INVALID_PARAM
    assert date_violation.error.field == "date"

    time_violation = _violation(booking.SPEC, {"date": FUTURE_DATE, "start_time": "2 PM"})
    assert time_violation.error.code is ErrorCode.INVALID_PARAM
    assert time_violation.error.field == "start_time"


def test_booking_rejects_a_past_date():
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    violation = _violation(booking.SPEC, {"date": yesterday})
    assert violation.error.code is ErrorCode.INVALID_PARAM
    assert violation.error.field == "date"
    assert "today or later" in violation.error.message


def test_booking_rejects_impossible_calendar_date():
    violation = _violation(booking.SPEC, {"date": "2026-02-31"})
    assert violation.error.code is ErrorCode.INVALID_PARAM
    assert "real calendar date" in violation.error.message
