"""Borsa Italiana scraper: parsing of real captured pages + routing/caching."""

import pytest
import requests
from fakes import FakeResponse, fixture_bytes

from backend import bond_market as bm

MOT_PAGE = "borsa_mot_btp_IT0005436693.html"
TLX_PAGE = "borsa_eurotlx_US912810TD00.html"
NOT_FOUND_URL = "https://www.borsaitaliana.it/borsa/obbligazioni/ricerca-avanzata.html"


def parse(fixture: str) -> bm.BondQuote:
    parser = bm._DataTableParser()
    parser.feed(bm._decode(fixture_bytes(fixture)))
    return bm._rows_to_quote("X", parser.rows, "ROUTE", "http://x")


# ─── Value parsers ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9.020.000", 9_020_000.0),
        ("79,49422", 79.49422),
        ("-0,19", -0.19),
        ("+0,2", 0.2),
        ("0,20%", 0.2),
        ("", None),
        ("n.d.", None),
        ("-", None),
    ],
)
def test_parse_it_number_when_italian_format_then_float(raw, expected):
    assert bm._parse_it_number(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("01/09/46", "2046-09-01"),
        ("15/05/2051", "2051-05-15"),
        ("25-09-2026", "2026-09-25"),
        ("2026", None),
        ("", None),
    ],
)
def test_parse_it_date_when_formats_vary_then_iso(raw, expected):
    assert bm._parse_it_date(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("25/09/26 - 17.15.29", "2026-09-25T17:15:29"),  # MOT
        ("25-09-2026 15:43", "2026-09-25T15:43:00"),  # EuroTLX
        ("ieri", None),
    ],
)
def test_parse_it_datetime_when_mot_or_tlx_then_iso(raw, expected):
    assert bm._parse_it_datetime(raw) == expected


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Quantità Ultimo Contratto:", "quantita ultimo contratto"),
        ("  Modalità   di negoziazione ", "modalita di negoziazione"),
    ],
)
def test_norm_label_when_accents_and_spaces_then_ascii_lower(label, expected):
    assert bm._norm_label(label) == expected


def test_decode_when_cp1252_bytes_then_fallback_decoding():
    assert bm._decode("Quantità".encode("cp1252")) == "Quantità"
    assert bm._decode("Quantità".encode()) == "Quantità"


def test_parser_when_other_tables_present_then_only_m_table_clear_rows():
    html = """<table class="other"><tr><td>Nome</td><td>NO</td></tr></table>
              <table class="m-table -clear-m"><tr><td>Nome</td><td> Btp  X </td></tr>
              <tr><td>solo label</td></tr></table>"""
    p = bm._DataTableParser()
    p.feed(html)
    assert p.rows == [["Nome", "Btp X"], ["solo label"]]


# ─── Real pages ───────────────────────────────────────────────────────────────


def test_mot_page_when_parsed_then_all_market_fields_extracted():
    q = parse(MOT_PAGE)
    assert q.name == "Btp Tf 0,6% Ag31 Eur"
    assert q.market == "MOT"
    assert q.instrument_type == "Titoli di stato italiani"
    assert q.currency == "EUR"
    assert q.last_price == 85.41 and q.price == 85.41
    assert q.official_price == pytest.approx(85.45162)
    assert q.official_price_date == "2026-09-24"
    assert q.last_trade_at == "2026-09-25T17:28:47"
    assert (q.day_high, q.day_low, q.year_high, q.year_low) == (85.59, 85.35, 89.85, 85.24)
    assert q.volume == 21_793_000 and q.trades == 146 and isinstance(q.trades, int)
    assert q.maturity == "2031-08-01"
    assert q.accrual_start == "2021-02-01"
    assert q.coupon_period_pct == 0.3
    assert q.min_lot == 1000


def test_eurotlx_page_when_parsed_then_coupon_and_reference_price():
    q = parse(TLX_PAGE)
    assert q.name == "Usa Tf 2,25% Fb52 Usd"
    assert q.instrument_type == "T-Bonds"
    assert q.issuer == "United States Of America"
    assert q.currency == "USD"
    assert q.last_price is None
    assert q.price == q.reference_price == 54.81  # falls back to reference price
    assert q.coupon_annual_pct == 2.25
    assert q.coupon_frequency == "6 Mesi"
    assert q.quotation == "Corso Secco"
    assert q.maturity == "2052-02-15"
    assert q.market == "ROUTE"  # no "Mercato" row → route name


def test_price_priority_when_no_last_then_reference_then_official():
    q = bm._rows_to_quote("X", [["Nome", "B"], ["Prezzo ufficiale", "99,1"]], "MOT", "u")
    assert q.price == 99.1


# ─── Fetch: routing, misses, errors, cache ────────────────────────────────────


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Route MOT/EuroTLX URLs to fixtures; records requested URLs."""
    calls: list[str] = []
    pages: dict[tuple[str, str], FakeResponse] = {
        ("mot", "IT0005436693"): FakeResponse(fixture_bytes(MOT_PAGE), url="mot-ok"),
        ("eurotlx", "US912810TD00"): FakeResponse(fixture_bytes(TLX_PAGE), url="tlx-ok"),
    }

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        route = "mot" if "/mot/" in url else "eurotlx"
        isin = url.split("isin=")[1].split("&")[0]
        return pages.get((route, isin), FakeResponse(b"<html></html>", url=NOT_FOUND_URL))

    monkeypatch.setattr(bm.requests, "get", fake_get)
    return calls


def test_fetch_when_listed_on_mot_then_first_route_hit(http):
    q = bm.fetch_bond_quote(" it0005436693 ")
    assert q.isin == "IT0005436693" and q.market == "MOT"
    assert len(http) == 1 and "/mot/btp/" in http[0]
    assert q.source_url == http[0]


def test_fetch_when_mot_redirects_to_search_then_eurotlx_tried(http):
    q = bm.fetch_bond_quote("US912810TD00")
    assert q.market == "EuroTLX"
    assert ["/mot/" in u for u in http] == [True, False]


def test_fetch_when_unknown_isin_then_none_and_miss_cached(http):
    assert bm.fetch_bond_quote("XS0000000000") is None
    assert bm.fetch_bond_quote("XS0000000000") is None
    assert len(http) == 2  # both routes tried once; second call served from cache


def test_fetch_when_page_has_no_name_row_then_none(monkeypatch):
    monkeypatch.setattr(
        bm.requests,
        "get",
        lambda *a, **k: FakeResponse(
            b'<table class="m-table -clear-m"><tr><td>Scadenza</td><td>01/01/30</td></tr></table>', url="ok"
        ),
    )
    assert bm.fetch_bond_quote("IT0000000001") is None


def test_fetch_when_http_error_or_network_failure_then_none(monkeypatch):
    monkeypatch.setattr(bm.requests, "get", lambda *a, **k: FakeResponse(b"", status_code=503, url="x"))
    assert bm.fetch_bond_quote("IT0000000002") is None

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(bm.requests, "get", boom)
    assert bm.fetch_bond_quote("IT0000000003") is None
