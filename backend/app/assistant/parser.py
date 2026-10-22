"""Deterministic utterance parser, the local stand-in for Alexa+'s intent layer.

This module is deliberately not a language model. It is a small, reviewable set of
patterns that map the spoken phrases to the tool calls Alexa+ would make.
The real assistant still owns intent in production. This parser exists so the
console, the journeys, and a local run can drive the same router without a
model, a network call, or a second source of truth.

Two rules keep it honest:

- It never invents a value that the router would accept silently. When a phrase
  is ambiguous it returns a clarification instead of guessing.
- It never changes state. It returns parameters, and `Router.execute` validates
  them against `rules.yaml` and writes the audit row, exactly as it does for a
  call that arrives over MCP.

The parser is pure: same utterance and same date produce the same result. That is
what makes the journeys repeatable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Intent:
    """A tool call the parser believes the user asked for.

    `params` are raw. They are not validated here on purpose: the router is the
    only place that can turn parameters into a decision, and a parser that
    pre-validated would duplicate the rules file.
    """

    tool: str
    params: dict[str, Any]
    rationale: str


@dataclass(frozen=True)
class Clarification:
    """A request the parser will not guess at.

    `speech` is ready to show or speak. `suggestions` are example phrases, not
    commands that were executed.
    """

    speech: str
    suggestions: tuple[str, ...] = ()
    reason: str = "unrecognised"


ParseResult = Intent | Clarification

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

# Spoken numbers are converted before the pattern matching so one duration rule
# handles "ten minutes" and "10 minutes" without a second grammar.
_UNITS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS: dict[str, int] = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | {"hundred", "and"}

_WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_PATTERN = "|".join(_MONTHS)

# Room names are a closed set in rules.yaml. The parser only maps the spoken
# synonyms; it never adds a room the rules would reject.
_ROOM_SYNONYMS: dict[str, str] = {
    "living room": "living_room",
    "livingroom": "living_room",
    "lounge": "living_room",
    "front room": "living_room",
    "bedroom": "bedroom",
    "bed room": "bedroom",
    "master bedroom": "bedroom",
    "kitchen": "kitchen",
    "office": "office",
    "study": "office",
}
_BOOKING_ROOMS: dict[str, str] = {"oak": "oak", "cedar": "cedar", "maple": "maple"}

_DURATION_UNIT = r"(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)"


def normalise(utterance: str) -> str:
    """Lowercase and flatten an utterance without losing times or decimals.

    Hyphens between letters become spaces so "ten-minute" reads like "ten
    minute". Hyphens between digits stay, because a date such as 2026-10-24 and
    a negative number both need them. Percent and degree signs are kept so the
    value parsers see the unit. Punctuation that carries no meaning for the
    parser is removed so "what's the thermostat set to?" and "what is the
    thermostat set to" match the same pattern.
    """
    text = utterance.strip().lower().replace("\u2019", "'")
    text = text.replace("p.m.", "pm").replace("a.m.", "am")
    # "2.30pm" is a common spoken-time transcription. Normalise it before the
    # generic punctuation pass, which would otherwise split the minutes off.
    text = re.sub(r"\b(\d{1,2})\.(\d{2})\s*(am|pm)\b", r"\1:\2\3", text)
    # A hyphen between a letter or digit and a letter becomes a space, so
    # "ten-minute" and "10-minute" both read as a duration. Hyphens between
    # digits stay, because 2026-10-24 is a date and -5 is a temperature.
    text = re.sub(r"(?<=[a-z0-9])-(?=[a-z])", " ", text)
    text = re.sub(r"[^a-z0-9\s:'%.\-\u00b0]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .")


def _is_number_word(token: str) -> bool:
    return token in _NUMBER_WORDS


def _number_at(tokens: list[str], start: int) -> tuple[int | None, int]:
    """Read one number phrase starting at `start`.

    Handles "twenty five", "one hundred and five", and a bare digit sequence is
    left to the regexes. The returned count lets the caller skip the words it
    consumed. A stray "and" is only consumed when a number follows it, so "one
    and the lights" does not swallow the command.
    """
    total = 0
    current = 0
    consumed = 0
    index = start
    while index < len(tokens):
        token = tokens[index]
        if token in _UNITS:
            current += _UNITS[token]
        elif token in _TENS:
            current += _TENS[token]
        elif token == "hundred":
            current = max(1, current) * 100
        elif token == "and" and consumed > 0 and index + 1 < len(tokens) and _is_number_word(tokens[index + 1]):
            pass
        else:
            break
        consumed += 1
        index += 1

    if consumed == 0:
        return None, 0
    return total + current, consumed


def words_to_digits(text: str) -> str:
    """Replace spoken numbers with digits, leaving the rest of the sentence alone."""
    tokens = text.split()
    result: list[str] = []
    index = 0
    while index < len(tokens):
        value, consumed = _number_at(tokens, index)
        if value is None:
            result.append(tokens[index])
            index += 1
        else:
            result.append(str(value))
            index += consumed
    return " ".join(result)


# ---------------------------------------------------------------------------
# Small value parsers
# ---------------------------------------------------------------------------


def parse_duration_seconds(text: str) -> int | None:
    """Read a duration phrase such as "10 minutes" or "1 hour 30 minutes"."""
    if re.search(r"\bhalf an hour\b", text):
        return 1800
    if re.search(r"\bquarter (?:of an )?hour\b", text):
        return 900
    if re.search(r"\b(?:an?|one|1) hour and a half\b", text):
        return 5400
    if re.search(r"\b(?:a|one|1) minute and a half\b", text):
        return 90

    digits = words_to_digits(text)
    total = 0.0
    found = False
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*" + _DURATION_UNIT + r"\b", digits):
        found = True
        value = float(match.group(1))
        unit = match.group(2)
        if unit.startswith("h"):
            total += value * 3600
        elif unit.startswith("m"):
            total += value * 60
        else:
            total += value
    if found:
        return round(total)

    # "a minute" and "an hour" are common enough to deserve their own patterns.
    if re.search(r"\ban? hour\b", digits):
        return 3600
    if re.search(r"\ban? minute\b", digits):
        return 60
    return None


def parse_percent(text: str) -> int | None:
    """Read a brightness percentage.

    A percentage sign is unambiguous. A bare number is only treated as a
    percentage when the sentence is clearly about lights, so "book for 4" is not
    mistaken for brightness.
    """
    match = re.search(r"\b(\d{1,3})\s*(?:%|percent\b|per cent\b)", text)
    if match:
        return int(match.group(1))
    if re.search(r"\blights?\b|\bbrightness\b|\bdim\b", text):
        match = re.search(r"\b(?:to|at)\s+(\d{1,3})\b", text)
        if match:
            return int(match.group(1))
        match = re.search(r"\bbrightness\s+(\d{1,3})\b", text)
        if match:
            return int(match.group(1))
    return None


def parse_temperature(text: str) -> int | None:
    """Read a thermostat setpoint in Celsius."""
    match = re.search(r"\b(-?\d{1,3})\s*(?:degrees?\b|deg\b|c\b|celsius\b|\u00b0)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(?:to|at)\s+(-?\d{1,3})\b", text)
    if match:
        return int(match.group(1))
    return None


def _assume_meridiem(hour: int) -> int:
    """Choose a sensible half of the day for a bare hour.

    A scheduling phrase such as "book at two" almost always means the
    afternoon. Hours 1 to 6 become 13:00 to 18:00. Hours 7 to 11 stay morning.
    Noon and midnight stay as written. The rule is documented here because it is
    a product choice, not a language fact.
    """
    if 1 <= hour <= 6:
        return hour + 12
    return hour


def parse_clock_time(text: str) -> str | None:
    """Read a time of day and return 24-hour HH:MM, or None."""
    digits = words_to_digits(text)
    if re.search(r"\bnoon\b", digits):
        return "12:00"
    if re.search(r"\bmidnight\b", digits):
        return "00:00"

    match = re.search(r"\bhalf past\s+(\d{1,2})\b", digits)
    if match:
        hour = _assume_meridiem(int(match.group(1)))
        return f"{hour:02d}:30"
    match = re.search(r"\bquarter past\s+(\d{1,2})\b", digits)
    if match:
        hour = _assume_meridiem(int(match.group(1)))
        return f"{hour:02d}:15"
    match = re.search(r"\bquarter to\s+(\d{1,2})\b", digits)
    if match:
        hour = _assume_meridiem(int(match.group(1))) - 1
        if hour < 0:
            hour = 23
        return f"{hour:02d}:45"

    # 12-hour clock first, so "2:30pm" is not read as 02:30 by the 24-hour rule.
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", digits)
    if match:
        hour = int(match.group(1)) % 12
        minute = int(match.group(2) or 0)
        if match.group(3) == "pm":
            hour += 12
        return f"{hour:02d}:{minute:02d}"

    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", digits)
    if match:
        hour = _assume_meridiem(int(match.group(1)))
        return f"{hour:02d}:{match.group(2)}"

    # "at two", "from 9". The meridiem rule above makes this predictable.
    match = re.search(r"\b(?:at|from)\s+(\d{1,2})\b", digits)
    if match:
        hour = int(match.group(1))
        if 0 <= hour <= 23:
            return f"{_assume_meridiem(hour):02d}:00"
    return None


def parse_date(text: str, today: date) -> date | None:
    """Read a calendar date relative to `today`.

    Supported forms: ISO dates, today, tomorrow, the day after tomorrow, weekday
    names, "next <weekday>", month and day in either order, and numeric
    month/day. A date in the past is still returned, so the rules can refuse it
    with the same message whether the user typed it or said it.
    """
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    digits = words_to_digits(text)
    if re.search(r"\bday after tomorrow\b", digits):
        return today + timedelta(days=2)
    if re.search(r"\btomorrow\b", digits):
        return today + timedelta(days=1)
    if re.search(r"\btoday\b", digits):
        return today

    for name, weekday in _WEEKDAYS.items():
        if re.search(rf"\b(?:next\s+)?{name}\b", digits):
            delta = (weekday - today.weekday()) % 7
            if delta == 0 and re.search(rf"\bnext\s+{name}\b", digits):
                delta = 7
            return today + timedelta(days=delta)

    match = re.search(rf"\b({_MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", digits)
    if match is None:
        match = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})\b", digits)
        if match is not None:
            month, day = _MONTHS[match.group(2)], int(match.group(1))
        else:
            month, day = 0, 0
    else:
        month, day = _MONTHS[match.group(1)], int(match.group(2))
    if month:
        try:
            candidate = date(today.year, month, day)
        except ValueError:
            return None
        return candidate if candidate >= today else candidate.replace(year=today.year + 1)

    match = re.search(r"\b(\d{1,2})/(\d{1,2})\b", digits)
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        # US month/day order first. If the first number cannot be a month, swap.
        month, day = (first, second) if first <= 12 else (second, first)
        try:
            candidate = date(today.year, month, day)
        except ValueError:
            return None
        return candidate if candidate >= today else candidate.replace(year=today.year + 1)
    return None


def _find_rooms(text: str) -> list[str]:
    """Return every room named, in order of first appearance in the text."""
    found: list[tuple[int, str]] = []
    for phrase in sorted(_ROOM_SYNONYMS, key=len, reverse=True):
        match = re.search(rf"\b{re.escape(phrase)}\b", text)
        if match and _ROOM_SYNONYMS[phrase] not in {value for _, value in found}:
            found.append((match.start(), _ROOM_SYNONYMS[phrase]))
    return [value for _, value in sorted(found)]


def _find_booking_room(text: str) -> str | None:
    for name, value in _BOOKING_ROOMS.items():
        if re.search(rf"\b{name}\b", text):
            return value
    return None


def _parse_guests(text: str) -> int | None:
    match = re.search(r"\bparty of\s+(\d{1,2})\b", text)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{1,2})\s*(?:guests?|people|persons?)\b", text)
    if match:
        return int(match.group(1))
    match = re.search(r"\bfor\s+(\d{1,2})\s*$", text)
    if match:
        return int(match.group(1))
    return None


def _parse_title(text: str) -> str | None:
    match = re.search(r"\btitled\s+(.+)$", text)
    if match:
        return match.group(1).strip()[:64]
    return None


def _timer_label(text: str) -> str | None:
    """Extract a label such as "pasta" from "timer for the pasta".

    Duration phrases and bare numbers are rejected so "timer for 10 minutes"
    does not become a timer named "10 minutes". The rule engine still enforces
    the 64 character limit.
    """
    candidates: list[str] = []
    match = re.search(r"\btimer\s+(?:for|named|called)\s+(?:the\s+)?([a-z0-9 ']{1,64})$", text)
    if match:
        candidates.append(match.group(1))
    match = re.search(r"\b([a-z]+)\s+timer\b", text)
    if match:
        candidates.append(match.group(1))

    stop_words = _NUMBER_WORDS | {"a", "an", "the", "set", "start", "minute", "minutes", "hour", "hours"}
    for candidate in candidates:
        cleaned = candidate.strip()
        if not cleaned or cleaned in stop_words:
            continue
        if re.search(r"\d", cleaned):
            continue
        if re.search(r"\b(minute|minutes|hour|hours|second|seconds|min|mins|sec|secs)\b", cleaned):
            continue
        return cleaned
    return None


def _toggle_value(text: str) -> bool | None:
    if re.search(r"\b(off|disable|disabled|stop|block|no)\b", text):
        return False
    if re.search(r"\b(on|enable|enabled|allow|yes)\b", text):
        return True
    return None


# ---------------------------------------------------------------------------
# Intent families
# ---------------------------------------------------------------------------


def _families(text: str) -> set[str]:
    """Which tool families a sentence mentions.

    More than one family means the sentence asks for two actions. The assistant does
    one thing per turn, so the parser asks which one instead of silently
    dropping the second. This is the main guard against a plausible but wrong
    tool call.
    """
    families: set[str] = set()
    if re.search(r"\btimer\b|\bcountdown\b", text):
        families.add("timer")
    if re.search(r"\blights?\b|\bdim\b|\bbrighten\b|\blamp\b", text):
        families.add("lights")
    if re.search(r"\bthermostat\b|\btemperature\b|\bdegrees?\b|\bheat\b|\bcool\b", text):
        families.add("thermostat")
    if re.search(r"\bbook\b|\breserve\b|\bmeeting room\b", text):
        families.add("booking")
    if re.search(r"\bundo\b|\brevert\b|\btake that back\b", text):
        families.add("undo")
    if re.search(
        r"\bprivacy\b|\bpersonalization\b|\bpersonalisation\b|\bshar(?:e|ing)\b|\bconcise\b|\bretention\b",
        text,
    ):
        families.add("privacy")
    if re.search(r"\btell me more\b|\bmore detail", text):
        families.add("details")
    return families


def _clarify(message: str, *suggestions: str, reason: str = "unrecognised") -> Clarification:
    return Clarification(speech=message, suggestions=suggestions, reason=reason)


def _privacy_get(text: str) -> Intent | None:
    """A privacy question reads state; a privacy instruction changes it."""
    question = re.match(r"^(what|how|is|are|am|do|does|show|tell)\b", text)
    field = re.search(
        r"\b(privacy|personalization|personalisation|shar(?:e|ing)|retention|concise|microphone|listening|history)\b",
        text,
    )
    if question and field:
        return Intent("privacy_get", {}, "privacy question")
    if re.search(r"\b(how long do you keep|what do you keep|what do you share)\b", text):
        return Intent("privacy_get", {}, "privacy question")
    return None


def _retention_days(text: str) -> int | None:
    if re.search(r"\b(no history|keep no|don't keep|do not keep|delete)\b", text):
        return 0
    match = re.search(r"\b(\d{1,3})\s*days?\b", text)
    if match:
        return int(match.group(1))
    if re.search(r"\bweek\b", text):
        return 7
    if re.search(r"\bmonth\b", text):
        return 30
    match = re.search(r"\bretention\b[^0-9]*(\d{1,3})\b", text)
    if match:
        return int(match.group(1))
    return None


def _privacy_set(text: str) -> Intent | Clarification | None:
    changes: dict[str, Any] = {}

    if re.search(r"\bthird party\b|\bshar(?:e|ing)\b", text):
        value = _toggle_value(text)
        if value is not None:
            changes["third_party_sharing"] = value
    if re.search(r"\bpersonalization\b|\bpersonalisation\b|\bpersonalized\b", text):
        value = _toggle_value(text)
        if value is not None:
            changes["personalization"] = value
    if re.search(r"\bconcise\b|\bshort answers?\b|\bbrief answers?\b", text):
        value = _toggle_value(text)
        # "be concise" and "keep it brief" are instructions, not questions.
        if value is None and re.search(r"\b(be|make|keep)\b", text):
            value = True
        if value is not None:
            changes["concise_mode"] = value
    if "wake word" in text:
        changes["microphone_mode"] = "wake_word"
    elif "continuous" in text or "always listening" in text:
        # "turn off continuous listening" means wake word only, not continuous.
        changes["microphone_mode"] = "wake_word" if _toggle_value(text) is False else "continuous"
    if re.search(r"\bretention\b|\bkeep details\b|\bkeep history\b|\bdelete my history\b|\bno history\b", text):
        days = _retention_days(text)
        if days is not None:
            changes["retention_days"] = days

    if changes:
        return Intent("privacy_set", changes, "privacy control phrase")

    # The user named a privacy control but not a direction. Ask instead of
    # toggling something the wrong way.
    if re.search(
        r"\b(third party sharing|sharing|personalization|personalisation|concise|retention|microphone|listening)\b",
        text,
    ):
        return _clarify(
            "Should I turn that on or off?",
            "turn off third party sharing",
            "turn on concise mode",
            reason="missing_privacy_value",
        )
    return None


def _timer_intent(text: str) -> Intent | None:
    if not re.search(r"\btimer\b|\bcountdown\b", text):
        return None
    params: dict[str, Any] = {}
    seconds = parse_duration_seconds(text)
    if seconds is None:
        # "timer for 10" without a unit is conventionally minutes. The rule
        # engine still checks the 1 second to 24 hour bounds.
        match = re.search(r"\btimer\s+for\s+(\d{1,4})\b", words_to_digits(text))
        if match:
            seconds = int(match.group(1)) * 60
    if seconds is not None:
        params["duration_seconds"] = seconds
    label = _timer_label(text)
    if label:
        params["label"] = label
    return Intent("timer_set", params, "timer phrase")


def _lights_intent(text: str) -> Intent | Clarification | None:
    trigger = re.search(r"\blights?\b|\bdim\b|\bbrighten\b|\blamp\b", text)
    if trigger is None:
        return None
    if re.search(r"\ball\b", text):
        return _clarify(
            "I can change one room at a time. Which room?",
            "dim the living room lights",
            "turn off the kitchen lights",
            reason="multiple_rooms",
        )
    rooms = _find_rooms(text)
    if len(rooms) > 1:
        return _clarify(
            "I can change one room at a time. Which room?",
            "dim the living room lights",
            "turn off the kitchen lights",
            reason="multiple_rooms",
        )
    room = rooms[0] if rooms else "living_room"

    params: dict[str, Any] = {"room": room}
    on: bool | None = None
    if re.search(r"\boff\b", text):
        on = False
    elif re.search(r"\bon\b", text):
        on = True
    if "dim" in text:
        on = True
        params["brightness"] = 30
    if "brighten" in text:
        on = True
        params["brightness"] = 80

    percent = parse_percent(text)
    if percent is not None:
        params["brightness"] = percent
        on = percent > 0
    if on is not None:
        params["on"] = on
    return Intent("lights_set", params, "room and lighting phrase")


def _thermostat_intent(text: str) -> Intent | Clarification | None:
    has_climate_word = re.search(r"\bthermostat\b|\btemperature\b|\bdegrees?\b|\bheat\b|\bcool\b", text)
    if has_climate_word is None:
        return None
    rooms = _find_rooms(text)
    if len(rooms) > 1:
        return _clarify(
            "I can set one zone at a time. Which room?",
            "set the living room thermostat to 22",
            reason="multiple_rooms",
        )
    zone = rooms[0] if rooms else "living_room"
    params: dict[str, Any] = {"zone": zone}
    target = parse_temperature(text)
    if target is not None:
        params["target_c"] = target
    return Intent("thermostat_set", params, "climate phrase")


def _booking_intent(text: str, today: date) -> Intent | None:
    if not re.search(r"\bbook\b|\breserve\b|\bmeeting room\b", text):
        return None
    params: dict[str, Any] = {}
    day = parse_date(text, today)
    if day is not None:
        params["date"] = day.isoformat()
    room = _find_booking_room(text)
    if room is not None:
        params["room"] = room
    start = parse_clock_time(text)
    if start is not None:
        params["start_time"] = start
    seconds = parse_duration_seconds(text)
    if seconds is not None:
        params["duration_minutes"] = max(1, round(seconds / 60))
    guests = _parse_guests(text)
    if guests is not None:
        params["guests"] = guests
    title = _parse_title(text)
    if title:
        params["title"] = title
    return Intent("book_room", params, "booking phrase")


def _undo_intent(text: str) -> Intent | None:
    if re.search(
        r"\bundo\b|\brevert\b|\btake that back\b|\bcancel that\b"
        r"|\bcancel the (timer|booking|light|lights|thermostat)\b",
        text,
    ):
        return Intent("undo", {}, "undo phrase")
    return None


def _details_intent(text: str) -> Intent | None:
    if re.search(r"\btell me more\b|\bmore details?\b|\bwhat else\b|\bexplain (that|it)\b|\bwhat did you do\b", text):
        return Intent("tell_me_more", {}, "detail follow-up")
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def is_affirmative(utterance: str) -> bool:
    """True only for a full confirmation, not a sentence that starts with yes.

    "yes" confirms a pending booking. "yes, set a timer" does not, because it
    contains a second request and confirming the wrong thing is worse than
    asking again.
    """
    text = normalise(utterance)
    return (
        re.fullmatch(
            r"(yes|yeah|yep|sure|sure thing|ok|okay|absolutely|go ahead|do it|confirm|please do|"
            r"that's right|correct)( please| thanks)?",
            text,
        )
        is not None
    )


def is_negative(utterance: str) -> bool:
    """True only for a full refusal of a pending action."""
    text = normalise(utterance)
    return (
        re.fullmatch(
            r"(no|no way|nope|nah|cancel|stop|never mind|don't|do not|cancel that)( please| thanks)?",
            text,
        )
        is not None
    )


def parse(utterance: str, *, today: date | None = None) -> ParseResult:
    """Map one utterance to one tool call or one clarification.

    `today` is injectable so date phrases in tests and journeys do not depend on
    the wall clock. Production passes nothing and uses the current UTC date.
    """
    text = normalise(utterance)
    if not text:
        return _clarify(
            "I did not catch that. Try a timer, lights, the thermostat, a room booking, or a privacy setting.",
            "set a ten minute timer",
            reason="empty",
        )

    families = _families(text)
    if len(families) > 1:
        return _clarify(
            "I can do one thing at a time. Which would you like first?",
            "set a ten minute timer",
            "dim the living room lights",
            reason="multiple_intents",
        )

    if re.search(r"\bhelp\b|\bwhat can you do\b|\bcommands\b", text):
        return _clarify(
            "I can set timers, change lights or the thermostat, book a room, undo, explain the last "
            "action, or change privacy settings.",
            "set a ten minute timer",
            "book a room tomorrow at 2 PM",
            reason="help",
        )

    privacy_get = _privacy_get(text)
    if privacy_get is not None:
        return privacy_get

    privacy_set = _privacy_set(text)
    if privacy_set is not None:
        return privacy_set

    timer = _timer_intent(text)
    if timer is not None:
        return timer

    lights = _lights_intent(text)
    if lights is not None:
        return lights

    thermostat = _thermostat_intent(text)
    if thermostat is not None:
        return thermostat

    booking = _booking_intent(text, today or datetime.now(UTC).date())
    if booking is not None:
        return booking

    undo = _undo_intent(text)
    if undo is not None:
        return undo

    details = _details_intent(text)
    if details is not None:
        return details

    return _clarify(
        "I can set timers, change lights or the thermostat, book a room, undo, explain the last "
        "action, or change privacy settings.",
        "set a ten minute timer",
        "dim the living room lights to 30 percent",
        "book a room tomorrow at 2 PM",
        reason="unrecognised",
    )


__all__ = [
    "Clarification",
    "Intent",
    "ParseResult",
    "is_affirmative",
    "is_negative",
    "normalise",
    "parse",
    "parse_clock_time",
    "parse_date",
    "parse_duration_seconds",
    "words_to_digits",
]
