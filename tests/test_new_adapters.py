from datetime import datetime

from local_housing_searcher.adapters.directwonen import DirectWonenAdapter
from local_housing_searcher.adapters.base import AdapterContext
from local_housing_searcher.adapters.funda import FundaAdapter
from local_housing_searcher.adapters.huurwoningen import HuurwoningenAdapter
from local_housing_searcher.adapters.vbt import VbtAdapter
from local_housing_searcher.adapters.vanderlinden import VanDerLindenAdapter
from local_housing_searcher.config import FilterConfig, SourceConfig
from local_housing_searcher.models import RentalType


FUNDA_HTML = """
<article>
  <h2>
    <a href="/detail/huur/amsterdam/appartement-example/12345678/">Examplelaan 10</a>
  </h2>
  <p>Amsterdam</p>
  <p>€ 2.450 p/m</p>
  <ul>
    <li>78 m²</li>
    <li>3 kamers</li>
  </ul>
</article>
"""

FUNDA_HTML_DUPLICATE_CARD = """
<script type="application/ld+json" data-hid="result-list-metadata">
{"@context":"https://schema.org","@type":["ItemList","WebPage"],"itemListElement":[{"@type":"ListItem","position":1,"url":"https://www.funda.nl/detail/huur/amsterdam/appartement-entrepotbrug-113/43378928/"}]}
</script>
<div class="@container border-b pb-3">
  <div class="flex flex-col @lg:flex-row">
    <div class="relative overflow-hidden rounded-md @lg:flex @lg:shrink-0">
      <a class="min-w-[358px] sm:max-w-[228px] sm:min-w-[228px]" href="/detail/huur/amsterdam/appartement-entrepotbrug-113/43378928/"></a>
    </div>
    <div class="relative flex flex-col flex-1 pt-4 pl-0 @lg:pt-0 @lg:pl-4">
      <h2>
        <a data-testid="listingDetailsAddress" href="/detail/huur/amsterdam/appartement-entrepotbrug-113/43378928/">
          <div class="flex font-semibold"><span>Entrepotbrug 113</span></div>
          <div class="truncate text-neutral-80">1019 JG Amsterdam</div>
        </a>
      </h2>
      <div class="mt-2">
        <div class="flex gap-2">
          <div class="font-semibold"><div class="truncate">€ 2.300 /maand</div></div>
        </div>
        <div class="flex gap-3">
          <ul class="flex flex-wrap gap-3 gap-y-2 truncate overflow-hidden py-1">
            <li><span>107 m²</span></li>
            <li><span>3</span></li>
            <li><span>A</span></li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</div>
<script>
"2026-03-10T09:15:00+01:00",[1,2,3],"/detail/huur/amsterdam/appartement-entrepotbrug-113/43378928/"
</script>
"""

FUNDA_HTML_PAGE_1 = """
<article>
  <h2>
    <a href="/detail/huur/amsterdam/appartement-example/12345678/">Examplelaan 10</a>
  </h2>
  <p>Amsterdam</p>
  <p>€ 2.450 p/m</p>
  <ul>
    <li>78 m²</li>
    <li>3 kamers</li>
  </ul>
</article>
<nav>
  <a rel="next" href="/zoeken/huur?page=2">Volgende</a>
</nav>
"""

FUNDA_HTML_PAGE_2 = """
<article>
  <h2>
    <a href="/detail/huur/amsterdam/huis-example/87654321/">Tweede Straat 20</a>
  </h2>
  <p>Amsterdam</p>
  <p>€ 2.100 p/m</p>
  <ul>
    <li>95 m²</li>
    <li>4 kamers</li>
  </ul>
</article>
"""

FUNDA_HTML_WITH_PUBLISH_DATE = """
<article>
  <h2>
    <a href="/detail/huur/amsterdam/appartement-example/12345678/">Examplelaan 10</a>
  </h2>
  <p>Amsterdam</p>
  <p>€ 2.450 p/m</p>
  <ul>
    <li>78 m²</li>
    <li>3 kamers</li>
  </ul>
</article>
<script>
"2026-03-10T09:15:00+01:00",[1,2,3],"/detail/huur/amsterdam/appartement-example/12345678/"
</script>
"""

HUURWONINGEN_HTML = """
<article>
  <h3>
    <a href="/huren/amsterdam/abcd1234/examplelaan/">Examplelaan 20 Amsterdam</a>
  </h3>
  <p>€ 1.850 per maand</p>
  <ul>
    <li>55 m²</li>
    <li>2 kamers</li>
  </ul>
</article>
"""

