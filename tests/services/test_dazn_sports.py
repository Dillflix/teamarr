"""Observed NSL/Beatdown tiles through parsing, configuration and feed assembly."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from teamarr.core.controller_feed import FeedQuery
from teamarr.services.broadcast_sessions import BroadcastConfig
from teamarr.services.controller_feed import ControllerFeedBuilder
from teamarr.services.dazn_sports import DAZNSportsScheduleService, parse_dazn_sports
from teamarr.services.dazn_tennis import parse_dazn_tennis

NOW = datetime(2026, 10, 29, 22, 30, tzinfo=UTC)


def payload(day="2026-10-30"):
    return json.loads((Path(__file__).parents[1] / "fixtures" / "dazn_sports"
                       / f"{day}.json").read_text())


def test_observed_squash_and_mma_preserve_provider_scope():
    squash = parse_dazn_sports(payload("2026-10-29"), NOW.date(), NOW)[0]
    mma = parse_dazn_sports(payload(), date(2026, 10, 30), NOW)[0]
    assert (squash.title, squash.competition, squash.sport, squash.status) == (
        "Philadelphia Freedom vs. Seattle Freeze", "nsl", "squash", "live")
    assert (mma.title, mma.competition, mma.sport, mma.status) == (
        "Beatdown 15: James vs. Stoddart", "beatdown", "mma", "scheduled")
    assert mma.kind == "fight_card" and mma.expected_end_time is None
    assert squash.related_events == mma.related_events == ()
    assert mma.id == "dazn_sports:ca:1vot4cy3ukrao1s1yx437lkdk9"
    assert mma.start_time == datetime(2026, 10, 30, 7, tzinfo=UTC)
    assert mma.playback_target == "prime_video" and mma.channel == "DAZN"
    assert parse_dazn_tennis(payload(), date(2026, 10, 30), NOW) == []


@pytest.mark.parametrize("change", [
    {"Type": "CatchUp"}, {"Type": "Vod"}, {"IsLinear": True},
    {"IsGeoRestricted": True}, {"Title": "Beatdown Highlights"},
    {"Title": "Beatdown Press Conference"},
    {"Title": "Beatdown Weigh-In"},
    {"Competition": {"Id": "other-promotion", "Title": "MMA Beatdown"}},
    {"Sport": {"Title": "Boxing"}},
])
def test_no_replays_shows_or_unrelated_promotions(change):
    body = payload()
    body["Tiles"] = [{**body["Tiles"][0], **change}]
    assert parse_dazn_sports(body, date(2026, 10, 30), NOW) == []


def test_identity_survives_title_asset_and_start_changes():
    body = payload()
    original = parse_dazn_sports(body, date(2026, 10, 30), NOW)[0]
    body["Tiles"][0].update(Title="Beatdown 15", AssetId="replacement",
                            Start="2026-10-31T07:00:00Z")
    changed = parse_dazn_sports(body, date(2026, 10, 30), NOW)[0]
    assert changed.id == original.id and changed.status == "scheduled"
    body["Tiles"][0]["EventId"] = None
    with pytest.raises(ValueError):
        parse_dazn_sports(body, date(2026, 10, 30), NOW)


def build(config=None, fetch=None):
    return ControllerFeedBuilder(
        lambda league, day: [], lambda day: [], config or BroadcastConfig(), UTC,
        {}, {}, 3, get_tennis=lambda day: [], get_dazn_sports=fetch,
    )


def query():
    return FeedQuery(start=NOW, end=NOW + timedelta(days=2), as_of=NOW,
                     leagues=[], lookback_hours=1)


def test_default_feed_includes_both_without_espn_leagues_and_deduplicates():
    sessions = parse_dazn_sports(payload("2026-10-29"), NOW.date(), NOW)
    sessions += parse_dazn_sports(payload(), date(2026, 10, 30), NOW)
    items = build(fetch=lambda day: sessions).build(query())
    assert len(items) == 3
    assert {item.competition for item in items} == {"nsl", "beatdown"}
    for item in items:
        assert item.kind == "broadcast" and item.event is None
        assert item.source == "dazn_sports" and item.status_basis == "provider"
        assert item.status_received_at == NOW
        assert item.viewing_options[0].app == "prime_video"
        assert item.viewing_options[0].stream_title == item.title


def test_config_opt_out_and_failure_semantics():
    def fail(day):
        raise RuntimeError("offline")
    for config in ({"enabled": False}, {"competitions": []}):
        assert build(BroadcastConfig(dazn_sports=config), fail).build(query()) == []
    with pytest.raises(RuntimeError, match="offline"):
        build(fetch=fail).build(query())
    sessions = parse_dazn_sports(payload(), date(2026, 10, 30), NOW)
    items = build(BroadcastConfig(dazn_sports={"competitions": ["beatdown"]}),
                  lambda day: sessions).build(query())
    assert len(items) == 1 and items[0].competition == "beatdown"


def test_cache_retains_acquisition_time_and_never_infers_completion():
    calls = []
    def fetch(day):
        calls.append(day)
        return payload()
    source = DAZNSportsScheduleService(fetch, lambda: NOW)
    first = source.get_sessions(date(2026, 10, 30))
    assert source.get_sessions(date(2026, 10, 30)) == first
    assert len(calls) == 1 and first[0].status_received_at == NOW
    later = parse_dazn_sports(payload(), date(2026, 10, 30), NOW + timedelta(days=30))
    assert later[0].status == "scheduled"
