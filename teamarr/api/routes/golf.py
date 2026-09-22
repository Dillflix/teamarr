"""Tournament discovery; these calendar dates are not broadcast start times."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from teamarr.api.dependencies import get_golf_catalog
from teamarr.core.golf import GolfTournament
from teamarr.services.golf import GolfCatalogService

router = APIRouter()


@router.get("/golf/tournaments", response_model=list[GolfTournament])
def get_golf_tournaments(
    target_date: date | None = Query(default=None, description="Query a single calendar date"),
    season_year: int | None = Query(default=None, ge=1900, le=2100),
    competition: Literal["pga"] = "pga",
    majors_only: bool = False,
    catalog: GolfCatalogService = Depends(get_golf_catalog),
) -> list[GolfTournament]:
    """Return provider tournaments with original date spans and stable IDs."""
    if (target_date is None) == (season_year is None):
        raise HTTPException(status_code=422, detail="Provide either target_date or season_year")
    if target_date is not None:
        events = catalog.get_tournaments(target_date, competition)
    else:
        assert season_year is not None  # exactly-one validation above
        events = catalog.get_season(season_year, competition)
    return [event for event in events if event.major is not None] if majors_only else events
