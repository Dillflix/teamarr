"""Controller feed contract: sporting events and broadcasts remain distinct."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from teamarr.core.broadcast import BroadcastSession
from teamarr.core.event_details import EventArtwork, EventSearchResult
from teamarr.core.special_events import ScheduledSession

FeedSource = Literal["games", "nfl_redzone", "golf", "special_events"]
FeedStatus = Literal["scheduled", "live", "final", "postponed", "cancelled", "unknown"]
WindowState = Literal["upcoming", "in_window", "elapsed", "unknown"]

DEFAULT_LEAGUES = ["nfl", "nhl", "mlb", "nba", "cfl", "uefa.champions", "f1"]


class ControllerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # User's deployment routing, NOT inferred from ESPN broadcaster names.
    league_apps: dict[str, str] = Field(
        default_factory=lambda: dict.fromkeys(DEFAULT_LEAGUES, "prime_video")
    )
    source_apps: dict[str, str] = Field(default_factory=lambda: {"nfl_redzone": "prime_video"})


class FeedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: AwareDatetime
    end: AwareDatetime
    as_of: AwareDatetime
    leagues: list[str] = Field(default_factory=lambda: list(DEFAULT_LEAGUES), max_length=20)
    sources: list[FeedSource] = Field(
        default_factory=lambda: ["games", "nfl_redzone", "golf", "special_events"]
    )
    statuses: list[FeedStatus] = Field(default_factory=list)
    window_states: list[WindowState] = Field(default_factory=list)
    lookback_hours: int = Field(default=48, ge=0, le=168)
    limit: int = Field(default=100, ge=1, le=500)

    @model_validator(mode="after")
    def bounded_window(self):
        span = self.end.astimezone(UTC) - self.start.astimezone(UTC)
        if not 0 < span.total_seconds() <= 7 * 86400:
            raise ValueError("Window must be positive and at most seven days")
        if any(not league.strip() or len(league) > 100 for league in self.leagues):
            raise ValueError("League codes must be nonempty and at most 100 characters")
        return self


class FeedViewingOption(BaseModel):
    id: str
    app: str | None = None
    channel: str | None = None
    stream_title: str | None = None
    listing_url: str | None = None
    broadcast_id: str | None = None
    start_time: datetime | None = None
    expected_end_time: datetime | None = None
    coverage_type: str | None = None
    presentation: str | None = None
    basis: str  # configured_route / configured / listing / rule
    decision: Literal["eligible", "review", "excluded"]
    reasons: list[str] = Field(default_factory=list)


class FeedSelection(BaseModel):
    rule_id: str
    decision: Literal["match", "pending", "no_match"]
    reasons: list[str] = Field(default_factory=list)


class FeedEntry(BaseModel):
    id: str
    kind: Literal["event", "session", "broadcast"]
    source: FeedSource
    title: str
    provider: str | None = None
    competition: str
    sports: list[str] = Field(default_factory=list)
    start_time: datetime
    expected_end_time: datetime | None = None
    end_time_estimated: bool | None = None
    timing_basis: str | None = None
    status: FeedStatus = "unknown"
    status_basis: Literal["provider", "configured", "unknown"] = "unknown"
    window_state: WindowState = "unknown"
    event: EventSearchResult | None = None
    sessions: list[ScheduledSession] = Field(default_factory=list)
    broadcast: BroadcastSession | None = None
    related_ids: list[str] = Field(default_factory=list)
    viewing_options: list[FeedViewingOption] = Field(default_factory=list)
    preferred_option_id: str | None = None
    selections: list[FeedSelection] = Field(default_factory=list)
    artwork: EventArtwork = Field(default_factory=EventArtwork)


class FeedResponse(BaseModel):
    schema_version: int = 1
    query: FeedQuery
    snapshot_created_at: datetime
    snapshot_expires_at: datetime
    total: int
    count: int
    items: list[FeedEntry]
    next_cursor: str | None = None
