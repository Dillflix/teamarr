"""Read-only event contract shared by search and the controller feed."""

from typing import Literal

from pydantic import BaseModel, Field

from teamarr.core.types import Bout, Venue


class EventTeamDetails(BaseModel):
    """Provider identity; name is the nickname, full_name is the display name."""

    id: str
    provider: str
    full_name: str
    city: str | None = Field(None, description="Provider location, not necessarily a city")
    name: str | None = Field(None, description="Provider nickname; never inferred from full_name")
    short_name: str
    abbreviation: str
    logo_url: str | None = None


class EventArtwork(BaseModel):
    league_logo_url: str | None = None
    home_team_logo_url: str | None = None
    away_team_logo_url: str | None = None
    matchup_logo_url: str | None = None
    cover_url: str | None = None


class EventSearchResult(BaseModel):
    """Event search result for correction UI and external controllers."""

    event_id: str
    event_name: str
    provider: str | None = None
    sport: str | None = None
    short_name: str | None = None
    league: str
    league_name: str | None = None
    start_time: str
    expected_end_time: str | None = None
    end_time_estimated: bool | None = None
    timing_basis: Literal["sport_duration", "default_duration", "configured"] | None = None
    home_team: str | None = None
    away_team: str | None = None
    home_team_details: EventTeamDetails | None = None
    away_team_details: EventTeamDetails | None = None
    status: str | None = None
    status_detail: str | None = None
    period: int | None = None
    clock: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    broadcasts: list[str] = Field(default_factory=list)
    broadcast_markets: dict[str, str] = Field(default_factory=dict)
    season_year: int | None = None
    season_type: str | None = None
    week: int | None = None
    event_note: str | None = None
    series_summary: str | None = None
    venue: Venue | None = None
    neutral_site: bool = False
    tournament_id: str | None = None
    tournament_name: str | None = None
    round_name: str | None = None
    draw_type: str | None = None
    is_major: bool = False
    main_card_start: str | None = None
    segment_times: dict[str, str] = Field(default_factory=dict)
    bouts: list[Bout] = Field(default_factory=list)
    artwork: EventArtwork = Field(default_factory=EventArtwork)


class EventSearchResponse(BaseModel):
    """Date-scoped event search with backward-compatible display names."""

    count: int
    target_date: str
    events: list[EventSearchResult]
