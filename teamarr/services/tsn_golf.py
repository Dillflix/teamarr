"""Join TSN broadcast rows to the PGA TOUR/majors catalog using explicit names."""

import logging
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from threading import Lock

import httpx

from teamarr.core.broadcast import BroadcastSession
from teamarr.providers.bellmedia.golf_schedule import (
    TSN_GOLF_SCHEDULE_URL,
    parse_tsn_golf_listings,
)
from teamarr.services.golf import GolfCatalogService
from teamarr.services.golf_sessions import GolfConfig, GolfCoverageWindow, GolfSessionSource
from teamarr.utilities.cache import TTLCache

logger = logging.getLogger(__name__)


def _name_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    return {
        "themasters": "masterstournament",
        "masters": "masterstournament",
        "theopenchampionship": "theopen",
        "openchampionship": "theopen",
    }.get(normalized, normalized)


class TSNGolfScheduleService:
    def __init__(self, catalog: GolfCatalogService, fetch_html: Callable[[], str] | None = None):
        self._catalog = catalog
        self._fetch_html = fetch_html or self._download
        self._cache = TTLCache(default_ttl_seconds=900, max_size=1)
        self._lock = Lock()

    @staticmethod
    def _download() -> str:
        response = httpx.get(TSN_GOLF_SCHEDULE_URL, timeout=15, follow_redirects=True)
        response.raise_for_status()
        return response.text

    def get_windows(self, target_date: date) -> list[GolfCoverageWindow]:
        with self._lock:
            rows = self._cache.get("listings")
            if rows is None:
                try:
                    rows = parse_tsn_golf_listings(self._fetch_html())
                except httpx.HTTPError as exc:
                    logger.warning("[TSN_GOLF] Schedule fetch failed: %s", exc)
                    rows = []
                self._cache.set("listings", rows)
        relevant = [row for row in rows if row.date == target_date]
        if not relevant:
            return []
        tournaments = self._catalog.get_season(target_date.year)
        windows = []
        occurrences: dict[tuple[str, str, str], int] = defaultdict(int)
        for row in relevant:
            matches = [
                event for event in tournaments if _name_key(event.name) == _name_key(row.tournament)
            ]
            if len(matches) != 1:
                logger.info("[TSN_GOLF] Unmatched/ambiguous tournament: %s", row.tournament)
                continue
            event = matches[0]
            if event.status in {"cancelled", "postponed"}:
                continue
            # Preserve day/final-round labels without assuming all formats are
            # four stroke-play rounds. No guessed end time or round duration.
            segment = re.sub(r"[^a-z0-9]+", "_", row.label.casefold()).strip("_")
            channel_key = row.channel.lower().replace("+", "plus")
            identity = (event.id, segment, channel_key)
            occurrences[identity] += 1
            windows.append(
                GolfCoverageWindow(
                    key=f"tsn-{segment[:65]}-{channel_key}-{occurrences[identity]}",
                    tournament_id=event.id,
                    tournament_name=event.name,
                    start_time=row.start_time,
                    label=f"{event.name} - {row.label} - {row.channel}",
                    segment=segment,
                    coverage_type=(
                        "featured_group"
                        if "featured group" in row.label.casefold()
                        else "featured_holes"
                        if "featured hole" in row.label.casefold()
                        else "main"
                    ),
                    playback_target="tsn",
                    channel=row.channel,
                    listing_url=TSN_GOLF_SCHEDULE_URL,
                    timing_basis="listing",
                )
            )
        return windows


def get_golf_sessions(
    target_date: date, config: GolfConfig, tsn: TSNGolfScheduleService
) -> list[BroadcastSession]:
    if not config.enabled:
        return []
    imported = (
        tsn.get_windows(target_date)
        if config.import_tsn_schedule and "tsn" in config.allowed_apps
        else []
    )
    windows = {window.session_id: window for window in imported}
    # Configured entries override their imported identity, including disabled
    # entries and rescheduled windows now belonging to a different date.
    windows.update({window.session_id: window for window in config.coverage})
    combined = config.model_copy(update={"coverage": list(windows.values())})
    return GolfSessionSource(combined).get_sessions(target_date)
