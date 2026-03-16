from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from local_housing_searcher.models import FurnishingPreference, RentalType


class LoggingConfig(BaseModel):
    level: str = "INFO"


class DesktopNotificationConfig(BaseModel):
    enabled: bool = True


class TelegramNotificationConfig(BaseModel):
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"

    def resolve(self) -> tuple[str | None, str | None]:
        return os.getenv(self.bot_token_env), os.getenv(self.chat_id_env)


class NotificationConfig(BaseModel):
    desktop: DesktopNotificationConfig = Field(default_factory=DesktopNotificationConfig)
    telegram: TelegramNotificationConfig = Field(default_factory=TelegramNotificationConfig)
    telegram_targets: list[TelegramNotificationConfig] = Field(default_factory=list)

    def enabled_telegram_targets(self) -> list[TelegramNotificationConfig]:
        targets = [target for target in self.telegram_targets if target.enabled]
        if self.telegram.enabled:
            targets.insert(0, self.telegram)
        return targets


class FilterConfig(BaseModel):
    cities: list[str] = Field(default_factory=list)
    max_rent_eur: int | None = None
    min_sqm: float | None = None
    furnishing: FurnishingPreference = FurnishingPreference.ANY
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    rental_types: list[RentalType] = Field(default_factory=list)
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None

    @field_validator("cities", "include_keywords", "exclude_keywords")
    @classmethod
    def normalize_texts(cls, values: list[str]) -> list[str]:
        return [value.strip().lower() for value in values if value.strip()]


class ScoringConfig(BaseModel):
    high_priority_threshold: float = 85.0
    keyword_bonus: float = 8.0


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    adapter: str
    enabled: bool = True
    search_url: str | None = None
    max_listings: int = 50
    timeout_seconds: int = 30
    headless: bool = True
    wait_until: str = "domcontentloaded"
    extra_wait_ms: int = 1200
    debug_artifacts_dir: Path | None = None


class AppConfig(BaseModel):
    database_path: Path = Path("./data/housing.db")
    poll_interval_seconds: int = 300
    timezone: str = "Europe/Amsterdam"
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    sources: list[SourceConfig] = Field(default_factory=list)

    @field_validator("database_path", mode="before")
    @classmethod
    def resolve_database_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @model_validator(mode="after")
    def validate_sources(self) -> "AppConfig":
        if not self.sources:
            raise ValueError("at least one source must be configured")
        return self

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def get_source(self, source_id: str) -> SourceConfig:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError(f"unknown source '{source_id}'")


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    data = yaml.safe_load(config_path.read_text()) or {}
    config = AppConfig.model_validate(data)
    if not config.database_path.is_absolute():
        config.database_path = (config_path.parent / config.database_path).resolve()
    for source in config.sources:
        if source.debug_artifacts_dir is not None and not source.debug_artifacts_dir.is_absolute():
            source.debug_artifacts_dir = (config_path.parent / source.debug_artifacts_dir).resolve()
    config.ensure_directories()
    return config


def write_example_config(destination: str | Path) -> Path:
    destination_path = Path(destination).expanduser().resolve()
    if destination_path.exists():
        return destination_path
    example_path = Path(__file__).resolve().parents[2] / "config.example.yaml"
    destination_path.write_text(example_path.read_text())
    return destination_path
