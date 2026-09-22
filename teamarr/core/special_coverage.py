"""Broadcast listing contract for special competitions and multi-sport coverage."""

from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator

from teamarr.core.special_events import CatalogModel, Slug


class ScheduledSessionReference(CatalogModel):
    edition_id: Slug
    provider: Slug
    id: Slug

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.edition_id, self.provider, self.id


class SpecialCoverageWindow(CatalogModel):
    id: Slug
    edition_id: Slug
    title: str = Field(min_length=1)
    start_time: AwareDatetime
    end_time: AwareDatetime | None = None
    end_time_estimated: bool = True
    timezone: str
    app: str = Field(min_length=1)
    channel: str | None = None
    stream_title: str | None = None
    listing_url: str | None = None
    enabled: bool = True
    coverage_type: Literal["dedicated", "multi_event"] = "dedicated"
    presentation: Literal["live", "replay"] = "live"
    sports: tuple[str, ...] = ()
    related_sessions: tuple[ScheduledSessionReference, ...] = ()

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        identities = [reference.identity for reference in self.related_sessions]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate related session")
        if self.coverage_type == "dedicated" and len(identities) != 1:
            raise ValueError("Dedicated coverage requires exactly one session reference")
        if not identities and self.end_time is None:
            raise ValueError("Unlinked multi-event coverage requires an end_time")
        return self


class SpecialCoverageConfig(CatalogModel):
    windows: tuple[SpecialCoverageWindow, ...] = ()
    allowed_apps: tuple[str, ...] | None = None
    preferred_apps: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_windows(self) -> Self:
        if len({window.id for window in self.windows}) != len(self.windows):
            raise ValueError("Duplicate special coverage window ID")
        return self
