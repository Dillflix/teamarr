"""Controller contract: identity joins, temporal boundaries and stable pagination."""

from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.core import Event, EventStatus, Team, Venue
from teamarr.core.controller_feed import FeedQuery
from teamarr.services.broadcast_sessions import BroadcastConfig
from teamarr.services.controller_feed import ControllerFeedBuilder, event_id
from teamarr.services.event_details import serialize_event
from teamarr.services.feed_snapshots import FeedSnapshotStore, SnapshotExpired
from teamarr.services.golf_sessions import GolfSessionSource


def dt(text):
    return datetime.fromisoformat(text)


def game(id="1", start="2026-10-04T17:00:00+00:00", league="nfl", **changes):
    team = Team(
        "8",
        "espn",
        "Detroit Lions",
        "Lions",
        "DET",
        league,
        "football",
        city="Detroit",
        nickname="Lions",
    )
    event = Event(
        id,
        "espn",
        "Green Bay Packers at Detroit Lions",
        "GB @ DET",
        dt(start),
        team,
        replace(team, id="9", name="Green Bay Packers", city="Green Bay", nickname="Packers"),
        EventStatus("scheduled"),
        league,
        "football",
        season_type="regular",
    )
    return replace(event, **changes)


def query(**changes):
    data = dict(
        start=dt("2026-10-04T16:00:00+00:00"),
        end=dt("2026-10-05T01:00:00+00:00"),
        as_of=dt("2026-10-04T18:00:00+00:00"),
        sources=["games"],
        leagues=["nfl"],
    )
    data.update(changes)
    return FeedQuery(**data)


def builder(events=(), config=None, timezone=UTC):
    config = config or BroadcastConfig()
    calls = Counter()

    def fetch(league, day):
        calls[league, day] += 1
        # Deliberately duplicate overnight events across date buckets.
        return [
            e
            for e in events
            if e.league == league
            and abs((e.start_time.astimezone(timezone).date() - day).days) <= 1
        ]

    service = ControllerFeedBuilder(
        fetch,
        GolfSessionSource(config.golf).get_sessions,
        config,
        timezone,
        {},
        {"football": 3.5, "hockey": 3},
        3,
    )
    return service, calls


def special_config(**changes):
    data = {
        "competitions": [{"id": "cup", "name": "Hockey Cup", "sports": ["hockey"]}],
        "editions": [
            {
                "id": "cup-2026",
                "competition_id": "cup",
                "name": "Cup 2026",
                "start_date": "2026-10-01",
                "end_date": "2026-10-10",
                "timezone": "America/Vancouver",
            }
        ],
        "sessions": [
            {
                "id": "final",
                "provider": "configured",
                "edition_id": "cup-2026",
                "title": "Canada vs USA",
                "sport": "hockey",
                "start_time": "2026-10-04T17:00:00Z",
                "end_time": "2026-10-04T20:00:00Z",
                "countries": ["CAN", "USA"],
                "stage": "final",
                "medal_event": True,
            }
        ],
        "coverage": {
            "windows": [
                {
                    "id": "final-live",
                    "edition_id": "cup-2026",
                    "title": "Hockey Final",
                    "app": "sportsnet",
                    "start_time": "2026-10-04T16:30:00Z",
                    "end_time": "2026-10-04T21:00:00Z",
                    "timezone": "America/Vancouver",
                    "sports": ["hockey"],
                    "stream_title": "Canada - USA Final",
                    "related_sessions": [
                        {"id": "final", "provider": "configured", "edition_id": "cup-2026"}
                    ],
                }
            ]
        },
    }
    data.update(changes)
    return BroadcastConfig.model_validate({"special_events": data})


