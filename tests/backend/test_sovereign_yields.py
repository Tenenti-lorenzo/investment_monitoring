"""Sovereign yields: parsing of a real captured CNBC response, fallback, spreads, cache."""

import json

import pytest
import requests
from fakes import FakeResponse, fixture_bytes

from backend import sovereign_yields as sy

CNBC_JSON = json.loads(fixture_bytes("cnbc_sovereign_yields.json"))  # US, DE, IT, PL × 10/20/30Y


@pytest.fixture
def cnbc(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Serve the captured CNBC payload; record every requested URL."""
    calls: list[str] = []

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        calls.append(url)
        return FakeResponse(json_data=CNBC_JSON)

    monkeypatch.setattr(sy.requests, "get", fake_get)
    monkeypatch.setattr(sy, "fetch_latest_10y_yield", lambda iso2: (None, None))
    return calls


def by_iso(resp: sy.SovereignYieldsResponse) -> dict[str, sy.CountryYields]:
    return {c.iso2: c for c in resp.countries}


@pytest.mark.parametrize(
    "iso2,tenor,expected",
    [("US", 10, "US10Y"), ("IT", 30, "IT30Y-IT"), ("DE", 20, "DE20Y-DE")],
)
def test_cnbc_symbol_when_country_and_tenor_then_cnbc_ticker(iso2, tenor, expected):
    assert sy.cnbc_symbol(iso2, tenor) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("4.12%", 4.12), ("+0.045", 0.045), ("-0.0026", -0.0026), ("UNCH", 0.0), ("", None), (None, None)],
)
def test_pct_when_cnbc_formats_then_float(raw, expected):
    assert sy._pct(raw) == expected


def test_fetch_when_cnbc_payload_then_all_tenors_parsed(cnbc):
    rows = by_iso(sy.fetch_sovereign_yields())
    assert set(rows) == {"US", "DE", "IT"}  # PL has no CNBC quote and no FRED fallback here
    it = rows["IT"]
    assert it.iso_numeric == "380" and it.name == "Italia"
    assert it.y10 and it.y20 and it.y30
    assert it.y10.source == "CNBC" and it.y10.instrument
    assert it.y10.year_low_pct <= it.y10.yield_pct <= it.y10.year_high_pct


def test_fetch_when_bund_available_then_spread_in_bps(cnbc):
    rows = by_iso(sy.fetch_sovereign_yields())
    it, de = rows["IT"].y10, rows["DE"].y10
    assert de.spread_vs_bund_bps == 0
    assert it.spread_vs_bund_bps == pytest.approx((it.yield_pct - de.yield_pct) * 100, abs=0.1)


def test_fetch_when_change_quoted_then_converted_to_bps(cnbc):
    raw = next(q for q in CNBC_JSON["FormattedQuoteResult"]["FormattedQuote"] if q["symbol"] == "US10Y")
    us = by_iso(sy.fetch_sovereign_yields())["US"].y10
    assert us.change_bps == pytest.approx(float(raw["change"]) * 100, abs=0.1)


def test_fetch_when_cnbc_misses_10y_then_fred_monthly_fallback_without_spread(cnbc, monkeypatch):
    monkeypatch.setattr(sy, "fetch_latest_10y_yield", lambda iso2: (5.1, "2026-08-01") if iso2 == "PL" else (None, None))
    pl = by_iso(sy.fetch_sovereign_yields())["PL"]
    assert pl.y10.yield_pct == 5.1 and pl.y10.source == "FRED (mensile)"
    assert pl.y10.spread_vs_bund_bps is None  # monthly vs live is not comparable
    assert pl.y20 is None and pl.y30 is None


def test_fetch_when_called_twice_then_cached(cnbc):
    sy.fetch_sovereign_yields()
    sy.fetch_sovereign_yields()
    assert len(cnbc) == 1


def test_fetch_when_cnbc_down_then_note_and_not_cached(monkeypatch):
    calls: list[str] = []

    def boom(url: str, **kwargs: object) -> FakeResponse:
        calls.append(url)
        raise requests.ConnectionError("down")

    monkeypatch.setattr(sy.requests, "get", boom)
    monkeypatch.setattr(sy, "fetch_latest_10y_yield", lambda iso2: (None, None))
    resp = sy.fetch_sovereign_yields()
    assert resp.countries == [] and resp.note
    sy.fetch_sovereign_yields()
    assert len(calls) == 2


@pytest.mark.live
def test_live_cnbc_when_fetched_then_major_countries_quoted():
    rows = by_iso(sy.fetch_sovereign_yields())
    for iso2 in ("US", "DE", "IT", "JP"):
        assert rows[iso2].y10 is not None and rows[iso2].y30 is not None
