"""Structured team identities survive provider parsing, caching and event search."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teamarr.api.dependencies import get_sports_service
from teamarr.api.routes import epg
from teamarr.core import Event, EventStatus
from teamarr.database.provider_cache import (
    dict_to_event,
    dict_to_team,
    event_to_dict,
    team_to_dict,
)
from teamarr.database.settings.types import AllSettings
from teamarr.providers.espn.provider import ESPNProvider


@pytest.fixture
def provider(monkeypatch):
    provider = ESPNProvider(client=Mock())
    monkeypatch.setattr(provider, "_get_sport_league_from_db", lambda league: ("football", league))
    monkeypatch.setattr(provider, "_get_sport", lambda league: "football")
    return provider


@pytest.fixture
def payload():
    return {
        "id": "8", "location": "Detroit", "name": "Lions",
        "displayName": "Detroit Lions", "shortDisplayName": "Lions",
        "abbreviation": "DET", "logo": "https://example.test/det.png",
    }


@pytest.mark.parametrize("path", ["scoreboard", "team", "teams"])
@pytest.mark.parametrize("league,location,nickname", [
    ("nfl", "Detroit", "Lions"),
    ("nhl", "Toronto", "Maple Leafs"),
    ("mlb", "Toronto", "Blue Jays"),
    ("nba", "Golden State", "Warriors"),
])
def test_provider_preserves_components(provider, payload, path, league, location, nickname):
    payload.update(location=location, name=nickname, displayName=f"{location} {nickname}")
    # Short display names are not necessarily nicknames (e.g. a location or abbreviation).
    payload["shortDisplayName"] = location
    if path == "scoreboard":
        team = provider._parse_team({"team": payload}, league, "sport")
    elif path == "team":
        provider._client.get_team.return_value = {"team": payload}
        team = provider.get_team("8", league)
    else:
        team = provider._parse_team_from_teams_endpoint(payload, league, "sport")
    assert team.city == location
    assert team.nickname == nickname
    assert team.name == f"{location} {nickname}"
    assert team.short_name == location


@pytest.fixture
def event(provider, payload):
    home = provider._parse_team({"team": payload}, "nfl", "football")
    away = replace(home, id="9", name="Green Bay Packers", city="Green Bay",
                   nickname="Packers", short_name="Packers", abbreviation="GB")
    return Event(
        id="event-1", provider="espn", name="Packers at Lions", short_name="GB @ DET",
        start_time=datetime(2026, 10, 4, 17, tzinfo=UTC), home_team=home, away_team=away,
        status=EventStatus(state="scheduled"), league="nfl", sport="football",
    )


def test_identity_survives_json_cache_roundtrip(event):
    import json

    cached = json.loads(json.dumps(event_to_dict(event)))
    assert dict_to_event(cached) == event


def test_legacy_cache_loads_without_guessing(event):
    cached = team_to_dict(event.home_team)
    cached.pop("city")
    cached.pop("nickname")
    team = dict_to_team(cached)
    assert team.name == "Detroit Lions"
    assert team.city is None
    assert team.nickname is None


@pytest.mark.parametrize("missing", [None, ""])
def test_provider_does_not_split_display_name(provider, payload, missing):
    payload.update(location=missing, name=missing)
    team = provider._parse_team({"team": payload}, "nfl", "football")
    assert team.name == "Detroit Lions"
    assert team.city is None
    assert team.nickname is None


@pytest.fixture
def api(monkeypatch, event):
    monkeypatch.setattr(epg, "get_db", lambda: nullcontext(None))
    monkeypatch.setattr(epg, "get_all_leagues", lambda conn: [
        {"league_code": "nfl", "display_name": "NFL"},
    ])
    monkeypatch.setattr(epg, "get_all_settings", lambda conn: AllSettings())
    service = Mock()
    service.get_events.return_value = [dict_to_event(event_to_dict(event))]
    app = FastAPI()
    app.include_router(epg.router, prefix="/api/v1")
    app.dependency_overrides[get_sports_service] = lambda: service
    with TestClient(app) as client:
        yield client, service


def test_search_http_contract_preserves_names_and_adds_details(api):
    client, service = api
    response = client.get("/api/v1/epg/events/search?league=nfl&target_date=2026-10-04")
    assert response.status_code == 200
    result = response.json()
    assert result["count"] == 1
    assert result["target_date"] == "2026-10-04"
    event = result["events"][0]
    assert event["home_team"] == "Detroit Lions"
    assert event["away_team"] == "Green Bay Packers"
    assert event["status"] == "scheduled"
    assert event["expected_end_time"] == "2026-10-04T20:30:00+00:00"
    assert event["end_time_estimated"] is True
    assert event["timing_basis"] == "sport_duration"
    assert event["home_team_details"] == {
        "id": "8", "provider": "espn", "full_name": "Detroit Lions",
        "city": "Detroit", "name": "Lions", "short_name": "Lions",
        "abbreviation": "DET", "logo_url": "https://example.test/det.png",
    }
    assert event["away_team_details"]["city"] == "Green Bay"
    assert event["away_team_details"]["name"] == "Packers"
    # No additional team/provider lookups are introduced by enrichment.
    assert service.mock_calls == [
        ("get_events", ("nfl", date(2026, 10, 4)), {}),
    ]
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert "home_team_details" in schema["EventSearchResult"]["properties"]


def test_search_handles_unknown_components_and_missing_opponent(api, event):
    client, service = api
    home = replace(event.home_team, provider="other", city=None, nickname=None)
    service.get_events.return_value = [replace(event, home_team=home, away_team=None)]
    response = client.get("/api/v1/epg/events/search?league=nfl&target_date=2026-10-04")
    assert response.status_code == 200
    result = response.json()["events"][0]
    assert result["home_team_details"]["city"] is None
    assert result["home_team_details"]["name"] is None
    assert result["away_team"] is None
    assert result["away_team_details"] is None


def test_team_filter_and_empty_results_unchanged(api):
    client, _ = api
    response = client.get(
        "/api/v1/epg/events/search?league=nfl&target_date=2026-10-04&team=unmatched"
    )
    assert response.json() == {"count": 0, "target_date": "2026-10-04", "events": []}


@pytest.mark.parametrize("sport,hours", [
    ("football", 3.5), ("hockey", 3), ("baseball", 3.5), ("basketball", 3),
])
def test_end_estimate_uses_configured_sport_duration(api, event, sport, hours):
    from datetime import timedelta

    client, service = api
    service.get_events.return_value = [replace(event, sport=sport)]
    result = client.get(
        "/api/v1/epg/events/search?league=nfl&target_date=2026-10-04"
    ).json()["events"][0]
    assert result["expected_end_time"] == (event.start_time + timedelta(hours=hours)).isoformat()
    assert result["timing_basis"] == "sport_duration"


def test_duration_settings_changes_and_default_fallback(api, monkeypatch, event):
    client, service = api
    settings = AllSettings()
    settings.durations.football = 4.25
    settings.durations.default = 2.25
    monkeypatch.setattr(epg, "get_all_settings", lambda conn: settings)
    url = "/api/v1/epg/events/search?league=nfl&target_date=2026-10-04"
    result = client.get(url).json()["events"][0]
    assert result["expected_end_time"] == "2026-10-04T21:15:00+00:00"
    assert result["timing_basis"] == "sport_duration"
    service.get_events.return_value = [replace(event, sport="unsupported")]
    result = client.get(url).json()["events"][0]
    assert result["expected_end_time"] == "2026-10-04T19:15:00+00:00"
    assert result["timing_basis"] == "default_duration"


@pytest.mark.parametrize("start,expected", [
    (datetime(2026, 10, 4, 23, tzinfo=UTC), "2026-10-05T02:30:00+00:00"),
    # Spring-forward: duration is elapsed time, not wall-clock arithmetic.
    (datetime(2026, 3, 8, 1, tzinfo=ZoneInfo("America/Vancouver")),
     "2026-03-08T12:30:00+00:00"),
    (datetime(2026, 10, 4, 17), "2026-10-04T20:30:00+00:00"),
])
def test_end_estimate_handles_midnight_dst_and_legacy_naive_times(event, start, expected):
    assert epg._event_end_estimate(replace(event, start_time=start), {"football": 3.5}, 3) == (
        expected, "sport_duration",
    )


@pytest.mark.parametrize("hours", [0, -1, float("inf"), float("nan"), 1e100])
def test_unusable_duration_does_not_invent_end_time(api, monkeypatch, hours):
    client, _ = api
    settings = AllSettings()
    settings.durations.football = hours
    monkeypatch.setattr(epg, "get_all_settings", lambda conn: settings)
    response = client.get("/api/v1/epg/events/search?league=nfl&target_date=2026-10-04")
    assert response.status_code == 200
    result = response.json()["events"][0]
    assert result["expected_end_time"] is None
    assert result["end_time_estimated"] is None
    assert result["timing_basis"] is None


@pytest.mark.parametrize("state", ["live", "final", "postponed", "cancelled"])
def test_estimate_never_replaces_provider_status(api, event, state):
    client, service = api
    # Deliberately in the past: passing the estimate cannot finish an event.
    service.get_events.return_value = [replace(
        event, start_time=datetime(2020, 1, 1, tzinfo=UTC), status=EventStatus(state=state),
    )]
    result = client.get(
        "/api/v1/epg/events/search?league=nfl&target_date=2020-01-01"
    ).json()["events"][0]
    assert result["status"] == state
    assert result["end_time_estimated"] is True
