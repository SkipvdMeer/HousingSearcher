from __future__ import annotations

from time import perf_counter

from local_housing_searcher.adapters.base import BaseAdapter
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.models import FurnishingPreference, Listing, RentalType
from local_housing_searcher.utils import canonicalize_url


class MockAdapter(BaseAdapter):
    def fetch(self):
        started_at = perf_counter()
        seed = int(getattr(self.context.source, "seed", 3))
        fixture_name = getattr(self.context.source, "fixture_name", "demo")
        listings = []
        for index in range(seed):
            url = f"https://mock.local/{fixture_name}/{index + 1}"
            listing = Listing(
                source=self.context.source.id,
                external_id=f"{fixture_name}-{index + 1}",
                url=url,
                canonical_url=canonicalize_url(url),
                title=f"{fixture_name.title()} apartment {index + 1}",
                address=f"Mockstraat {100 + index}",
                city="Amsterdam" if index % 2 == 0 else "Utrecht",
                postcode=f"10{index}0 AB",
                price_eur=1500 + (index * 150),
                area_sqm=55 + (index * 10),
                bedrooms=1 + (index % 3),
                rooms=2 + (index % 2),
                furnishing=(
                    FurnishingPreference.FURNISHED
                    if index % 2 == 0
                    else FurnishingPreference.UNFURNISHED
                ),
                rental_type=RentalType.APARTMENT,
                description="Balcony near station and recently renovated.",
                raw={"fixture_name": fixture_name, "index": index + 1},
            )
            listing.fingerprint = listing_fingerprint(listing)
            listings.append(listing)
        return self.wrap_result(
            listings=listings,
            ok=True,
            message=f"generated {len(listings)} mock listings",
            details={"fixture_name": fixture_name},
            started_at=started_at,
        )
