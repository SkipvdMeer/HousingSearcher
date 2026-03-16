from pathlib import Path

from local_housing_searcher.config import FilterConfig, ScoringConfig
from local_housing_searcher.db import Database
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.filtering import score_listing
from local_housing_searcher.models import FurnishingPreference, Listing, RentalType
from local_housing_searcher.utils import canonicalize_url


def test_db_deduplicates_by_fingerprint(tmp_path: Path) -> None:
    database = Database(tmp_path / "housing.db")
    database.initialize()

    listing_one = Listing(
        source="mock-a",
        external_id="1",
        url="https://example.com/a/1",
        canonical_url=canonicalize_url("https://example.com/a/1"),
        title="Flat Example Street 10",
        address="Example Street 10",
        city="Amsterdam",
        price_eur=2000,
        area_sqm=60,
        furnishing=FurnishingPreference.FURNISHED,
        rental_type=RentalType.APARTMENT,
    )
    listing_one.fingerprint = listing_fingerprint(listing_one)
    match_one = score_listing(listing_one, FilterConfig(cities=["amsterdam"]), ScoringConfig())
    stored_one, created_one = database.upsert_listing(match_one)

    listing_two = listing_one.model_copy(
        update={
            "source": "mock-b",
            "external_id": "99",
            "url": "https://example.com/b/99",
            "canonical_url": canonicalize_url("https://example.com/b/99"),
            "price_eur": 2010,
        }
    )
    listing_two.fingerprint = listing_fingerprint(listing_two)
    match_two = score_listing(listing_two, FilterConfig(cities=["amsterdam"]), ScoringConfig())
    stored_two, created_two = database.upsert_listing(match_two)

    assert created_one is True
    assert created_two is False
    assert stored_one.id == stored_two.id
    assert len(database.recent_matches()) == 1