VANDERLINDEN_HTML = """
<div id="zoekresultaten">
  <div class="woninginfo">
    <div class="p-2">
      <div><strong>Pigmentstraat 21</strong></div>
      <div class="text-80 mb-0"><i class="fa-solid fa-location-dot"></i> Amsterdam</div>
      <div class="mt-2">€ 1.833 per maand</div>
      <div class="text-80 mt-3 position-relative">
        <span class="me-2">14 m²</span>
        <span class="me-2">14 m²</span>
        <span class="me-2">1</span>
      </div>
      <a href="/huurwoning/Pigmentstraat-21-Amsterdam/2049/" class="blocklink blocklinkarrow"></a>
    </div>
    <div class="fotolabel">Binnenkort beschikbaar</div>
  </div>
</div>
"""

DIRECTWONEN_HTML = """
<div class="new-search-advert">
  <div class="advert-header">
    <div class="advert-location">
      <div class="advert-location-title"><span class="advert-location-header h2">Appartement</span></div>
      <div class="advert-location-price">€ 2.150</div>
    </div>
    <div class="advert-location">
      <div class="advert-location-title"><h3 class="location-text">Midscheeps, Amsterdam</h3></div>
      <div class="kale-huur">(Excl.)</div>
    </div>
  </div>
  <div class="advertise-content">
    <div class="small-banner rooms"><p class="small-banner-top">4</p></div>
    <div class="small-banner surface"><p class="small-banner-top">90</p></div>
  </div>
  <div class="advert-content-detail">
    <a href="https://directwonen.nl/huurwoningen-huren/amsterdam/midscheeps/appartement-511170">Alle kenmerken tonen</a>
    <table>
      <tr><td>Servicekosten:</td><td>€ 50</td></tr>
      <tr><td>Opleverniveau:</td><td>Gemeubileerd</td></tr>
      <tr><td>Beschikbaar per:</td><td>01-04-2026</td></tr>
    </table>
  </div>
</div>
"""

DIRECTWONEN_HTML_WITH_RECAPTCHA = """
<html>
  <head>
    <script src="https://www.google.com/recaptcha/api.js?render=example"></script>
  </head>
  <body>
    <div class="new-search-advert">
      <div class="advert-header">
        <div class="advert-location">
          <div class="advert-location-title"><span class="advert-location-header h2">Appartement</span></div>
          <div class="advert-location-price">€ 2.150</div>
        </div>
        <div class="advert-location">
          <div class="advert-location-title"><h3 class="location-text">Midscheeps, Amsterdam</h3></div>
        </div>
      </div>
      <div class="advertise-content">
        <div class="small-banner rooms"><p class="small-banner-top">4</p></div>
        <div class="small-banner surface"><p class="small-banner-top">90</p></div>
      </div>
      <div class="advert-content-detail">
        <a href="https://directwonen.nl/huurwoningen-huren/amsterdam/midscheeps/appartement-511170">Alle kenmerken tonen</a>
        <table>
          <tr><td>Beschikbaar per:</td><td>01-04-2026</td></tr>
        </table>
      </div>
    </div>
  </body>
</html>
"""

VBT_HTML = """
<div class="itemviewer houses svelte-16bhc06">
  <a class="property svelte-16bhc06" href="/woning/haarlem-amerikaweg-26">
    <div class="items">
      <div>Haarlem</div>
      <span class="normal">Amerikaweg 26</span>
      <div class="price">€ 2.180,-</div>
      <table>
        <tr><td>Soort object</td><td>Appartement</td></tr>
        <tr><td>Woonoppervlakte</td><td>112 m²</td></tr>
        <tr><td>Kamers</td><td>3 Kamers</td></tr>
        <tr><td>Beschikbaar</td><td>1 april 2026</td></tr>
      </table>
    </div>
  </a>
  <a class="property svelte-16bhc06" href="/woning/amsterdam-wittgensteinlaan-155">
    <div class="visual"><span class="status available svelte-16bhc06">Beschikbaar</span></div>
    <div class="items">
      <div>Amsterdam</div>
      <span class="normal">Wittgensteinlaan 155</span>
      <div class="price">€ 1.799,-</div>
      <table>
        <tr><td>Soort object</td><td>Appartement</td></tr>
        <tr><td>Woonoppervlakte</td><td>92 m²</td></tr>
        <tr><td>Kamers</td><td>3 Kamers</td></tr>
        <tr><td>Servicekosten</td><td>€ 50,- per maand</td></tr>
        <tr><td>Huurtermijn (min.)</td><td>12 Maanden</td></tr>
        <tr><td>Beschikbaar</td><td>10 april 2026</td></tr>
        <tr><td>Aantal reacties</td><td>5</td></tr>
      </table>
    </div>
  </a>
</div>
"""


