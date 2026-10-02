from dataclasses import replace
from datetime import timedelta

from test_controller_feed import builder, dt, game, query

from teamarr.core import EventStatus, RacingSession
from teamarr.database.provider_cache import dict_to_event, event_to_dict
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.services.sports_data import _event_dict_is_stale


def weekend():
    return game(
        id="weekend",
        league="f1",
        sport="racing",
        name="Singapore Grand Prix",
        start="2026-10-02T09:30:00Z",
        status=EventStatus("scheduled"),
        sessions=[
            RacingSession(
                "fp1", "Practice 1", dt("2026-10-02T09:30:00Z"), id="practice", status="final"
            ),
            RacingSession(
                "qualifying", "Qualifying", dt("2026-10-03T13:00:00Z"), id="quali", status="live"
            ),
            RacingSession(
                "race", "Race", dt("2026-10-04T12:00:00Z"), id="race", status="scheduled"
            ),
        ],
    )


def test_f1_sessions_have_separate_stable_identity_status_and_prime_routes():
    event = weekend()
    service, _ = builder([event])
    window = query(leagues=["f1"], start=dt("2026-10-02T00:00:00Z"), end=dt("2026-10-05T00:00:00Z"))
    items = service.build(window)
    assert len(items) == 3
    assert [i.status for i in items] == ["final", "live", "scheduled"]
    assert all(i.kind == "session" and i.source == "games" for i in items)
    assert all(i.event.home_team_details is i.event.away_team_details is None for i in items)
    assert all(i.event.tournament_id == "weekend" for i in items)
    assert all(i.viewing_options[0].app == "prime_video" for i in items)
    assert all(i.viewing_options[0].id == "route:f1:prime_video" for i in items)
    assert items[0].preferred_option_id is None
    assert items[1].preferred_option_id == "route:f1:prime_video"
    assert items[-1].title == "Singapore Grand Prix — Race"
    assert len({i.id for i in items}) == 3
    moved = replace(
        event,
        name="Renamed Grand Prix",
        sessions=[replace(s, start_time=s.start_time + timedelta(hours=2)) for s in event.sessions],
    )
    updated, _ = builder([moved])
    assert [i.id for i in updated.build(window)] == [i.id for i in items]


def test_live_session_overruns_estimate_without_weekend_status_or_time_inference():
    event = weekend()
    service, _ = builder([event])
    window = query(leagues=["f1"], start=dt("2026-10-03T19:00:00Z"), statuses=["live"])
    items = service.build(window)
    assert len(items) == 1 and items[0].event.event_id == "quali"
    assert items[0].expected_end_time < window.start
    unknown = replace(event, sessions=[replace(event.sessions[1], status="unknown")])
    service, _ = builder([unknown])
    assert service.build(window) == []


def test_session_identity_and_status_survive_cache_and_legacy_cache_stays_unknown():
    event = weekend()
    payload = event_to_dict(event)
    assert not _event_dict_is_stale(payload)
    assert dict_to_event(payload).sessions == event.sessions
    for row in payload["sessions"]:
        row.pop("id")
        row.pop("status")
        row.pop("status_detail")
    restored = dict_to_event(payload)
    assert _event_dict_is_stale(payload)
    assert all(s.id is None and s.status == "unknown" for s in restored.sessions)
    service, _ = builder([restored])
    assert service.build(query(leagues=["f1"])) == []


def test_espn_session_uses_its_own_id_status_and_handles_postponed_cancelled():
    provider = ESPNProvider()
    competition = {"id": "876", "date": "2026-10-04T12:00Z", "type": {"abbreviation": "Race"}}
    for source, expected in [
        ({}, "unknown"),
        ({"state": "pre"}, "scheduled"),
        ({"state": "in"}, "live"),
        ({"state": "post"}, "final"),
        ({"state": "pre", "name": "STATUS_POSTPONED"}, "postponed"),
        ({"state": "post", "name": "STATUS_CANCELED"}, "cancelled"),
    ]:
        session = provider._parse_racing_session({**competition, "status": {"type": source}})
        assert session.id == "876"
        assert session.status == expected
