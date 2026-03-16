from __future__ import annotations

import re
from time import perf_counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from local_housing_searcher.adapters.base import BaseAdapter
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.models import Listing, RentalType
from local_housing_searcher.utils import canonicalize_url, extract_digits, normalize_text


class DirectWonenAdapter(BaseAdapter):
    def fetch(self):
        started_at = perf_counter()
        source = self.context.source
        if not source.search_url:
            return self.wrap_result(
                listings=[],
                ok=False,
                message="source is missing search_url",
                started_at=started_at,
            )
        try:
            page_result = self.fetch_page(
                source.search_url,
                source.timeout_seconds,
                headless=source.headless,
                wait_until=source.wait_until,
                extra_wait_ms=source.extra_wait_ms,
            )
            candidate_count = self._candidate_count(page_result.html)
            self.logger.debug("%s candidate listing nodes detected | count=%s", source.id, candidate_count)
            blocked = self.detect_access_block(page_result.html) if candidate_count == 0 else None
            if blocked is not None:
                self.log_access_block(page_result, blocked)
                return self.wrap_result(
                    listings=[],
                    ok=False,
                    message=blocked,
                    details=self.block_details(page_result, blocked),
                    started_at=started_at,
                )
            listings = self._parse_search_results(page_result.html, source.max_listings)
            return self.wrap_result(
                listings=listings,
                ok=True,
                message=f"fetched {len(listings)} listings",
                details={
                    "search_url": source.search_url,
                    "final_url": page_result.final_url,
                    "status_code": page_result.status_code,
                    "title": page_result.title,
                },
                started_at=started_at,
            )
        except PlaywrightTimeoutError:
            return self.wrap_result(
                listings=[],
                ok=False,
                message=f"timed out after {source.timeout_seconds}s",
                details={"search_url": source.search_url},
                started_at=started_at,
            )
        except Exception as exc:  # pragma: no cover
            return self.wrap_result(
                listings=[],
                ok=False,
                message=str(exc),
                details={"search_url": source.search_url},
                started_at=started_at,
            )

    def _parse_search_results(self, html: str, max_listings: int) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.new-search-advert")
        listings: list[Listing] = []
        seen_urls: set[str] = set()
        skip_counts = {
            "duplicate_url": 0,
            "missing_nodes": 0,
            "missing_href": 0,
            "missing_price": 0,
        }
        for card in cards:
            detail_link = card.select_one("div.advert-content-detail a[href*='/huurwoningen-huren/']")
            location_node = card.select_one("h3.location-text")
            price_node = card.select_one("div.advert-location-price")
            type_node = card.select_one("span.advert-location-header")
            if detail_link is None or location_node is None or price_node is None or type_node is None:
                skip_counts["missing_nodes"] += 1
                continue

            href = detail_link.get("href")
            if not href:
                skip_counts["missing_href"] += 1
                continue

            absolute_url = urljoin("https://www.directwonen.nl", href)
            canonical_url = canonicalize_url(absolute_url)
            if canonical_url in seen_urls:
                skip_counts["duplicate_url"] += 1
                continue
            seen_urls.add(canonical_url)

            price_eur = extract_digits(price_node.get_text(" ", strip=True))
            if price_eur is None:
                skip_counts["missing_price"] += 1
                continue

            location_text = location_node.get_text(" ", strip=True)
            address, city = self._parse_location(location_text)
            metadata = self._parse_detail_table(card)
            rooms = extract_digits(self._text_or_none(card.select_one(".small-banner.rooms .small-banner-top")))
            area_sqm = extract_digits(self._text_or_none(card.select_one(".small-banner.surface .small-banner-top")))
            rental_type = self._parse_rental_type(type_node.get_text(" ", strip=True), canonical_url, location_text)

            listing = Listing(
                source=self.context.source.id,
                external_id=self._extract_external_id(canonical_url),
                url=absolute_url,
                canonical_url=canonical_url,
                title=location_text,
                address=address,
                city=city,
                price_eur=price_eur,
                area_sqm=float(area_sqm) if area_sqm is not None else None,
                bedrooms=self._estimate_bedrooms(rooms, rental_type),
                rooms=rooms,
                rental_type=rental_type,
                available_from=metadata.get("beschikbaar per"),
                raw={
                    "listing_type": type_node.get_text(" ", strip=True),
                    "price_label": self._text_or_none(card.select_one("div.kale-huur")),
                    "service_costs": metadata.get("servicekosten"),
                    "delivery_level": metadata.get("opleverniveau"),
                },
            )
            listing.fingerprint = listing_fingerprint(listing)
            listings.append(listing)
            if len(listings) >= max_listings:
                break

        self.log_parse_summary(candidate_count=len(cards), parsed_count=len(listings), skip_counts=skip_counts)
        return listings

    def _candidate_count(self, html: str) -> int:
        soup = BeautifulSoup(html, "html.parser")
        return len(soup.select("div.new-search-advert"))

    def _parse_detail_table(self, card) -> dict[str, str]:
        data: dict[str, str] = {}
        for row in card.select("div.advert-content-detail tr"):
            columns = row.select("td")
            if len(columns) != 2:
                continue
            key = normalize_text(columns[0].get_text(" ", strip=True)).rstrip(":")
            value = columns[1].get_text(" ", strip=True)
            if key:
                data[key] = value
        return data

    def _parse_location(self, location_text: str) -> tuple[str, str]:
        parts = [part.strip() for part in location_text.split(",") if part.strip()]
        if len(parts) >= 2:
            return ", ".join(parts[:-1]), parts[-1]
        return location_text.strip(), "Amsterdam"

    def _parse_rental_type(self, listing_type: str, url: str, title: str) -> RentalType:
        normalized = normalize_text(f"{listing_type} {url} {title}")
        if "appartement" in normalized or "apartment" in normalized:
            return RentalType.APARTMENT
        if "studio" in normalized:
            return RentalType.STUDIO
        if "kamer" in normalized or "room" in normalized:
            return RentalType.ROOM
        if "huis" in normalized or "woning" in normalized or "house" in normalized:
            return RentalType.HOUSE
        return RentalType.OTHER

    def _estimate_bedrooms(self, rooms: int | None, rental_type: RentalType) -> int | None:
        if rooms is None:
            return None
        if rental_type == RentalType.ROOM:
            return rooms
        return max(rooms - 1, 0)

    def _extract_external_id(self, url: str) -> str:
        last_part = [part for part in urlparse(url).path.split("/") if part][-1]
        match = re.search(r"(\d+)$", last_part)
        return match.group(1) if match else last_part

    def _text_or_none(self, node) -> str | None:
        return node.get_text(" ", strip=True) if node is not None else None
