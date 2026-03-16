from local_housing_searcher.config import FilterConfig, ScoringConfig
from local_housing_searcher.dedupe import listing_fingerprint
from local_housing_searcher.filtering import score_listing
from local_housing_searcher.models import FurnishingPreference, Listing, RentalType
from local_housing_searcher.utils import canonicalize_url


def make_listing(**overrides) -> Listing:
    base = Listing(
        source="mock",
        external_id="abc123",
        url="https://example.com/listing/abc123?utm_source=test",
        canonical_url=canonicalize_url("https://example.com/listing/abc123?utm_source=test"),
        title="Apartment on Example Street 10",
        address="Example Street 10",
        city="Amsterdam",
        price_eur=1900,
        area_sqm=60,
        bedrooms=2,
        rooms=3,
        furnishing=FurnishingPreference.UNFURNISHED,
        rental_type=RentalType.APARTMENT,
        description="Balcony near station",
    )
    return base.model_copy(update=overrides)


def test_fingerprint_buckets_minor_price_difference() -> None:
    listing_a = make_listing()
    listing_b = make_listing(price_eur=1910, area_sqm=62)

    assert listing_fingerprint(listing_a) == listing_fingerprint(listing_b)


def test_score_listing_match_and_high_priority() -> None:
    listing = make_listing()
    filters = FilterConfig(
        cities=["amsterdam"],
        max_rent_eur=2200,
        min_sqm=50,
        furnishing=FurnishingPreference.UNFURNISHED,
        include_keywords=["balcony"],
        rental_types=[RentalType.APARTMENT],
        bedrooms_min=1,
    )
    scoring = ScoringConfig(high_priority_threshold=70.0, keyword_bonus=10.0)

    result = score_listing(listing, filters, scoring)

    assert result.is_match is True
    assert result.is_high_priority is True
    assert result.score >= 70.0


def test_score_listing_rejects_excluded_keyword() -> None:
    listing = make_listing(description="Temporary student housing")
    filters = FilterConfig(cities=["amsterdam"], exclude_keywords=["student"])
    scoring = ScoringConfig()

    result = score_listing(listing, filters, scoring)

    assert result.is_match is False
    assert result.reasons == ["excluded keyword: student"]
