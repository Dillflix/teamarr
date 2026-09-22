"""Join current sporting sessions to explicit broadcast listings by identity."""

from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from teamarr.core.broadcast import BroadcastSession, EventReference
from teamarr.core.special_coverage import SpecialCoverageWindow
from teamarr.core.special_events import CatalogModel, SessionSelection
from teamarr.services.special_events import SpecialEventsConfig


class CoverageOption(CatalogModel):
    broadcast: BroadcastSession
    decision: Literal["eligible", "review", "excluded"]
    reasons: tuple[str, ...] = ()


class ViewingOptions(CatalogModel):
    selection: SessionSelection
    options: tuple[CoverageOption, ...]
    preferred_broadcast_id: str | None = None


class SpecialCoverageSource:
    def __init__(self, config: SpecialEventsConfig):
        self.config = config
        self._editions = {edition.id: edition for edition in config.editions}

    def _broadcast(self, window: SpecialCoverageWindow) -> BroadcastSession:
        return BroadcastSession(
            id=f"special_events:{window.id}",
            source="special_events",
            title=window.title,
            kind="event_coverage"
            if window.coverage_type == "dedicated"
            else "multi_event_coverage",
            sport=window.sports[0] if len(window.sports) == 1 else None,
            sports=window.sports,
            competition=self._editions[window.edition_id].competition_id,
            edition_id=window.edition_id,
            session_date=window.start_time.astimezone(ZoneInfo(window.timezone)).date(),
            timezone=window.timezone,
            start_time=window.start_time.astimezone(UTC),
            expected_end_time=window.end_time.astimezone(UTC) if window.end_time else None,
            end_time_estimated=window.end_time_estimated if window.end_time else True,
            timing_basis="configured",
            related_events=tuple(
                EventReference(reference.provider, reference.id)
                for reference in window.related_sessions
            ),
            related_sessions=window.related_sessions,
            coverage_type=window.coverage_type,
            presentation=window.presentation,
            playback_target=window.app,
            channel=window.channel,
            stream_title=window.stream_title,
            listing_url=window.listing_url,
        )

    def get_sessions(self, target_date: date) -> list[BroadcastSession]:
        """Inventory includes replays/disallowed apps; selection reports suitability."""
        if not self.config.enabled:
            return []
        return sorted(
            (
                self._broadcast(window)
                for window in self.config.coverage.windows
                if window.enabled
                and window.start_time.astimezone(ZoneInfo(window.timezone)).date() == target_date
            ),
            key=lambda item: (item.start_time, item.id),
        )

    def get_options(self, selection: SessionSelection) -> ViewingOptions:
        """Exact references establish event membership; timing alone never does."""
        if not self.config.enabled:
            return ViewingOptions(selection=selection, options=())
        session = selection.session
        ancestry = {session.edition_id}
        edition = self._editions[session.edition_id]
        while edition.parent_edition_id is not None:
            edition = self._editions[edition.parent_edition_id]
            ancestry.add(edition.id)
        options = []
        for window in self.config.coverage.windows:
            if not window.enabled or window.edition_id not in ancestry:
                continue
            references = {reference.identity for reference in window.related_sessions}
            if references and session.identity not in references:
                continue
            # A broad broadcast is only a candidate when it covers the contest's
            # start. Explicit references survive stale timing so it can be reported.
            if not references and not (
                window.start_time <= session.start_time
                and window.end_time is not None
                and session.start_time < window.end_time
            ):
                continue
            if window.sports and session.sport is not None and session.sport not in window.sports:
                continue
            excluded: list[str] = []
            review: list[str] = []
            allowed = self.config.coverage.allowed_apps
            if allowed is not None and window.app not in allowed:
                excluded.append("app_not_allowed")
            if window.presentation != "live":
                excluded.append("replay")
            if window.end_time is not None and window.end_time <= session.start_time:
                excluded.append("ends_before_event")
            if window.start_time > session.start_time:
                review.append("starts_after_event")
            if window.end_time is None:
                review.append("end_time_unknown")
            if (
                window.end_time is not None
                and session.end_time is not None
                and window.end_time < session.end_time
            ):
                review.append("ends_during_event")
            if window.coverage_type == "multi_event":
                review.append("multi_event_coverage")
            if not references:
                review.append("event_coverage_unconfirmed")
            options.append(
                CoverageOption(
                    broadcast=self._broadcast(window),
                    decision="excluded" if excluded else "review" if review else "eligible",
                    reasons=tuple(excluded or review),
                )
            )
        preferences = self.config.coverage.preferred_apps

        def rank(option: CoverageOption) -> tuple[int, int, datetime, str]:
            target = option.broadcast.playback_target
            app_rank = (
                preferences.index(target)
                if target is not None and target in preferences
                else len(preferences)
            )
            return (
                {"eligible": 0, "review": 1, "excluded": 2}[option.decision],
                app_rank,
                option.broadcast.start_time,
                option.broadcast.id,
            )

        options.sort(key=rank)
        preferred = next((item for item in options if item.decision == "eligible"), None)
        return ViewingOptions(
            selection=selection,
            options=tuple(options),
            preferred_broadcast_id=preferred.broadcast.id
            if preferred is not None and selection.decision == "match"
            else None,
        )
