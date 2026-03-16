from __future__ import annotations

import logging
from dataclasses import dataclass, field

from local_housing_searcher.adapters import AdapterContext, build_adapter
from local_housing_searcher.config import AppConfig, SourceConfig
from local_housing_searcher.db import Database
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.filtering import score_listing
from local_housing_searcher.notifications import NotificationManager

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SourceRunSummary:
    source_id: str
    ok: bool
    fetched: int = 0
    new_matches: int = 0
    message: str = ""


@dataclass(slots=True)
class PollSummary:
    dry_run: bool
    source_summaries: list[SourceRunSummary] = field(default_factory=list)

    @property
    def total_new_matches(self) -> int:
        return sum(item.new_matches for item in self.source_summaries)


class PollService:
    def __init__(
        self,
        config: AppConfig,
        database: Database,
        notifications: NotificationManager,
        *,
        debug: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.database = database
        self.notifications = notifications
        self.debug = debug
        self.dry_run = dry_run

    def poll_once(self, source_ids: list[str] | None = None) -> PollSummary:
        summaries: list[SourceRunSummary] = []
        sources = [source for source in self.config.sources if source.enabled]
        if source_ids is not None:
            selected = set(source_ids)
            sources = [source for source in sources if source.id in selected]

        for source in sources:
            summaries.append(self._poll_source(source))
        return PollSummary(dry_run=self.dry_run, source_summaries=summaries)

    def _poll_source(self, source: SourceConfig) -> SourceRunSummary:
        LOGGER.debug("starting source poll | source_id=%s | adapter=%s | search_url=%s", source.id, source.adapter, source.search_url)
        adapter = build_adapter(
            AdapterContext(
                source=source,
                filters=self.config.filters,
                database=self.database,
                debug=self.debug,
            )
        )
        result = adapter.fetch()
        new_matches = 0
        matched_count = 0
        existing_count = 0
        rejected_count = 0

        if not self.dry_run:
            self.database.save_source_run(
                source_id=result.source_id,
                ok=result.health.ok,
                message=result.health.message,
                duration_ms=result.duration_ms,
                listings_found=len(result.listings),
            )

        if not result.health.ok:
            LOGGER.warning("%s failed: %s", source.id, result.health.message)
            if result.health.details:
                LOGGER.debug("%s failure details | %s", source.id, result.health.details)
            return SourceRunSummary(
                source_id=source.id,
                ok=False,
                fetched=0,
                new_matches=0,
                message=result.health.message,
            )

        for listing in result.listings:
            if not listing.fingerprint:
                listing.fingerprint = listing_fingerprint(listing)
            match = score_listing(listing, self.config.filters, self.config.scoring)
            existing_id = self.database.find_existing_listing_id(listing)
            is_new = existing_id is None
            if is_new:
                LOGGER.debug("%s listing seen first time | external_id=%s | url=%s", source.id, listing.external_id, listing.url)
            else:
                existing_count += 1
                LOGGER.debug("%s listing already known | existing_id=%s | external_id=%s | url=%s", source.id, existing_id, listing.external_id, listing.url)

            if match.is_match:
                matched_count += 1
                LOGGER.debug(
                    "%s listing matched | score=%.1f | high_priority=%s | reasons=%s | url=%s",
                    source.id,
                    match.score,
                    match.is_high_priority,
                    match.reasons,
                    listing.url,
                )
            else:
                rejected_count += 1
                LOGGER.debug("%s listing rejected | reasons=%s | url=%s", source.id, match.reasons, listing.url)

            if self.dry_run:
                if is_new and match.is_match:
                    new_matches += 1
                    LOGGER.info("dry-run new match | %s | %s", source.id, listing.url)
                continue

            stored, was_created = self.database.upsert_listing(match)
            if was_created and match.is_match:
                self.notifications.notify(stored, match, dry_run=False)
                self.database.mark_notified(stored.id, match.is_high_priority)
                new_matches += 1
                LOGGER.debug("%s notification sent | listing_id=%s | url=%s", source.id, stored.id, listing.url)

        LOGGER.debug(
            "%s source poll complete | fetched=%s | matched=%s | rejected=%s | existing=%s | new_matches=%s",
            source.id,
            len(result.listings),
            matched_count,
            rejected_count,
            existing_count,
            new_matches,
        )

        return SourceRunSummary(
            source_id=source.id,
            ok=True,
            fetched=len(result.listings),
            new_matches=new_matches,
            message=result.health.message,
        )
