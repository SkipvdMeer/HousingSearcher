from __future__ import annotations

import json
import re
from datetime import datetime
from time import perf_counter
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from local_housing_searcher.adapters.base import BaseAdapter
from local_housing_searcher.config import FilterConfig
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.models import Listing, RentalType
from local_housing_searcher.utils import canonicalize_url, extract_digits, normalize_text


class FundaAdapter(BaseAdapter):
    def fetch(self):
        started_at = perf_counter()
        source = self.context.source
        search_url = self._resolve_search_url()
        if not search_url:
            return self.wrap_result(
                listings=[],
                ok=False,
                message="source is missing search_url",
                started_at=started_at,
            )
        try:
            listings: list[Listing] = []
            seen_listing_urls: set[str] = set()
            visited_urls: set[str] = set()
            next_url = search_url
            pages_requested = 0
            pages_with_new_results = 0
            last_page_result = None
            max_pages = 50
            publish_date_cutoff = None
            stop_reason: str | None = None
            if self.context.database is not None:
                publish_date_cutoff = self.context.database.latest_publish_date_for_source(source.id)

            while next_url and next_url not in visited_urls and len(listings) < source.max_listings and pages_requested < max_pages:
                visited_urls.add(next_url)
                try:
                    page_result = self.fetch_page(
                        next_url,
                        source.timeout_seconds,
                        headless=source.headless,
                        wait_until=source.wait_until,
                        extra_wait_ms=source.extra_wait_ms,
                    )
                    pages_requested += 1
                except Exception:
                    if listings:
                        self.logger.warning(
                            "%s pagination stopped after %s requested page(s); failed to fetch %s",
                            source.id,
                            pages_requested,
                            next_url,
                            exc_info=True,
                        )
                        stop_reason = "fetch_failed"
                        break
                    raise
                last_page_result = page_result
                blocked = self.detect_access_block(page_result.html)
                if blocked is not None:
                    self.log_access_block(page_result, blocked)
                    if not listings:
                        return self.wrap_result(
                            listings=[],
                            ok=False,
                            message=blocked,
                            details=self.block_details(page_result, blocked),
                            started_at=started_at,
                        )
                    self.logger.warning(
                        "%s pagination stopped by access block after %s requested page(s): %s",
                        source.id,
                        pages_requested,
                        blocked,
                    )
                    stop_reason = "access_block"
                    break

                remaining = source.max_listings - len(listings)
                page_listings = self._parse_search_results(page_result.html, remaining)
                unique_page_listings = []
                for listing in page_listings:
                    if listing.canonical_url in seen_listing_urls:
                        continue
                    seen_listing_urls.add(listing.canonical_url)
                    unique_page_listings.append(listing)
                if not unique_page_listings:
                    self.logger.debug("%s pagination stopped after duplicate-only page %s", source.id, next_url)
                    stop_reason = "duplicate_only_page"
                    break
                listings.extend(unique_page_listings)
                pages_with_new_results += 1

                if len(listings) >= source.max_listings:
                    stop_reason = "max_listings_reached"
                    break
                if publish_date_cutoff is not None and self._should_stop_pagination(unique_page_listings, publish_date_cutoff):
                    self.logger.debug(
                        "%s pagination stopped at publish_date cutoff %s after %s requested page(s)",
                        source.id,
                        publish_date_cutoff.isoformat(),
                        pages_requested,
                    )
                    stop_reason = "publish_date_cutoff"
                    break
                next_url = self._extract_next_page_url(page_result.html, page_result.final_url)
                if next_url is None:
                    stop_reason = "no_next_page"

            if last_page_result is None:
                raise RuntimeError("no page result returned for funda source")

            return self.wrap_result(
                listings=listings,
                ok=True,
                message=(
                    f"fetched {len(listings)} listings across "
                    f"{pages_with_new_results} result page(s) ({pages_requested} requested)"
                ),
                details={
                    "search_url": search_url,
                    "final_url": last_page_result.final_url,
                    "status_code": last_page_result.status_code,
                    "title": last_page_result.title,
                    "pages_fetched": pages_requested,
                    "pages_with_new_results": pages_with_new_results,
                    "publish_date_cutoff": publish_date_cutoff.isoformat() if publish_date_cutoff else None,
                    "stop_reason": stop_reason,
                },
                started_at=started_at,
            )
        except PlaywrightTimeoutError:
            return self.wrap_result(
                listings=[],
                ok=False,
                message=f"timed out after {source.timeout_seconds}s",
                details={"search_url": search_url},
                started_at=started_at,
            )
        except Exception as exc:  # pragma: no cover
            return self.wrap_result(
                listings=[],
                ok=False,
                message=str(exc),
                details={"search_url": search_url},
                started_at=started_at,
            )

    def _parse_search_results(self, html: str, max_listings: int) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        publish_dates = self._extract_publish_dates(html)
        ordered_urls = self._extract_ordered_listing_urls(soup)
        listings: list[Listing] = []
        skip_counts = {
            "missing_anchor": 0,
            "missing_card": 0,
            "missing_title": 0,
            "missing_price": 0,
            "invalid_listing": 0,
        }
        for canonical_url in ordered_urls:
            anchor = self._find_listing_anchor(soup, canonical_url)
            if anchor is None:
                skip_counts["missing_anchor"] += 1
                continue
            container = self._find_listing_card(anchor)
            if container is None:
                skip_counts["missing_card"] += 1
                continue

            street, title, postcode, city = self._extract_listing_location(anchor, container)
            if not title:
                skip_counts["missing_title"] += 1
                continue
            price_eur = self._extract_listing_price(container)
            if price_eur is None:
                skip_counts["missing_price"] += 1
                continue
            area_sqm = self._extract_listing_area(container)
            rooms = self._extract_listing_rooms(container)
            text = container.get_text(" ", strip=True)
            try:
                listing = Listing(
                    source=self.context.source.id,
                    external_id=self._extract_external_id(canonical_url),
                    url=canonical_url,
                    canonical_url=canonical_url,
                    title=title,
                    address=street or title,
                    city=city,
                    postcode=postcode,
                    price_eur=price_eur,
                    area_sqm=float(area_sqm) if area_sqm is not None else None,
                    bedrooms=max(rooms - 1, 0) if rooms is not None else None,
                    rooms=rooms,
                    rental_type=self._parse_rental_type(canonical_url, title),
                    raw={
                        "card_text": text[:500],
                        "publish_date": publish_dates.get(canonical_url),
                    },
                )
            except Exception:
                skip_counts["invalid_listing"] += 1
                continue
            listing.fingerprint = listing_fingerprint(listing)
            listings.append(listing)
            if len(listings) >= max_listings:
                break
        self.log_parse_summary(candidate_count=len(ordered_urls), parsed_count=len(listings), skip_counts=skip_counts)
        return listings

    def _extract_ordered_listing_urls(self, soup: BeautifulSoup) -> list[str]:
        ordered_urls: list[str] = []
        metadata = soup.select_one('script[type="application/ld+json"][data-hid="result-list-metadata"]')
        if metadata is not None and metadata.string:
            try:
                payload = json.loads(metadata.string)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                for item in payload.get("itemListElement", []):
                    url = item.get("url")
                    if not isinstance(url, str) or "/detail/huur/" not in url:
                        continue
                    canonical_url = canonicalize_url(urljoin("https://www.funda.nl", url))
                    if canonical_url not in ordered_urls:
                        ordered_urls.append(canonical_url)
        if ordered_urls:
            return ordered_urls

        for anchor in soup.select('h2 a[href*="/detail/huur/"], a[data-testid="listingDetailsAddress"][href*="/detail/huur/"]'):
            href = anchor.get("href")
            if not href:
                continue
            canonical_url = canonicalize_url(urljoin("https://www.funda.nl", href))
            if canonical_url not in ordered_urls:
                ordered_urls.append(canonical_url)
        if ordered_urls:
            return ordered_urls

        for anchor in soup.select('a[href*="/detail/huur/"]'):
            href = anchor.get("href")
            if not href:
                continue
            title = anchor.get_text(" ", strip=True)
            if not title:
                continue
            canonical_url = canonicalize_url(urljoin("https://www.funda.nl", href))
            if canonical_url not in ordered_urls:
                ordered_urls.append(canonical_url)
        return ordered_urls

    def _find_listing_anchor(self, soup: BeautifulSoup, canonical_url: str) -> Tag | None:
        selectors = [
            'h2 a[href*="/detail/huur/"]',
            'a[data-testid="listingDetailsAddress"][href*="/detail/huur/"]',
            'a[href*="/detail/huur/"]',
        ]
        for selector in selectors:
            for anchor in soup.select(selector):
                href = anchor.get("href")
                if not href:
                    continue
                if canonicalize_url(urljoin("https://www.funda.nl", href)) != canonical_url:
                    continue
                if anchor.get_text(" ", strip=True):
                    return anchor
        return None

    def _find_listing_card(self, anchor: Tag) -> Tag | None:
        current: Tag | None = anchor
        while current is not None:
            if current.name in {"article", "li", "div", "section"}:
                text = current.get_text(" ", strip=True)
                if "€" in text:
                    return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    def _extract_listing_location(self, anchor: Tag, container: Tag) -> tuple[str | None, str, str | None, str]:
        lines = [child.get_text(" ", strip=True) for child in anchor.find_all("div", recursive=False)]
        lines = [line for line in lines if line]
        if not lines:
            lines = [anchor.get_text(" ", strip=True)]
        street = lines[0].strip() if lines else None
        remainder = " ".join(lines[1:]).strip()
        title = " ".join(part for part in [street, remainder] if part).strip()
        location_text = remainder or title or container.get_text(" ", strip=True)
        postcode_match = re.search(r"\b\d{4}\s?[A-Z]{2}\b", location_text)
        postcode = postcode_match.group(0).replace(" ", "") if postcode_match else None
        city = self._extract_city(location_text) or self._extract_city(container.get_text(" ", strip=True)) or "Amsterdam"
        return street, title, postcode, city

    def _extract_listing_price(self, container: Tag) -> int | None:
        for price_node in container.select(".font-semibold .truncate, .font-semibold"):
            text = price_node.get_text(" ", strip=True)
            if "€" not in text:
                continue
            price = extract_digits(text)
            if price is not None:
                return price
        return extract_digits(self._first_match(container.get_text(" ", strip=True), r"€\s*[\d\.\,]+"))

    def _extract_listing_area(self, container: Tag) -> int | None:
        for node in container.select("ul li span"):
            text = node.get_text(" ", strip=True)
            if "m²" in text:
                return extract_digits(text)
        return extract_digits(self._first_match(container.get_text(" ", strip=True), r"\d+\s*m²"))

    def _extract_listing_rooms(self, container: Tag) -> int | None:
        for node in container.select("ul li span"):
            text = node.get_text(" ", strip=True)
            if re.fullmatch(r"\d+", text):
                return int(text)
            if re.search(r"\d+\s*(?:kamer|kamers|room|rooms)\b", text, re.I):
                return extract_digits(text)
        return extract_digits(self._first_match(container.get_text(" ", strip=True), r"\d+\s*(?:kamer|kamers|room|rooms)\b"))

    def _first_match(self, text: str, pattern: str) -> str | None:
        match = re.search(pattern, text, re.I)
        return match.group(0) if match else None

    def _extract_city(self, text: str) -> str | None:
        match = re.search(r"\b(Amsterdam)\b", text, re.I)
        return match.group(1).title() if match else None

    def _extract_external_id(self, url: str) -> str:
        parts = [part for part in urlparse(url).path.split("/") if part]
        return parts[-1]

    def _parse_rental_type(self, url: str, title: str) -> RentalType:
        normalized = normalize_text(url + " " + title)
        if "appartement" in normalized or "apartment" in normalized:
            return RentalType.APARTMENT
        if "huis" in normalized or "house" in normalized:
            return RentalType.HOUSE
        if "studio" in normalized:
            return RentalType.STUDIO
        if "kamer" in normalized or "room" in normalized:
            return RentalType.ROOM
        return RentalType.OTHER

    def _extract_next_page_url(self, html: str, current_url: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        candidates = [
            'a[rel="next"]',
            'a[aria-label*="Volgende"]',
            'a[aria-label*="volgende"]',
            'a[href*="page="][aria-current!="page"]',
            'a[href*="search_result="][aria-current!="page"]',
        ]
        for selector in candidates:
            for anchor in soup.select(selector):
                href = anchor.get("href")
                if href:
                    resolved = self._resolve_next_page_url(href, current_url)
                    if resolved:
                        return resolved

        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            text = anchor.get_text(" ", strip=True)
            aria_label = (anchor.get("aria-label") or "").strip()
            if not href:
                continue
            if text.lower() == "volgende" or "volgende" in aria_label.lower():
                resolved = self._resolve_next_page_url(href, current_url)
                if resolved:
                    return resolved

        return self._increment_page_url(current_url)

    def _resolve_next_page_url(self, href: str, current_url: str) -> str | None:
        current = urlparse(current_url)
        resolved = urljoin(current_url, href)
        resolved_parts = urlparse(resolved)

        if resolved_parts.netloc and resolved_parts.netloc != current.netloc:
            return None

        current_query = parse_qs(current.query, keep_blank_values=True)
        resolved_query = parse_qs(resolved_parts.query, keep_blank_values=True)

        # Some Funda pagination links only carry `page=2` and accidentally point
        # at `/`. Preserve the active search path and filters in that case.
        paging_key = "search_result" if current.path.startswith("/zoeken/huur") else "page"
        alternate_paging_key = "page" if paging_key == "search_result" else "search_result"

        if alternate_paging_key in resolved_query and paging_key not in resolved_query:
            resolved_query[paging_key] = resolved_query.pop(alternate_paging_key)

        if paging_key in resolved_query and resolved_parts.path in {"", "/"} and current.path not in {"", "/"}:
            merged_query = dict(current_query)
            merged_query.update(resolved_query)
            return urlunparse(
                (
                    current.scheme,
                    current.netloc,
                    current.path,
                    current.params,
                    urlencode(merged_query, doseq=True),
                    current.fragment,
                )
            )

        # If the next-link only overrides the page number on the same search path,
        # keep the current filters unless the link explicitly replaces them.
        if paging_key in resolved_query and resolved_parts.path == current.path:
            merged_query = dict(current_query)
            merged_query.update(resolved_query)
            return urlunparse(
                (
                    current.scheme,
                    current.netloc,
                    resolved_parts.path,
                    resolved_parts.params,
                    urlencode(merged_query, doseq=True),
                    resolved_parts.fragment,
                )
            )

        if current.path.startswith("/zoeken/huur") and not resolved_parts.path.startswith("/zoeken/huur"):
            return None

        return resolved

    def _increment_page_url(self, current_url: str) -> str | None:
        parsed = urlparse(current_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        paging_key = "search_result" if parsed.path.startswith("/zoeken/huur") else "page"
        alternate_paging_key = "page" if paging_key == "search_result" else "search_result"
        if alternate_paging_key in query and paging_key not in query:
            query[paging_key] = query.pop(alternate_paging_key)
        if paging_key in query:
            try:
                page_number = int(query[paging_key][0])
            except (TypeError, ValueError):
                return None
            query[paging_key] = [str(page_number + 1)]
        else:
            query[paging_key] = ["2"]
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query, doseq=True),
                parsed.fragment,
            )
        )

    def _resolve_search_url(self) -> str | None:
        source = self.context.source
        filters = self.context.filters
        base_url = source.search_url or "https://www.funda.nl/zoeken/huur"
        if filters is None:
            return base_url

        parsed = urlparse(base_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        path = "/zoeken/huur"

        selected_areas = self._selected_areas(filters)
        if selected_areas:
            query["selected_area"] = [json.dumps(selected_areas, separators=(",", ":"))]

        if filters.max_rent_eur is not None:
            query["price"] = [json.dumps(f"0-{int(filters.max_rent_eur)}")]

        if filters.min_sqm is not None:
            query["floor_area"] = [json.dumps(f"{self._format_number(filters.min_sqm)}-")]

        object_types = self._object_types(filters)
        if object_types:
            query["object_type"] = [json.dumps(object_types, separators=(",", ":"))]
        if "sort" not in query:
            query["sort"] = [json.dumps("date_down")]

        return urlunparse(
            (
                parsed.scheme or "https",
                parsed.netloc or "www.funda.nl",
                path,
                parsed.params,
                urlencode(query, doseq=True),
                parsed.fragment,
            )
        )

    def _selected_areas(self, filters: FilterConfig) -> list[str]:
        return [normalize_text(city) for city in filters.cities if city.strip()]

    def _object_types(self, filters: FilterConfig) -> list[str]:
        mapping = {
            RentalType.APARTMENT: "apartment",
            RentalType.HOUSE: "house",
            RentalType.ROOM: "room",
        }
        object_types = [mapping[rental_type] for rental_type in filters.rental_types if rental_type in mapping]
        return list(dict.fromkeys(object_types))

    def _format_number(self, value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:g}"

    def _extract_publish_dates(self, html: str) -> dict[str, str]:
        publish_dates: dict[str, str] = {}
        pattern = re.compile(
            r'"(?P<publish>\d{4}-\d{2}-\d{2}T[^"]+)"(?:(?!"/detail/huur/).){0,400}"(?P<url>/detail/huur/[^"]+/)"',
            re.DOTALL,
        )
        for match in pattern.finditer(html):
            absolute_url = urljoin("https://www.funda.nl", match.group("url"))
            canonical_url = canonicalize_url(absolute_url)
            publish_dates.setdefault(canonical_url, match.group("publish"))
        return publish_dates

    def _publish_date_for_listing(self, listing: Listing) -> datetime | None:
        value = listing.raw.get("publish_date")
        if not value or not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _should_stop_pagination(self, page_listings: list[Listing], publish_date_cutoff: datetime) -> bool:
        if not page_listings:
            return False
        for listing in page_listings:
            published_at = self._publish_date_for_listing(listing)
            if published_at is None:
                return False
            if published_at > publish_date_cutoff:
                return False
            if published_at == publish_date_cutoff and self.context.database is not None:
                if self.context.database.find_existing_listing_id(listing) is None:
                    return False
        return True
