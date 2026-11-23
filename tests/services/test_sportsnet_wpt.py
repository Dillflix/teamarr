import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from teamarr.core.controller_feed import FeedQuery
from teamarr.services.broadcast_sessions import BroadcastConfig
from teamarr.services.controller_feed import ControllerFeedBuilder
from teamarr.services.sportsnet_wpt import SportsnetWPTScheduleService, parse_sportsnet_wpt

DAY = date(2026, 11, 23)
NOW = datetime(2026, 11, 23, 20, 30, tzinfo=UTC)


def payload():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/sportsnet_wpt/2026-11-23.json").read_text()
    )


def test_consecutive_tv_episodes_have_distinct_stable_airing_identities():
    first, second = parse_sportsnet_wpt(payload(), DAY, NOW)
    assert first.title == second.title == "World Poker Tour"
    assert first.id != second.id
    assert first.expected_end_time == second.start_time
    assert (first.status, second.status) == ("live", "scheduled")
    assert first.channel == "Sportsnet Pacific"
    assert first.coverage_type == "linear_program" and first.competition == "wpt"
    assert first.related_events == () and first.sport == "poker"
    body = payload()
    body[0]["schedules"][0]["item"]["id"] = "replacement-program-id"
    assert parse_sportsnet_wpt(body, DAY, NOW)[0].id == first.id


@pytest.mark.parametrize(
    "field,value",
    [
        ("VideoStatus", "OnDemand"),
        ("VideoWorkflow", "VOD"),
        ("CatalogType", "vod"),
    ],
)
def test_only_live_channel_airings_are_included(field, value):
    body = payload()
    for row in body[0]["schedules"]:
        row["customFields"][field] = value
    assert parse_sportsnet_wpt(body, DAY, NOW) == []


def test_other_poker_series_are_not_wpt():
    body = payload()
    for row in body[0]["schedules"]:
        row["item"]["title"] = "Poker After Dark"
    assert parse_sportsnet_wpt(body, DAY, NOW) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b[0].update(startDate="2026-11-22T00:00:00Z"),
        lambda b: b[0].update(channelId="unknown"),
        lambda b: b[0]["schedules"][0].update(channelId="155049"),
        lambda b: b[0]["schedules"][0].update(id=None),
        lambda b: b[0]["schedules"][0].update(endDate="2026-11-23T20:00:00Z"),
        lambda b: b[0]["schedules"][0].update(startDate="2026-11-23T20:00:00"),
    ],
)
def test_invalid_source_data_fails_instead_of_claiming_empty_schedule(mutation):
    body = payload()
    mutation(body)
    with pytest.raises(ValueError):
        parse_sportsnet_wpt(body, DAY, NOW)


def test_cache_keeps_evidence_time_and_elapsed_end_does_not_prove_completion():
    calls = []

    def fetch(day):
        calls.append(day)
        return payload()

    source = SportsnetWPTScheduleService(fetch, lambda: NOW)
    assert source.get_sessions(DAY) == source.get_sessions(DAY)
    assert calls == [DAY]
    later = parse_sportsnet_wpt(payload(), DAY, NOW + timedelta(days=1))
    assert [s.status for s in later] == ["live", "scheduled"]


def test_default_feed_and_opt_out_without_game_leagues():
    sessions = parse_sportsnet_wpt(payload(), DAY, NOW)

    def build(config):
        return ControllerFeedBuilder(
            lambda league, day: [],
            lambda day: [],
            config,
            UTC,
            {},
            {},
            3,
            get_tennis=lambda day: [],
            get_dazn_sports=lambda day: [],
            get_sportsnet_wpt=lambda day: sessions,
        ).build(FeedQuery(start=NOW, end=NOW + timedelta(hours=3), as_of=NOW, leagues=[]))

    items = build(BroadcastConfig())
    assert len(items) == 2
    assert all(i.kind == "broadcast" and i.event is None for i in items)
    assert all(i.status_basis == "provider" and i.status_received_at == NOW for i in items)
    assert all(i.viewing_options[0].channel == "Sportsnet Pacific" for i in items)
    assert build(BroadcastConfig(sportsnet_wpt={"enabled": False})) == []
