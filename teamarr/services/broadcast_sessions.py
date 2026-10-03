"""Rule-based NFL RedZone sessions, composed with the existing sports service.

NFL events remain owned/refreshed by Teamarr. No synthetic teams or fixtures
are inserted into its event catalog, provider registry, or XMLTV pipeline.
"""

import os
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from teamarr.core.broadcast import BroadcastSession, EventReference
from teamarr.core.controller_feed import ControllerConfig
from teamarr.core.types import SEASON_REGULAR, Event
from teamarr.services.dazn_tennis import DAZNTennisConfig
from teamarr.services.golf_sessions import GolfConfig
from teamarr.services.special_events import SpecialEventsConfig

REDZONE_TIMEZONE = "America/New_York"


class SessionOverride(BaseModel):
    """An explicit date can suppress or add a session, including special broadcasts."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    start_time: time | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)

    @field_validator("start_time")
    @classmethod
    def local_time_only(cls, value: time | None) -> time | None:
        if value is not None and value.tzinfo is not None:
            raise ValueError("Use an Eastern wall-clock time without a UTC offset")
        return value


class RedZoneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    start_time: time = time(13)
    duration_minutes: int = Field(default=420, ge=1, le=1440)
    overrides: dict[date, SessionOverride] = Field(default_factory=dict)

    @field_validator("start_time")
    @classmethod
    def local_time_only(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("Use an Eastern wall-clock time without a UTC offset")
        return value


class BroadcastConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    redzone: RedZoneConfig = Field(default_factory=RedZoneConfig)
    golf: GolfConfig = Field(default_factory=GolfConfig)
    dazn_tennis: DAZNTennisConfig = Field(default_factory=DAZNTennisConfig)
    special_events: SpecialEventsConfig = Field(default_factory=SpecialEventsConfig)
    controller: ControllerConfig = Field(default_factory=ControllerConfig)


def load_broadcast_config() -> BroadcastConfig:
    """Read at request time so mounted configuration changes take effect immediately."""
    path = os.environ.get("TEAMARR_BROADCAST_CONFIG")
    if not path:
        return BroadcastConfig()
    # An explicitly configured missing/invalid file must not silently use defaults.
    return BroadcastConfig.model_validate_json(Path(path).read_text())


class RedZoneSource:
    """Default Sunday sessions require a regular-season NFL game in the window.

    Date-specific enabled overrides explicitly authorize a session even if the
    schedule has no games, e.g. a special broadcast. Times are planning defaults,
    not a claim of live channel availability or a command to stop playback.
    """

    def __init__(
        self,
        get_events: Callable[[str, date], list[Event]],
        schedule_timezone: tzinfo,
        config: RedZoneConfig | None = None,
    ):
        self._get_events = get_events
        self._schedule_timezone = schedule_timezone
        self._config = config or RedZoneConfig()

    def get_sessions(self, target_date: date) -> list[BroadcastSession]:
        config = self._config
        override = config.overrides.get(target_date)
        if not config.enabled or (override is not None and not override.enabled):
            return []
        if override is None and target_date.weekday() != 6:
            return []

        start_clock = (
            override.start_time
            if override and override.start_time is not None
            else config.start_time
        )
        duration = (
            override.duration_minutes
            if override and override.duration_minutes is not None
            else config.duration_minutes
        )
        start = datetime.combine(target_date, start_clock, ZoneInfo(REDZONE_TIMEZONE))
        start_utc = start.astimezone(UTC)
        end_utc = start_utc + timedelta(minutes=duration)

        # get_events uses Teamarr's configured user timezone. Fetch each local
        # calendar day touched by this Eastern session, including UTC+14 users.
        first_day = start_utc.astimezone(self._schedule_timezone).date()
        last_day = (end_utc - timedelta(microseconds=1)).astimezone(self._schedule_timezone).date()
        related: dict[tuple[str, str], EventReference] = {}
        day = first_day
        while day <= last_day:
            for event in self._get_events("nfl", day):
                if (
                    event.league == "nfl"
                    and event.season_type == SEASON_REGULAR
                    and event.start_time is not None
                    and start_utc <= event.start_time < end_utc
                    and event.status.state not in {"cancelled", "postponed"}
                ):
                    key = (event.provider, event.id)
                    related[key] = EventReference(*key)
            day += timedelta(days=1)

        if not related and override is None:
            return []
        return [
            BroadcastSession(
                id=f"nfl_redzone:{target_date.isoformat()}",
                source="nfl_redzone",
                title="NFL RedZone",
                kind="multi_event_coverage",
                sport="football",
                competition="nfl",
                session_date=target_date,
                timezone=REDZONE_TIMEZONE,
                start_time=start_utc,
                expected_end_time=end_utc,
                timing_basis="override" if override is not None else "rule",
                related_events=tuple(related[key] for key in sorted(related)),
            )
        ]