def test_game_deduplication_sorting_and_league_scoped_identity():
    events = [game("b"), game("a"), game("a", league="nhl", sport="hockey")]
    service, calls = builder(events)
    items = service.build(query(leagues=["nfl", "nhl", "nfl"]))
    assert len(items) == 3
    assert [item.id for item in items] == sorted(event_id(e) for e in events)
    assert max(calls.values()) == 1
    nfl = next(item for item in items if item.competition == "nfl")
    nhl = next(item for item in items if item.competition == "nhl")
    assert nfl.viewing_options[0].app == "prime_video"
    assert nfl.viewing_options[0].basis == "configured_route"
    assert nhl.viewing_options[0].app == "prime_video"
    assert nhl.viewing_options[0].basis == "configured_route"


def test_live_overtime_survives_estimated_end_and_status_filter():
    events = [game("live", status=EventStatus("live")), game("final", status=EventStatus("final"))]
    service, _ = builder(events)
    items = service.build(query(start=dt("2026-10-04T22:00:00Z"), statuses=["live"]))
    assert [item.event.event_id for item in items] == ["live"]
    assert items[0].expected_end_time < query(start=dt("2026-10-04T22:00:00Z")).start


@pytest.mark.parametrize(
    "league,sport",
    [
        ("mlb", "baseball"),
        ("nhl", "hockey"),
        ("nba", "basketball"),
        ("cfl", "football"),
        ("uefa.champions", "soccer"),
    ],
)
@pytest.mark.parametrize("app,apps", [(None, []), ("sportsnet", ["sportsnet"])])
def test_explicit_league_routing_replaces_default_prime_video(league, sport, app, apps):
    routes = {league: app} if app else {}
    config = BroadcastConfig.model_validate({"controller": {"league_apps": routes}})
    service, _ = builder([game(league=league, sport=sport)], config=config)
    item = service.build(query(leagues=[league]))[0]
    assert [option.app for option in item.viewing_options] == apps


def test_overnight_previous_day_and_half_open_window_boundaries():
    events = [
        game("overnight", "2026-10-03T23:00:00Z"),
        game("ends-at-start", "2026-10-03T20:30:00Z"),
        game("starts-at-end", "2026-10-04T02:00:00Z"),
    ]
    service, _ = builder(events, timezone=ZoneInfo("America/Vancouver"))
    items = service.build(query(start=dt("2026-10-04T00:00:00Z"), end=dt("2026-10-04T02:00:00Z")))
    assert [item.event.event_id for item in items] == ["overnight"]


def test_redzone_is_broadcast_unknown_live_and_not_full_game_option():
    event = game()
    service, calls = builder([event])
    items = service.build(query(sources=["games", "nfl_redzone"]))
    assert len(items) == 2
    match = next(item for item in items if item.kind == "event")
    redzone = next(item for item in items if item.kind == "broadcast")
    assert redzone.status == "unknown" and redzone.window_state == "in_window"
    assert redzone.related_ids == [match.id]
    assert redzone.viewing_options[0].app == "prime_video"
    assert redzone.preferred_option_id is not None
    option = next(o for o in match.viewing_options if o.broadcast_id == redzone.id)
    assert option.decision == "review"
    assert "multi_event_coverage_not_full_game" in option.reasons
    assert match.preferred_option_id != option.id
    assert max(calls.values()) == 1
    assert len(service.build(query(sources=["games", "nfl_redzone"], statuses=["live"]))) == 0


def test_golf_coverage_has_parent_round_and_unknown_end_without_fake_live():
    config = BroadcastConfig.model_validate(
        {
            "golf": {
                "import_tsn_schedule": False,
                "coverage": [
                    {
                        "key": "round-4-main",
                        "tournament_id": "401",
                        "tournament_name": "Example Major",
                        "round_number": 4,
                        "start_time": "2026-10-04T15:00:00Z",
                        "playback_target": "tsn",
                        "channel": "TSN4",
                        "listing_url": "https://example.test/listing",
                    }
                ],
            }
        }
    )
    service, _ = builder(config=config)
    item = service.build(query(sources=["golf"]))[0]
    assert item.broadcast.segment == "round_4"
    assert item.related_ids == ["event:espn:pga:401"]
    assert item.status == "unknown" and item.window_state == "unknown"
    assert item.viewing_options[0].decision == "review"
    assert item.preferred_option_id is None
    assert item.viewing_options[0].channel == "TSN4"


