"""Read-only competition catalog and repeatable selection of current sessions."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from teamarr.api.dependencies import get_sports_service
from teamarr.config import get_user_timezone
from teamarr.core.special_events import (
    Competition,
    CompetitionEdition,
    ScheduledSession,
    SessionSelection,
)
from teamarr.services.broadcast_sessions import load_broadcast_config
from teamarr.services.special_events import SpecialEventsCatalog
from teamarr.services.sports_data import SportsDataService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/special-events")


def get_special_catalog(
    service: SportsDataService = Depends(get_sports_service),
) -> SpecialEventsCatalog:
    try:
        config = load_broadcast_config().special_events
    except (OSError, ValueError) as exc:
        logger.error("[SPECIAL_EVENTS] Invalid broadcast configuration: %s", exc)
        raise HTTPException(status_code=503, detail="Invalid broadcast configuration") from exc
    return SpecialEventsCatalog(config, service.get_events, get_user_timezone())


@router.get("/competitions", response_model=list[Competition])
def get_competitions(
    catalog: SpecialEventsCatalog = Depends(get_special_catalog),
) -> list[Competition]:
    return list(catalog.config.competitions)


@router.get("/editions", response_model=list[CompetitionEdition])
def get_editions(
    catalog: SpecialEventsCatalog = Depends(get_special_catalog),
) -> list[CompetitionEdition]:
    return list(catalog.config.editions)


@router.get("/sessions", response_model=list[ScheduledSession])
def get_sessions(
    target_date: date = Query(description="Session start date in its edition's timezone"),
    catalog: SpecialEventsCatalog = Depends(get_special_catalog),
) -> list[ScheduledSession]:
    return catalog.get_sessions(target_date)


@router.get("/selections", response_model=list[SessionSelection])
def get_selections(
    target_date: date = Query(description="Session start date in its edition's timezone"),
    rule_id: str | None = None,
    catalog: SpecialEventsCatalog = Depends(get_special_catalog),
) -> list[SessionSelection]:
    rules = list(catalog.config.rules)
    if rule_id is not None:
        rules = [rule for rule in rules if rule.id == rule_id]
        if not rules:
            raise HTTPException(status_code=404, detail="Unknown viewing rule")
    if not rules:
        return []
    return [
        catalog.select(session, rule)
        for session in catalog.get_sessions(target_date)
        for rule in rules
    ]
