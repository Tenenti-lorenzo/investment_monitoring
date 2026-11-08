"""Government-bond yields by country and maturity (10/20/30Y) for the world map.

Source: CNBC's public quote service (the same JSON the cnbc.com quote pages
use).  One batched request returns every country × maturity with the live
yield, the daily change, the previous close and the 52-week range.  CNBC
symbols are ``US10Y`` for the US and ``<CC><N>Y-<CC>`` for everyone else.

Coverage is uneven: ~35 countries at 10Y, ~12 at 20Y/30Y.  For the few
countries CNBC does not quote at 10Y the OECD monthly series on FRED is used
as a fallback (see :func:`backend.bonds.fetch_latest_10y_yield`), flagged as
monthly so it is never mistaken for a live quote.
"""
from __future__ import annotations

import logging
import time
from typing import Literal, Optional

import requests
from pydantic import BaseModel

from backend.bonds import fetch_latest_10y_yield

logger = logging.getLogger(__name__)

Tenor = Literal[10, 20, 30]
TENORS: tuple[int, ...] = (10, 20, 30)

_CNBC_URL = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
}
_CACHE_TTL = 5 * 60
_cache: dict[str, tuple[float, "SovereignYieldsResponse"]] = {}
_BENCHMARK = "DE"  # spreads are quoted vs the German Bund, same maturity

# ISO-2 → (ISO 3166 numeric as used by world-atlas TopoJSON, Italian name).
COUNTRIES: dict[str, tuple[str, str]] = {
    "US": ("840", "Stati Uniti"), "CA": ("124", "Canada"), "MX": ("484", "Messico"),
    "BR": ("076", "Brasile"), "CL": ("152", "Cile"), "AR": ("032", "Argentina"),
    "GB": ("826", "Regno Unito"), "DE": ("276", "Germania"), "FR": ("250", "Francia"),
    "IT": ("380", "Italia"), "ES": ("724", "Spagna"), "PT": ("620", "Portogallo"),
    "NL": ("528", "Paesi Bassi"), "BE": ("056", "Belgio"), "AT": ("040", "Austria"),
    "IE": ("372", "Irlanda"), "FI": ("246", "Finlandia"), "GR": ("300", "Grecia"),
    "SI": ("705", "Slovenia"), "CH": ("756", "Svizzera"), "SE": ("752", "Svezia"),
    "NO": ("578", "Norvegia"), "DK": ("208", "Danimarca"), "PL": ("616", "Polonia"),
    "CZ": ("203", "Cechia"), "HU": ("348", "Ungheria"), "TR": ("792", "Turchia"),
    "ZA": ("710", "Sudafrica"), "NG": ("566", "Nigeria"), "JP": ("392", "Giappone"),
    "CN": ("156", "Cina"), "HK": ("344", "Hong Kong"), "KR": ("410", "Corea del Sud"),
    "IN": ("356", "India"), "ID": ("360", "Indonesia"), "TH": ("764", "Thailandia"),
    "SG": ("702", "Singapore"), "AU": ("036", "Australia"), "NZ": ("554", "Nuova Zelanda"),
}


class TenorYield(BaseModel):
    """One country's yield at one maturity."""

    yield_pct: float
    change_bps: Optional[float] = None       # vs previous close
    prev_close_pct: Optional[float] = None
    year_high_pct: Optional[float] = None
    year_low_pct: Optional[float] = None
    spread_vs_bund_bps: Optional[float] = None
    instrument: str = ""                     # e.g. "Italy 10 Year Bond"
    as_of: Optional[str] = None              # ISO datetime (live) or date (monthly)
    source: str = "CNBC"                     # "CNBC" | "FRED (mensile)"


class CountryYields(BaseModel):
    """Yields of one sovereign issuer across the supported maturities."""

    iso2: str
    iso_numeric: str
    name: str
    y10: Optional[TenorYield] = None
    y20: Optional[TenorYield] = None
    y30: Optional[TenorYield] = None


class SovereignYieldsResponse(BaseModel):
    """Full snapshot served to the /rendimenti page."""

    countries: list[CountryYields]
    fetched_at: str
    note: str = ""


# ── CNBC ─────────────────────────────────────────────────────────────────────

def cnbc_symbol(iso2: str, tenor: int) -> str:
    """CNBC ticker of a government benchmark bond (``US10Y``, ``IT30Y-IT``)."""
    return f"US{tenor}Y" if iso2 == "US" else f"{iso2}{tenor}Y-{iso2}"


