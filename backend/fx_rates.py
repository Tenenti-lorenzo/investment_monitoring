"""EUR exchange rates for turning a EUR amount into a number of shares.

Source: Yahoo Finance FX pairs (``EURUSD=X`` = USD per 1 EUR). London
listings quote in pence (``GBp``), handled as GBP × 100. Rates are cached
for an hour: they only size a position, they are not a trading quote.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import yfinance as yf
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_CACHE_TTL = 60 * 60
_cache: dict[str, tuple[float, "FxRate"]] = {}

# Minor-unit quotes: (ISO currency of the pair, units per major unit).
_MINOR_UNITS: dict[str, tuple[str, int]] = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100)}


class FxRate(BaseModel):
    """How many units of ``currency`` one euro buys."""

    currency: str
    per_eur: Optional[float]
    source: str = "Yahoo Finance"


def _yahoo_pair(iso: str) -> Optional[float]:
    try:
        price = getattr(yf.Ticker(f"EUR{iso}=X").fast_info, "last_price", None)
    except Exception:
        logger.warning("FX lookup failed for EUR%s", iso, exc_info=True)
        return None
    return float(price) if price and price > 0 else None


def fetch_eur_rate(currency: str) -> FxRate:
    """Units of ``currency`` per 1 EUR (``per_eur`` is None when unavailable).

    Args:
        currency: ISO code as reported by Yahoo (``USD``, ``GBp``, …).
    """
    currency = currency.strip()
    if currency.upper() == "EUR":
        return FxRate(currency="EUR", per_eur=1.0)

    cached = _cache.get(currency)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    iso, factor = _MINOR_UNITS.get(currency, (currency.upper(), 1))
    rate = _yahoo_pair(iso)
    result = FxRate(currency=currency, per_eur=round(rate * factor, 6) if rate else None)
    if rate:  # never cache an outage
        _cache[currency] = (time.time(), result)
    return result
