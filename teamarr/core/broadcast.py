"""Broadcast sessions are viewing windows that can cover zero or many events."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from teamarr.core.special_coverage import ScheduledSessionReference


@dataclass(frozen=True)
class EventReference:
    provider: str
    event_id: str


@dataclass(frozen=True)
class BroadcastSession:
    id: str
    source: str
    title: str
    kind: str
    sport: str | None
    competition: str
    session_date: date
    timezone: str
    start_time: datetime
    expected_end_time: datetime | None
    timing_basis: str
    related_events: tuple[EventReference, ...] = ()
    end_time_estimated: bool = True
    parent_event: EventReference | None = None
    segment: str | None = None
    coverage_type: str | None = None
    playback_target: str | None = None
    channel: str | None = None
    listing_url: str | None = None
    edition_id: str | None = None
    sports: tuple[str, ...] = ()
    related_sessions: tuple[ScheduledSessionReference, ...] = ()
    presentation: str | None = None
    stream_title: str | None = None


class BroadcastSessionSource(Protocol):
    """Additional sources may describe golf rounds, fight cards or Olympic sessions."""

    def get_sessions(self, target_date: date) -> list[BroadcastSession]: ...
