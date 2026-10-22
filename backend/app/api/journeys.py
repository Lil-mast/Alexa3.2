"""Journey list and runner endpoints for the console's Journeys screen.

Running a journey is a read of the contract, not a write to the demo. The runner
gets its own `AppState`, so this endpoint cannot change the live timer, light,
booking, or audit state. That isolation is the reason the console can offer a
"run" button without a confirmation step.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import Principal
from app.config import Settings
from app.journeys.loader import get_journey, load_journeys
from app.journeys.models import JourneyResult
from app.journeys.runner import run_journey

logger = logging.getLogger("alexa.journeys.api")


class JourneySummary(BaseModel):
    name: str
    title: str
    description: str
    steps: int


class JourneyList(BaseModel):
    journeys: list[JourneySummary]


def _load_error(exc: RuntimeError) -> HTTPException:
    # The fixtures are code. A broken one is a server configuration problem, so
    # it gets a 500 with the reason rather than an empty list that looks healthy.
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "JOURNEY_LOAD_FAILED", "message": str(exc)},
    )


def build_journeys_router(settings: Settings, require_principal) -> APIRouter:
    api = APIRouter(prefix="/api/journeys", tags=["journeys"])

    @api.get("", response_model=JourneyList)
    async def list_journeys(_: Principal = Depends(require_principal)) -> JourneyList:
        try:
            journeys = load_journeys()
        except RuntimeError as exc:
            raise _load_error(exc) from exc
        return JourneyList(
            journeys=[
                JourneySummary(
                    name=journey.name,
                    title=journey.title,
                    description=journey.description,
                    steps=len(journey.steps),
                )
                for journey in journeys
            ]
        )

    @api.post("/{name}/run", response_model=JourneyResult)
    async def run(name: str, _: Principal = Depends(require_principal)) -> JourneyResult:
        try:
            journey = get_journey(name)
        except RuntimeError as exc:
            raise _load_error(exc) from exc
        if journey is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "NOT_FOUND",
                    "message": f"No journey named {name!r}.",
                    "follow_up": "Use GET /api/journeys to list the available journeys.",
                },
            )
        return run_journey(journey, settings=settings)

    return api


__all__ = ["JourneyList", "JourneySummary", "build_journeys_router"]
