from __future__ import annotations

from rapidfuzz.utils import default_process

from local_housing_searcher.models import Listing
from local_housing_searcher.utils import normalize_text


def bucket_price(value: int) -> int:
    return round(value / 25) * 25


def bucket_area(value: float | None) -> int:
    if value is None:
        return 0
    return round(value / 5) * 5


def listing_fingerprint(listing: Listing) -> str:
    base_parts = [
        listing.city,
        listing.address or "",
        listing.title,
        str(bucket_price(listing.price_eur)),
        str(bucket_area(listing.area_sqm)),
    ]
    normalized = [default_process(normalize_text(part)) or "" for part in base_parts]
    return "|".join(normalized)
