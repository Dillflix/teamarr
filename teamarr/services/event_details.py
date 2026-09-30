"""Serialize existing provider data without fetching or inferring identities."""

import math
from datetime import UTC, timedelta
from typing import Literal

from teamarr.core import Event, Team
from teamarr.core.event_details import EventArtwork, EventSearchResult, EventTeamDetails
from teamarr.templates.filters import filter_pascal, filter_urlencode
from teamarr.utilities.art_url import apply_art_base_url, is_relative_art_path
from teamarr.utilities.sports import get_sport_duration


def event_team_details(team: Team | None) -> EventTeamDetails | None:
    if team is None:
        return None
    return EventTeamDetails(
        id=team.id,
        provider=team.provider,
        full_name=team.name,
        city=team.city,
        name=team.nickname,
        short_name=team.short_name,
        abbreviation=team.abbreviation,
        logo_url=team.logo_url,
    )


def event_end_estimate(
    event: Event, sport_durations: dict[str, float], default: float
) -> tuple[str | None, Literal["sport_duration", "default_duration"] | None]:
    """Planning estimate in UTC; never an observed finish or a status transition."""
    hours = get_sport_duration(event.sport, sport_durations, default)
    if not math.isfinite(hours) or hours <= 0:
        return None, None
    start = event.start_time
    # Match Teamarr's treatment of naive timestamps in legacy provider data.
    start_utc = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    try:
        end = start_utc + timedelta(hours=hours)
    except OverflowError:
        return None, None
    basis = "sport_duration" if event.sport.lower() in sport_durations else "default_duration"
    return end.isoformat(), basis


def league_artwork(league_code: str, league_info: dict, base_url: str) -> EventArtwork:
    art = EventArtwork(league_logo_url=league_info.get("logo_url"))
    if not base_url or is_relative_art_path(base_url):
        return art
    league = filter_urlencode(league_info.get("league_id") or league_code)
    art.league_logo_url = apply_art_base_url(f"{league}/logo.png", base_url)
    art.cover_url = apply_art_base_url(f"{league}/cover.png", base_url)
    return art


def event_artwork(event: Event, league_info: dict, base_url: str) -> EventArtwork:
    """Use Teamarr's existing league mapping, path filters and art URL helper."""
    home = event.home_team
    away = event.away_team
    art = league_artwork(event.league, league_info, base_url)
    art.home_team_logo_url = home.logo_url if home else None
    art.away_team_logo_url = away.logo_url if away else None
    if not base_url or is_relative_art_path(base_url):
        return art
    league = filter_urlencode(league_info.get("league_id") or event.league)
    sides = []
    for team, field in ((away, "away_team_logo_url"), (home, "home_team_logo_url")):
        side = filter_pascal(team.name) if team else ""
        sides.append(side)
        if side:
            setattr(art, field, apply_art_base_url(f"{league}/{side}/logo.png", base_url))
    if all(sides):
        path = f"{league}/{sides[0]}/{sides[1]}"
        art.matchup_logo_url = apply_art_base_url(
            f"{path}/logo.png?style=1&logo=true&fallback=true", base_url
        )
        art.cover_url = apply_art_base_url(
            f"{path}/cover.png?style=6&logo=true&fallback=true", base_url
        )
    return art


def serialize_event(
    event: Event,
    league_info: dict,
    durations: dict[str, float],
    default: float,
    art_base_url: str = "",
) -> EventSearchResult:
    end, basis = event_end_estimate(event, durations, default)
    return EventSearchResult(
        event_id=event.id,
        provider=event.provider,
        event_name=event.name,
        sport=event.sport,
        short_name=event.short_name,
        league=event.league,
        league_name=league_info.get("display_name"),
        start_time=event.start_time.isoformat(),
        expected_end_time=end,
        end_time_estimated=True if end is not None else None,
        timing_basis=basis,
        home_team=event.home_team.name if event.home_team else None,
        away_team=event.away_team.name if event.away_team else None,
        home_team_details=event_team_details(event.home_team),
        away_team_details=event_team_details(event.away_team),
        status=event.status.state if event.status else None,
        status_detail=event.status.detail if event.status else None,
        period=event.status.period if event.status else None,
        clock=event.status.clock if event.status else None,
        home_score=event.home_score,
        away_score=event.away_score,
        broadcasts=event.broadcasts,
        broadcast_markets=event.broadcast_markets,
        season_year=event.season_year,
        season_type=event.season_type,
        week=event.week,
        event_note=event.game_event_note or event.soccer_match_note or None,
        series_summary=event.series_summary or None,
        venue=event.venue,
        neutral_site=event.neutral_site,
        tournament_id=event.tournament_id,
        tournament_name=event.tournament_name,
        round_name=event.round_name,
        draw_type=event.draw_type,
        is_major=event.is_major,
        main_card_start=event.main_card_start.isoformat() if event.main_card_start else None,
        segment_times={key: value.isoformat() for key, value in event.segment_times.items()},
        bouts=event.bouts,
        artwork=event_artwork(event, league_info, art_base_url),
    )
