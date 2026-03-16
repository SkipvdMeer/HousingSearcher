from __future__ import annotations

import re
from time import perf_counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from local_housing_searcher.adapters.base import BaseAdapter
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.models import Listing, RentalType
from local_housing_searcher.utils import canonicalize_url, extract_digits, normalize_text


class HuurwoningenAdapter(BaseAdapter):
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
        anchors = soup.select('a[href*="/huren/"]')
        seen_urls: set[str] = set()
        listings: list[Listing] = []
        skip_counts = {
            "duplicate_url": 0,
            "missing_container": 0,
            "missing_price": 0,
            "missing_title": 0,
        }
        for anchor in anchors:
            href = anchor.get("href")
            if not href:
                continue
            absolute_url = urljoin("https://www.huurwoningen.nl", href)
            canonical_url = canonicalize_url(absolute_url)
            if canonical_url in seen_urls:
                skip_counts["duplicate_url"] += 1
                continue
            seen_urls.add(canonical_url)
            container = self._find_container(anchor)
            if container is None:
                skip_counts["missing_container"] += 1
                continue
            text = container.get_text(" ", strip=True)
            price_eur = extract_digits(self._first_match(text, r"€\s*[\d\.\,]+"))
            title = anchor.get_text(" ", strip=True) or self._first_match(text, r"[A-Za-z].+?Amsterdam")
            if price_eur is None or not title:
                if price_eur is None:
                    skip_counts["missing_price"] += 1
                else:
                    skip_counts["missing_title"] += 1
                continue
            area_sqm = extract_digits(self._first_match(text, r"\d+\s*m²"))
            rooms = extract_digits(self._first_match(text, r"\d+\s*(?:kamers?|rooms?)"))
            city = self._extract_city(text) or "Amsterdam"
            listing = Listing(
                source=self.context.source.id,
                external_id=self._extract_external_id(canonical_url),
                url=absolute_url,
                canonical_url=canonical_url,
                title=title.strip(),
                address=title.strip(),
                city=city,
                price_eur=price_eur,
                area_sqm=float(area_sqm) if area_sqm is not None else None,
                bedrooms=max(rooms - 1, 0) if rooms is not None else None,
                rooms=rooms,
                rental_type=self._parse_rental_type(canonical_url, title),
                raw={"card_text": text[:500]},
            )
            listing.fingerprint = listing_fingerprint(listing)
            listings.append(listing)
            if len(listings) >= max_listings:
                break
        self.log_parse_summary(candidate_count=len(anchors), parsed_count=len(listings), skip_counts=skip_counts)
        return listings

    def _find_container(self, anchor: Tag) -> Tag | None:
        current: Tag | None = anchor
        while current is not None:
            if current.name in {"article", "li", "div", "section"}:
                text = current.get_text(" ", strip=True)
                if "€" in text:
                    return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    def _first_match(self, text: str, pattern: str) -> str | None:
        match = re.search(pattern, text, re.I)
        return match.group(0) if match else None

    def _extract_city(self, text: str) -> str | None:
        match = re.search(r"\b(Amsterdam)\b", text, re.I)
        return match.group(1).title() if match else None

    def _extract_external_id(self, url: str) -> str:
        parts = [part for part in urlparse(url).path.split("/") if part]
        return parts[-2] if len(parts) >= 2 else parts[-1]

    def _parse_rental_type(self, url: str, title: str) -> RentalType:
        normalized = normalize_text(url + " " + title)
        if "/appartement/" in normalized or "apartment" in normalized or "appartement" in normalized:
            return RentalType.APARTMENT
        if "/huis/" in normalized or "house" in normalized or "huis" in normalized:
            return RentalType.HOUSE
        if "/studio/" in normalized or "studio" in normalized:
            return RentalType.STUDIO
        if "/kamer/" in normalized or "room" in normalized or "kamer" in normalized:
            return RentalType.ROOM
        return RentalType.OTHER
