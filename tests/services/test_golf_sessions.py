"""Golf calendars and configured coverage must never be confused with each other."""

from copy import deepcopy
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import create_app
from teamarr.api.dependencies import get_golf_catalog, get_sports_service
from teamarr.providers.espn.golf import parse_golf_tournaments
from teamarr.services.golf import GolfCatalogService
from teamarr.services.golf_sessions import GolfConfig, GolfSessionSource


@pytest.fixture
def scoreboard():
    return {
        "events": [
            {
                "id": "123",
                "name": "Example Championship",
                "date": "2026-09-17T04:00Z",
                "endDate": "2026-09-20T04:00Z",
                "season": {"year": 2026},
                "competitions": [
                    {
                        "timeValid": False,
                        "status": {"period": 4, "type": {"state": "post", "name": "STATUS_FINAL"}},
                        "broadcasts": [{"names": ["ESPN+", "Golf Chnl", "ESPN+"]}],
                    }
                ],
            }
        ],
    }


def window(**changes):
    return {
        "key": "round4-main",
        "tournament_id": "123",
        "tournament_name": "Example Championship",
        "round_number": 4,
        "start_time": "2026-09-20T13:00:00-04:00",
        **changes,
    }


def sessions(windows, day=date(2026, 9, 20), **config):
    return GolfSessionSource(GolfConfig(coverage=windows, **config)).get_sessions(day)


def test_calendar_retains_full_span_and_round_without_becoming_session(scoreboard):
    tournaments = parse_golf_tournaments(scoreboard, "pga")
    assert len(tournaments) == 1
    tournament = tournaments[0]
    assert tournament.name == "Example Championship"
    assert tournament.start_date == date(2026, 9, 17)
    assert tournament.end_date == date(2026, 9, 20)
    assert tournament.current_round == 4
    assert tournament.status == "final"
    assert tournament.season_year == 2026
    assert tournament.broadcasters == ("ESPN+", "Golf Chnl")
    assert sessions([]) == []


def test_discovery_on_final_day_retains_original_start_and_caches(scoreboard):
    calls = []

    def fetch(*args):
        calls.append(args)
        return scoreboard

    catalog = GolfCatalogService(SimpleNamespace(get_scoreboard=fetch))
    assert catalog.get_tournaments(date(2026, 9, 20))[0].start_date == date(2026, 9, 17)
    first = catalog.get_tournaments(date(2026, 9, 20))
    first.clear()
    assert len(catalog.get_tournaments(date(2026, 9, 20))) == 1
    assert calls == [("pga", "20260920", ("golf", "pga"))]
    with pytest.raises(ValueError):
        catalog.get_tournaments(date(2026, 9, 20), "unsupported")


def test_missing_end_unknown_status_and_malformed_neighbor(scoreboard):
    event = scoreboard["events"][0]
    del event["endDate"]
    event["competitions"][0]["status"] = {}
    scoreboard["events"].append({"id": "bad", "name": "Bad", "date": "not-a-date"})
    scoreboard["events"].append(deepcopy(event))
    tournaments = parse_golf_tournaments(scoreboard, "pga")
    assert len(tournaments) == 1
    assert tournaments[0].end_date is None
    assert tournaments[0].status == "unknown"


def test_round_session_parent_utc_and_unknown_end():
    session = sessions([window()])[0]
    assert session.id == "golf:espn:pga:123:round4-main"
    assert session.start_time == datetime(2026, 9, 20, 17, tzinfo=UTC)
    assert session.expected_end_time is None
    assert session.end_time_estimated is True
    assert session.parent_event == session.related_events[0]
    assert session.parent_event.event_id == "123"
    assert session.segment == "round_4"
    assert session.coverage_type == "main"
    assert session.playback_target is None
    assert session.timing_basis == "configured"


def test_delayed_round_keeps_id_and_moves_date():
    original = sessions([window()])[0]
    delayed = window(start_time="2026-09-21T09:00:00-04:00")
    assert sessions([delayed]) == []
    assert sessions([delayed], day=date(2026, 9, 21))[0].id == original.id


def test_multiple_windows_for_one_round_and_routing_override():
    first = window(end_time="2026-09-20T15:00:00-04:00", end_time_estimated=False)
    second = window(
        key="round4-main-late",
        start_time="2026-09-20T15:00:00-04:00",
        playback_target="alternate_app",
    )
    result = sessions([second, first], playback_target="golf_app")
    assert len(result) == 2
    assert result[0].playback_target == "golf_app"
    assert result[1].playback_target == "alternate_app"
    assert result[0].end_time_estimated is False
    assert result[0].expected_end_time == result[1].start_time


