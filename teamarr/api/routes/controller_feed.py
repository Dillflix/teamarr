"""Unified read-only controller feed with immutable pagination snapshots."""

import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime, ValidationError

from teamarr.api.dependencies import get_sports_service, get_tsn_golf_schedule
from teamarr.config import get_user_timezone
from teamarr.core.controller_feed import (
    DEFAULT_LEAGUES,
    FeedQuery,
    FeedResponse,
    FeedSource,
    FeedStatus,
    WindowState,
)
from teamarr.database import get_db
from teamarr.database.leagues import get_all_leagues
from teamarr.database.settings import get_all_settings
from teamarr.services.broadcast_sessions import load_broadcast_config
from teamarr.services.controller_feed import ControllerFeedBuilder
from teamarr.services.feed_snapshots import FeedSnapshotStore, SnapshotExpired
from teamarr.services.sports_data import SportsDataService
from teamarr.services.tsn_golf import TSNGolfScheduleService, get_golf_sessions

logger = logging.getLogger(__name__)
router = APIRouter()
_snapshots = FeedSnapshotStore()


def get_feed_snapshots() -> FeedSnapshotStore:
    return _snapshots


@router.get("/events/feed", response_model=FeedResponse)
def get_feed(
    request: Request,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    as_of: AwareDatetime | None = None,
    league: list[str] | None = Query(None, max_length=20),
    source: list[FeedSource] | None = Query(None),
    status: list[FeedStatus] | None = Query(None),
    window_state: list[WindowState] | None = Query(None),
    lookback_hours: int = Query(48, ge=0, le=168),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = Query(None, max_length=64),
    service: SportsDataService = Depends(get_sports_service),
    tsn: TSNGolfScheduleService = Depends(get_tsn_golf_schedule),
    snapshots: FeedSnapshotStore = Depends(get_feed_snapshots),
) -> FeedResponse:
    """Overlapping games and broadcasts, sorted by UTC start then stable ID.

    Filters use repeated query parameters (league=nfl&league=nhl). A cursor
    request must contain only cursor; it reads the same snapshot with no new
    source fetches. Snapshot timestamps are not provider data freshness.
    """
    if cursor is not None:
        if set(request.query_params) != {"cursor"}:
            raise HTTPException(
                422, "Use cursor alone; filters and page size are fixed in the snapshot"
            )
        try:
            return snapshots.page(cursor)
        except SnapshotExpired as exc:
            raise HTTPException(410, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    now = datetime.now(UTC)
    start = start or now
    try:
        query = FeedQuery(
            start=start,
            end=end or start + timedelta(hours=24),
            as_of=as_of or now,
            leagues=league if league is not None else list(DEFAULT_LEAGUES),
            sources=source
            if source is not None
            else ["games", "nfl_redzone", "golf", "special_events"],
            statuses=status or [],
            window_states=window_state or [],
            lookback_hours=lookback_hours,
            limit=limit,
        )
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        config = load_broadcast_config()
    except (OSError, ValueError) as exc:
        logger.error("[CONTROLLER_FEED] Invalid broadcast configuration: %s", exc)
        raise HTTPException(503, "Invalid broadcast configuration") from exc
    with get_db() as conn:
        settings = get_all_settings(conn)
        leagues = {row["league_code"]: row for row in get_all_leagues(conn)}
    durations = asdict(settings.durations)
    default = durations.pop("default")
    builder = ControllerFeedBuilder(
        service.get_events,
        lambda day: get_golf_sessions(day, config.golf, tsn),
        config,
        get_user_timezone(),
        leagues,
        durations,
        default,
        settings.epg.art_base_url or "",
    )
    try:
        items = builder.build(query)
    except Exception as exc:
        # Do not turn an exception in this adapter into a successful empty feed.
        # Upstream services still have their existing failure/empty semantics.
        logger.exception("[CONTROLLER_FEED] Source aggregation failed")
        raise HTTPException(503, "Unable to assemble controller feed") from exc
    try:
        return snapshots.create(query, items)
    except ValueError as exc:
        raise HTTPException(413, str(exc)) from exc
