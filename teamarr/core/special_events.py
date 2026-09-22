"""Competition identities and scheduled sessions independent of matchup teams."""

from datetime import date
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Slug = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")]


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Competition(CatalogModel):
    id: Slug
    name: str = Field(min_length=1)
    # Empty means the catalog has not enumerated its sports (e.g. an Olympics).
    sports: tuple[str, ...] = ()


class CompetitionEdition(CatalogModel):
    id: Slug
    competition_id: Slug
    name: str = Field(min_length=1)
    start_date: date
    end_date: date
    timezone: str
    parent_edition_id: Slug | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def valid_dates(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class SessionDetails(CatalogModel):
    discipline: str | None = None
    category: str | None = None
    stage: str | None = None
    participants: tuple[str, ...] | None = None
    # Use consistent codes within a catalog, e.g. CAN, USA. None is unknown;
    # an empty tuple explicitly means there are no represented countries.
    countries: tuple[str, ...] | None = None
    medal_event: bool | None = None


class ScheduledSession(SessionDetails):
    provider: Slug
    id: Slug
    edition_id: Slug
    title: str = Field(min_length=1)
    sport: str | None = None
    kind: Literal["game", "race", "heat", "round", "ceremony", "other"] = "game"
    start_time: AwareDatetime
    end_time: AwareDatetime | None = None
    status: Literal["scheduled", "live", "final", "postponed", "cancelled"] = "scheduled"

    @model_validator(mode="after")
    def valid_end(self) -> Self:
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.edition_id, self.provider, self.id


class ViewingRule(CatalogModel):
    id: Slug
    enabled: bool = True
    edition_ids: tuple[Slug, ...] = ()
    competition_ids: tuple[Slug, ...] = ()
    include_descendants: bool = True
    kinds: tuple[Literal["game", "race", "heat", "round", "ceremony", "other"], ...] = ()
    sports: tuple[str, ...] = ()
    disciplines: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    participants: tuple[str, ...] = ()
    medal_event: bool | None = None


class SessionSelection(CatalogModel):
    rule_id: str
    session: ScheduledSession
    decision: Literal["match", "pending", "no_match"]
    reasons: tuple[str, ...] = ()
