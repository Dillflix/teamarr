"""Broadcast sessions are viewing windows that can cover zero or many events."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


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
    sport: str
    competition: str
    session_date: date
    timezone: str
    start_time: datetime
    expected_end_time: datetime
    timing_basis: str
    related_events: tuple[EventReference, ...] = ()
    end_time_estimated: bool = True


class BroadcastSessionSource(Protocol):
    """Additional sources may describe golf rounds, fight cards or Olympic sessions."""

    def get_sessions(self, target_date: date) -> list[BroadcastSession]: ...