def test_special_session_links_exact_coverage_and_context():
    service, _ = builder(config=special_config())
    items = service.build(query(sources=["special_events"]))
    sporting = next(item for item in items if item.kind == "session")
    broadcast = next(item for item in items if item.kind == "broadcast")
    assert sporting.sessions[0].medal_event is True
    assert sporting.sessions[0].countries == ("CAN", "USA")
    assert sporting.related_ids == [broadcast.id]
    assert broadcast.related_ids == [sporting.id]
    assert sporting.preferred_option_id == sporting.viewing_options[0].id
    assert sporting.viewing_options[0].stream_title == "Canada - USA Final"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"presentation": "replay"}, "replay"),
        ({"coverage_type": "multi_event"}, "multi_event_coverage"),
        ({"start_time": dt("2026-10-04T18:00:00Z")}, "starts_after_event"),
    ],
)
def test_special_unsuitable_options_never_preferred(change, reason):
    config = special_config()
    window = config.special_events.coverage.windows[0].model_copy(update=change)
    config.special_events = config.special_events.model_copy(
        update={
            "coverage": config.special_events.coverage.model_copy(update={"windows": (window,)})
        }
    )
    service, _ = builder(config=config)
    sporting = next(
        i for i in service.build(query(sources=["special_events"])) if i.kind == "session"
    )
    assert sporting.preferred_option_id is None
    assert reason in sporting.viewing_options[0].reasons


def test_imported_special_game_merges_with_regular_game_and_configured_move():
    config = special_config(
        imports=[{"edition_id": "cup-2026", "league": "nhl", "sport": "hockey"}],
        sessions=[],
        coverage={},
    )
    event = game("1", league="nhl", sport="hockey")
    service, _ = builder([event], config)
    items = service.build(query(leagues=["nhl"], sources=["games", "special_events"]))
    assert len(items) == 1
    assert items[0].id == event_id(event)
    assert len(items[0].sessions) == 1
    assert items[0].sessions[0].provider == "espn"


def test_explicit_long_window_is_found_before_discovery_lookback():
    config = special_config()
    window = config.special_events.coverage.windows[0].model_copy(
        update={
            "start_time": dt("2026-10-01T16:30:00Z"),
            "coverage_type": "multi_event",
        }
    )
    config.special_events = config.special_events.model_copy(
        update={
            "coverage": config.special_events.coverage.model_copy(update={"windows": (window,)})
        }
    )
    service, _ = builder(config=config)
    items = service.build(query(sources=["special_events"], lookback_hours=1))
    assert any(i.kind == "broadcast" and i.start_time.day == 1 for i in items)


def test_event_metadata_and_artwork_uses_mapped_league_and_existing_filters():
    event = game(
        league="eng.1",
        home_score=2,
        away_score=0,
        status=EventStatus("live", "Halftime", 1, "45:00"),
        season_year=2026,
        week=4,
        game_event_note="Final",
        neutral_site=True,
        venue=Venue("Example Stadium", city="London"),
        broadcasts=["Example TV"],
        broadcast_markets={"Example TV": "national"},
    )
    result = serialize_event(
        event, {"league_id": "epl"}, {"football": 3.5}, 3, "https://art.example.test/"
    )
    assert result.status_detail == "Halftime" and result.clock == "45:00"
    assert result.home_score == 2 and result.away_score == 0
    assert result.event_note == "Final" and result.week == 4
    assert result.broadcast_markets == {"Example TV": "national"}
    assert result.artwork.league_logo_url == "https://art.example.test/epl/logo.png"
    assert "/epl/GreenBayPackers/DetroitLions/" in result.artwork.cover_url
    assert result.venue.city == "London"
    assert serialize_event(event, {}, {}, 3).artwork.cover_url is None