def _pct(raw: object) -> Optional[float]:
    """Parse CNBC numbers such as ``"4.12%"``, ``"+0.045"``, ``"UNCH"``."""
    if raw is None:
        return None
    text = str(raw).strip().rstrip("%").replace(",", "")
    if text.upper() == "UNCH":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def _quote_to_tenor(quote: dict[str, object]) -> Optional[TenorYield]:
    """Map a CNBC ``FormattedQuote`` item; ``None`` for unknown symbols."""
    if quote.get("code") != 0:
        return None
    y = _pct(quote.get("last"))
    if y is None:
        return None
    change = _pct(quote.get("change"))
    return TenorYield(
        yield_pct=y,
        change_bps=round(change * 100, 1) if change is not None else None,
        prev_close_pct=_pct(quote.get("previous_day_closing")),
        year_high_pct=_pct(quote.get("yrhiprice")),
        year_low_pct=_pct(quote.get("yrloprice")),
        instrument=str(quote.get("name") or ""),
        as_of=str(quote.get("last_time") or "") or None,
    )


def _fetch_cnbc() -> dict[str, TenorYield]:
    """All country × tenor quotes in one request, keyed by CNBC symbol."""
    symbols = [cnbc_symbol(c, t) for t in TENORS for c in COUNTRIES]
    try:
        resp = requests.get(
            _CNBC_URL,
            params={
                "symbols": "|".join(symbols),
                "requestMethod": "itv",
                "noform": "0",
                "partnerId": "2",
                "fund": "1",
                "exthrs": "1",
                "output": "json",
            },
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("CNBC quote service returned HTTP %s", resp.status_code)
            return {}
        quotes = resp.json()["FormattedQuoteResult"]["FormattedQuote"]
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        logger.warning("CNBC quote service failed: %s", exc)
        return {}
    if isinstance(quotes, dict):  # a single symbol comes back unwrapped
        quotes = [quotes]
    out: dict[str, TenorYield] = {}
    for q in quotes:
        parsed = _quote_to_tenor(q) if isinstance(q, dict) else None
        if parsed is not None:
            out[str(q["symbol"])] = parsed
    return out


# ── Assembly ─────────────────────────────────────────────────────────────────

def _fred_10y(iso2: str) -> Optional[TenorYield]:
    y, as_of = fetch_latest_10y_yield(iso2)
    if y is None:
        return None
    return TenorYield(yield_pct=y, as_of=as_of, source="FRED (mensile)",
                      instrument="OECD long-term rate (10Y)")


def _add_bund_spreads(countries: list[CountryYields]) -> None:
    bund = next((c for c in countries if c.iso2 == _BENCHMARK), None)
    for tenor in TENORS:
        field = f"y{tenor}"
        ref: Optional[TenorYield] = getattr(bund, field) if bund else None
        if ref is None:
            continue
        for c in countries:
            ty: Optional[TenorYield] = getattr(c, field)
            # A monthly FRED average vs a live Bund quote is not a meaningful spread.
            if ty is not None and ty.source == ref.source:
                ty.spread_vs_bund_bps = round((ty.yield_pct - ref.yield_pct) * 100, 1)


def fetch_sovereign_yields() -> SovereignYieldsResponse:
    """Snapshot of 10/20/30Y government yields for every covered country (5-min cache)."""
    cached = _cache.get("all")
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    quotes = _fetch_cnbc()
    countries: list[CountryYields] = []
    for iso2, (numeric, name) in COUNTRIES.items():
        row = CountryYields(
            iso2=iso2,
            iso_numeric=numeric,
            name=name,
            y10=quotes.get(cnbc_symbol(iso2, 10)),
            y20=quotes.get(cnbc_symbol(iso2, 20)),
            y30=quotes.get(cnbc_symbol(iso2, 30)),
        )
        if row.y10 is None:
            row.y10 = _fred_10y(iso2)
        if row.y10 or row.y20 or row.y30:
            countries.append(row)
    _add_bund_spreads(countries)

    result = SovereignYieldsResponse(
        countries=countries,
        fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        note="" if quotes else "Quotazioni live non disponibili: mostrati solo i dati mensili FRED.",
    )
    if quotes:  # never cache an outage
        _cache["all"] = (time.time(), result)
    return result
