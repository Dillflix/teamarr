"""Broadcast identity joins and conservative selection of live viewing options."""

import json
from datetime import UTC, date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import create_app
from teamarr.api.dependencies import get_sports_service
from teamarr.core.special_coverage import SpecialCoverageWindow
from teamarr.services.broadcast_sessions import BroadcastConfig
from teamarr.services.special_coverage import SpecialCoverageSource
from teamarr.services.special_events import SpecialEventsCatalog, SpecialEventsConfig


def config_data(windows, **preferences):
    data = json.loads(Path("docs/examples/special-events.json").read_text())["special_events"]
    data["sessions"][0]["countries"] = ["CAN", "USA"]
    data["coverage"] = {"windows": windows, **preferences}
    return data


def window(**changes):
    data = {
        "id": "hockey-main",
        "edition_id": "demo-winter-games",
        "title": "Example hockey final coverage",
        "start_time": "2030-02-10T11:30:00Z",
        "end_time": "2030-02-10T15:00:00Z",
        "timezone": "Europe/Paris",
        "app": "cbc_gem",
        "stream_title": "Women's hockey final",
        "sports": ["hockey"],
        "related_sessions": [
            {"edition_id": "demo-womens-hockey", "provider": "configured", "id": "hockey-final"}
        ],
    }
    data.update(changes)
    return data


def options(data, session_update=None):
    config = SpecialEventsConfig.model_validate(data)
    catalog = SpecialEventsCatalog(config, lambda league, day: [], UTC)
    session = config.sessions[0]
    if session_update:
        session = type(session).model_validate({**session.model_dump(), **session_update})
    selection = catalog.select(session, config.rules[0])
    return SpecialCoverageSource(config).get_options(selection)


def test_exact_identity_link_and_parent_edition_preserve_navigation_metadata():
    result = options(config_data([window()]))
    assert result.preferred_broadcast_id == "special_events:hockey-main"
    broadcast = result.options[0].broadcast
    assert broadcast.related_sessions[0].identity == (
        "demo-womens-hockey",
        "configured",
        "hockey-final",
    )
    assert broadcast.edition_id == "demo-winter-games"
    assert broadcast.playback_target == "cbc_gem"
    assert broadcast.stream_title == "Women's hockey final"
    assert broadcast.presentation == "live"
    assert broadcast.timing_basis == "configured"


def test_matching_titles_and_times_do_not_replace_exact_identity():
    other = window(
        related_sessions=[
            {"edition_id": "demo-womens-hockey", "provider": "other", "id": "hockey-final"}
        ]
    )
    assert options(config_data([other])).options == ()
    with pytest.raises(ValueError, match="outside its edition scope"):
        SpecialEventsConfig.model_validate(config_data([window(edition_id="demo-four-nations")]))


def test_multiple_feeds_rank_app_preferences_without_rewriting_destinations():
    data = config_data(
        [window(id="cbc"), window(id="tsn", app="tsn"), window(id="sn", app="sportsnet")],
        preferred_apps=["sportsnet", "tsn"],
        allowed_apps=["tsn", "sportsnet"],
    )
    result = options(data)
    assert result.preferred_broadcast_id == "special_events:sn"
    assert [option.broadcast.playback_target for option in result.options] == [
        "sportsnet",
        "tsn",
        "cbc_gem",
    ]
    assert result.options[-1].decision == "excluded"
    assert result.options[-1].reasons == ("app_not_allowed",)
    assert options(config_data([window()], allowed_apps=[])).preferred_broadcast_id is None


@pytest.mark.parametrize(
    ("changes", "decision", "reason"),
    [
        ({"presentation": "replay"}, "excluded", "replay"),
        ({"end_time": "2030-02-10T12:00:00Z"}, "excluded", "ends_before_event"),
        ({"start_time": "2030-02-10T12:30:00Z"}, "review", "starts_after_event"),
        ({"end_time": None}, "review", "end_time_unknown"),
        ({"coverage_type": "multi_event"}, "review", "multi_event_coverage"),
    ],
)
def test_unsuitable_or_uncertain_coverage_is_not_preferred(changes, decision, reason):
    result = options(config_data([window(**changes)]))
    assert result.options[0].decision == decision
    assert reason in result.options[0].reasons
    assert result.preferred_broadcast_id is None


def test_known_partial_coverage_and_schedule_move_require_reassessment():
    data = config_data([window()])
    assert options(data, {"end_time": "2030-02-10T16:00:00Z"}).options[0].reasons == (
        "ends_during_event",
    )
    result = options(data, {"start_time": "2030-02-11T12:00:00Z"})
    assert result.options[0].reasons == ("ends_before_event",)
    assert result.preferred_broadcast_id is None


