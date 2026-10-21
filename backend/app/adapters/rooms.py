"""The closed set of rooms the simulated home knows about.

Kept in one place so lighting and climate cannot disagree. The rules file repeats
the keys because rules are reviewed as data; a test asserts the two lists match.
"""

from __future__ import annotations

ROOMS: dict[str, str] = {
    # Wire value -> spoken name. Never speak "living_room".
    "living_room": "Living room",
    "bedroom": "Bedroom",
    "kitchen": "Kitchen",
    "office": "Office",
}
