"""Read-only aggregation of sports, special sessions and broadcast coverage."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import cast
from urllib.parse import quote
from zoneinfo import ZoneInfo

from teamarr.core import Event, EventStatus
from teamarr.core.broadcast import BroadcastSession
from teamarr.core.controller_feed import (
    FeedEntry,
    FeedQuery,
    FeedSelection,
    FeedSource,
    FeedStatus,
    FeedViewingOption,
    WindowState,
)
from teamarr.core.event_details import EventArtwork
from teamarr.core.special_events import ScheduledSession, SessionSelection
from teamarr.services.broadcast_sessions import BroadcastConfig, RedZoneSource
from teamarr.services.event_details import league_artwork, serialize_event
from teamarr.services.special_coverage import SpecialCoverageSource
from teamarr.services.special_events import SpecialEventsCatalog


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def identity(kind: str, *parts: str) -> str:
    return ":".join([kind, *(quote(part, safe="") for part in parts)])


def event_id(event: Event) -> str:
    return identity("event", event.provider, event.league, event.id)


def session_id(session: ScheduledSession) -> str:
    return identity("session", session.edition_id, session.provider, session.id)


def window_state(start: datetime, end: datetime | None, now: datetime) -> WindowState:
    if now < start:
        return "upcoming"
    if end is None:
        return "unknown"
    return "in_window" if now < end else "elapsed"


def dates_between(start: datetime, end: datetime, timezone: tzinfo) -> set[date]:
    first = start.astimezone(timezone).date()
    last = (end - timedelta(microseconds=1)).astimezone(timezone).date()
    return {first + timedelta(days=i) for i in range((last - first).days + 1)}


class ControllerFeedBuilder:
    def __init__(
        self,
        get_events: Callable[[str, date], list[Event]],
        get_golf: Callable[[date], list[BroadcastSession]],
        config: BroadcastConfig,
        timezone: tzinfo,
        leagues: dict[str, dict],
        durations: dict[str, float],
        default_duration: float,
        art_base_url: str = "",
        get_tennis: Callable[[date], list[BroadcastSession]] | None = None,
    ):
        self.get_events = get_events
        self.get_golf = get_golf
        self.get_tennis = get_tennis
        self.config = config
        self.timezone = timezone
        self.leagues = leagues
        self.durations = durations
        self.default_duration = default_duration
        self.art_base_url = art_base_url
        self.fetched: dict[tuple[str, date], list[Event]] = {}

    def _fetch(self, league: str, day: date) -> list[Event]:
        key = league, day
        if key not in self.fetched:
            self.fetched[key] = self.get_events(league, day)
        return self.fetched[key]

    def _session_league(self, session: ScheduledSession) -> str | None:
        leagues = {
            binding.league
            for binding in self.config.special_events.imports
            if binding.edition_id == session.edition_id and binding.sport == session.sport
        }
        # The identity cannot depend on which date buckets happened to be cached.
        return next(iter(leagues)) if len(leagues) == 1 else None

    def _event(self, event: Event, source: FeedSource = "games") -> FeedEntry:
        details = serialize_event(
            event,
            self.leagues.get(event.league, {}),
            self.durations,
            self.default_duration,
            self.art_base_url,
        )
        item = FeedEntry(
            id=event_id(event),
            kind="event",
            source=source,
            title=event.name,
            provider=event.provider,
            competition=event.league,
            sports=[event.sport],
            start_time=utc(event.start_time),
            expected_end_time=datetime.fromisoformat(details.expected_end_time)
            if details.expected_end_time
            else None,
            end_time_estimated=details.end_time_estimated,
            timing_basis=details.timing_basis,
            status=cast(FeedStatus, details.status)
            if details.status in {"scheduled", "live", "final", "postponed", "cancelled"}
            else "unknown",
            status_basis="provider",
            event=details,
            artwork=details.artwork,
        )
        app = self.config.controller.league_apps.get(event.league)
        if app:
            item.viewing_options.append(
                FeedViewingOption(
                    id=identity("route", event.league, app),
                    app=app,
                    basis="configured_route",
                    decision="eligible",
                    reasons=["user_configured_league_route"],
                )
            )
        return item

    def _racing_sessions(self, event: Event) -> list[FeedEntry]:
        """Discover provider sessions, not a fictional weekend-long live event."""
        items = []
        for session in event.sessions:
            if not session.id:
                # Old cache records and providers without session identities must
                # refresh before they can supply stable controller commitments.
                continue
            entry = self._event(
                replace(
                    event,
                    id=session.id,
                    name=f"{event.name} — {session.name}",
                    short_name=session.name,
                    start_time=session.start_time,
                    status=EventStatus(session.status, detail=session.status_detail),
                    # Provider racing placeholders are not competing home/away teams.
                    home_team=None,
                    away_team=None,
                )
            )
            entry.id = identity("session", event.provider, event.league, event.id, session.id)
            entry.kind = "session"
            entry.related_ids = [event_id(event)]
            # Keep the original weekend and session identity in structured fields.
            entry.event = entry.event.model_copy(
                update={
                    "tournament_id": event.id,
                    "tournament_name": event.name,
                    "round_name": session.name,
                }
            )
            items.append(entry)
        return items

    def _option(self, broadcast: BroadcastSession) -> FeedViewingOption:
        app = broadcast.playback_target or self.config.controller.source_apps.get(broadcast.source)
        excluded = []
        review = []
        if broadcast.presentation == "replay":
            excluded.append("replay")
        if broadcast.source == "special_events":
            allowed = self.config.special_events.coverage.allowed_apps
            if allowed is not None and app not in allowed:
                excluded.append("app_not_allowed")
        if not app:
            review.append("app_unknown")
        if broadcast.expected_end_time is None:
            review.append("end_time_unknown")
        return FeedViewingOption(
            id=identity("view", broadcast.id),
            app=app,
            channel=broadcast.channel,
            stream_title=broadcast.stream_title or broadcast.title,
            listing_url=broadcast.listing_url,
            broadcast_id=identity("broadcast", broadcast.id),
            start_time=utc(broadcast.start_time),
            expected_end_time=utc(broadcast.expected_end_time)
            if broadcast.expected_end_time
            else None,
            coverage_type=broadcast.coverage_type or broadcast.kind,
            presentation=broadcast.presentation,
            basis=broadcast.timing_basis,
            decision="excluded" if excluded else "review" if review else "eligible",
            reasons=excluded or review,
        )

    def _broadcast(self, broadcast: BroadcastSession) -> FeedEntry:
        return FeedEntry(
            id=identity("broadcast", broadcast.id),
            kind="broadcast",
            source=cast(FeedSource, broadcast.source),
            title=broadcast.title,
            provider=broadcast.provider,
            competition=broadcast.competition,
            sports=list(broadcast.sports) or ([broadcast.sport] if broadcast.sport else []),
            start_time=utc(broadcast.start_time),
            expected_end_time=utc(broadcast.expected_end_time)
            if broadcast.expected_end_time
            else None,
            end_time_estimated=broadcast.end_time_estimated,
            timing_basis=broadcast.timing_basis,
            # A scheduled TV window is not provider-confirmed live sporting action.
            status=cast(FeedStatus, broadcast.status)
            if broadcast.source == "dazn_tennis" and broadcast.status in {"live", "scheduled"}
            else "unknown",
            status_basis="provider" if broadcast.source == "dazn_tennis" else "unknown",
            status_received_at=broadcast.status_received_at,
            broadcast=broadcast,
            viewing_options=[self._option(broadcast)],
            artwork=EventArtwork(cover_url=broadcast.artwork_url)
            if broadcast.artwork_url else league_artwork(
                broadcast.competition, self.leagues[broadcast.competition], self.art_base_url
            )
            if broadcast.competition in self.leagues
            else EventArtwork(),
        )

    def _apply_session(self, item: FeedEntry, session: ScheduledSession, configured: bool) -> None:
        """Apply explicit schedule corrections before filtering, including moves out of range."""
        previous_start = item.start_time
        item.start_time = utc(session.start_time)
        item.title = session.title
        item.status = session.status
        item.status_basis = "configured" if configured else "provider"
        if session.end_time:
            item.expected_end_time = utc(session.end_time)
            item.end_time_estimated = False
            item.timing_basis = "configured"
        elif item.event and item.expected_end_time:
            item.expected_end_time += item.start_time - previous_start
        if item.event:
            item.event = item.event.model_copy(
                update={
                    "event_name": item.title,
                    "start_time": item.start_time.isoformat(),
                    "status": item.status,
                    "expected_end_time": item.expected_end_time.isoformat()
                    if item.expected_end_time
                    else None,
                    "end_time_estimated": item.end_time_estimated,
                    "timing_basis": item.timing_basis,
                }
            )

    def build(self, query: FeedQuery) -> list[FeedEntry]:
        self.fetched.clear()
        start, end = utc(query.start), utc(query.end)
        discovery_start = start - timedelta(hours=query.lookback_hours)
        items: dict[str, FeedEntry] = {}
        if "games" in query.sources:
            for league in dict.fromkeys(query.leagues):
                for day in sorted(dates_between(discovery_start, end, self.timezone)):
                    for event in self._fetch(league, day):
                        entries = (
                            self._racing_sessions(event)
                            if event.league == "f1"
                            else [self._event(event)]
                        )
                        for entry in entries:
                            items[entry.id] = entry

        # Keep each source's date buckets separate: a long configured Olympic
        # window must not cause unrelated historic NFL or TSN schedule fetches.
        source_days = {
            "nfl_redzone": dates_between(discovery_start, end, ZoneInfo("America/New_York")),
            "golf": dates_between(discovery_start, end, ZoneInfo("America/New_York")),
            "dazn_tennis": dates_between(discovery_start, end, UTC),
            "special_events": set(),
        }
        editions = {edition.id: edition for edition in self.config.special_events.editions}
        for edition in editions.values():
            source_days["special_events"].update(
                dates_between(discovery_start, end, ZoneInfo(edition.timezone))
            )
        for source, windows in (
            ("golf", self.config.golf.coverage),
            ("special_events", self.config.special_events.coverage.windows),
        ):
            for window in windows:
                zone = ZoneInfo(window.timezone)
                source_days[source].update(dates_between(discovery_start, end, zone))
                if window.start_time < end and window.end_time and window.end_time > start:
                    source_days[source].add(window.start_time.astimezone(zone).date())
        for session in self.config.special_events.sessions:
            if session.start_time < end and (
                session.status == "live" or (session.end_time and session.end_time > start)
            ):
                zone = ZoneInfo(editions[session.edition_id].timezone)
                source_days["special_events"].add(session.start_time.astimezone(zone).date())

        aliases: dict[tuple[str, str, str], str] = {}
        catalog = SpecialEventsCatalog(self.config.special_events, self._fetch, self.timezone)
        coverage = SpecialCoverageSource(self.config.special_events)
        if "special_events" in query.sources:
            if catalog.config.enabled:
                for session in catalog.config.sessions:
                    league = self._session_league(session)
                    key = (
                        identity("event", session.provider, league, session.id) if league else None
                    )
                    if key in items:
                        self._apply_session(items[key], session, configured=True)
            sessions = {
                session.identity: session
                for day in sorted(source_days["special_events"])
                for session in catalog.get_sessions(day)
            }
            for session in sessions.values():
                # Imports and games share provider/league/id, not display-name guesses.
                league = self._session_league(session)
                key = identity("event", session.provider, league, session.id) if league else None
                matching = [
                    event
                    for (fetched_league, _), events in self.fetched.items()
                    for event in events
                    if event.provider == session.provider
                    and event.id == session.id
                    and league == fetched_league
                ]
                item = items.get(key) if key else None
                if item is None and matching:
                    item = self._event(matching[-1], "special_events")
                if item is None:
                    item = FeedEntry(
                        id=key or session_id(session),
                        kind="event" if key else "session",
                        source="special_events",
                        title=session.title,
                        provider=session.provider,
                        competition=league or editions[session.edition_id].competition_id,
                        sports=[session.sport] if session.sport else [],
                        start_time=utc(session.start_time),
                        status=session.status,
                    )
                aliases[session.identity] = item.id
                item.sessions.append(session)
                self._apply_session(
                    item,
                    session,
                    configured=any(s.identity == session.identity for s in catalog.config.sessions),
                )
                selections = [catalog.select(session, rule) for rule in catalog.config.rules]
                item.selections.extend(
                    FeedSelection(rule_id=s.rule_id, decision=s.decision, reasons=list(s.reasons))
                    for s in selections
                )
                selection = SessionSelection(
                    rule_id="controller_inventory",
                    session=session,
                    decision="match"
                    if not selections or any(s.decision == "match" for s in selections)
                    else "no_match",
                )
                for candidate in coverage.get_options(selection).options:
                    option = self._option(candidate.broadcast)
                    # Preserve the existing exact-reference/partial-coverage rules.
                    if candidate.decision == "excluded" or option.decision != "excluded":
                        option.decision = candidate.decision
                    option.reasons = list(dict.fromkeys(option.reasons + list(candidate.reasons)))
                    item.viewing_options.append(option)
                    item.related_ids.append(identity("broadcast", candidate.broadcast.id))
                items[item.id] = item

        broadcasts: dict[str, BroadcastSession] = {}
        if "dazn_tennis" in query.sources and self.config.dazn_tennis.enabled:
            if self.get_tennis is None:
                raise ValueError("DAZN tennis schedule source is not configured")
            for day in sorted(source_days["dazn_tennis"]):
                for session in self.get_tennis(day):
                    previous = broadcasts.get(session.id)
                    # Overlapping EPG days can include the same event. Use the
                    # latest acquired record, never the order of date buckets.
                    if (
                        previous is None
                        or session.status_received_at >= previous.status_received_at
                    ):
                        broadcasts[session.id] = session
        redzone = RedZoneSource(self._fetch, self.timezone, self.config.redzone)
        for source, get_sessions in (
            ("nfl_redzone", redzone.get_sessions),
            ("golf", self.get_golf),
            ("special_events", coverage.get_sessions),
        ):
            if source in query.sources:
                for day in sorted(source_days[source]):
                    broadcasts.update((session.id, session) for session in get_sessions(day))
        for broadcast in broadcasts.values():
            item = self._broadcast(broadcast)
            if broadcast.related_sessions:
                item.related_ids = [
                    aliases.get(ref.identity, identity("session", *ref.identity))
                    for ref in broadcast.related_sessions
                ]
            else:
                item.related_ids = [
                    identity("event", ref.provider, broadcast.competition, ref.event_id)
                    for ref in broadcast.related_events
                ]
            for related in item.related_ids:
                parent = items.get(related)
                if parent is None:
                    continue
                parent.related_ids.append(item.id)
                if broadcast.source == "nfl_redzone":
                    option = self._option(broadcast)
                    if option.decision != "excluded":
                        option.decision = "review"
                    option.reasons.append("multi_event_coverage_not_full_game")
                    parent.viewing_options.append(option)
            items[item.id] = item

        result = []
        for item in items.values():
            item.window_state = window_state(
                item.start_time, item.expected_end_time, utc(query.as_of)
            )
            item.related_ids = sorted(set(item.related_ids))
            item.viewing_options = list({o.id: o for o in item.viewing_options}.values())
            # Configured preferences from the special coverage matcher retain their order.
            item.viewing_options.sort(
                key=lambda o: {"eligible": 0, "review": 1, "excluded": 2}[o.decision]
            )
            selectable = item.status in {"scheduled", "live", "unknown"}
            rule_match = not item.selections or any(s.decision == "match" for s in item.selections)
            if selectable and rule_match:
                item.preferred_option_id = next(
                    (o.id for o in item.viewing_options if o.decision == "eligible"), None
                )
            if item.start_time >= end:
                continue
            # A live event can overrun its estimate. Never discard it solely for that.
            overlaps = item.expected_end_time is not None and item.expected_end_time > start
            unknown_end = item.expected_end_time is None and item.start_time >= discovery_start
            if not (overlaps or unknown_end or item.status == "live"):
                continue
            if query.statuses and item.status not in query.statuses:
                continue
            if query.window_states and item.window_state not in query.window_states:
                continue
            result.append(item)
        return sorted(result, key=lambda item: (item.start_time, item.id))
