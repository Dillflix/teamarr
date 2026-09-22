"""Golf calendar discovery using Teamarr's existing ESPN HTTP client and TTL cache."""

from datetime import date
from threading import Lock

from teamarr.core.golf import GolfTournament
from teamarr.providers.espn.client import ESPNClient
from teamarr.providers.espn.golf import parse_golf_tournaments
from teamarr.utilities.cache import TTLCache


class GolfCatalogService:
    def __init__(self, client: ESPNClient | None = None):
        self._client = client or ESPNClient()
        self._cache = TTLCache(default_ttl_seconds=1800, max_size=256)
        self._fetch_lock = Lock()

    def get_tournaments(self, target_date: date, competition: str = "pga") -> list[GolfTournament]:
        return self._fetch(target_date.strftime("%Y%m%d"), competition)

    def get_season(self, season_year: int, competition: str = "pga") -> list[GolfTournament]:
        if not 1900 <= season_year <= 2100:
            raise ValueError("season_year must be between 1900 and 2100")
        return self._fetch(str(season_year), competition)

    def _fetch(self, dates: str, competition: str) -> list[GolfTournament]:
        if competition != "pga":
            raise ValueError("Only the PGA TOUR catalog is enabled in this increment")
        key = f"golf:{competition}:{dates}"
        with self._fetch_lock:
            cached = self._cache.get(key)
            if cached is not None:
                return list(cached)
            data = self._client.get_scoreboard(competition, dates, ("golf", competition))
            # Retain upstream empty-result semantics; source-health reporting
            # remains deferred. In particular, no exception/last-good layer.
            events = parse_golf_tournaments(data, competition) if data else []
            self._cache.set(key, tuple(events))
            return events
