"""RedZone scheduling boundaries and the public API; no live network needed."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import create_app
from teamarr.api.dependencies import get_sports_service
from teamarr.services.broadcast_sessions import RedZoneConfig, RedZoneSource


def game(timestamp, season_type="regular", event_id="123", status="scheduled"):
    return SimpleNamespace(
        id=event_id,
        provider="espn",
        league="nfl",
        start_time=datetime.fromisoformat(timestamp),
        season_type=season_type,
        status=SimpleNamespace(state=status),
    )


def source(events, config=None, timezone=UTC):
    return RedZoneSource(lambda league, day: events, timezone, config)


@pytest.mark.parametrize(
    ("day", "kickoff", "utc_hour"),
    [
        (date(2026, 9, 27), "2026-09-27T17:00:00+00:00", 17),
        (date(2026, 11, 1), "2026-11-01T18:00:00+00:00", 18),
        (date(2027, 1, 3), "2027-01-03T18:00:00+00:00", 18),
    ],
)
def test_regular_season_dst_and_january(day, kickoff, utc_hour):
    session = source([game(kickoff)]).get_sessions(day)[0]
    assert session.start_time.hour == utc_hour
    assert (session.expected_end_time - session.start_time).total_seconds() == 7 * 3600
    assert session.end_time_estimated is True
    assert session.related_events[0].event_id == "123"


@pytest.mark.parametrize("season_type", ["preseason", "postseason", "offseason", None])
def test_non_regular_season_has_no_automatic_session(season_type):
    assert (
        source([game("2027-01-17T18:00:00+00:00", season_type)]).get_sessions(date(2027, 1, 17))
        == []
    )


def test_no_games_or_only_evening_games_has_no_session():
    day = date(2026, 9, 27)
    assert source([]).get_sessions(day) == []
    assert source([game("2026-09-28T00:20:00+00:00")]).get_sessions(day) == []


@pytest.mark.parametrize("status", ["cancelled", "postponed"])
def test_inactive_games_do_not_create_session(status):
    assert (
        source([game("2026-09-27T17:00:00+00:00", status=status)]).get_sessions(date(2026, 9, 27))
        == []
    )


def test_thursday_requires_explicit_override():
    day = date(2026, 11, 26)
    events = [game("2026-11-26T18:00:00+00:00")]
    assert source(events).get_sessions(day) == []
    config = RedZoneConfig.model_validate(
        {"overrides": {str(day): {"start_time": "12:00", "duration_minutes": 600}}}
    )
    session = source([], config).get_sessions(day)[0]
    assert session.start_time == datetime(2026, 11, 26, 17, tzinfo=UTC)
    assert session.timing_basis == "override"
    assert session.related_events == ()


def test_disable_and_same_day_time_correction_preserve_identity():
    day = date(2026, 9, 27)
    events = [game("2026-09-27T17:00:00+00:00")]
    original = source(events).get_sessions(day)[0]
    shifted = RedZoneConfig.model_validate({"overrides": {str(day): {"start_time": "12:55"}}})
    assert source(events, shifted).get_sessions(day)[0].id == original.id
    disabled = RedZoneConfig.model_validate({"overrides": {str(day): {"enabled": False}}})
    assert source(events, disabled).get_sessions(day) == []
    assert source(events, RedZoneConfig(enabled=False)).get_sessions(day) == []


def test_schedule_timezone_date_conversion_and_deduplication():
    calls = []
    event = game("2026-09-27T17:00:00+00:00")

    def fetch(league, day):
        calls.append((league, day))
        return [event, event]

    sessions = RedZoneSource(fetch, ZoneInfo("Pacific/Kiritimati")).get_sessions(date(2026, 9, 27))
    assert calls == [("nfl", date(2026, 9, 28))]
    assert len(sessions[0].related_events) == 1


def test_api_configuration_reload_validation_and_serialization(tmp_path, monkeypatch):
    path = tmp_path / "broadcasts.json"
    monkeypatch.setenv("TEAMARR_BROADCAST_CONFIG", str(path))
    path.write_text('{"redzone": {"overrides": {"2026-09-27": {}}}}')
    app = create_app()
    app.dependency_overrides[get_sports_service] = lambda: SimpleNamespace(
        get_events=lambda league, day: []
    )
    # No lifespan/database/background workers are needed to exercise the route.
    client = TestClient(app)
    url = "/api/v1/broadcast-sessions?target_date=2026-09-27"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()[0]["id"] == "nfl_redzone:2026-09-27"
    assert response.json()[0]["start_time"] == "2026-09-27T17:00:00Z"
    path.write_text('{"redzone": {"enabled": false}}')
    assert client.get(url).json() == []
    path.write_text('{"redzone": {"duration_minutes": -1}}')
    assert client.get(url).status_code == 503
    path.unlink()
    assert client.get(url).status_code == 503
    monkeypatch.delenv("TEAMARR_BROADCAST_CONFIG")
    assert client.get(url).json() == []
    assert client.get("/api/v1/broadcast-sessions?target_date=not-a-date").status_code == 422
    assert client.get(url + "&source=unknown").status_code == 422


def test_configuration_rejects_offset_time_and_unknown_fields():
    with pytest.raises(ValueError):
        RedZoneConfig(start_time="13:00+03:00")
    with pytest.raises(ValueError):
        RedZoneConfig.model_validate({"enable": False})
