"""Special competition identity, schedule refresh and rule selection contracts."""

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import create_app
from teamarr.api.dependencies import get_sports_service
from teamarr.core.special_events import ScheduledSession, ViewingRule
from teamarr.services.special_events import SpecialEventsCatalog, SpecialEventsConfig


def configuration(**changes):
    data = {
        "competitions": [
            {"id": "winter-olympics", "name": "Winter Olympics"},
            {"id": "olympic-hockey", "name": "Olympic Hockey", "sports": ["hockey"]},
            {"id": "four-nations", "name": "4 Nations Face-Off", "sports": ["hockey"]},
        ],
        "editions": [
            {
                "id": key,
                "competition_id": competition,
                "name": key,
                "start_date": "2026-02-01",
                "end_date": "2026-02-28",
                "timezone": "Europe/Rome",
                "parent_edition_id": parent,
            }
            for key, competition, parent in (
                ("winter-test", "winter-olympics", None),
                ("hockey-test", "olympic-hockey", "winter-test"),
                ("nations-test", "four-nations", None),
            )
        ],
    }
    data.update(changes)
    return data


def session(**changes):
    data = {
        "id": "final",
        "provider": "manual",
        "edition_id": "hockey-test",
        "title": "Example final",
        "sport": "hockey",
        "category": "women",
        "stage": "final",
        "countries": ["CAN", "USA"],
        "medal_event": True,
        "start_time": "2026-02-22T12:00:00+01:00",
    }
    data.update(changes)
    return ScheduledSession.model_validate(data)


def catalog(data=None, fetch=None, timezone=UTC):
    return SpecialEventsCatalog(
        SpecialEventsConfig.model_validate(data or configuration()),
        fetch or (lambda league, day: []),
        timezone,
    )


def rule(**changes):
    return ViewingRule.model_validate({"id": "canada-medals", **changes})


def test_olympic_parent_selection_does_not_include_unrelated_hockey():
    service = catalog()
    selected = rule(edition_ids=["winter-test"], countries=["CAN"], medal_event=True)
    assert service.select(session(), selected).decision == "match"
    assert service.select(session(edition_id="nations-test"), selected).decision == "no_match"
    assert (
        service.select(
            session(), selected.model_copy(update={"include_descendants": False})
        ).decision
        == "no_match"
    )
    assert service.select(session(), rule(competition_ids=["winter-olympics"])).decision == "match"


def test_unknown_participation_is_pending_and_refresh_can_match_same_identity():
    service = catalog()
    selected = rule(countries=["CAN"], stages=["semifinal", "final"])
    before = session(countries=None)
    after = session(countries=["CAN", "SWE"], start_time="2026-02-23T12:00:00+01:00")
    result = service.select(before, selected)
    assert result.decision == "pending"
    assert result.reasons == ("countries",)
    assert service.select(after, selected).decision == "match"
    assert before.identity == after.identity
    assert service.select(session(countries=[]), selected).decision == "no_match"


def test_known_mismatch_beats_unknown_and_filters_are_and_between_or_within():
    result = catalog().select(session(countries=None), rule(countries=["CAN"], categories=["men"]))
    assert result.decision == "no_match"
    assert result.reasons == ("categories",)
    assert (
        catalog()
        .select(session(), rule(countries=["CAN", "FIN"], stages=["semifinal", "final"]))
        .decision
        == "match"
    )


@pytest.mark.parametrize("status", ["final", "cancelled", "postponed"])
def test_inactive_contests_remain_in_catalog_but_are_not_selected(status):
    item = session(status=status)
    service = catalog(configuration(sessions=[item.model_dump(mode="json")]))
    assert service.get_sessions(date(2026, 2, 22)) == [item]
    assert service.select(item, rule()).decision == "no_match"


def test_individual_session_and_ceremony_need_no_fake_teams():
    race = session(
        edition_id="winter-test", sport="skiing", kind="race", participants=["Example athlete"]
    )
    ceremony = session(
        edition_id="winter-test", sport=None, kind="ceremony", countries=[], medal_event=False
    )
    assert race.participants == ("Example athlete",)
    assert catalog().select(race, rule(participants=["Example athlete"])).decision == "match"
    assert catalog().select(ceremony, rule(medal_event=True)).decision == "no_match"
    assert catalog().select(ceremony, rule(kinds=["ceremony"])).decision == "match"


@pytest.mark.parametrize(
    "problem", ["cycle", "parent", "competition", "rule", "duplicate", "sport"]
)
def test_invalid_catalog_relationships_are_rejected(problem):
    data = configuration()
    if problem == "cycle":
        data["editions"][0]["parent_edition_id"] = "hockey-test"
    elif problem == "parent":
        data["editions"][0]["parent_edition_id"] = "absent"
    elif problem == "competition":
        data["editions"][0]["competition_id"] = "absent"
    elif problem == "rule":
        data["rules"] = [{"id": "bad", "edition_ids": ["absent"]}]
    elif problem == "duplicate":
        data["sessions"] = [session().model_dump(mode="json")] * 2
    else:
        data["sessions"] = [session(sport="golf").model_dump(mode="json")]
    with pytest.raises(ValueError):
        SpecialEventsConfig.model_validate(data)


def test_timestamp_timezone_and_date_validation():
    with pytest.raises(ValueError):
        session(start_time="2026-02-22T12:00:00")
    with pytest.raises(ValueError):
        session(end_time="2026-02-22T10:00:00Z")
    for update in ({"timezone": "invalid/zone"}, {"end_date": "2026-01-01"}):
        data = configuration()
        data["editions"][0].update(update)
        with pytest.raises(ValueError):
            SpecialEventsConfig.model_validate(data)


