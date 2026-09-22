"""Edition-scoped Teamarr imports, configured sessions, and viewing selection.

This is a read-only planning catalog. Broadcast listings and device arbitration
are separate from the competition schedule and its selection rules.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from teamarr.core.special_coverage import SpecialCoverageConfig
from teamarr.core.special_events import (
    CatalogModel,
    Competition,
    CompetitionEdition,
    ScheduledSession,
    SessionDetails,
    SessionSelection,
    Slug,
    ViewingRule,
)
from teamarr.core.types import Event


class TeamarrLeagueImport(CatalogModel):
    edition_id: Slug
    league: str = Field(min_length=1)
    sport: str = Field(min_length=1)
    category: str | None = None
    # Provider-scoped team keys, e.g. "espn:123" -> "CAN". No name guessing.
    team_countries: dict[str, str] = Field(default_factory=dict)
    # Optional event metadata keyed by "provider:event_id". Provider start,
    # status, and participants continue to refresh from Teamarr.
    event_details: dict[str, SessionDetails] = Field(default_factory=dict)


class SpecialEventsConfig(CatalogModel):
    enabled: bool = True
    competitions: tuple[Competition, ...] = ()
    editions: tuple[CompetitionEdition, ...] = ()
    imports: tuple[TeamarrLeagueImport, ...] = ()
    sessions: tuple[ScheduledSession, ...] = ()
    rules: tuple[ViewingRule, ...] = ()
    coverage: SpecialCoverageConfig = Field(default_factory=SpecialCoverageConfig)

    @model_validator(mode="after")
    def valid_catalog(self) -> Self:
        for name in ("competitions", "editions", "rules"):
            values = getattr(self, name)
            if len({item.id for item in values}) != len(values):
                raise ValueError(f"Duplicate {name} IDs")
        competitions = {item.id: item for item in self.competitions}
        editions = {item.id: item for item in self.editions}
        for edition in self.editions:
            if edition.competition_id not in competitions:
                raise ValueError(f"Unknown competition: {edition.competition_id}")
            visited: set[str] = set()
            current: CompetitionEdition | None = edition
            while current is not None:
                if current.id in visited:
                    raise ValueError("Edition parent cycle")
                visited.add(current.id)
                parent = current.parent_edition_id
                if parent is not None and parent not in editions:
                    raise ValueError(f"Unknown parent edition: {parent}")
                current = editions.get(parent) if parent is not None else None
        for item in (*self.imports, *self.sessions):
            if item.edition_id not in editions:
                raise ValueError(f"Unknown edition: {item.edition_id}")
            sports = competitions[editions[item.edition_id].competition_id].sports
            if sports and item.sport is not None and item.sport not in sports:
                raise ValueError(f"Sport is outside competition: {item.sport}")
        if len({item.identity for item in self.sessions}) != len(self.sessions):
            raise ValueError("Duplicate scheduled session identity")
        keys = [(item.edition_id, item.league) for item in self.imports]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate edition/league import")
        for rule in self.rules:
            if set(rule.edition_ids) - editions.keys():
                raise ValueError(f"Unknown edition in rule: {rule.id}")
            if set(rule.competition_ids) - competitions.keys():
                raise ValueError(f"Unknown competition in rule: {rule.id}")
        for window in self.coverage.windows:
            if window.edition_id not in editions:
                raise ValueError(f"Unknown broadcast edition: {window.edition_id}")
            for reference in window.related_sessions:
                if reference.edition_id not in editions:
                    raise ValueError(f"Unknown referenced edition: {reference.edition_id}")
                current = editions[reference.edition_id]
                while current.id != window.edition_id and current.parent_edition_id is not None:
                    current = editions[current.parent_edition_id]
                if current.id != window.edition_id:
                    raise ValueError("Broadcast reference is outside its edition scope")
        return self


class SpecialEventsCatalog:
    def __init__(
        self,
        config: SpecialEventsConfig,
        get_events: Callable[[str, date], list[Event]],
        schedule_timezone: tzinfo,
    ):
        self.config = config
        self._get_events = get_events
        self._schedule_timezone = schedule_timezone
        self._editions = {edition.id: edition for edition in config.editions}

    def get_sessions(self, target_date: date) -> list[ScheduledSession]:
        """Query start dates in each edition's timezone, never a fixed UTC offset."""
        if not self.config.enabled:
            return []
        sessions: dict[tuple[str, str, str], ScheduledSession] = {}
        fetched: dict[tuple[str, date], list[Event]] = {}
        for binding in self.config.imports:
            edition = self._editions[binding.edition_id]
            if not edition.start_date <= target_date <= edition.end_date:
                continue
            timezone = ZoneInfo(edition.timezone)
            start = datetime.combine(target_date, time(), timezone).astimezone(UTC)
            end = datetime.combine(target_date + timedelta(days=1), time(), timezone).astimezone(
                UTC
            )
            day = start.astimezone(self._schedule_timezone).date()
            last_day = (end - timedelta(microseconds=1)).astimezone(self._schedule_timezone).date()
            while day <= last_day:
                fetch_key = binding.league, day
                if fetch_key not in fetched:
                    fetched[fetch_key] = self._get_events(*fetch_key)
                for event in fetched[fetch_key]:
                    if (
                        event.league != binding.league
                        or event.sport != binding.sport
                        or event.start_time is None
                        or event.start_time.tzinfo is None
                        or not start <= event.start_time < end
                    ):
                        continue
                    teams = (event.home_team, event.away_team)
                    codes = [
                        binding.team_countries.get(f"{team.provider}:{team.id}") for team in teams
                    ]
                    details = SessionDetails(
                        category=binding.category,
                        participants=tuple(team.name for team in teams),
                        countries=tuple(code for code in codes if code is not None)
                        if all(code is not None for code in codes)
                        else None,
                    ).model_dump()
                    supplement = binding.event_details.get(f"{event.provider}:{event.id}")
                    if supplement is not None:
                        # Explicit fields only: absent fields must not erase refreshed values.
                        details.update(supplement.model_dump(exclude_unset=True))
                    session = ScheduledSession.model_validate(
                        {
                            **details,
                            "provider": event.provider,
                            "id": event.id,
                            "edition_id": edition.id,
                            "title": event.name,
                            "sport": binding.sport,
                            "start_time": event.start_time.astimezone(UTC),
                            "status": event.status.state,
                        }
                    )
                    sessions[session.identity] = session
                day += timedelta(days=1)

        # Configured rows are authoritative, including reschedules out of the
        # original day and cancellations. Remove an import BEFORE date filtering.
        for session in self.config.sessions:
            sessions.pop(session.identity, None)
            timezone = ZoneInfo(self._editions[session.edition_id].timezone)
            if session.start_time.astimezone(timezone).date() == target_date:
                sessions[session.identity] = session.model_copy(
                    update={
                        "start_time": session.start_time.astimezone(UTC),
                        "end_time": session.end_time.astimezone(UTC) if session.end_time else None,
                    }
                )
        return sorted(sessions.values(), key=lambda item: (item.start_time, item.identity))

    def select(self, session: ScheduledSession, rule: ViewingRule) -> SessionSelection:
        """AND between criteria; OR within each criterion. Unknown is pending."""
        failed: list[str] = []
        unknown: list[str] = []
        if not rule.enabled or not self.config.enabled:
            failed.append("disabled")
        if session.status not in {"scheduled", "live"}:
            failed.append("status")
        edition = self._editions[session.edition_id]
        ancestry = [edition]
        while rule.include_descendants and edition.parent_edition_id is not None:
            edition = self._editions[edition.parent_edition_id]
            ancestry.append(edition)
        if rule.edition_ids and not set(rule.edition_ids).intersection(e.id for e in ancestry):
            failed.append("edition_ids")
        if rule.competition_ids and not set(rule.competition_ids).intersection(
            e.competition_id for e in ancestry
        ):
            failed.append("competition_ids")
        for plural, singular in (
            ("kinds", "kind"),
            ("sports", "sport"),
            ("disciplines", "discipline"),
            ("categories", "category"),
            ("stages", "stage"),
            ("countries", "countries"),
            ("participants", "participants"),
        ):
            wanted = getattr(rule, plural)
            actual = getattr(session, singular)
            if not wanted:
                continue
            if actual is None:
                unknown.append(plural)
            elif not set(wanted).intersection((actual,) if isinstance(actual, str) else actual):
                failed.append(plural)
        if rule.medal_event is not None:
            if session.medal_event is None:
                unknown.append("medal_event")
            elif session.medal_event != rule.medal_event:
                failed.append("medal_event")
        return SessionSelection(
            rule_id=rule.id,
            session=session,
            decision="no_match" if failed else "pending" if unknown else "match",
            reasons=tuple(failed or unknown),
        )
