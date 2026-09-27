"""Bond detection and sovereign-risk enrichment from an ISIN.

Three responsibilities, all bond-domain:
  1. classify_bond()        – decide if an ISIN is a single bond (vs equity/ETF)
                              using OpenFIGI ``marketSector`` / ``securityType2``,
                              and split Governativo vs Corporate.
  2. currency / geography   – infer the trading currency and region from the
                              issuer country (ISIN prefix).
  3. fetch_sovereign_risk() – pull the live 10Y government-bond yield from FRED
                              and turn the spread vs the German Bund into a
                              risk tier.

Free data only. FRED needs ``FRED_API_KEY`` in the environment; without it the
risk simply degrades to ``N/D`` instead of failing.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests
from pydantic import BaseModel

# ── OpenFIGI signals that mean "this is a single bond" ───────────────────────
# marketSector is the Bloomberg yellow-key: "Govt" = sovereign/agency,
# "Corp" = corporate.  securityType2 is the finer instrument class.
_BOND_MARKET_SECTORS = {"Govt", "Corp"}
_BOND_SECTYPES2 = {
    "Bond", "Note", "Bill", "Domestic MTN", "Medium Term Note",
    "Euro Medium Term Note", "Global", "Sovereign", "Agency",
}

# ── Issuer country (ISIN prefix) → trading/redemption currency ────────────────
# For sovereign govies the currency is the issuer's own currency in the vast
# majority of cases.  Eurozone members all map to EUR.  (Eurobonds with prefix
# "XS"/"EU" have no inferable country and are left blank for manual input.)
SOVEREIGN_CURRENCY: dict[str, str] = {
    "IT": "EUR", "DE": "EUR", "FR": "EUR", "ES": "EUR", "PT": "EUR",
    "NL": "EUR", "BE": "EUR", "AT": "EUR", "IE": "EUR", "FI": "EUR",
    "GR": "EUR", "SK": "EUR", "SI": "EUR", "LT": "EUR", "LV": "EUR",
    "EE": "EUR", "LU": "EUR", "CY": "EUR", "MT": "EUR", "HR": "EUR",
    "US": "USD", "GB": "GBP", "JP": "JPY", "CH": "CHF", "CA": "CAD",
    "AU": "AUD", "NZ": "NZD", "SE": "SEK", "NO": "NOK", "DK": "DKK",
    "PL": "PLN", "CZ": "CZK", "HU": "HUF", "RO": "RON", "BG": "BGN",
    "MX": "MXN", "BR": "BRL", "ZA": "ZAR", "IN": "INR", "CN": "CNY",
    "TR": "TRY", "KR": "KRW", "SG": "SGD", "HK": "HKD",
}
_EUROZONE = {c for c, cur in SOVEREIGN_CURRENCY.items() if cur == "EUR"}

# ── Issuer country → portfolio geography bucket (matches the app's buckets) ───
_REGION_NORD_AMERICA = {"US", "CA"}
_REGION_EUROPA = _EUROZONE | {"GB", "CH", "SE", "NO", "DK", "PL", "CZ", "HU", "RO", "BG"}
_REGION_ASIA_PACIFICO = {"JP", "AU", "NZ", "KR", "SG", "HK", "CN"}
_REGION_EMERGENTI = {"MX", "BR", "ZA", "IN", "TR"}


def sovereign_geography(iso2: str) -> dict[str, float]:
    """Return a 100% single-region geography for a sovereign issuer."""
    if iso2 in _REGION_NORD_AMERICA:
        return {"Nord America": 100}
    if iso2 in _REGION_ASIA_PACIFICO:
        return {"Asia-Pacifico": 100}
    if iso2 in _REGION_EMERGENTI:
        return {"Mercati Emergenti": 100}
    if iso2 in _REGION_EUROPA:
        return {"Europa": 100}
    return {"Globale": 100}


# ── FRED 10Y government-bond-yield series (OECD MEI, "Main incl. benchmark") ──
# Keyed by ISIN country prefix.  Series IDs follow IRLTLT01<cc>M156N; verify
# against FRED if a country returns N/D (a wrong id degrades to N/D, never crashes).
FRED_YIELD_SERIES: dict[str, str] = {
    "US": "IRLTLT01USM156N", "DE": "IRLTLT01DEM156N", "IT": "IRLTLT01ITM156N",
    "FR": "IRLTLT01FRM156N", "ES": "IRLTLT01ESM156N", "GB": "IRLTLT01GBM156N",
    "JP": "IRLTLT01JPM156N", "CA": "IRLTLT01CAM156N", "AU": "IRLTLT01AUM156N",
    "CH": "IRLTLT01CHM156N", "NL": "IRLTLT01NLM156N", "BE": "IRLTLT01BEM156N",
    "AT": "IRLTLT01ATM156N", "PT": "IRLTLT01PTM156N", "IE": "IRLTLT01IEM156N",
    "FI": "IRLTLT01FIM156N", "SE": "IRLTLT01SEM156N", "NO": "IRLTLT01NOM156N",
    "DK": "IRLTLT01DKM156N", "PL": "IRLTLT01PLM156N", "CZ": "IRLTLT01CZM156N",
    "HU": "IRLTLT01HUM156N", "GR": "IRLTLT01GRM156N", "NZ": "IRLTLT01NZM156N",
    "KR": "IRLTLT01KRM156N",
}
_BUND_COUNTRY = "DE"

_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_CACHE_TTL = 6 * 3600  # yields move daily; 6h cache is plenty within a warm process
_yield_cache: dict[str, tuple[float, float, str]] = {}  # iso2 -> (yield, fetched_at, as_of)


# ── Pydantic contracts at the module boundary ────────────────────────────────

class BondInfo(BaseModel):
    is_bond: bool = False
    bond_type: str = ""          # "Governativo" | "Corporate" | "Obbligazione"
    issuer_country: str = ""     # ISO-2 from the ISIN prefix ("" if supranational)
    currency: str = ""           # inferred trading currency ("" if unknown)
    geography: dict[str, float] = {}
    market_sector: str = ""      # raw OpenFIGI marketSector (debug/traceability)
    security_type2: str = ""     # raw OpenFIGI securityType2


class SovereignRisk(BaseModel):
    country: str
    yield_10y: Optional[float] = None       # latest 10Y yield, %
    bund_spread_bps: Optional[float] = None  # spread vs German 10Y, basis points
    risk_tier: str = "N/D"                    # Molto basso | Basso | Medio | Alto | Molto alto | N/D
    as_of: Optional[str] = None               # observation date (FRED)
    source: str = "FRED"
    note: str = ""


# ── Classification ───────────────────────────────────────────────────────────

def classify_bond(items: list[dict], isin: str) -> BondInfo:
    """Classify OpenFIGI mapping ``items`` for ``isin`` as a bond or not.

    Scans every candidate (not just the "best" one) because the ticker-resolution
    path is equity-biased and may not surface the Govt/Corp candidate.
    """
    if not items:
        return BondInfo()

    sectors = {x.get("marketSector") or "" for x in items}
    types2 = {x.get("securityType2") or "" for x in items}

    is_bond = bool(sectors & _BOND_MARKET_SECTORS) or bool(types2 & _BOND_SECTYPES2)
    if not is_bond:
        return BondInfo()

    if "Govt" in sectors:
        bond_type = "Governativo"
    elif "Corp" in sectors:
        bond_type = "Corporate"
    else:
        bond_type = "Obbligazione"

    iso2 = isin[:2] if len(isin) >= 2 else ""
    # Supranational/Eurobond prefixes carry no country → no currency inference.
    has_country = iso2 in SOVEREIGN_CURRENCY
    currency = SOVEREIGN_CURRENCY.get(iso2, "")
    geography = sovereign_geography(iso2) if has_country else {"Globale": 100}

    market_sector = next((s for s in ("Govt", "Corp") if s in sectors), "")
    security_type2 = next((t for t in types2 if t in _BOND_SECTYPES2), "")

    return BondInfo(
        is_bond=True,
        bond_type=bond_type,
        issuer_country=iso2 if has_country else "",
        currency=currency,
        geography=geography,
        market_sector=market_sector,
        security_type2=security_type2,
    )


# ── Sovereign risk via FRED ──────────────────────────────────────────────────

def _fetch_latest_yield(iso2: str) -> tuple[Optional[float], Optional[str]]:
    """Latest non-missing 10Y yield (%) and its observation date for ``iso2``."""
    cached = _yield_cache.get(iso2)
    if cached and (time.time() - cached[1]) < _CACHE_TTL:
        return cached[0], cached[2]

    series_id = FRED_YIELD_SERIES.get(iso2)
    api_key = os.getenv("FRED_API_KEY")
    if not series_id or not api_key:
        return None, None

    try:
        resp = requests.get(
            _FRED_URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 6,
            },
            timeout=8,
        )
        if resp.status_code != 200:
            return None, None
        for obs in resp.json().get("observations", []):
            value = obs.get("value", ".")
            if value not in (".", "", None):
                y = float(value)
                date = obs.get("date", "")
                _yield_cache[iso2] = (y, time.time(), date)
                return y, date
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None, None


def _tier_from_spread(bps: float) -> str:
    if bps < 50:
        return "Molto basso"
    if bps < 150:
        return "Basso"
    if bps < 300:
        return "Medio"
    if bps < 500:
        return "Alto"
    return "Molto alto"


def _tier_from_yield(y: float) -> str:
    if y < 2:
        return "Molto basso"
    if y < 3.5:
        return "Basso"
    if y < 5:
        return "Medio"
    if y < 8:
        return "Alto"
    return "Molto alto"


def fetch_sovereign_risk(iso2: str, currency: str = "") -> SovereignRisk:
    """Live sovereign risk for an issuer country, from FRED 10Y yields.

    For eurozone issuers the spread vs the German Bund is a clean same-currency
    credit measure → tier from spread.  For non-euro issuers the yield also
    embeds local rates/inflation, so the tier falls back to the absolute yield
    and a caveat is attached.
    """
    iso2 = (iso2 or "").upper()
    y, as_of = _fetch_latest_yield(iso2)
    if y is None:
        return SovereignRisk(
            country=iso2,
            risk_tier="N/D",
            note="Rendimento non disponibile su FRED per questo paese (o FRED_API_KEY assente).",
        )

    is_eur = currency == "EUR" or iso2 in _EUROZONE
    bund, _ = _fetch_latest_yield(_BUND_COUNTRY)
    spread_bps = round((y - bund) * 100, 1) if bund is not None else None

    if is_eur and spread_bps is not None:
        tier = _tier_from_spread(spread_bps)
        note = "Tier da spread vs Bund tedesco (stesso conio = rischio di credito)."
    else:
        tier = _tier_from_yield(y)
        note = (
            "Tier dal rendimento assoluto: valuta diversa dall'EUR, "
            "il rendimento riflette anche tassi/inflazione locali."
        )

    return SovereignRisk(
        country=iso2,
        yield_10y=round(y, 2),
        bund_spread_bps=spread_bps,
        risk_tier=tier,
        as_of=as_of,
        note=note,
    )
