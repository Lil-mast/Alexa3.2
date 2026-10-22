"""Load and validate journey fixtures.

Fixtures live beside the package under `fixtures/` so the Docker image, which
copies `app/`, includes them without a second COPY line. There is no cache:
editing a journey and re-running it from the console should not require a
restart. The files are small and read only when the journeys screen asks.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.journeys.models import Journey

JOURNEYS_DIR = Path(__file__).with_name("fixtures")


def load_journeys(directory: Path | None = None) -> list[Journey]:
    """Read every `*.yaml` in the fixture directory, sorted by filename.

    A malformed fixture is a startup-style configuration error, not a silent
    skip. The API turns the raised `RuntimeError` into a 500 with the reason, so
    a broken journey is visible before a run rather than during one.
    """
    root = directory or JOURNEYS_DIR
    if not root.is_dir():
        raise RuntimeError(f"journey directory {root} does not exist")

    paths = sorted(root.glob("*.yaml"))
    if not paths:
        raise RuntimeError(f"no journey fixtures found in {root}")

    journeys: list[Journey] = []
    seen: set[str] = set()
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(f"cannot read journey {path}") from exc
        except yaml.YAMLError as exc:
            raise RuntimeError(f"journey {path} is not valid YAML") from exc
        if not isinstance(raw, dict):
            raise RuntimeError(f"journey {path} must contain a mapping")
        try:
            journey = Journey.model_validate(raw)
        except ValidationError as exc:
            raise RuntimeError(f"journey {path} is invalid: {exc}") from exc
        if journey.name != path.stem:
            raise RuntimeError(f"journey {path} is named {journey.name!r}, which must match the file name")
        if journey.name in seen:
            raise RuntimeError(f"duplicate journey name {journey.name!r}")
        seen.add(journey.name)
        journeys.append(journey)
    return journeys


def get_journey(name: str, directory: Path | None = None) -> Journey | None:
    """Return one journey by name, or None so the route can answer a real 404."""
    for journey in load_journeys(directory):
        if journey.name == name:
            return journey
    return None


__all__ = ["JOURNEYS_DIR", "get_journey", "load_journeys"]
