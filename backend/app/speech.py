"""Speech helpers. `speech` is what Alexa+ says: one short sentence, always.

English only. No SSML, because Alexa+ owns the rendering and the
ElevenLabs fallback reads plain text.
"""

from __future__ import annotations

from datetime import date, time

UNITS: tuple[tuple[int, str], ...] = ((3600, "hour"), (60, "minute"), (1, "second"))


def human_duration(total_seconds: int) -> str:
    """600 -> '10 minutes'; 3660 -> '1 hour 1 minute'."""
    parts: list[str] = []
    remaining = total_seconds
    for size, name in UNITS:
        if remaining >= size:
            count, remaining = divmod(remaining, size)
            parts.append(f"{count} {name}{'' if count == 1 else 's'}")
    return " ".join(parts) or "0 seconds"


def clock(total_seconds: int) -> str:
    """600 -> '10:00'; 3660 -> '1:01:00'."""
    hours, rest = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def human_date(value: str) -> str:
    """'2026-10-23' -> 'Friday, October 23'. Input is already validated ISO."""
    parsed = date.fromisoformat(value)
    return f"{parsed.strftime('%A, %B')} {parsed.day}"


def human_time(value: str) -> str:
    """'09:00' -> '9 AM'; '14:30' -> '2:30 PM'. Input is already validated."""
    parsed = time.fromisoformat(value)
    hour = parsed.hour % 12 or 12
    suffix = "AM" if parsed.hour < 12 else "PM"
    if parsed.minute == 0:
        return f"{hour} {suffix}"
    return f"{hour}:{parsed.minute:02d} {suffix}"