def test_broad_multisport_coverage_remains_unconfirmed_and_expires():
    broad = window(coverage_type="multi_event", sports=[], related_sessions=[])
    result = options(config_data([broad]))
    assert result.options[0].broadcast.sport is None
    assert result.options[0].broadcast.sports == ()
    assert result.options[0].reasons == ("multi_event_coverage", "event_coverage_unconfirmed")
    assert options(config_data([broad]), {"start_time": "2030-02-11T12:00:00Z"}).options == ()
    assert options(config_data([dict(broad, sports=["skiing"])])).options == ()


def test_multi_event_listing_can_reference_several_sports_without_becoming_dedicated():
    broad = window(coverage_type="multi_event", sports=["hockey", "skiing"])
    broad["related_sessions"].append(
        {"edition_id": "demo-winter-games", "provider": "configured", "id": "downhill"}
    )
    config = SpecialEventsConfig.model_validate(config_data([broad]))
    service = SpecialCoverageSource(config)
    catalog = SpecialEventsCatalog(config, lambda league, day: [], UTC)
    for item in config.sessions[:2]:
        result = service.get_options(catalog.select(item, config.rules[0]))
        assert (
            result.options[0].broadcast.related_sessions
            == config.coverage.windows[0].related_sessions
        )
        assert result.preferred_broadcast_id is None


@pytest.mark.parametrize(
    "update", [{"countries": None}, {"status": "cancelled"}, {"countries": []}]
)
def test_nonmatching_or_pending_contest_never_has_preferred_playback(update):
    result = options(config_data([window()]), update)
    assert (
        result.options[0].decision == "eligible"
    )  # Suitability is distinct from the viewing rule.
    assert result.selection.decision != "match"
    assert result.preferred_broadcast_id is None


def test_broadcast_on_previous_local_day_can_cover_next_day_contest():
    data = config_data([window(start_time="2030-02-09T22:30:00Z", end_time="2030-02-10T03:00:00Z")])
    config = SpecialEventsConfig.model_validate(data)
    source = SpecialCoverageSource(config)
    assert len(source.get_sessions(date(2030, 2, 9))) == 1
    assert source.get_sessions(date(2030, 2, 10)) == []
    assert options(data, {"start_time": "2030-02-10T00:00:00Z"}).preferred_broadcast_id is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"related_sessions": []},
        {"start_time": "2030-02-10T12:00:00"},
        {"end_time": "2030-02-10T10:00:00Z"},
        {"timezone": "wrong/zone"},
        {"coverage_type": "multi_event", "related_sessions": [], "end_time": None},
    ],
)
def test_invalid_listings_are_rejected(changes):
    with pytest.raises(ValueError):
        SpecialCoverageWindow.model_validate(window(**changes))


def test_duplicate_and_unknown_edition_listings_are_rejected():
    for rows in ([window(), window()], [window(edition_id="absent")]):
        with pytest.raises(ValueError):
            SpecialEventsConfig.model_validate(config_data(rows))


def test_endpoints_reload_and_do_not_call_golf_or_device_services(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("TEAMARR_BROADCAST_CONFIG", str(config_path))
    data = config_data([window()])
    config_path.write_text(json.dumps({"special_events": data}))
    app = create_app()
    app.dependency_overrides[get_sports_service] = lambda: SimpleNamespace(
        get_events=lambda league, day: pytest.fail("Configured sessions must not fetch leagues")
    )
    client = TestClient(app)
    query = "?target_date=2030-02-10"
    broadcasts = "/api/v1/broadcast-sessions" + query + "&source=special_events"
    response = client.get(broadcasts)
    assert response.status_code == 200
    assert response.json()[0]["related_sessions"][0]["edition_id"] == "demo-womens-hockey"
    endpoint = "/api/v1/special-events/viewing-options" + query + "&rule_id=canada-hockey-medals"
    result = client.get(endpoint)
    assert result.status_code == 200
    assert result.json()[1]["preferred_broadcast_id"] == "special_events:hockey-main"
    data["coverage"]["windows"][0]["enabled"] = False
    config_path.write_text(json.dumps({"special_events": data}))
    assert client.get(broadcasts).json() == []
    assert all(row["preferred_broadcast_id"] is None for row in client.get(endpoint).json())
    assert client.get(endpoint.replace("canada-hockey-medals", "absent")).status_code == 404
    config_path.write_text('{"special_events": {"coverage": {"windows": [{}]}}}')
    assert client.get(endpoint).status_code == 503
    assert client.get(broadcasts).status_code == 503


def test_golf_app_allowlist_does_not_leak_into_olympic_options():
    config = BroadcastConfig.model_validate(
        {
            "golf": {"allowed_apps": ["tsn"]},
            "special_events": config_data([window()]),
        }
    )
    catalog = SpecialEventsCatalog(config.special_events, lambda league, day: [], UTC)
    selection = catalog.select(config.special_events.sessions[0], config.special_events.rules[0])
    result = SpecialCoverageSource(config.special_events).get_options(selection)
    assert result.preferred_broadcast_id is not None
    assert result.options[0].broadcast.playback_target == "cbc_gem"
