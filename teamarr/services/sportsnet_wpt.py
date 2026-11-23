"""World Poker Tour linear airings from Sportsnet's public TV listings.

An airing can contain recorded poker. Its live status describes the channel
broadcast, never whether the tournament itself is taking place now.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from threading import Lock

import httpx
from pydantic import BaseModel, ConfigDict

from teamarr.core.broadcast import BroadcastSession
from teamarr.utilities.cache import TTLCache

URL = "https://production-cdn.d3-rgr-diva.com/api/schedules"
MAX_BYTES = 8 * 1024 * 1024
CHANNELS = {
    "155049": "Sportsnet Ontario",
    "155046": "Sportsnet East",
    "155047": "Sportsnet One",
    "155068": "Sportsnet 360",
    "155050": "Sportsnet West",
    "155048": "Sportsnet Pacific",
    "155080": "Sportsnet World",
}
_ID = re.compile(r"[A-Za-z0-9-]{1,150}\Z")


class SportsnetWPTConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing Sportsnet airing timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Naive Sportsnet airing timestamp")
    return result.astimezone(UTC)


def parse_sportsnet_wpt(body: list, day: date, received_at: datetime) -> list[BroadcastSession]:
    if not isinstance(body, list) or len(body) > len(CHANNELS):
        raise ValueError("Invalid Sportsnet schedule envelope")
    sessions = {}
    seen = set()
    for channel in body:
        if not isinstance(channel, dict):
            raise ValueError("Invalid Sportsnet channel")
        cid = channel.get("channelId")
        if not isinstance(cid, str) or cid not in CHANNELS or cid in seen:
            raise ValueError("Unknown or duplicate Sportsnet channel")
        seen.add(cid)
        start = timestamp(channel.get("startDate"))
        end = timestamp(channel.get("endDate"))
        if start != datetime.combine(day, datetime.min.time(), UTC) or end != start + timedelta(
            days=1
        ):
            raise ValueError("Wrong Sportsnet schedule day")
        rows = channel.get("schedules")
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("Invalid Sportsnet listings")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("item"), dict):
                raise ValueError("Invalid Sportsnet program")
            item = row["item"]
            # Exact observed series identity; never match arbitrary poker titles.
            if item.get("title") != "World Poker Tour" or item.get("type") != "program":
                continue
            fields = row.get("customFields")
            if not isinstance(fields, dict):
                raise ValueError("Invalid Sportsnet airing metadata")
            if fields.get("CatalogType") != "airing" or fields.get("VideoWorkflow") != "LIVE":
                continue
            video_status = fields.get("VideoStatus")
            status = (
                {"Live": "live", "Scheduled": "scheduled"}.get(video_status)
                if isinstance(video_status, str) else None
            )
            if status is None:
                continue  # OnDemand is never a new live playback opportunity.
            airing_id = row.get("id")
            if (
                row.get("channelId") != cid
                or not isinstance(airing_id, str)
                or not _ID.fullmatch(airing_id)
            ):
                raise ValueError("Invalid Sportsnet airing identity")
            airing_start, airing_end = (
                timestamp(row.get("startDate")),
                timestamp(row.get("endDate")),
            )
            if airing_end <= airing_start or airing_start >= end or airing_end <= start:
                raise ValueError("Invalid Sportsnet airing window")
            session = BroadcastSession(
                id=f"sportsnet_wpt:{cid}:{airing_id}",
                source="sportsnet_wpt",
                title=item["title"],
                kind="linear_program",
                sport="poker",
                competition="wpt",
                session_date=airing_start.date(),
                timezone="UTC",
                start_time=airing_start,
                expected_end_time=airing_end,
                timing_basis="listing",
                end_time_estimated=True,
                coverage_type="linear_program",
                playback_target="prime_video",
                channel=CHANNELS[cid],
                listing_url="https://watch.sportsnet.ca/schedule/tvlistings",
                presentation="live",
                stream_title=item["title"],
                provider="sportsnet",
                provider_event_id=airing_id,
                competition_name="World Poker Tour",
                status=status,
                status_received_at=received_at,
            )
            if session.id in sessions and sessions[session.id] != session:
                raise ValueError("Conflicting Sportsnet airing identities")
            sessions[session.id] = session
    return list(sessions.values())


class SportsnetWPTScheduleService:
    def __init__(self, fetch: Callable[[date], list] | None = None, clock=None):
        self._fetch = fetch or self._download
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cache = TTLCache(default_ttl_seconds=30, max_size=20)
        self._lock = Lock()

    def get_sessions(self, day: date) -> list[BroadcastSession]:
        with self._lock:
            sessions = self._cache.get(day.isoformat())
            if sessions is None:
                sessions = parse_sportsnet_wpt(self._fetch(day), day, self._clock())
                self._cache.set(day.isoformat(), sessions)
            return list(sessions)

    @staticmethod
    def _download(day: date) -> list:
        with httpx.stream(
            "GET",
            URL,
            params={
                "channels": ",".join(CHANNELS),
                "date": day.isoformat(),
                "hour": 0,
                "duration": 24,
                "lang": "en",
            },
            timeout=8,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Sportsnet schedule exceeds 8 MiB")
                chunks.append(chunk)
        body = json.loads(b"".join(chunks))
        if (
            not isinstance(body, list)
            or any(not isinstance(c, dict) for c in body)
            or {c.get("channelId") for c in body} != set(CHANNELS)
        ):
            raise ValueError("Incomplete Sportsnet channel response")
        return body
