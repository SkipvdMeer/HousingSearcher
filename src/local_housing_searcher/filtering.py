from __future__ import annotations

from local_housing_searcher.config import FilterConfig, ScoringConfig
from local_housing_searcher.models import FurnishingPreference, Listing, MatchResult
from local_housing_searcher.utils import normalize_text


def score_listing(listing: Listing, filters: FilterConfig, scoring: ScoringConfig) -> MatchResult:
    reasons: list[str] = []
    score = 50.0
    haystack = normalize_text(f"{listing.title} {listing.description or ''} {listing.address or ''}")

    if filters.cities:
        if normalize_text(listing.city) not in filters.cities:
            return MatchResult(listing=listing, is_match=False, score=0.0, is_high_priority=False, reasons=["city mismatch"])
        score += 10.0
        reasons.append("city matched")

    if filters.max_rent_eur is not None:
        if listing.price_eur > filters.max_rent_eur:
            return MatchResult(listing=listing, is_match=False, score=0.0, is_high_priority=False, reasons=["rent too high"])
        budget_gain = max(0.0, min(15.0, (filters.max_rent_eur - listing.price_eur) / 50))
        score += budget_gain
        reasons.append("within budget")

    if filters.min_sqm is not None:
        if listing.area_sqm is None or listing.area_sqm < filters.min_sqm:
            return MatchResult(listing=listing, is_match=False, score=0.0, is_high_priority=False, reasons=["area too small"])
        score += min(10.0, (listing.area_sqm - filters.min_sqm) / 5)
        reasons.append("meets area target")

    if filters.furnishing in {FurnishingPreference.FURNISHED, FurnishingPreference.UNFURNISHED}:
        if listing.furnishing != filters.furnishing:
            return MatchResult(
                listing=listing,
                is_match=False,
                score=0.0,
                is_high_priority=False,
                reasons=["furnishing mismatch"],
            )
        score += 5.0
        reasons.append("furnishing matched")

    if filters.rental_types:
        if listing.rental_type not in filters.rental_types:
            return MatchResult(listing=listing, is_match=False, score=0.0, is_high_priority=False, reasons=["rental type mismatch"])
        score += 5.0
        reasons.append("rental type matched")

    if filters.bedrooms_min is not None:
        if listing.bedrooms is None or listing.bedrooms < filters.bedrooms_min:
            return MatchResult(listing=listing, is_match=False, score=0.0, is_high_priority=False, reasons=["bedroom count too low"])
        score += 5.0
        reasons.append("bedroom minimum matched")

    if filters.bedrooms_max is not None and listing.bedrooms is not None:
        if listing.bedrooms > filters.bedrooms_max:
            return MatchResult(listing=listing, is_match=False, score=0.0, is_high_priority=False, reasons=["bedroom count too high"])

    for keyword in filters.exclude_keywords:
        if keyword in haystack:
            return MatchResult(listing=listing, is_match=False, score=0.0, is_high_priority=False, reasons=[f"excluded keyword: {keyword}"])

    keyword_hits = [keyword for keyword in filters.include_keywords if keyword in haystack]
    if filters.include_keywords and not keyword_hits:
        return MatchResult(listing=listing, is_match=False, score=0.0, is_high_priority=False, reasons=["missing required keywords"])
    if keyword_hits:
        reasons.append(f"keyword hits: {', '.join(keyword_hits)}")
        score += min(scoring.keyword_bonus * len(keyword_hits), 15.0)

    score = min(score, 100.0)
    return MatchResult(
        listing=listing,
        is_match=True,
        score=score,
        is_high_priority=score >= scoring.high_priority_threshold,
        reasons=reasons,
    )
