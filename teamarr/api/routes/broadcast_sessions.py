"""Read-only broadcast-session catalog alongside Teamarr's existing event API."""

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from teamarr.api.dependencies import get_sports_service
from teamarr.config import get_user_timezone
from teamarr.core.broadcast import BroadcastSession
from teamarr.services.broadcast_sessions import RedZoneSource, load_broadcast_config
from teamarr.services.sports_data import SportsDataService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/broadcast-sessions", response_model=list[BroadcastSession])
def get_broadcast_sessions(
    target_date: date = Query(
        description="Session date in the source timezone (Eastern for RedZone)"
    ),
    source: Literal["nfl_redzone"] = "nfl_redzone",
    service: SportsDataService = Depends(get_sports_service),
) -> list[BroadcastSession]:
    """Enumerate planning sessions; does not start or stop device playback."""
    try:
        config = load_broadcast_config()
    except (OSError, ValueError, ValidationError) as exc:
        logger.error("[BROADCAST] Invalid broadcast configuration: %s", exc)
        raise HTTPException(status_code=503, detail="Invalid broadcast configuration") from exc

    return RedZoneSource(service.get_events, get_user_timezone(), config.redzone).get_sessions(
        target_date
    )