def test_session_date_follows_configured_timezone_and_overnight_end():
    coverage = window(
        start_time="2026-09-21T03:00:00Z",
        end_time="2026-09-21T10:00:00Z",
        timezone="America/Vancouver",
    )
    assert len(sessions([coverage])) == 1
    assert sessions([coverage], day=date(2026, 9, 21)) == []
    assert sessions([coverage])[0].expected_end_time == datetime(2026, 9, 21, 10, tzinfo=UTC)


def test_distinct_tournaments_same_day_disable_and_unknown_round():
    events = [window(), window(tournament_id="456", round_number=None)]
    result = sessions(events)
    assert len(result) == 2
    assert result[1].segment is None
    assert sessions(events, enabled=False) == []
    assert sessions([window(enabled=False)]) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"start_time": "2026-09-20T13:00:00"},
        {"end_time": "2026-09-20T12:00:00-04:00"},
        {"end_time": "2026-09-20T13:00:00-04:00"},
        {"end_time": "2026-09-20T19:00:00"},
        {"timezone": "Invalid/Timezone"},
        {"round_number": 0},
        {"key": ""},
        {"competition": "unvalidated-tour"},
    ],
)
def test_invalid_coverage_is_rejected(changes):
    with pytest.raises(ValueError):
        GolfConfig(coverage=[window(**changes)])


def test_duplicate_identity_is_rejected_even_with_different_start():
    with pytest.raises(ValueError):
        GolfConfig(coverage=[window(), window(start_time="2026-09-20T14:00:00-04:00")])


@pytest.mark.parametrize(
    ("name", "major"),
    [
        ("Masters Tournament", "masters"),
        ("PGA Championship", "pga_championship"),
        ("U.S. Open", "us_open"),
        ("The Open", "the_open"),
        ("The Open Championship", "the_open"),
        ("THE PLAYERS Championship", None),
        ("RBC Canadian Open", None),
    ],
)
def test_major_identification(scoreboard, name, major):
    scoreboard["events"][0]["name"] = name
    assert parse_golf_tournaments(scoreboard, "pga")[0].major == major


def test_season_and_day_cache_keys_do_not_collide(scoreboard):
    calls = []

    def fetch(*args):
        calls.append(args)
        return scoreboard

    catalog = GolfCatalogService(SimpleNamespace(get_scoreboard=fetch))
    catalog.get_season(2026)
    catalog.get_tournaments(date(2026, 9, 20))
    catalog.get_season(2026)
    assert calls == [("pga", "2026", ("golf", "pga")), ("pga", "20260920", ("golf", "pga"))]


def test_api_discovery_configuration_reload_and_backwards_compatibility(
    scoreboard, tmp_path, monkeypatch
):
    path = tmp_path / "broadcasts.json"
    monkeypatch.setenv("TEAMARR_BROADCAST_CONFIG", str(path))
    config = GolfConfig(coverage=[window()])
    path.write_text('{"golf":' + config.model_dump_json() + "}")
    app = create_app()
    app.dependency_overrides[get_sports_service] = lambda: SimpleNamespace(
        get_events=lambda league, day: []
    )
    app.dependency_overrides[get_golf_catalog] = lambda: GolfCatalogService(
        SimpleNamespace(get_scoreboard=lambda *args: scoreboard)
    )
    client = TestClient(app)
    calendar = client.get("/api/v1/golf/tournaments?target_date=2026-09-20")
    assert calendar.status_code == 200
    assert calendar.json()[0]["end_date"] == "2026-09-20"
    assert client.get("/api/v1/golf/tournaments?season_year=2026").status_code == 200
    assert client.get("/api/v1/golf/tournaments?season_year=2026&majors_only=true").json() == []
    scoreboard["events"][0]["name"] = "Masters Tournament"
    assert (
        client.get("/api/v1/golf/tournaments?season_year=2026&majors_only=true").json()[0]["major"]
        == "masters"
    )
    assert client.get("/api/v1/golf/tournaments").status_code == 422
    assert (
        client.get("/api/v1/golf/tournaments?season_year=2026&target_date=2026-09-20").status_code
        == 422
    )
    url = "/api/v1/broadcast-sessions?source=golf&target_date=2026-09-20"
    result = client.get(url)
    assert result.status_code == 200
    assert result.json()[0]["parent_event"] == {"provider": "espn", "event_id": "123"}
    assert result.json()[0]["expected_end_time"] is None
    path.write_text('{"golf":{"enabled":false}}')
    assert client.get(url).json() == []
    assert client.get("/api/v1/broadcast-sessions?target_date=2026-09-20").json() == []
    path.write_text('{"golf":{"coverage":[{}]}}')
    assert client.get(url).status_code == 503
    assert client.get("/api/v1/golf/tournaments?target_date=bad").status_code == 422
    assert (
        client.get(
            "/api/v1/golf/tournaments?target_date=2026-09-20&competition=unsupported"
        ).status_code
        == 422
    )
