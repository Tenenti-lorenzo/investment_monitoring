"""Bond classification (OpenFIGI) and sovereign risk (FRED)."""

import pytest
import requests
from fakes import FakeResponse

from backend import bonds

# ─── classify_bond ────────────────────────────────────────────────────────────


def test_classify_when_govt_italian_isin_then_governativo_eur_europe():
    info = bonds.classify_bond(
        [{"marketSector": "Equity"}, {"marketSector": "Govt", "securityType2": "Bond"}], "IT0005436693"
    )
    assert info.is_bond and info.bond_type == "Governativo"
    assert (info.issuer_country, info.currency) == ("IT", "EUR")
    assert info.geography == {"Europa": 100}
    assert (info.market_sector, info.security_type2) == ("Govt", "Bond")


def test_classify_when_us_corporate_then_corporate_usd_north_america():
    info = bonds.classify_bond([{"marketSector": "Corp", "securityType2": "Note"}], "US0378331005")
    assert info.bond_type == "Corporate" and info.currency == "USD"
    assert info.geography == {"Nord America": 100}


def test_classify_when_eurobond_prefix_then_no_country_global():
    info = bonds.classify_bond([{"marketSector": "Corp"}], "XS1234567890")
    assert info.is_bond and info.issuer_country == "" and info.currency == ""
    assert info.geography == {"Globale": 100}


def test_classify_when_only_security_type_matches_then_generic_bond():
    info = bonds.classify_bond(
        [{"marketSector": "Mtge", "securityType2": "Medium Term Note"}], "DE0001102580"
    )
    assert info.is_bond and info.bond_type == "Obbligazione"


@pytest.mark.parametrize("items", [[], [{"marketSector": "Equity", "securityType2": "Common Stock"}]])
def test_classify_when_equity_or_empty_then_not_bond(items):
    assert bonds.classify_bond(items, "US0378331005").is_bond is False


@pytest.mark.parametrize(
    "iso2,region",
    [
        ("US", "Nord America"),
        ("JP", "Asia-Pacifico"),
        ("BR", "Mercati Emergenti"),
        ("GB", "Europa"),
        ("AR", "Globale"),
    ],
)
def test_sovereign_geography_when_country_then_region(iso2, region):
    assert bonds.sovereign_geography(iso2) == {region: 100}


# ─── Tiers ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bps,tier",
    [
        (0, "Molto basso"),
        (49.9, "Molto basso"),
        (50, "Basso"),
        (149.9, "Basso"),
        (150, "Medio"),
        (300, "Alto"),
        (500, "Molto alto"),
    ],
)
def test_tier_from_spread_when_boundaries_then_bucket(bps, tier):
    assert bonds._tier_from_spread(bps) == tier


@pytest.mark.parametrize(
    "y,tier", [(1.99, "Molto basso"), (2, "Basso"), (3.5, "Medio"), (5, "Alto"), (8, "Molto alto")]
)
def test_tier_from_yield_when_boundaries_then_bucket(y, tier):
    assert bonds._tier_from_yield(y) == tier


# ─── FRED ─────────────────────────────────────────────────────────────────────

YIELDS = {"IRLTLT01ITM156N": ["3.60"], "IRLTLT01DEM156N": ["2.60"], "IRLTLT01USM156N": ["4.20"]}


@pytest.fixture
def fred(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setenv("FRED_API_KEY", "k")
    calls: list[str] = []

    def fake_get(url, params=None, timeout=None):
        sid = params["series_id"]
        calls.append(sid)
        if sid not in YIELDS:
            return FakeResponse(status_code=400)
        obs = [{"date": "2026-08-01", "value": "."}] + [
            {"date": "2026-07-01", "value": v} for v in YIELDS[sid]
        ]
        return FakeResponse(json_data={"observations": obs})

    monkeypatch.setattr(bonds.requests, "get", fake_get)
    return calls


def test_sovereign_risk_when_eurozone_then_tier_from_bund_spread(fred):
    r = bonds.fetch_sovereign_risk("it", "EUR")
    assert r.yield_10y == 3.6 and r.bund_spread_bps == 100.0
    assert r.risk_tier == "Basso" and r.as_of == "2026-07-01"  # skips missing "." value
    assert "Bund" in r.note


def test_sovereign_risk_when_non_euro_then_tier_from_absolute_yield(fred):
    r = bonds.fetch_sovereign_risk("US", "USD")
    assert r.risk_tier == "Medio" and r.bund_spread_bps == 160.0
    assert "valuta diversa" in r.note


def test_sovereign_risk_when_cached_then_fred_called_once_per_country(fred):
    bonds.fetch_sovereign_risk("IT", "EUR")
    bonds.fetch_sovereign_risk("IT", "EUR")
    assert fred.count("IRLTLT01ITM156N") == 1


def test_sovereign_risk_when_no_api_key_then_nd(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    r = bonds.fetch_sovereign_risk("IT", "EUR")
    assert r.risk_tier == "N/D" and r.yield_10y is None


def test_sovereign_risk_when_unknown_country_or_http_error_then_nd(fred, monkeypatch):
    assert bonds.fetch_sovereign_risk("AR").risk_tier == "N/D"

    def boom(*a, **k):
        raise requests.Timeout()

    monkeypatch.setattr(bonds.requests, "get", boom)
    assert bonds.fetch_sovereign_risk("FR", "EUR").risk_tier == "N/D"