def game(timestamp="2026-02-21T23:30:00+00:00", **changes):
    data = {
        "provider": "espn",
        "id": "123",
        "league": "olympics-womens-ice-hockey",
        "sport": "hockey",
        "name": "Canada vs USA",
        "start_time": datetime.fromisoformat(timestamp),
        "status": SimpleNamespace(state="scheduled"),
        "home_team": SimpleNamespace(provider="espn", id="1", name="Canada"),
        "away_team": SimpleNamespace(provider="espn", id="2", name="USA"),
    }
    data.update(changes)
    return SimpleNamespace(**data)


def imported(**changes):
    binding = {
        "edition_id": "hockey-test",
        "league": "olympics-womens-ice-hockey",
        "sport": "hockey",
        "category": "women",
        "team_countries": {"espn:1": "CAN", "espn:2": "USA"},
        "event_details": {"espn:123": {"stage": "final", "medal_event": True}},
    }
    binding.update(changes)
    return configuration(imports=[binding])


def test_import_date_conversion_dedup_and_provider_identity():
    calls = []

    def fetch(league, day):
        calls.append((league, day))
        return [game(), game(), game(league="nhl"), game(sport="football")]

    service = catalog(imported(), fetch)
    items = service.get_sessions(date(2026, 2, 22))
    assert calls == [
        ("olympics-womens-ice-hockey", date(2026, 2, 21)),
        ("olympics-womens-ice-hockey", date(2026, 2, 22)),
    ]
    assert len(items) == 1
    item = items[0]
    assert item.identity == ("hockey-test", "espn", "123")
    assert item.start_time == datetime(2026, 2, 21, 23, 30, tzinfo=UTC)
    assert item.countries == ("CAN", "USA")
    assert item.category == "women"
    assert item.stage == "final"
    assert item.medal_event is True
    calls.clear()
    assert service.get_sessions(date(2027, 2, 22)) == []
    assert calls == []  # No annual recurrence implied by a tournament edition.


def test_import_metadata_does_not_guess_unknown_countries_and_updates_times():
    current = [game()]
    service = catalog(imported(team_countries={}), lambda league, day: current)
    original = service.get_sessions(date(2026, 2, 22))[0]
    assert original.countries is None
    assert service.select(original, rule(countries=["CAN"])).decision == "pending"
    current[:] = [game("2026-02-23T10:00:00+00:00")]
    assert service.get_sessions(date(2026, 2, 22)) == []
    assert service.get_sessions(date(2026, 2, 23))[0].identity == original.identity


def test_manual_override_moves_import_and_retains_cancellation():
    replacement = session(
        provider="espn", id="123", start_time="2026-03-01T12:00:00Z", status="cancelled"
    )
    data = imported()
    data["sessions"] = [replacement.model_dump(mode="json")]
    service = catalog(data, lambda league, day: [game()])
    assert service.get_sessions(date(2026, 2, 22)) == []
    # Explicit resumption dates can be outside an edition's original import bounds.
    assert service.get_sessions(date(2026, 3, 1)) == [replacement]


def test_dst_day_is_not_assumed_to_be_24_hours():
    data = imported()
    for edition in data["editions"]:
        edition.update(start_date="2026-03-01", end_date="2026-03-31", timezone="America/New_York")
    events = [
        game("2026-03-08T04:59:00Z", id="before"),
        game("2026-03-08T05:00:00Z", id="start"),
        game("2026-03-09T03:59:00Z", id="end"),
        game("2026-03-09T04:00:00Z", id="after"),
    ]
    service = catalog(data, lambda league, day: events, ZoneInfo("Pacific/Kiritimati"))
    assert [s.id for s in service.get_sessions(date(2026, 3, 8))] == ["start", "end"]


def test_api_configuration_reload_selection_and_validation(tmp_path, monkeypatch):
    path = tmp_path / "broadcasts.json"
    monkeypatch.setenv("TEAMARR_BROADCAST_CONFIG", str(path))
    data = configuration(
        sessions=[session(countries=None).model_dump(mode="json")],
        rules=[{"id": "canada", "edition_ids": ["winter-test"], "countries": ["CAN"]}],
    )
    path.write_text(json.dumps({"special_events": data}))
    app = create_app()
    app.dependency_overrides[get_sports_service] = lambda: SimpleNamespace(
        get_events=lambda league, day: []
    )
    client = TestClient(app)
    base = "/api/v1/special-events"
    query = "?target_date=2026-02-22"
    assert len(client.get(base + "/competitions").json()) == 3
    assert len(client.get(base + "/editions").json()) == 3
    assert client.get(base + "/sessions" + query).json()[0]["start_time"].endswith("Z")
    assert client.get(base + "/selections" + query).json()[0]["decision"] == "pending"
    data["sessions"][0]["countries"] = ["CAN", "USA"]
    path.write_text(json.dumps({"special_events": data}))
    assert client.get(base + "/selections" + query).json()[0]["decision"] == "match"
    assert client.get(base + "/selections" + query + "&rule_id=absent").status_code == 404
    assert client.get(base + "/sessions?target_date=bad").status_code == 422
    data["enabled"] = False
    path.write_text(json.dumps({"special_events": data}))
    assert client.get(base + "/sessions" + query).json() == []
    path.write_text('{"special_events": {"editions": [{}]}}')
    assert client.get(base + "/sessions" + query).status_code == 503
    path.unlink()
    assert client.get(base + "/editions").status_code == 503
    monkeypatch.delenv("TEAMARR_BROADCAST_CONFIG")
    assert client.get(base + "/sessions" + query).json() == []
