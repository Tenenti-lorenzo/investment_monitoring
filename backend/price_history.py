"""Daily price history in EUR from Yahoo Finance.

One batched `yf.download` call fetches instruments, benchmarks and the FX
pairs needed to convert everything to EUR.
"""

import logging
from datetime import date

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Quote currencies expressed in minor units (1/100 of the major currency).
_MINOR_UNITS = {"GBp": "GBP", "GBX": "GBP", "ZAc": "ZAR", "ILA": "ILS"}


def normalize_currency(currency: str | None) -> tuple[str, float]:
    """Map a Yahoo quote currency to (ISO code, multiplier to major units).

    Args:
        currency: Currency as reported by Yahoo (e.g. "USD", "GBp").

    Returns:
        ISO code and the factor that converts a quote to major units.
    """
    if not currency:
        return "EUR", 1.0
    if currency in _MINOR_UNITS:
        return _MINOR_UNITS[currency], 0.01
    return currency.upper(), 1.0


def _download_close(tickers: list[str], start: date) -> pd.DataFrame:
    raw = yf.download(
        tickers,
        start=start.isoformat(),
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close[close.index.dayofweek < 5]  # align crypto to trading days
    return close.sort_index().ffill()


class PriceHistory:
    """Local-currency and EUR close prices for a set of tickers.

    Attributes:
        local: Adjusted closes in the instrument's major currency unit.
        eur: Same prices converted to EUR.
        fx: EUR→currency rates (units of currency per 1 EUR) per ticker.
    """

    def __init__(self, local: pd.DataFrame, eur: pd.DataFrame, fx: pd.DataFrame) -> None:
        self.local = local
        self.eur = eur
        self.fx = fx

    @property
    def index(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.eur.index)


def fetch_price_history(currencies: dict[str, str | None], start: date) -> PriceHistory:
    """Download closes for `currencies` keys and convert them to EUR.

    Args:
        currencies: yf_ticker → Yahoo quote currency (None = EUR).
        start: First date to download.

    Returns:
        PriceHistory; tickers without data are simply missing from the frames.
    """
    norm = {t: normalize_currency(c) for t, c in currencies.items()}
    fx_pairs = {iso: f"EUR{iso}=X" for iso, _ in norm.values() if iso != "EUR"}
    close = _download_close(sorted(set(currencies) | set(fx_pairs.values())), start)
    if close.empty:
        return PriceHistory(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    local, eur, fx = {}, {}, {}
    for ticker, (iso, mult) in norm.items():
        if ticker not in close or close[ticker].dropna().empty:
            logger.info("no price history for %s", ticker)
            continue
        px = close[ticker] * mult
        if iso == "EUR":
            rate = pd.Series(1.0, index=close.index)
        else:
            pair = fx_pairs[iso]
            if pair not in close or close[pair].dropna().empty:
                logger.warning("missing FX %s for %s", pair, ticker)
                continue
            rate = close[pair].bfill()
        local[ticker] = px
        eur[ticker] = px / rate
        fx[ticker] = rate
    return PriceHistory(pd.DataFrame(local), pd.DataFrame(eur), pd.DataFrame(fx))
