"""The observed TSN table layout, source matching and allowed-app routing."""

from datetime import UTC, date
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from teamarr.api.app import create_app
from teamarr.api.dependencies import get_sports_service, get_tsn_golf_schedule
from teamarr.core.golf import GolfTournament
from teamarr.providers.bellmedia.golf_schedule import parse_tsn_golf_listings
from teamarr.services.golf_sessions import GolfConfig, GolfCoverageWindow
from teamarr.services.tsn_golf import TSNGolfScheduleService, get_golf_sessions

# The table structure and factual rows were observed on TSN's current public
# schedule on 2026-09-22. No archived article body or unrelated content.
HTML = """<h4>PGA Broadcast Schedule</h4><table>
<tr><th>Event</th><th>Location</th><th></th><th></th></tr>
<tr><td>Presidents Cup</td><td>Medinah CC, IL</td><td></td><td></td></tr>
<tr><th>Date</th><th>Event</th><th>Time (ET)</th><th>Network</th></tr>
<tr><td>Thursday, September 24, 2026</td><td>Opening Ceremony</td><td>Noon</td><td>TSN1</td></tr>
<tr><td>Thursday, September 24, 2026</td><td>Day One</td><td>12:30pm</td><td>TSN1</td></tr>
<tr><td>Friday, September 25, 2026</td><td>Day Two</td><td>2pm</td><td>TSN1</td></tr>
<tr><td>Saturday, September 26, 2026</td><td>Day Three</td><td>8am</td><td>TSN1</td></tr>
<tr><td>Saturday, September 26, 2026</td><td>Day Three</td><td>9am</td><td>TSN1</td></tr>
<tr><td>Sunday, September 27, 2026</td><td>Day Four</td><td>Noon</td><td>TSN1</td></tr>
</table>"""


def service(html=HTML, name="Presidents Cup"):
    event = GolfTournament(
        id="401824815",
        provider="espn",
        competition="pga",
        name=name,
        start_date=date(2026, 9, 24),
        end_date=date(2026, 9, 27),
        status="scheduled",
    )
    return TSNGolfScheduleService(SimpleNamespace(get_season=lambda year: [event]), lambda: html)


def test_observed_table_maps_all_five_windows_and_skips_ceremony():
    rows = parse_tsn_golf_listings(HTML)
    assert len(rows) == 5
    assert rows[0].tournament == "Presidents Cup"
    assert rows[0].start_time.astimezone(UTC).isoformat() == "2026-09-24T16:30:00+00:00"
    assert rows[-1].start_time.astimezone(UTC).hour == 16
    assert rows[0].channel == "TSN1"
    windows = service().get_windows(date(2026, 9, 26))
    assert len(windows) == 2
    assert windows[0].session_id != windows[1].session_id
    assert windows[0].segment == "day_three"
    assert windows[0].round_number is None


def test_tbd_replays_and_ctv_only_rows_do_not_become_tsn_sessions():
    assert service(HTML.replace("12:30pm", "TBD")).get_windows(date(2026, 9, 24)) == []
    assert service(HTML.replace("Day One", "Day One Replay")).get_windows(date(2026, 9, 24)) == []
    assert service(HTML.replace("TSN1", "CTV2")).get_windows(date(2026, 9, 24)) == []
    assert service(name="An Unrelated Tournament").get_windows(date(2026, 9, 24)) == []
    assert service().get_windows(date(2027, 9, 24)) == []


def test_duplicate_rows_and_major_aliases():
    assert len(parse_tsn_golf_listings(HTML + HTML)) == 5
    windows = service(
        HTML.replace("Presidents Cup", "The Masters"), "Masters Tournament"
    ).get_windows(date(2026, 9, 24))
    assert len(windows) == 1


def test_winter_offset_and_multiple_channels():
    html = HTML.replace("September 24", "November 26").replace("12:30pm", "1 p.m. ET")
    html = html.replace("TSN1", "TSN1 / TSN3 / CTV2")
    windows = service(html).get_windows(date(2026, 11, 26))
    assert {window.channel for window in windows} == {"TSN1", "TSN3"}
    assert windows[0].start_time.astimezone(UTC).hour == 18


def test_allowlist_is_not_evidence_of_availability():
    config = GolfConfig()
    day = date(2026, 9, 24)
    result = get_golf_sessions(day, config, service())
    assert result[0].playback_target == "tsn"
    assert result[0].channel == "TSN1"
    assert result[0].listing_url.startswith("https://www.tsn.ca/")
    assert result[0].expected_end_time is None
    assert result[0].timing_basis == "listing"
    assert get_golf_sessions(day, GolfConfig(allowed_apps=["sportsnet"]), service()) == []
    assert get_golf_sessions(day, GolfConfig(import_tsn_schedule=False), service()) == []
    assert get_golf_sessions(day, GolfConfig(enabled=False), service()) == []


def test_manual_override_can_disable_or_move_listing_with_stable_id():
    day = date(2026, 9, 24)
    source = service()
    original = source.get_windows(day)[0]
    disabled = original.model_copy(update={"enabled": False})
    assert get_golf_sessions(day, GolfConfig(coverage=[disabled]), source) == []
    moved = original.model_copy(
        update={
            "start_time": original.start_time.replace(day=25),
            "timing_basis": "configured",
        }
    )
    assert get_golf_sessions(day, GolfConfig(coverage=[moved]), source) == []
    result = get_golf_sessions(date(2026, 9, 25), GolfConfig(coverage=[moved]), source)
    assert any(item.id == original.session_id for item in result)


def test_explicit_sportsnet_listing_survives_empty_tsn():
    window = GolfCoverageWindow(
        key="round4-sn",
        tournament_id="123",
        tournament_name="Example",
        start_time="2026-09-20T13:00:00-04:00",
        playback_target="sportsnet",
        channel="SN Ontario",
    )
    result = get_golf_sessions(date(2026, 9, 20), GolfConfig(coverage=[window]), service())
    assert result[0].playback_target == "sportsnet"
    assert (
        get_golf_sessions(
            date(2026, 9, 20), GolfConfig(coverage=[window], allowed_apps=["tsn"]), service()
        )
        == []
    )


def test_source_cache_and_failed_fetch():
    calls = []

    def fetch():
        calls.append(True)
        return HTML

    source = TSNGolfScheduleService(service()._catalog, fetch)
    source.get_windows(date(2026, 9, 24))
    source.get_windows(date(2026, 9, 25))
    assert len(calls) == 1

    def failure():
        raise httpx.ConnectError("offline")

    assert TSNGolfScheduleService(service()._catalog, failure).get_windows(date(2026, 9, 24)) == []


def test_api_returns_imported_sessions_with_no_config_file(monkeypatch):
    monkeypatch.delenv("TEAMARR_BROADCAST_CONFIG", raising=False)
    app = create_app()
    app.dependency_overrides[get_sports_service] = lambda: SimpleNamespace(
        get_events=lambda league, day: []
    )
    app.dependency_overrides[get_tsn_golf_schedule] = service
    response = TestClient(app).get("/api/v1/broadcast-sessions?source=golf&target_date=2026-09-24")
    assert response.status_code == 200
    assert response.json()[0]["playback_target"] == "tsn"
    assert response.json()[0]["channel"] == "TSN1"
