from __future__ import annotations

import re
from time import perf_counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from local_housing_searcher.adapters.base import BaseAdapter, PageFetchResult
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.models import FurnishingPreference, Listing, RentalType
from local_housing_searcher.utils import canonicalize_url, extract_digits, normalize_text

POSTCODE_RE = re.compile(r"(?P<postcode>\d{4}\s?[A-Z]{2})\s+(?P<city>[^()]+)")


class ParariusAdapter(BaseAdapter):
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
            page_result = self._fetch_page(source.search_url, source.timeout_seconds)
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
        except Exception as exc:  # pragma: no cover - exercised via CLI integration
            return self.wrap_result(
                listings=[],
                ok=False,
                message=str(exc),
                details={"search_url": source.search_url},
                started_at=started_at,
            )

    def _fetch_page(self, url: str, timeout_seconds: int) -> PageFetchResult:
        self.logger.debug(
            "%s fetch start | url=%s | headless=%s | wait_until=%s | extra_wait_ms=%s | timeout_seconds=%s",
            self.context.source.id,
            url,
            True,
            "domcontentloaded",
            1200,
            timeout_seconds,
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_timeout(1200)
            result = PageFetchResult(
                requested_url=url,
                final_url=page.url,
                title=page.title(),
                status_code=response.status if response else None,
                html=page.content(),
            )
            self.logger.debug(
                "%s fetch complete | status=%s | final_url=%s | title=%r | content_length=%s",
                self.context.source.id,
                result.status_code,
                result.final_url,
                result.title,
                result.content_length,
            )
            self.logger.debug("%s fetch preview | %s", self.context.source.id, self.html_preview(result.html))
            browser.close()
            return result

    def _parse_search_results(self, html: str, max_listings: int) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(".listing-search-item")
        listings: list[Listing] = []
        skip_counts = {
            "missing_nodes": 0,
            "missing_href": 0,
            "missing_price": 0,
        }
        for item in items[:max_listings]:
            title_link = item.select_one("a.listing-search-item__link--title")
            price_node = item.select_one(".listing-search-item__price")
            subtitle_node = item.select_one(".listing-search-item__sub-title")
            feature_nodes = item.select(".illustrated-features__item")
            if title_link is None or price_node is None or subtitle_node is None:
                skip_counts["missing_nodes"] += 1
                continue

            href = title_link.get("href")
            if not href:
                skip_counts["missing_href"] += 1
                continue
            absolute_url = urljoin("https://www.pararius.com", href)
            canonical_url = canonicalize_url(absolute_url)
            external_id = self._extract_external_id(canonical_url)
            title = title_link.get_text(" ", strip=True)
            subtitle = subtitle_node.get_text(" ", strip=True)
            postcode, city, address = self._parse_location(subtitle, title)
            price_eur = extract_digits(price_node.get_text(" ", strip=True))
            if price_eur is None:
                skip_counts["missing_price"] += 1
                continue

            area_sqm = extract_digits(feature_nodes[0].get_text(" ", strip=True)) if len(feature_nodes) > 0 else None
            rooms = extract_digits(feature_nodes[1].get_text(" ", strip=True)) if len(feature_nodes) > 1 else None
            furnishing = self._parse_furnishing(feature_nodes[2].get_text(" ", strip=True) if len(feature_nodes) > 2 else None)

            listing = Listing(
                source=self.context.source.id,
                external_id=external_id,
                url=absolute_url,
                canonical_url=canonical_url,
                title=title,
                address=address,
                city=city,
                postcode=postcode,
                price_eur=price_eur,
                area_sqm=float(area_sqm) if area_sqm is not None else None,
                bedrooms=self._estimate_bedrooms(rooms, title),
                rooms=rooms,
                furnishing=furnishing,
                rental_type=self._parse_rental_type(canonical_url, title),
                description=None,
                raw={
                    "subtitle": subtitle,
                    "features": [node.get_text(" ", strip=True) for node in feature_nodes],
                },
            )
            listing.fingerprint = listing_fingerprint(listing)
            listings.append(listing)
        self.log_parse_summary(candidate_count=len(items[:max_listings]), parsed_count=len(listings), skip_counts=skip_counts)
        return listings

    def _candidate_count(self, html: str) -> int:
        soup = BeautifulSoup(html, "html.parser")
        return len(soup.select(".listing-search-item"))

    def _extract_external_id(self, url: str) -> str:
        path_parts = [part for part in urlparse(url).path.split("/") if part]
        if len(path_parts) >= 3:
            return path_parts[2]
        return path_parts[-1]

    def _parse_location(self, subtitle: str, title: str) -> tuple[str | None, str, str]:
        match = POSTCODE_RE.search(subtitle)
        if match:
            postcode = match.group("postcode").replace(" ", "")
            city = match.group("city").strip()
        else:
            postcode = None
            city = subtitle.split("(")[0].strip()
        address = self._strip_city_from_title(title, city)
        return postcode, city, address

    def _strip_city_from_title(self, title: str, city: str) -> str:
        lowered_city = normalize_text(city)
        words = title.split()
        if words and normalize_text(words[0]) in {"flat", "house", "room", "studio"}:
            words = words[1:]
        address = " ".join(words).strip()
        if lowered_city and normalize_text(address).endswith(lowered_city):
            address = address[: -len(city)].strip()
        return address

    def _parse_furnishing(self, value: str | None) -> FurnishingPreference | None:
        normalized = normalize_text(value)
        if "furnished" in normalized:
            return FurnishingPreference.FURNISHED
        if "upholstered" in normalized or "shell" in normalized or "unfurnished" in normalized:
            return FurnishingPreference.UNFURNISHED
        return None

    def _parse_rental_type(self, url: str, title: str) -> RentalType:
        normalized = normalize_text(url + " " + title)
        if "apartment-for-rent" in normalized or normalized.startswith("flat "):
            return RentalType.APARTMENT
        if "house-for-rent" in normalized:
            return RentalType.HOUSE
        if "studio-for-rent" in normalized or normalized.startswith("studio "):
            return RentalType.STUDIO
        if "room-for-rent" in normalized or normalized.startswith("room "):
            return RentalType.ROOM
        return RentalType.OTHER

    def _estimate_bedrooms(self, rooms: int | None, title: str) -> int | None:
        normalized = normalize_text(title)
        match = re.search(r"(\d+)\s+bed", normalized)
        if match:
            return int(match.group(1))
        if rooms is None:
            return None
        return max(rooms - 1, 0)
