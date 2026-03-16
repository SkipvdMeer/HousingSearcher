from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from local_housing_searcher.models import DashboardRecord, Listing, MatchResult, StoredListing


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    address TEXT,
                    city TEXT NOT NULL,
                    postcode TEXT,
                    price_eur INTEGER NOT NULL,
                    area_sqm REAL,
                    bedrooms INTEGER,
                    rooms INTEGER,
                    furnishing TEXT,
                    rental_type TEXT NOT NULL,
                    description TEXT,
                    available_from TEXT,
                    raw_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    match_score REAL,
                    match_reasons_json TEXT NOT NULL DEFAULT '[]',
                    is_match INTEGER NOT NULL DEFAULT 0,
                    is_high_priority INTEGER NOT NULL DEFAULT 0,
                    notification_sent_at TEXT,
                    high_priority_notified INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS listing_identities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    UNIQUE(kind, value)
                );

                CREATE TABLE IF NOT EXISTS source_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    ran_at TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    listings_found INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_listings_last_seen_at ON listings(last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_listings_match ON listings(is_match, last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_source_runs_source_id ON source_runs(source_id, ran_at DESC);
                """
            )

    def save_source_run(
        self,
        source_id: str,
        ok: bool,
        message: str,
        duration_ms: int,
        listings_found: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_runs (source_id, ran_at, ok, message, duration_ms, listings_found)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (source_id, _utcnow(), int(ok), message, duration_ms, listings_found),
            )

    def latest_source_statuses(self) -> list[dict[str, str | int | bool]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT sr.source_id, sr.ran_at, sr.ok, sr.message, sr.duration_ms, sr.listings_found
                FROM source_runs sr
                INNER JOIN (
                    SELECT source_id, MAX(ran_at) AS max_ran_at
                    FROM source_runs
                    GROUP BY source_id
                ) latest
                  ON latest.source_id = sr.source_id
                 AND latest.max_ran_at = sr.ran_at
                ORDER BY sr.source_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_listing(self, match: MatchResult) -> tuple[StoredListing, bool]:
        listing = match.listing
        identities = [
            ("source_external", f"{listing.source}:{listing.external_id}"),
            ("canonical_url", listing.canonical_url),
            ("fingerprint", listing.fingerprint),
        ]
        with self.connect() as conn:
            existing_id = self._find_existing_listing_id(conn, identities)
            if existing_id is None:
                row_id = self._insert_listing(conn, listing, match)
                self._insert_identities(conn, row_id, identities)
                stored = self._get_listing(conn, row_id)
                return stored, True

            self._update_listing(conn, existing_id, listing, match)
            self._insert_identities(conn, existing_id, identities)
            stored = self._get_listing(conn, existing_id)
            return stored, False

    def find_existing_listing_id(self, listing: Listing) -> int | None:
        identities = [
            ("source_external", f"{listing.source}:{listing.external_id}"),
            ("canonical_url", listing.canonical_url),
            ("fingerprint", listing.fingerprint),
        ]
        with self.connect() as conn:
            return self._find_existing_listing_id(conn, identities)

    def mark_notified(self, listing_id: int, high_priority: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE listings
                   SET notification_sent_at = ?,
                       high_priority_notified = CASE
                           WHEN ? THEN 1
                           ELSE high_priority_notified
                       END
                 WHERE id = ?
                """,
                (_utcnow(), int(high_priority), listing_id),
            )

    def get_listing(self, listing_id: int) -> StoredListing:
        with self.connect() as conn:
            return self._get_listing(conn, listing_id)

    def recent_matches(self, limit: int = 20) -> list[StoredListing]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM listings
                 WHERE is_match = 1
                 ORDER BY last_seen_at DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_stored_listing(row) for row in rows]

    def latest_publish_date_for_source(self, source_id: str) -> datetime | None:
        latest: datetime | None = None
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT raw_json
                  FROM listings
                 WHERE source = ?
                """,
                (source_id,),
            ).fetchall()
        for row in rows:
            try:
                raw = json.loads(row["raw_json"])
            except Exception:
                continue
            value = raw.get("publish_date")
            if not value or not isinstance(value, str):
                continue
            try:
                published_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if latest is None or published_at > latest:
                latest = published_at
        return latest

    def recent_dashboard_rows(self, limit: int = 50) -> list[DashboardRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, city, price_eur, area_sqm, match_score, is_match,
                       is_high_priority, source, url, last_seen_at
                  FROM listings
                 ORDER BY last_seen_at DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            DashboardRecord(
                id=row["id"],
                title=row["title"],
                city=row["city"],
                price_eur=row["price_eur"],
                area_sqm=row["area_sqm"],
                score=row["match_score"],
                is_match=bool(row["is_match"]),
                is_high_priority=bool(row["is_high_priority"]),
                source=row["source"],
                url=row["url"],
                last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            )
            for row in rows
        ]

    def export_json(self, destination: Path, matches_only: bool = False) -> Path:
        records = self._export_rows(matches_only)
        destination.write_text(json.dumps(records, indent=2, ensure_ascii=True))
        return destination

    def export_csv(self, destination: Path, matches_only: bool = False) -> Path:
        records = self._export_rows(matches_only)
        if not records:
            destination.write_text("")
            return destination
        with destination.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)
        return destination

    def _find_existing_listing_id(
        self,
        conn: sqlite3.Connection,
        identities: list[tuple[str, str]],
    ) -> int | None:
        for kind, value in identities:
            row = conn.execute(
                "SELECT listing_id FROM listing_identities WHERE kind = ? AND value = ?",
                (kind, value),
            ).fetchone()
            if row:
                return int(row["listing_id"])
        return None

    def _get_listing(self, conn: sqlite3.Connection, listing_id: int) -> StoredListing:
        row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
        if row is None:
            raise KeyError(f"listing {listing_id} not found")
        return self._row_to_stored_listing(row)

    def _insert_listing(self, conn: sqlite3.Connection, listing: Listing, match: MatchResult) -> int:
        cursor = conn.execute(
            """
            INSERT INTO listings (
                source, external_id, canonical_url, url, title, address, city, postcode, price_eur,
                area_sqm, bedrooms, rooms, furnishing, rental_type, description, available_from,
                raw_json, fingerprint, first_seen_at, last_seen_at, match_score, match_reasons_json,
                is_match, is_high_priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing.source,
                listing.external_id,
                listing.canonical_url,
                listing.url,
                listing.title,
                listing.address,
                listing.city,
                listing.postcode,
                listing.price_eur,
                listing.area_sqm,
                listing.bedrooms,
                listing.rooms,
                listing.furnishing.value if listing.furnishing else None,
                listing.rental_type.value,
                listing.description,
                listing.available_from,
                json.dumps(listing.raw),
                listing.fingerprint,
                listing.discovered_at.isoformat(),
                _utcnow(),
                match.score,
                json.dumps(match.reasons),
                int(match.is_match),
                int(match.is_high_priority),
            ),
        )
        return int(cursor.lastrowid)

    def _update_listing(
        self,
        conn: sqlite3.Connection,
        listing_id: int,
        listing: Listing,
        match: MatchResult,
    ) -> None:
        conn.execute(
            """
            UPDATE listings
               SET source = ?,
                   external_id = ?,
                   canonical_url = ?,
                   url = ?,
                   title = ?,
                   address = COALESCE(?, address),
                   city = ?,
                   postcode = COALESCE(?, postcode),
                   price_eur = ?,
                   area_sqm = COALESCE(?, area_sqm),
                   bedrooms = COALESCE(?, bedrooms),
                   rooms = COALESCE(?, rooms),
                   furnishing = COALESCE(?, furnishing),
                   rental_type = ?,
                   description = COALESCE(?, description),
                   available_from = COALESCE(?, available_from),
                   raw_json = ?,
                   fingerprint = ?,
                   last_seen_at = ?,
                   match_score = ?,
                   match_reasons_json = ?,
                   is_match = ?,
                   is_high_priority = ?
             WHERE id = ?
            """,
            (
                listing.source,
                listing.external_id,
                listing.canonical_url,
                listing.url,
                listing.title,
                listing.address,
                listing.city,
                listing.postcode,
                listing.price_eur,
                listing.area_sqm,
                listing.bedrooms,
                listing.rooms,
                listing.furnishing.value if listing.furnishing else None,
                listing.rental_type.value,
                listing.description,
                listing.available_from,
                json.dumps(listing.raw),
                listing.fingerprint,
                _utcnow(),
                match.score,
                json.dumps(match.reasons),
                int(match.is_match),
                int(match.is_high_priority),
                listing_id,
            ),
        )

    def _insert_identities(
        self,
        conn: sqlite3.Connection,
        listing_id: int,
        identities: list[tuple[str, str]],
    ) -> None:
        for kind, value in identities:
            conn.execute(
                """
                INSERT OR IGNORE INTO listing_identities (listing_id, kind, value)
                VALUES (?, ?, ?)
                """,
                (listing_id, kind, value),
            )

    def _row_to_stored_listing(self, row: sqlite3.Row) -> StoredListing:
        listing = Listing(
            source=row["source"],
            external_id=row["external_id"],
            url=row["url"],
            canonical_url=row["canonical_url"],
            title=row["title"],
            address=row["address"],
            city=row["city"],
            postcode=row["postcode"],
            price_eur=row["price_eur"],
            area_sqm=row["area_sqm"],
            bedrooms=row["bedrooms"],
            rooms=row["rooms"],
            furnishing=row["furnishing"],
            rental_type=row["rental_type"],
            description=row["description"],
            available_from=row["available_from"],
            raw=json.loads(row["raw_json"]),
            fingerprint=row["fingerprint"],
            discovered_at=datetime.fromisoformat(row["first_seen_at"]),
        )
        return StoredListing(
            id=row["id"],
            listing=listing,
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            match_score=row["match_score"],
            match_reasons=json.loads(row["match_reasons_json"]),
            notification_sent_at=(
                datetime.fromisoformat(row["notification_sent_at"])
                if row["notification_sent_at"]
                else None
            ),
            high_priority_notified=bool(row["high_priority_notified"]),
        )

    def _export_rows(self, matches_only: bool) -> list[dict[str, str | int | float | None]]:
        query = "SELECT * FROM listings"
        if matches_only:
            query += " WHERE is_match = 1"
        query += " ORDER BY last_seen_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [
            {
                "id": row["id"],
                "source": row["source"],
                "external_id": row["external_id"],
                "title": row["title"],
                "city": row["city"],
                "price_eur": row["price_eur"],
                "area_sqm": row["area_sqm"],
                "bedrooms": row["bedrooms"],
                "furnishing": row["furnishing"],
                "rental_type": row["rental_type"],
                "url": row["url"],
                "canonical_url": row["canonical_url"],
                "match_score": row["match_score"],
                "is_match": row["is_match"],
                "is_high_priority": row["is_high_priority"],
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
                "notification_sent_at": row["notification_sent_at"],
            }
            for row in rows
        ]
