from __future__ import annotations

from time import perf_counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from local_housing_searcher.adapters.base import BaseAdapter
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.models import Listing, RentalType
from local_housing_searcher.utils import canonicalize_url, extract_digits, normalize_text


class VbtAdapter(BaseAdapter):
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
            blocked = self.detect_access_block(page_result.html)
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
        cards = soup.select("div.itemviewer.houses a.property")
        city_filter = normalize_text(getattr(self.context.source, "city", "Amsterdam"))
        listings: list[Listing] = []
        seen_urls: set[str] = set()
        skip_counts = {
            "duplicate_url": 0,
            "city_mismatch": 0,
            "missing_nodes": 0,
            "missing_price": 0,
        }
        for card in cards:
            href = card.get("href")
            city_node = card.select_one("div.items > div")
            address_node = card.select_one("span.normal")
            price_node = card.select_one("div.price")
            if not href or city_node is None or address_node is None or price_node is None:
                skip_counts["missing_nodes"] += 1
                continue

            city = city_node.get_text(" ", strip=True)
            if city_filter and normalize_text(city) != city_filter:
                skip_counts["city_mismatch"] += 1
                continue

            absolute_url = urljoin("https://vbtverhuurmakelaars.nl", href)
            canonical_url = canonicalize_url(absolute_url)
            if canonical_url in seen_urls:
                skip_counts["duplicate_url"] += 1
                continue
            seen_urls.add(canonical_url)

            price_eur = extract_digits(price_node.get_text(" ", strip=True))
            if price_eur is None:
                skip_counts["missing_price"] += 1
                continue

            metadata = self._parse_table(card)
            rooms = extract_digits(metadata.get("kamers"))
            area_sqm = extract_digits(metadata.get("woonoppervlakte"))
            rental_type = self._parse_rental_type(metadata.get("soort object"), canonical_url, address_node.get_text(" ", strip=True))

            listing = Listing(
                source=self.context.source.id,
                external_id=self._extract_external_id(canonical_url),
                url=absolute_url,
                canonical_url=canonical_url,
                title=address_node.get_text(" ", strip=True),
                address=address_node.get_text(" ", strip=True),
                city=city,
                price_eur=price_eur,
                area_sqm=float(area_sqm) if area_sqm is not None else None,
                bedrooms=self._estimate_bedrooms(rooms, rental_type),
                rooms=rooms,
                rental_type=rental_type,
                available_from=metadata.get("beschikbaar"),
                raw={
                    "status": self._text_or_none(card.select_one("span.status")),
                    "service_costs": metadata.get("servicekosten"),
                    "minimum_term": metadata.get("huurtermijn (min.)"),
                    "reaction_count": metadata.get("aantal reacties"),
                },
            )
            listing.fingerprint = listing_fingerprint(listing)
            listings.append(listing)
            if len(listings) >= max_listings:
                break

        self.log_parse_summary(candidate_count=len(cards), parsed_count=len(listings), skip_counts=skip_counts)
        return listings

    def _parse_table(self, card) -> dict[str, str]:
        data: dict[str, str] = {}
        for row in card.select("table tr"):
            columns = row.select("td")
            if len(columns) != 2:
                continue
            key = normalize_text(columns[0].get_text(" ", strip=True)).rstrip(":")
            value = columns[1].get_text(" ", strip=True)
            if key:
                data[key] = value
        return data

    def _parse_rental_type(self, object_type: str | None, url: str, title: str) -> RentalType:
        normalized = normalize_text(f"{object_type or ''} {url} {title}")
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
        parts = [part for part in urlparse(url).path.split("/") if part]
        return parts[-1]

    def _text_or_none(self, node) -> str | None:
        return node.get_text(" ", strip=True) if node is not None else None