def test_snapshot_stable_after_source_changes_and_equal_start_ties():
    service, _ = builder([game("a"), game("b"), game("c")])
    items = service.build(query())
    store = FeedSnapshotStore()
    first = store.create(query(limit=1), items)
    # Mutation of original data or a returned page cannot modify subsequent pages.
    items[1].title = "changed"
    first.items[0].title = "client mutation"
    second = store.page(first.next_cursor)
    assert second.items[0].title != "changed"
    third = store.page(second.next_cursor)
    assert third.next_cursor is None
    assert len({i.id for page in [first, second, third] for i in page.items}) == 3
    assert second.query == first.query and third.snapshot_created_at == first.snapshot_created_at


def test_cursor_expiry_eviction_and_invalid_offsets():
    service, _ = builder([game("a"), game("b")])
    items = service.build(query())
    store = FeedSnapshotStore(max_snapshots=1)
    first = store.create(query(limit=1), items)
    with pytest.raises(ValueError):
        store.page(first.next_cursor.rsplit(".", 1)[0] + ".999")
    store.create(query(limit=1), items)
    with pytest.raises(SnapshotExpired):
        store.page(first.next_cursor)
    expired = FeedSnapshotStore(ttl_seconds=-1)
    page = expired.create(query(limit=1), items)
    with pytest.raises(SnapshotExpired):
        expired.page(page.next_cursor)
    with pytest.raises(ValueError):
        store.page("bad")
    with pytest.raises(ValueError):
        FeedSnapshotStore(max_items=1).create(query(), items)


def test_configured_reschedule_suppresses_stale_game_even_outside_requested_window():
    config = special_config(
        imports=[{"edition_id": "cup-2026", "league": "nhl", "sport": "hockey"}],
        sessions=[
            {
                "id": "1",
                "provider": "espn",
                "edition_id": "cup-2026",
                "title": "Moved game",
                "sport": "hockey",
                "start_time": "2026-10-07T17:00:00Z",
                "status": "postponed",
            }
        ],
        coverage={},
    )
    event = game("1", league="nhl", sport="hockey")
    service, _ = builder([event], config)
    assert service.build(query(leagues=["nhl"], sources=["games", "special_events"])) == []
    moved_query = query(
        start=dt("2026-10-07T16:00:00Z"),
        end=dt("2026-10-08T01:00:00Z"),
        leagues=["nhl"],
        sources=["games", "special_events"],
    )
    items = service.build(moved_query)
    assert len(items) == 1
    assert items[0].status == "postponed" and items[0].preferred_option_id is None
    assert items[0].title == "Moved game"
    assert items[0].id == event_id(event)


def test_in_window_is_not_live_and_filters_remain_independent():
    service, _ = builder([game()])
    assert service.build(query(statuses=["live"])) == []
    items = service.build(query(window_states=["in_window"]))
    assert len(items) == 1 and items[0].status == "scheduled"
    assert service.build(query(window_states=["upcoming"])) == []


def test_source_dates_use_eastern_dst_for_redzone():
    event = game(start="2026-11-01T18:00:00Z")
    service, _ = builder([event], timezone=ZoneInfo("Pacific/Kiritimati"))
    items = service.build(
        query(
            start=dt("2026-11-01T17:00:00Z"),
            end=dt("2026-11-02T03:00:00Z"),
            sources=["nfl_redzone"],
        )
    )
    assert len(items) == 1
    assert items[0].start_time.hour == 18
    assert items[0].expected_end_time == dt("2026-11-02T01:00:00Z")


