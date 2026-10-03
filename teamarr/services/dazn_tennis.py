"""DAZN Canada tournament/court broadcasts, independent of individual matches.

The public EPG contract was observed on 2026-10-03, including Beijing Day 4
(Live) and Day 5 sessions (UpComing, despite VideoType=Vod). No account, video
URLs, Prime navigation, or assumed tournament-day arithmetic is involved.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from threading import Lock
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict

from teamarr.core.broadcast import BroadcastSession
from teamarr.utilities.cache import TTLCache

DAZN_EPG_URL = "https://epg.discovery.indazn.com/eu/v1/Epg"
MAX_BYTES = 8 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9_-]{1,150}$")
_EXCLUDED = re.compile(r"\b(replay|highlights?|recap|preview|press conference)\b", re.I)


class DAZNTennisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"DAZN tennis listing has invalid {field}")
    return value.strip()


def _id(value, field):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"DAZN tennis listing has invalid {field}")
    return value


def _time(value, field):
    value = _text(value, field)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError(f"DAZN tennis listing has naive {field}")
    return result.astimezone(UTC)


def parse_dazn_tennis(body: dict, day: date, received_at: datetime) -> list[BroadcastSession]:
    """Fail malformed source data; valid empty days are distinct from failures."""
    if (
        not isinstance(body, dict)
        or body.get("Date") != day.isoformat()
        or body.get("Id") != f"en-ca-{day.isoformat()}"
        or not isinstance(body.get("Tiles"), list)
        or len(body["Tiles"]) > 10_000
    ):
        raise ValueError("Invalid DAZN Canada schedule envelope")
    sessions = {}
    for tile in body["Tiles"]:
        if not isinstance(tile, dict):
            raise ValueError("Invalid DAZN schedule tile")
        sport = tile.get("Sport") or {}
        if not isinstance(sport, dict) or sport.get("Title") != "Tennis":
            continue
        # Named match streams and 24/7 linear channels are outside this source.
        if tile.get("IsLinear") or tile.get("Contestants"):
            continue
        presentation = tile.get("Type")
        if presentation not in {"Live", "UpComing"}:
            continue  # CatchUp/VOD is never turned into an ended/live session.
        title = _text(tile.get("Title"), "Title")
        if _EXCLUDED.search(title) or tile.get("IsGeoRestricted"):
            continue
        event_id = _id(tile.get("EventId"), "EventId")
        asset_id = _id(tile.get("AssetId"), "AssetId")
        start = _time(tile.get("Start"), "Start")
        end = _time(tile["End"], "End") if tile.get("End") else None
        if end is not None and end <= start:
            raise ValueError("Invalid DAZN tennis end time")
        competition = tile.get("Competition") or {}
        tournament = tile.get("TournamentCalendar") or {}
        if not isinstance(competition, dict) or not isinstance(tournament, dict):
            raise ValueError("Invalid DAZN tennis competition")
        artwork = tile.get("Image") or {}
        image_id = artwork.get("Id") if isinstance(artwork, dict) else None
        artwork_url = None
        if isinstance(image_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,300}", image_id):
            # Same image endpoint and sizing contract as DAZN's public schedule.
            artwork_url = "https://image.discovery.indazn.com/ca/v2/ca/image?" + urlencode(
                {
                    "id": image_id,
                    "quality": 75,
                    "width": 666,
                    "height": 374,
                    "resizeAction": "fill",
                    "verticalAlignment": "top",
                    "format": "jpg",
                }
            )
        # Never manufacture live status by comparing the clock with Start/End.
        status = "scheduled" if presentation == "UpComing" else "unknown"
        if presentation == tile.get("DisplayType") == tile.get("VideoType") == "Live":
            status = "live"
        session = BroadcastSession(
            id=f"dazn_tennis:ca:{event_id}",
            source="dazn_tennis",
            title=title,
            kind="tournament_coverage",
            sport="tennis",
            competition="tennis",
            session_date=start.date(),
            timezone="UTC",
            start_time=start,
            expected_end_time=end,
            timing_basis="listing",
            end_time_estimated=True,
            coverage_type="tournament_coverage",
            playback_target="prime_video",
            channel="DAZN",
            listing_url="https://www.dazn.com/en-CA/schedule",
            presentation="live",
            stream_title=title,
            provider="dazn",
            provider_event_id=event_id,
            provider_asset_id=asset_id,
            tournament_id=tournament.get("Id"),
            tournament_name=tournament.get("Title"),
            competition_name=competition.get("Title"),
            status=status,
            status_received_at=received_at,
            artwork_url=artwork_url,
        )
        previous = sessions.get(session.id)
        if previous is not None and previous != session:
            raise ValueError("Conflicting DAZN tennis session identities")
        sessions[session.id] = session
    return list(sessions.values())


class DAZNTennisScheduleService:
    def __init__(self, fetch: Callable[[date], dict] | None = None, clock=None):
        self._fetch = fetch or self._download
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cache = TTLCache(default_ttl_seconds=30, max_size=20)
        self._lock = Lock()

    @staticmethod
    def _download(day: date) -> dict:
        # With the endpoint default offset, an Oct 3 query includes Oct 4 UTC
        # sessions. Explicit UTC makes date buckets independent of host timezone.
        with httpx.stream(
            "GET",
            DAZN_EPG_URL,
            params={
                "date": day.isoformat(),
                "country": "ca",
                "languageCode": "en",
                "openBrowse": "true",
                "timeZoneOffset": 0,
            },
            timeout=8,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("DAZN schedule exceeds 8 MiB")
                chunks.append(chunk)
        return json.loads(b"".join(chunks))

    def get_sessions(self, day: date) -> list[BroadcastSession]:
        with self._lock:
            sessions = self._cache.get(day.isoformat())
            if sessions is None:
                body = self._fetch(day)
                sessions = parse_dazn_tennis(body, day, self._clock())
                self._cache.set(day.isoformat(), sessions)
            # Cached evidence keeps its acquisition time. Failures propagate;
            # the controller retains the last complete catalog and marks stale.
            return list(sessions)
