"""main.py helpers: OpenFIGI resolution, justETF TER scraping, classification."""

import pytest
import requests
from fakes import FakeFundsData, FakeResponse, FakeTicker, fixture_bytes

from backend import main

# ─── OpenFIGI ─────────────────────────────────────────────────────────────────


def test_openfigi_when_mapping_found_then_rows(monkeypatch):
    sent = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        sent.update(url=url, json=json)
        return FakeResponse(json_data=[{"data": [{"ticker": "EUNL", "exchCode": "GR"}]}])

    monkeypatch.setattr(main.requests, "post", fake_post)
    assert main.openfigi_items("IE00B4L5Y983") == [{"ticker": "EUNL", "exchCode": "GR"}]
    assert sent["json"] == [{"idType": "ID_ISIN", "idValue": "IE00B4L5Y983"}]


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status_code=429),
        FakeResponse(json_data=[{"warning": "No identifier found."}]),
        FakeResponse(json_data=[]),
    ],
)
def test_openfigi_when_miss_or_rate_limited_then_empty(monkeypatch, response):
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: response)
    assert main.openfigi_items("XX0000000000") == []


def test_openfigi_when_network_error_then_empty(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(main.requests, "post", boom)
    assert main.openfigi_items("IE00B4L5Y983") == []


def test_isin_to_ticker_when_ucits_etf_then_prefers_eur_exchange_fund_listing():
    items = [
        {"ticker": "SWDA", "exchCode": "LN", "securityType": "ETP"},
        {"ticker": "EUNL", "exchCode": "GR", "securityType": "ETP"},
        {"ticker": "SWDA", "exchCode": "MI", "securityType": "ETP"},
        {"ticker": "XXX", "exchCode": "GR", "securityType": "Common Stock"},
    ]
    assert main.isin_to_ticker("IE00B4L5Y983", items)["exchCode"] == "GR"


def test_isin_to_ticker_when_us_stock_then_first_preferred_exchange():
    items = [{"ticker": "AAPL", "exchCode": "XY"}, {"ticker": "AAPL", "exchCode": "US", "name": "APPLE INC"}]
    res = main.isin_to_ticker("US0378331005", items)
    assert (res["ticker"], res["exchCode"], res["name"]) == ("AAPL", "US", "APPLE INC")


def test_isin_to_ticker_when_no_items_then_empty(monkeypatch):
    monkeypatch.setattr(main, "openfigi_items", lambda isin: [])
    assert main.isin_to_ticker("US0378331005") == {}


@pytest.mark.parametrize(
    "ticker,exch,expected",
    [
        ("SWDA", "LN", "SWDA.L"),
        ("EUNL", "GR", "EUNL.DE"),
        ("SWDA", "IM", "SWDA.MI"),
        ("IWDA", "NA", "IWDA.AS"),
        ("AAPL", "US", "AAPL"),
    ],
)
def test_build_yf_ticker_when_exchange_code_then_yahoo_suffix(ticker, exch, expected):
    assert main.build_yf_ticker(ticker, exch) == expected


# ─── Classification ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,sec,expected",
    [
        ("iShares Core MSCI World UCITS ETF", "", "ETF"),
        ("Bitcoin", "", "Criptovalute"),
        ("Some Fund", "Open-End Fund", "ETF"),
        ("Apple Inc", "Common Stock", "Azioni"),
    ],
)
def test_guess_category_when_name_or_type_then_category(name, sec, expected):
    assert main.guess_category_from_name(name, sec) == expected


@pytest.mark.parametrize(
    "info,name,expected",
    [
        ({"category": "EUR Government Bond"}, "X", "ETF Obbligazionario"),
        ({}, "iShares Euro Aggregate Bond", "ETF Obbligazionario"),
        ({"category": "Global Large-Cap Blend Equity"}, "iShares Core MSCI World", "ETF Azionario"),
    ],
)
def test_classify_etf_type_when_bond_keywords_then_bond_etf(info, name, expected):
    assert main.classify_etf_type(info, name) == expected


@pytest.mark.parametrize(
    "info,region",
    [
        ({"category": "Global Large-Cap Blend Equity"}, "Nord America"),
        ({"category": "Europe Large-Cap"}, "Europa"),
        ({"category": "US Large-Cap Blend Equity, S&P 500"}, "Nord America"),
        ({"country": "Japan"}, "Asia-Pacifico"),
        ({}, "Globale"),
    ],
)
def test_etf_geography_when_category_or_country_then_top_region(info, region):
    geo = main.get_etf_geography(info)
    assert max(geo, key=geo.get) == region
    assert sum(geo.values()) == 100


# ─── TER (Yahoo + justETF scraping) ───────────────────────────────────────────


@pytest.mark.parametrize(
    "info,expected",
    [
        ({"netExpenseRatio": 0.002}, 0.2),  # Yahoo decimal → percent
        ({"totalExpenseRatio": 0.0035}, 0.35),
        ({"annualReportExpenseRatio": 0.07}, None),  # 7 % → rejected as bogus
        ({}, None),
    ],
)
def test_ter_from_info_when_decimals_then_percent_within_sanity(info, expected):
    assert main._ter_from_info(info) == expected


def test_ter_from_info_when_already_percent_then_kept():
    assert main._ter_from_info({"netExpenseRatio": 1.5}) == 1.5
    assert main._ter_from_info({"netExpenseRatio": 7}) is None


def test_justetf_when_real_profile_page_then_ter_parsed(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        return FakeResponse(fixture_bytes("justetf_profile_IE00B4L5Y983.html"))

    monkeypatch.setattr(main.requests, "get", fake_get)
    assert main._fetch_ter_justetf("IE00B4L5Y983") == 0.2
    assert "isin=IE00B4L5Y983" in seen["url"]


def test_justetf_when_comma_decimal_then_parsed(monkeypatch):
    html = "<td>Total expense ratio</td><td>0,07%</td>"
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: FakeResponse(html))
    assert main._fetch_ter_justetf("IE00B4L5Y983") == 0.07


@pytest.mark.parametrize("html", ["<p>Performance 12.5% p.a.</p>", "Total expense ratio 9.50%"])
def test_justetf_when_no_ter_or_absurd_value_then_none(monkeypatch, html):
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: FakeResponse(html))
    assert main._fetch_ter_justetf("IE00B4L5Y983") is None


def test_justetf_when_bad_isin_or_http_error_then_none(monkeypatch):
    assert main._fetch_ter_justetf("SHORT") is None
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: FakeResponse(status_code=403))
    assert main._fetch_ter_justetf("IE00B4L5Y983") is None


def test_fetch_ter_full_when_yahoo_missing_then_justetf_fallback(monkeypatch):
    monkeypatch.setattr(main, "_fetch_ter_yf", lambda t: None)
    monkeypatch.setattr(main, "_fetch_ter_justetf", lambda isin: 0.12)
    assert main._fetch_ter_full("SWRD.L", "IE00BFY0GT14") == 0.12
    assert main._fetch_ter_full("SWRD.L", "") is None


def test_fetch_ter_yf_when_only_fund_overview_then_used(monkeypatch):
    t = FakeTicker(info={}, funds_data=FakeFundsData(fund_overview={"expenseRatio": 0.0022}))
    monkeypatch.setattr(main.yf, "Ticker", lambda s: t)
    assert main._fetch_ter_yf("X") == 0.22
