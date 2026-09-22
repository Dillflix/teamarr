"""Preserve ESPN's golf tournament calendar without inventing coverage times."""

import logging
import re
from datetime import date, datetime

from teamarr.core.golf import GolfTournament

logger = logging.getLogger(__name__)

# Exact normalized titles, scoped to the men's PGA catalog. Do not classify
# unrelated "Open" events or THE PLAYERS Championship as majors.
_MAJOR_NAMES = {
    "masters": "masters",
    "themasters": "masters",
    "masterstournament": "masters",
    "pgachampionship": "pga_championship",
    "usopen": "us_open",
    "theopen": "the_open",
    "openchampionship": "the_open",
    "theopenchampionship": "the_open",
}


def _calendar_date(value: str | None) -> date | None:
    # ESPN supplies calendar markers, not tee times. Preserve their date
    # component without shifting it into Teamarr's display timezone.
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if value else None


def parse_golf_tournaments(data: dict, competition: str) -> list[GolfTournament]:
    tournaments: dict[str, GolfTournament] = {}
    for item in data.get("events", []):
        try:
            event_id = str(item.get("id") or "")
            name = item.get("name")
            if not event_id or not name:
                continue
            contests = item.get("competitions") or []
            contest = contests[0] if contests else {}
            start = _calendar_date(item.get("date") or contest.get("date"))
            end = _calendar_date(item.get("endDate") or contest.get("endDate"))
            if start is None or (end is not None and end < start):
                continue
            status = contest.get("status") or item.get("status") or {}
            status_type = status.get("type") or {}
            state = str(status_type.get("state") or "")
            normalized = {"pre": "scheduled", "in": "live", "post": "final"}.get(state, "unknown")
            if status_type.get("name") == "STATUS_CANCELED":
                normalized = "cancelled"
            elif status_type.get("name") == "STATUS_POSTPONED":
                normalized = "postponed"
            period = status.get("period")
            round_number = int(period) if period is not None and int(period) > 0 else None
            year = (item.get("season") or {}).get("year")
            names = {
                name
                for c in contests
                for broadcast in c.get("broadcasts", [])
                for name in broadcast.get("names", [])
                if isinstance(name, str) and name
            }
            tournaments[event_id] = GolfTournament(
                id=event_id,
                provider="espn",
                competition=competition,
                name=name,
                start_date=start,
                end_date=end,
                status=normalized,
                current_round=round_number,
                season_year=int(year) if year is not None else None,
                broadcasters=tuple(sorted(names)),
                major=(
                    _MAJOR_NAMES.get(re.sub(r"[^a-z0-9]", "", name.casefold()))
                    if competition == "pga"
                    else None
                ),
            )
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning("[GOLF] Skipping malformed tournament: %s", exc)
    return sorted(tournaments.values(), key=lambda event: (event.start_date, event.id))
