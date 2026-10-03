"""Observed DAZN data plus broadcast identity, source health and feed integration."""

import copy
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from teamarr.core.controller_feed import FeedQuery
from teamarr.services.broadcast_sessions import BroadcastConfig
from teamarr.services.controller_feed import ControllerFeedBuilder
from teamarr.services.dazn_tennis import DAZNTennisScheduleService, parse_dazn_tennis

DAY = date(2026, 10, 3)
NOW = datetime(2026, 10, 3, 6, 40, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures" / "dazn_tennis"


def payload(name="live"):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_observed_live_and_upcoming_are_broadcasts_not_individual_matches():
    live = parse_dazn_tennis(payload(), DAY, NOW)[0]
    upcoming = parse_dazn_tennis(payload("upcoming"), DAY, NOW)[0]
    assert live.title == live.stream_title == "Beijing Open: Day 4"
    assert live.status == "live" and live.status_received_at == NOW
    assert live.provider_event_id == "72azqisnst7q4bkov8xhkdjdv"
    assert live.provider_asset_id == "8i8e3lsdee53p0t3exybrs1vb"
    assert live.tournament_name == "WTA Beijing, China Women Singles 2026"
    assert live.playback_target == "prime_video" and live.channel == "DAZN"
    assert live.related_events == () and live.parent_event is None
    assert upcoming.status == "scheduled"  # VideoType=Vod is an upcoming stub.
    assert upcoming.expected_end_time is None  # ExpirationDate is not an end time.
    assert live.id != upcoming.id


def test_identity_survives_rescheduling_renaming_and_asset_replacement():
    original = parse_dazn_tennis(payload(), DAY, NOW)[0]
    body = payload()
    body["Tiles"][0].update(
        Title="Beijing Open: Court 1",
        Start="2026-10-04T03:00:00Z",
        End="2026-10-04T16:00:00Z",
        AssetId="replacement-asset",
    )
    changed = parse_dazn_tennis(body, DAY, NOW)[0]
    assert original.id == changed.id
    assert original.listing_url == changed.listing_url
    assert changed.start_time.date() != original.start_time.date()


@pytest.mark.parametrize(
    "change",
    [
        {"Type": "CatchUp"},
        {"Type": "Vod"},
        {"Title": "Beijing Open Highlights"},
        {"IsLinear": True},
        {"Contestants": [{"Title": "Player"}]},
        {"IsGeoRestricted": True},
    ],
)
def test_non_live_coverage_and_match_tiles_are_excluded(change):
    body = payload()
    body["Tiles"][0].update(change)
    assert parse_dazn_tennis(body, DAY, NOW) == []


def test_live_conflict_and_elapsed_end_never_prove_completion():
    body = payload()
    body["Tiles"][0]["VideoType"] = "Vod"
    assert parse_dazn_tennis(body, DAY, NOW)[0].status == "unknown"
    # Scheduled time passing cannot turn UpComing into Live or Final.
    assert (
        parse_dazn_tennis(payload("upcoming"), DAY, NOW + timedelta(days=30))[0].status
        == "scheduled"
    )
    assert parse_dazn_tennis(payload(), DAY, NOW + timedelta(days=30))[0].status == "live"


@pytest.mark.parametrize(
    "change",
    [
        {"EventId": None},
        {"AssetId": "../invalid"},
        {"Title": " "},
        {"Start": "2026-10-03T03:00:00"},
        {"End": "2026-10-02T03:00:00Z"},
    ],
)
def test_malformed_tennis_is_an_error_not_a_successful_empty_day(change):
    body = payload()
    body["Tiles"][0].update(change)
    with pytest.raises(ValueError):
        parse_dazn_tennis(body, DAY, NOW)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"Tiles": []},
        {
            "Id": "en-ca-2026-10-03",
            "Date": "2026-10-02",
            "Tiles": [],
        },
    ],
)
def test_invalid_envelope_is_an_error(body):
    with pytest.raises(ValueError):
        parse_dazn_tennis(body, DAY, NOW)


def test_duplicates_collapse_but_conflicting_sessions_fail():
    body = payload()
    body["Tiles"] *= 2
    assert len(parse_dazn_tennis(body, DAY, NOW)) == 1
    body = copy.deepcopy(body)
    body["Tiles"][1] = {**body["Tiles"][1], "Title": "Different court"}
    with pytest.raises(ValueError, match="Conflicting"):
        parse_dazn_tennis(body, DAY, NOW)


def test_cache_keeps_acquisition_time_and_failure_does_not_become_empty():
    calls = []
    clock = [NOW]

    def fetch(day):
        calls.append(day)
        return payload()

    source = DAZNTennisScheduleService(fetch, lambda: clock[0])
    first = source.get_sessions(DAY)
    clock[0] += timedelta(seconds=15)
    assert source.get_sessions(DAY) == first
    assert calls == [DAY]
    assert first[0].status_received_at == NOW

    def fail(day):
        raise httpx.ConnectError("offline")

    with pytest.raises(httpx.ConnectError):
        DAZNTennisScheduleService(fail).get_sessions(DAY)


def test_download_uses_canadian_utc_buckets(monkeypatch):
    def handler(request):
        assert request.url.params["timeZoneOffset"] == "0"
        assert request.url.params["country"] == "ca"
        assert request.url.params["languageCode"] == "en"
        return httpx.Response(200, json=payload())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(httpx, "stream", client.stream)
        assert DAZNTennisScheduleService._download(DAY) == payload()


def build(fetch, enabled=True):
    return ControllerFeedBuilder(
        lambda league, day: [],
        lambda day: [],
        BroadcastConfig.model_validate({"dazn_tennis": {"enabled": enabled}}),
        UTC,
        {},
        {},
        3,
        get_tennis=fetch,
    )


def query():
    return FeedQuery(
        start=NOW,
        end=NOW + timedelta(days=1),
        as_of=NOW,
        sources=["dazn_tennis"],
        leagues=[],
        lookback_hours=12,
    )


def test_feed_preserves_session_scope_unknown_end_and_prime_route():
    calls = []

    def fetch(day):
        calls.append(day)
        return parse_dazn_tennis(payload(), DAY, NOW) + parse_dazn_tennis(
            payload("upcoming"),
            DAY,
            NOW,
        )

    items = build(fetch).build(query())
    assert calls == [date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4)]
    assert len(items) == 2
    assert items[0].kind == "broadcast" and items[0].event is None
    assert items[0].competition == "tennis" and items[0].sports == ["tennis"]
    assert items[0].status == "live" and items[0].status_basis == "provider"
    assert items[0].status_received_at == NOW
    option = items[0].viewing_options[0]
    assert option.app == "prime_video" and option.channel == "DAZN"
    assert option.stream_title == items[0].title and option.presentation == "live"
    assert items[1].expected_end_time is None and items[1].status == "scheduled"
    assert items[0].related_ids == []


def test_source_can_be_disabled_and_fetch_errors_propagate():
    def fail(day):
        raise RuntimeError("source failed")

    assert build(fail, enabled=False).build(query()) == []
    with pytest.raises(RuntimeError, match="source failed"):
        build(fail).build(query())