def test_special_selection_rules_and_preferences_are_preserved():
    config = special_config(rules=[{"id": "canada", "countries": ["CAN"]}])
    coverage = config.special_events.coverage
    extra = coverage.windows[0].model_copy(update={"id": "tsn-feed", "app": "tsn"})
    config.special_events = config.special_events.model_copy(
        update={
            "coverage": coverage.model_copy(
                update={
                    "windows": (*coverage.windows, extra),
                    "preferred_apps": ("tsn",),
                }
            ),
        }
    )
    service, _ = builder(config=config)
    item = next(i for i in service.build(query(sources=["special_events"])) if i.kind == "session")
    assert item.selections[0].decision == "match"
    assert item.viewing_options[0].app == "tsn"
    assert item.preferred_option_id == item.viewing_options[0].id
    original = config.special_events.sessions[0]
    config.special_events = config.special_events.model_copy(
        update={
            "sessions": (original.model_copy(update={"countries": None}),),
        }
    )
    service, _ = builder(config=config)
    item = next(i for i in service.build(query(sources=["special_events"])) if i.kind == "session")
    assert item.selections[0].decision == "pending"
    assert item.preferred_option_id is None


@pytest.fixture
def api(monkeypatch):
    from contextlib import nullcontext
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from teamarr.api.dependencies import (
        get_dazn_tennis_schedule,
        get_sports_service,
        get_tsn_golf_schedule,
    )
    from teamarr.api.routes import controller_feed as route
    from teamarr.database.settings.types import AllSettings

    app = FastAPI()
    app.include_router(route.router, prefix="/api/v1")
    service = Mock()
    service.get_events.return_value = [game("a"), game("b"), game("c")]
    app.dependency_overrides[get_sports_service] = lambda: service
    app.dependency_overrides[get_tsn_golf_schedule] = lambda: Mock()
    tennis = Mock()
    tennis.get_sessions.return_value = []
    app.dependency_overrides[get_dazn_tennis_schedule] = lambda: tennis
    app.dependency_overrides[route.get_feed_snapshots] = lambda: snapshots
    snapshots = FeedSnapshotStore()
    monkeypatch.setattr(route, "get_db", lambda: nullcontext(None))
    monkeypatch.setattr(route, "get_all_settings", lambda conn: AllSettings())
    monkeypatch.setattr(route, "get_all_leagues", lambda conn: [])
    monkeypatch.setattr(route, "get_user_timezone", lambda: UTC)
    monkeypatch.setattr(route, "load_broadcast_config", BroadcastConfig)
    with TestClient(app) as client:
        yield client, service, route


def api_params(**updates):
    data = dict(
        start="2026-10-04T16:00:00Z",
        end="2026-10-05T01:00:00Z",
        as_of="2026-10-04T18:00:00Z",
        source="games",
        league="nfl",
        limit=1,
    )
    data.update(updates)
    return data


@pytest.mark.parametrize(
    "league,sport",
    [
        ("mlb", "baseball"),
        ("nhl", "hockey"),
        ("nba", "basketball"),
        ("cfl", "football"),
        ("uefa.champions", "soccer"),
    ],
)
def test_http_league_has_eligible_prime_video_route(api, league, sport):
    client, service, _ = api
    service.get_events.return_value = [game("league-game", league=league, sport=sport)]
    response = client.get("/api/v1/events/feed", params=api_params(league=league))
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["competition"] == league
    option = item["viewing_options"][0]
    assert option["id"] == f"route:{league}:prime_video"
    assert option["app"] == "prime_video"
    assert option["decision"] == "eligible"
    assert option["basis"] == "configured_route"
    assert option["reasons"] == ["user_configured_league_route"]
    assert item["preferred_option_id"] == option["id"]


