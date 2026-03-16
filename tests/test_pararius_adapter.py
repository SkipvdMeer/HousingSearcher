from local_housing_searcher.adapters.base import AdapterContext
from local_housing_searcher.adapters.pararius import ParariusAdapter
from local_housing_searcher.config import SourceConfig
from local_housing_searcher.models import FurnishingPreference, RentalType


HTML = """
<div class="listing-search-item">
  <h3 class="listing-search-item__title">
    <a class="listing-search-item__link listing-search-item__link--title"
       href="/apartment-for-rent/amsterdam/f39e2a2e/jan-van-zutphenstraat">
       Flat Jan van Zutphenstraat 115
    </a>
  </h3>
  <div class="listing-search-item__sub-title">1069 RR Amsterdam (Osdorp-Midden)</div>
  <div class="listing-search-item__price">€2,250 per month</div>
  <ul class="listing-search-item__features">
    <li class="illustrated-features__item">72 m²</li>
    <li class="illustrated-features__item">3 rooms</li>
    <li class="illustrated-features__item">Furnished</li>
  </ul>
</div>
"""


def test_pararius_parser_extracts_listing() -> None:
    adapter = ParariusAdapter(
        AdapterContext(source=SourceConfig(id="pararius-amsterdam", adapter="pararius", search_url="https://www.pararius.com/apartments/amsterdam"))
    )

    listings = adapter._parse_search_results(HTML, max_listings=10)

    assert len(listings) == 1
    listing = listings[0]
    assert listing.external_id == "f39e2a2e"
    assert listing.city == "Amsterdam"
    assert listing.price_eur == 2250
    assert listing.area_sqm == 72
    assert listing.furnishing == FurnishingPreference.FURNISHED
    assert listing.rental_type == RentalType.APARTMENT
