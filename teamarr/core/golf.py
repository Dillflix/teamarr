"""Golf tournament identity and calendar metadata, independent of TV coverage."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GolfTournament:
    id: str
    provider: str
    competition: str
    name: str
    start_date: date
    end_date: date | None
    status: str
    current_round: int | None = None
    season_year: int | None = None
    broadcasters: tuple[str, ...] = ()
    major: str | None = None