def test_http_snapshot_pagination_does_not_refetch_and_contract_in_openapi(api):
    client, service, _ = api
    first = client.get("/api/v1/events/feed", params=api_params())
    assert first.status_code == 200
    payload = first.json()
    assert payload["total"] == 3 and payload["count"] == 1
    assert payload["items"][0]["event"]["provider"] == "espn"
    assert payload["items"][0]["viewing_options"][0]["app"] == "prime_video"
    calls = service.get_events.call_count
    service.get_events.side_effect = RuntimeError("sources changed after page 1")
    second = client.get("/api/v1/events/feed", params={"cursor": payload["next_cursor"]})
    assert second.status_code == 200
    assert second.json()["items"][0]["id"] != payload["items"][0]["id"]
    assert service.get_events.call_count == calls
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert "FeedResponse" in schemas and "EventSearchResult" in schemas
    assert (
        client.get(
            "/api/v1/events/feed",
            params={
                "cursor": payload["next_cursor"],
                "limit": 1,
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"start": "2026-10-04T16:00:00"},
        {"end": "2026-10-04T15:00:00Z"},
        {"end": "2026-10-20T00:00:00Z"},
        {"source": "typo"},
        {"status": "playing"},
        {"limit": 501},
        {"lookback_hours": 169},
    ],
)
def test_http_rejects_invalid_queries_before_fetch(api, updates):
    client, service, _ = api
    assert client.get("/api/v1/events/feed", params=api_params(**updates)).status_code == 422
    service.get_events.assert_not_called()


def test_http_source_exception_is_not_successful_empty_feed(api):
    client, service, _ = api
    service.get_events.side_effect = RuntimeError("provider unavailable")
    assert client.get("/api/v1/events/feed", params=api_params()).status_code == 503


def test_http_dazn_source_supports_empty_game_leagues_and_stable_pagination(api):
    import json
    from pathlib import Path

    from teamarr.api.dependencies import get_dazn_tennis_schedule
    from teamarr.services.dazn_tennis import parse_dazn_tennis

    client, _, _ = api
    day = dt("2026-10-03T00:00:00Z").date()
    data = json.loads((Path(__file__).parents[1] / "fixtures/dazn_tennis/live.json").read_text())
    tennis = client.app.dependency_overrides[get_dazn_tennis_schedule]()
    tennis.get_sessions.return_value = parse_dazn_tennis(data, day, dt("2026-10-03T06:00:00Z"))
    params = api_params(source="dazn_tennis", start="2026-10-03T06:00:00Z",
                        end="2026-10-04T06:00:00Z")
    response = client.get("/api/v1/events/feed", params=params)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["kind"] == "broadcast" and item["event"] is None
    assert item["title"] == "Beijing Open: Day 4"
    assert item["viewing_options"][0]["app"] == "prime_video"
    assert item["viewing_options"][0]["channel"] == "DAZN"
    assert item["artwork"]["cover_url"].startswith("https://image.discovery.indazn.com/")
    tennis.get_sessions.side_effect = RuntimeError("schedule unavailable")
    assert client.get("/api/v1/events/feed", params=params).status_code == 503


def test_http_invalid_configuration_is_503(api, monkeypatch):
    client, _, route = api

    def invalid():
        raise ValueError("invalid configuration")

    monkeypatch.setattr(route, "load_broadcast_config", invalid)
    assert client.get("/api/v1/events/feed", params=api_params()).status_code == 503


def test_http_unknown_and_malformed_cursor(api):
    client, _, _ = api
    assert client.get("/api/v1/events/feed?cursor=bad").status_code == 422
    assert client.get("/api/v1/events/feed?cursor=" + "a" * 32 + ".1").status_code == 410


def test_long_special_window_does_not_expand_redzone_fetch_dates():
    config = special_config()
    window = config.special_events.coverage.windows[0].model_copy(
        update={
            "start_time": dt("2026-09-01T16:00:00Z"),
            "coverage_type": "multi_event",
        }
    )
    config.special_events = config.special_events.model_copy(
        update={
            "coverage": config.special_events.coverage.model_copy(update={"windows": (window,)})
        }
    )
    service, calls = builder([game()], config)
    service.build(query(sources=["nfl_redzone", "special_events"], lookback_hours=1))
    assert all(day >= dt("2026-10-03T00:00:00Z").date() for league, day in calls if league == "nfl")
