"""FastAPI dependencies for dependency injection."""

from functools import lru_cache

from teamarr.services import SportsDataService, create_default_service
from teamarr.services.golf import GolfCatalogService
from teamarr.services.tsn_golf import TSNGolfScheduleService


@lru_cache
def get_tsn_golf_schedule() -> TSNGolfScheduleService:
    return TSNGolfScheduleService(get_golf_catalog())


@lru_cache
def get_golf_catalog() -> GolfCatalogService:
    return GolfCatalogService()


@lru_cache
def get_sports_service() -> SportsDataService:
    """Get singleton SportsDataService with providers from registry.

    Providers are configured in teamarr/providers/__init__.py.
    """
    return create_default_service()