def test_funda_parser_extracts_listing() -> None:
    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url="https://www.funda.nl/huur/amsterdam/",
            )
        )
    )

    listings = adapter._parse_search_results(FUNDA_HTML, max_listings=10)

    assert len(listings) == 1
    listing = listings[0]
    assert listing.city == "Amsterdam"
    assert listing.price_eur == 2450
    assert listing.area_sqm == 78
    assert listing.rooms == 3
    assert listing.rental_type == RentalType.APARTMENT


def test_funda_parser_deduplicates_card_anchors_and_extracts_structured_card() -> None:
    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url="https://www.funda.nl/zoeken/huur",
            )
        )
    )

    listings = adapter._parse_search_results(FUNDA_HTML_DUPLICATE_CARD, max_listings=10)

    assert len(listings) == 1
    listing = listings[0]
    assert listing.title == "Entrepotbrug 113 1019 JG Amsterdam"
    assert listing.address == "Entrepotbrug 113"
    assert listing.postcode == "1019JG"
    assert listing.city == "Amsterdam"
    assert listing.price_eur == 2300
    assert listing.area_sqm == 107
    assert listing.rooms == 3
    assert listing.raw["publish_date"] == "2026-03-10T09:15:00+01:00"


def test_funda_resolve_search_url_builds_dynamic_query_from_filters() -> None:
    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url=(
                    "https://www.funda.nl/zoeken/huur?availability=[%22available%22]"
                    "&rental_agreement=[%22indefinite_duration%22]"
                ),
            ),
            filters=FilterConfig(
                cities=["Amsterdam"],
                max_rent_eur=2500,
                min_sqm=60,
                rental_types=[RentalType.APARTMENT, RentalType.HOUSE],
            ),
        )
    )

    search_url = adapter._resolve_search_url()

    assert search_url is not None
    assert search_url.startswith("https://www.funda.nl/zoeken/huur?")
    assert "selected_area=%5B%22amsterdam%22%5D" in search_url
    assert "price=%220-2500%22" in search_url
    assert "floor_area=%2260-%22" in search_url
    assert "object_type=%5B%22apartment%22%2C%22house%22%5D" in search_url
    assert "availability=%5B%22available%22%5D" in search_url
    assert "rental_agreement=%5B%22indefinite_duration%22%5D" in search_url
    assert "sort=%22date_down%22" in search_url


def test_funda_resolve_search_url_uses_default_search_path_without_source_query() -> None:
    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url="https://www.funda.nl/zoeken/huur",
            ),
            filters=FilterConfig(
                cities=["Amsterdam"],
                max_rent_eur=2500,
                min_sqm=60,
                rental_types=[RentalType.APARTMENT, RentalType.HOUSE],
            ),
        )
    )

    search_url = adapter._resolve_search_url()

    assert search_url is not None
    assert search_url.startswith("https://www.funda.nl/zoeken/huur?")
    assert "selected_area=%5B%22amsterdam%22%5D" in search_url
    assert "price=%220-2500%22" in search_url
    assert "sort=%22date_down%22" in search_url


def test_funda_parser_extracts_publish_date_from_embedded_state() -> None:
    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url="https://www.funda.nl/zoeken/huur",
            )
        )
    )

    listings = adapter._parse_search_results(FUNDA_HTML_WITH_PUBLISH_DATE, max_listings=10)

    assert len(listings) == 1
    assert listings[0].raw["publish_date"] == "2026-03-10T09:15:00+01:00"


