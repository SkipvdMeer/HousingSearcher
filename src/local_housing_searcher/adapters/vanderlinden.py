from __future__ import annotations

from time import perf_counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from local_housing_searcher.adapters.base import BaseAdapter
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.models import Listing, RentalType
from local_housing_searcher.utils import canonicalize_url, extract_digits


class VanDerLindenAdapter(BaseAdapter):
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
        items = soup.select("#zoekresultaten .woninginfo")
        listings: list[Listing] = []
        skip_counts = {
            "missing_nodes": 0,
            "missing_href": 0,
            "missing_price": 0,
        }
        for item in items[:max_listings]:
            title_node = item.select_one("strong")
            link_node = item.select_one("a.blocklink")
            price_node = item.select_one(".mt-2")
            detail_meta = item.select_one(".text-80.mt-3")
            city_node = item.select_one(".fa-location-dot")
            if title_node is None or link_node is None or price_node is None:
                skip_counts["missing_nodes"] += 1
                continue
            href = link_node.get("href")
            if not href:
                skip_counts["missing_href"] += 1
                continue
            absolute_url = urljoin("https://www.vanderlinden.nl", href)
            canonical_url = canonicalize_url(absolute_url)
            city_text = city_node.parent.get_text(" ", strip=True) if city_node and city_node.parent else "Amsterdam"
            spans = detail_meta.select("span") if detail_meta else []
            area_sqm = extract_digits(spans[0].get_text(" ", strip=True)) if len(spans) > 0 else None
            bedrooms = extract_digits(spans[2].get_text(" ", strip=True)) if len(spans) > 2 else None
            price_eur = extract_digits(price_node.get_text(" ", strip=True))
            if price_eur is None or price_eur <= 0:
                skip_counts["missing_price"] += 1
                continue
            listing = Listing(
                source=self.context.source.id,
                external_id=self._extract_external_id(canonical_url),
                url=absolute_url,
                canonical_url=canonical_url,
                title=title_node.get_text(" ", strip=True),
                address=title_node.get_text(" ", strip=True),
                city=city_text.strip() or "Amsterdam",
                price_eur=price_eur,
                area_sqm=float(area_sqm) if area_sqm is not None else None,
                bedrooms=bedrooms,
                rooms=bedrooms + 1 if bedrooms is not None else None,
                rental_type=RentalType.OTHER,
                raw={
                    "availability": item.select_one(".fotolabel").get_text(" ", strip=True)
                    if item.select_one(".fotolabel")
                    else None
                },
            )
            listing.fingerprint = listing_fingerprint(listing)
            listings.append(listing)
        self.log_parse_summary(candidate_count=len(items[:max_listings]), parsed_count=len(listings), skip_counts=skip_counts)
        return listings

    def _extract_external_id(self, url: str) -> str:
        parts = [part for part in urlparse(url).path.split("/") if part]
        return parts[-1]
