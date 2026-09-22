"""Explicit golf coverage windows attached to provider tournament identities.

Both configuration and broadcaster-listing importers produce these windows.
"""

from datetime import UTC, date
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from teamarr.core.broadcast import BroadcastSession, EventReference


class GolfCoverageWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Explicit identity, independent of broadcast date/time. Keep it when a
    # round is delayed to another day or its broadcast start changes.
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    tournament_id: str = Field(min_length=1, pattern=r"^[0-9]+$")
    tournament_name: str = Field(min_length=1)
    competition: Literal["pga"] = "pga"
    round_number: int | None = Field(default=None, ge=1)
    coverage_type: Literal["main", "featured_group", "featured_holes", "other"] = "main"
    label: str | None = Field(default=None, min_length=1)
    start_time: AwareDatetime
    end_time: AwareDatetime | None = None
    end_time_estimated: bool = True
    timezone: str = "America/New_York"
    enabled: bool = True
    playback_target: str | None = Field(default=None, min_length=1)
    segment: str | None = None
    channel: str | None = None
    listing_url: str | None = None
    timing_basis: Literal["configured", "listing"] = "configured"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone, e.g. America/New_York") from exc
        return value

    @model_validator(mode="after")
    def valid_end(self) -> Self:
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        return self

    @property
    def session_id(self) -> str:
        return f"golf:espn:{self.competition}:{self.tournament_id}:{self.key}"


class GolfConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allowed_apps: list[Literal["tsn", "sportsnet"]] = Field(
        default_factory=lambda: ["tsn", "sportsnet"]
    )
    import_tsn_schedule: bool = True
    playback_target: str | None = Field(default=None, min_length=1)
    coverage: list[GolfCoverageWindow] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_windows(self) -> Self:
        ids = [window.session_id for window in self.coverage]
        if len(ids) != len(set(ids)):
            raise ValueError("Coverage keys must be unique within each tournament")
        return self


class GolfSessionSource:
    def __init__(self, config: GolfConfig):
        self._config = config

    def get_sessions(self, target_date: date) -> list[BroadcastSession]:
        if not self._config.enabled:
            return []
        sessions = []
        for window in self._config.coverage:
            if not window.enabled:
                continue
            target = window.playback_target or self._config.playback_target
            if target is not None and target not in self._config.allowed_apps:
                continue
            session_date = window.start_time.astimezone(ZoneInfo(window.timezone)).date()
            if session_date != target_date:
                continue
            parent = EventReference(provider="espn", event_id=window.tournament_id)
            round_label = f"Round {window.round_number}" if window.round_number else "Coverage"
            title = window.label or (
                f"{window.tournament_name} - {round_label} - "
                f"{window.coverage_type.replace('_', ' ').title()}"
            )
            sessions.append(
                BroadcastSession(
                    id=window.session_id,
                    source="golf",
                    title=title,
                    kind="tournament_coverage",
                    sport="golf",
                    competition=window.competition,
                    session_date=session_date,
                    timezone=window.timezone,
                    start_time=window.start_time.astimezone(UTC),
                    expected_end_time=window.end_time.astimezone(UTC) if window.end_time else None,
                    timing_basis=window.timing_basis,
                    related_events=(parent,),
                    end_time_estimated=window.end_time_estimated if window.end_time else True,
                    parent_event=parent,
                    segment=window.segment
                    or (f"round_{window.round_number}" if window.round_number else None),
                    coverage_type=window.coverage_type,
                    playback_target=target,
                    channel=window.channel,
                    listing_url=window.listing_url,
                )
            )
        return sorted(sessions, key=lambda session: (session.start_time, session.id))