def test_funda_fetch_paginates_via_next_link(monkeypatch) -> None:
    search_url = (
        "https://www.funda.nl/zoeken/huur?selected_area=[%22amsterdam%22]"
        "&price=%220-2500%22&object_type=[%22apartment%22,%22house%22]"
        "&availability=[%22available%22]&floor_area=%2260-%22"
        "&rental_agreement=[%22indefinite_duration%22]"
    )
    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url=search_url,
                max_listings=10,
            )
        )
    )

    pages = {
        search_url: FUNDA_HTML_PAGE_1,
        (
            "https://www.funda.nl/zoeken/huur?selected_area=%5B%22amsterdam%22%5D"
            "&price=%220-2500%22&object_type=%5B%22apartment%22%2C%22house%22%5D"
            "&availability=%5B%22available%22%5D&floor_area=%2260-%22"
            "&rental_agreement=%5B%22indefinite_duration%22%5D&search_result=2"
        ): FUNDA_HTML_PAGE_2,
    }

    def fake_fetch_page(url, timeout_seconds, *, headless, wait_until, extra_wait_ms):
        html = pages[url]
        return type(
            "FakePageResult",
            (),
            {
                "requested_url": url,
                "final_url": url,
                "title": "Zoekresultaten huur",
                "status_code": 200,
                "html": html,
            },
        )()

    monkeypatch.setattr(adapter, "fetch_page", fake_fetch_page)

    result = adapter.fetch()

    assert result.health.ok is True
    assert len(result.listings) == 2
    assert result.health.details["pages_fetched"] == 2
    assert result.health.details["pages_with_new_results"] == 2
    assert result.listings[0].external_id == "12345678"
    assert result.listings[1].external_id == "87654321"


def test_funda_next_page_falls_back_to_page_query_param() -> None:
    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url=(
                    "https://www.funda.nl/zoeken/huur?selected_area=[%22amsterdam%22]"
                    "&price=%220-2500%22&object_type=[%22apartment%22,%22house%22]"
                    "&availability=[%22available%22]&floor_area=%2260-%22"
                    "&rental_agreement=[%22indefinite_duration%22]"
                ),
            )
        )
    )

    next_url = adapter._extract_next_page_url("<html></html>", adapter.context.source.search_url)

    assert next_url is not None
    assert "search_result=2" in next_url
    assert "selected_area=%5B%22amsterdam%22%5D" in next_url


def test_funda_next_page_keeps_search_path_when_link_points_to_root() -> None:
    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url=(
                    "https://www.funda.nl/zoeken/huur?selected_area=[%22amsterdam%22]"
                    "&price=%220-2500%22&object_type=[%22apartment%22,%22house%22]"
                    "&availability=[%22available%22]&floor_area=%2260-%22"
                    "&rental_agreement=[%22indefinite_duration%22]"
                ),
            )
        )
    )

    next_url = adapter._extract_next_page_url(
        '<nav><a rel="next" href="/?page=2">Volgende</a></nav>',
        adapter.context.source.search_url,
    )

    assert next_url is not None
    assert next_url.startswith("https://www.funda.nl/zoeken/huur?")
    assert "search_result=2" in next_url
    assert "selected_area=%5B%22amsterdam%22%5D" in next_url


def test_funda_should_stop_pagination_at_seen_publish_date_boundary() -> None:
    class FakeDatabase:
        def find_existing_listing_id(self, listing):
            return 1

    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url="https://www.funda.nl/zoeken/huur",
            ),
            database=FakeDatabase(),
        )
    )
    listings = adapter._parse_search_results(FUNDA_HTML_WITH_PUBLISH_DATE, max_listings=10)

    assert adapter._should_stop_pagination(listings, adapter._publish_date_for_listing(listings[0])) is True


def test_funda_should_not_stop_pagination_when_page_contains_newer_listing() -> None:
    class FakeDatabase:
        def find_existing_listing_id(self, listing):
            return 1

    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url="https://www.funda.nl/zoeken/huur",
            ),
            database=FakeDatabase(),
        )
    )
    listings = adapter._parse_search_results(FUNDA_HTML_WITH_PUBLISH_DATE, max_listings=10)

    assert adapter._should_stop_pagination(listings, datetime.fromisoformat("2026-03-09T09:15:00+01:00")) is False


def test_huurwoningen_parser_extracts_listing() -> None:
    adapter = HuurwoningenAdapter(
        AdapterContext(
            source=SourceConfig(
                id="huurwoningen-amsterdam",
                adapter="huurwoningen",
                search_url="https://www.huurwoningen.nl/in/amsterdam/",
            )
        )
    )

    listings = adapter._parse_search_results(HUURWONINGEN_HTML, max_listings=10)

    assert len(listings) == 1
    listing = listings[0]
    assert listing.city == "Amsterdam"
    assert listing.price_eur == 1850
    assert listing.area_sqm == 55
    assert listing.rooms == 2


