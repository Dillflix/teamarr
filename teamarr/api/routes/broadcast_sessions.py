"""Read-only broadcast-session catalog alongside Teamarr's existing event API."""

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from teamarr.api.dependencies import get_sports_service, get_tsn_golf_schedule
from teamarr.config import get_user_timezone
from teamarr.core.broadcast import BroadcastSession
from teamarr.services.broadcast_sessions import RedZoneSource, load_broadcast_config
from teamarr.services.special_coverage import SpecialCoverageSource
from teamarr.services.sports_data import SportsDataService
from teamarr.services.tsn_golf import TSNGolfScheduleService, get_golf_sessions

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/broadcast-sessions", response_model=list[BroadcastSession])
def get_broadcast_sessions(
    target_date: date = Query(
        description="Session start date in its timezone (Eastern for RedZone)"
    ),
    source: Literal["nfl_redzone", "golf", "special_events"] = "nfl_redzone",
    service: SportsDataService = Depends(get_sports_service),
    tsn: TSNGolfScheduleService = Depends(get_tsn_golf_schedule),
) -> list[BroadcastSession]:
    """Enumerate planning sessions; does not start or stop device playback."""
    try:
        config = load_broadcast_config()
    except (OSError, ValueError, ValidationError) as exc:
        logger.error("[BROADCAST] Invalid broadcast configuration: %s", exc)
        raise HTTPException(status_code=503, detail="Invalid broadcast configuration") from exc

    if source == "golf":
        return get_golf_sessions(target_date, config.golf, tsn)
    if source == "special_events":
        return SpecialCoverageSource(config.special_events).get_sessions(target_date)
    return RedZoneSource(service.get_events, get_user_timezone(), config.redzone).get_sessions(
        target_date
    )
