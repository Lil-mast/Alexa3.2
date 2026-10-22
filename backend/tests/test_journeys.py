"""Journey fixture and runner tests.

A journey is the demo's executable claim: the same sentence, the same tool, the
same status, and the expected audit decision. These tests run every fixture
against an isolated app state, so a parser change cannot make the demo less
honest without failing here.
"""

from __future__ import annotations

import pytest

from app.journeys import load_journeys
from app.journeys.loader import get_journey
from app.journeys.runner import run_journey
from tests.conftest import make_settings


def test_fixtures_load_with_stable_names() -> None:
    journeys = load_journeys()

    assert [journey.name for journey in journeys] == [
        "booking",
        "lights-and-rules",
        "privacy",
        "timer",
    ]


@pytest.mark.parametrize("name", ["booking", "lights-and-rules", "privacy", "timer"])
def test_every_journey_passes(name: str) -> None:
    journey = get_journey(name)
    assert journey is not None

    result = run_journey(journey, settings=make_settings())

    assert result.passed is True, result.steps
    assert result.audit_ok is True
    assert result.audit_rows >= 3  # the seeded fixture plus the journey rows
    assert result.notes == []


def test_malformed_fixture_is_rejected(tmp_path) -> None:
    (tmp_path / "broken.yaml").write_text("name: broken\ntitle: Broken\nsteps: []\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid"):
        load_journeys(tmp_path)


def test_fixture_name_must_match_the_file_name(tmp_path) -> None:
    (tmp_path / "filename.yaml").write_text(
        "name: other\ntitle: Other\nsteps:\n  - say: undo\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="must match the file name"):
        load_journeys(tmp_path)