def test_vanderlinden_parser_extracts_listing() -> None:
    adapter = VanDerLindenAdapter(
        AdapterContext(
            source=SourceConfig(
                id="vanderlinden-rentals",
                adapter="vanderlinden",
                search_url="https://www.vanderlinden.nl/woning-huren/",
            )
        )
    )

    listings = adapter._parse_search_results(VANDERLINDEN_HTML, max_listings=10)

    assert len(listings) == 1
    listing = listings[0]
    assert listing.external_id == "2049"
    assert listing.city == "Amsterdam"
    assert listing.price_eur == 1833
    assert listing.area_sqm == 14
    assert listing.bedrooms == 1


def test_directwonen_parser_extracts_listing() -> None:
    adapter = DirectWonenAdapter(
        AdapterContext(
            source=SourceConfig(
                id="directwonen-amsterdam",
                adapter="directwonen",
                search_url="https://www.directwonen.nl/huurwoningen-huren/amsterdam",
            )
        )
    )

    listings = adapter._parse_search_results(DIRECTWONEN_HTML, max_listings=10)

    assert len(listings) == 1
    listing = listings[0]
    assert listing.external_id == "511170"
    assert listing.city == "Amsterdam"
    assert listing.price_eur == 2150
    assert listing.area_sqm == 90
    assert listing.rooms == 4
    assert listing.bedrooms == 3
    assert listing.available_from == "01-04-2026"
    assert listing.rental_type == RentalType.APARTMENT


def test_directwonen_fetch_ignores_recaptcha_script_when_listings_exist(monkeypatch) -> None:
    adapter = DirectWonenAdapter(
        AdapterContext(
            source=SourceConfig(
                id="directwonen-amsterdam",
                adapter="directwonen",
                search_url="https://www.directwonen.nl/huurwoningen-huren/amsterdam",
            )
        )
    )

    monkeypatch.setattr(
        adapter,
        "fetch_page",
        lambda url, timeout_seconds, *, headless, wait_until, extra_wait_ms: type(
            "FakePageResult",
            (),
            {
                "requested_url": url,
                "final_url": url,
                "title": "Huurwoningen Amsterdam | Vrije sector huur Amsterdam | Direct Wonen",
                "status_code": 200,
                "html": DIRECTWONEN_HTML_WITH_RECAPTCHA,
            },
        )(),
    )

    result = adapter.fetch()

    assert result.health.ok is True
    assert len(result.listings) == 1
    assert result.listings[0].external_id == "511170"


def test_vbt_parser_filters_to_amsterdam_and_extracts_listing() -> None:
    adapter = VbtAdapter(
        AdapterContext(
            source=SourceConfig(
                id="vbt-amsterdam",
                adapter="vbt",
                search_url="https://vbtverhuurmakelaars.nl/woningen",
                city="Amsterdam",
            )
        )
    )

    listings = adapter._parse_search_results(VBT_HTML, max_listings=10)

    assert len(listings) == 1
    listing = listings[0]
    assert listing.external_id == "amsterdam-wittgensteinlaan-155"
    assert listing.city == "Amsterdam"
    assert listing.price_eur == 1799
    assert listing.area_sqm == 92
    assert listing.rooms == 3
    assert listing.bedrooms == 2
    assert listing.available_from == "10 april 2026"
    assert listing.rental_type == RentalType.APARTMENT


def test_funda_fetch_reports_access_block(monkeypatch) -> None:
    adapter = FundaAdapter(
        AdapterContext(
            source=SourceConfig(
                id="funda-amsterdam",
                adapter="funda",
                search_url="https://www.funda.nl/huur/amsterdam/",
            )
        )
    )
    monkeypatch.setattr(
        adapter,
        "get_page_html",
        lambda url, timeout: "<html><title>Je bent bijna op de pagina die je zoekt [funda]</title></html>",
    )

    result = adapter.fetch()

    assert result.health.ok is False
    assert "verification" in result.health.message


def test_huurwoningen_fetch_reports_access_block(monkeypatch) -> None:
    adapter = HuurwoningenAdapter(
        AdapterContext(
            source=SourceConfig(
                id="huurwoningen-amsterdam",
                adapter="huurwoningen",
                search_url="https://www.huurwoningen.nl/in/amsterdam/",
            )
        )
    )
    monkeypatch.setattr(
        adapter,
        "get_page_html",
        lambda url, timeout: "<html><title>Just a moment...</title></html>",
    )

    result = adapter.fetch()

    assert result.health.ok is False
    assert "challenge" in result.health.message
