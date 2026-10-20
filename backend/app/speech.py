"""Speech helpers. `speech` is what Alexa+ says: one short sentence, always.

English only for the demo. No SSML, because Alexa+ owns the rendering and the
ElevenLabs fallback reads plain text.
"""

from __future__ import annotations

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
