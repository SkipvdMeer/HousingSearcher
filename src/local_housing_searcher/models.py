from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class FurnishingPreference(StrEnum):
    ANY = "any"
    FURNISHED = "furnished"
    UNFURNISHED = "unfurnished"
    EITHER = "either"


class RentalType(StrEnum):
    APARTMENT = "apartment"
    HOUSE = "house"
    STUDIO = "studio"
    ROOM = "room"
    OTHER = "other"


class Listing(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    external_id: str
    url: str
    canonical_url: str
    title: str
    address: str | None = None
    city: str
    postcode: str | None = None
    price_eur: int
    area_sqm: float | None = None
    bedrooms: int | None = None
    rooms: int | None = None
    furnishing: FurnishingPreference | None = None
    rental_type: RentalType = RentalType.OTHER
    description: str | None = None
    available_from: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("title", "city")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()

    @field_validator("price_eur")
    @classmethod
    def validate_price(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("price must be positive")
        return value


class MatchResult(BaseModel):
    listing: Listing
    is_match: bool
    score: float
    is_high_priority: bool
    reasons: list[str] = Field(default_factory=list)


class StoredListing(BaseModel):
    id: int
    listing: Listing
    first_seen_at: datetime
    last_seen_at: datetime
    match_score: float | None = None
    match_reasons: list[str] = Field(default_factory=list)
    notification_sent_at: datetime | None = None
    high_priority_notified: bool = False


class AdapterHealth(BaseModel):
    source_id: str
    ok: bool
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AdapterResult(BaseModel):
    source_id: str
    listings: list[Listing] = Field(default_factory=list)
    health: AdapterHealth
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int = 0


class ExportFormat(StrEnum):
    CSV = "csv"
    JSON = "json"


class DashboardRecord(BaseModel):
    id: int
    title: str
    city: str
    price_eur: int
    area_sqm: float | None = None
    score: float | None = None
    is_match: bool
    is_high_priority: bool
    source: str
    url: HttpUrl
    last_seen_at: datetime
