"""Bond market data scraped from Borsa Italiana, by ISIN.

Same approach as the MarketValues Excel add-in (simpletoolsforinvestors.eu):
download the public "dati-completi" page of the instrument and read the
label/value rows of the ``<table class="m-table -clear-m">`` tables.

Two routes cover every bond listed in Milan:
  * MOT family (MOT BTP/CCT/CTZ/BOT, EuroMOT, ExtraMOT, ExtraMOT PRO³,
    segmento professionale): any MOT-family URL resolves any ISIN of the
    family, so a single path is enough.
  * EuroTLX: separate page layout and labels (and served as cp1252).

An unknown ISIN is redirected to ``ricerca-avanzata.html``; that is how a
miss is detected.  Prices are quoted as % of nominal ("corso secco").
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
from typing import Optional

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_BASE = "https://www.borsaitaliana.it/borsa/obbligazioni"
_ROUTES: tuple[tuple[str, str], ...] = (
    ("MOT", f"{_BASE}/mot/btp/dati-completi.html?isin={{isin}}&lang=it"),
    ("EuroTLX", f"{_BASE}/eurotlx/dati-completi.html?isin={{isin}}&lang=it"),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
}
_NOT_FOUND_MARKER = "ricerca-avanzata"
_CACHE_TTL = 5 * 60  # MarketValues also refuses to re-download within 5 minutes
_quote_cache: dict[str, tuple[float, Optional["BondQuote"]]] = {}


class BondQuote(BaseModel):
    """Market snapshot of a bond listed on Borsa Italiana (prices in % of nominal)."""

    isin: str
    name: str = ""
    market: str = ""                 # MOT | EuroMOT | ExtraMOT | EuroTLX ...
    instrument_type: str = ""        # e.g. "Titoli di stato italiani", "T-Bonds"
    issuer: str = ""
    currency: str = ""
    market_phase: str = ""

    price: Optional[float] = None    # best available: last > reference > official
    last_price: Optional[float] = None
    last_trade_at: Optional[str] = None      # ISO datetime
    change_pct: Optional[float] = None
    change_abs: Optional[float] = None
    reference_price: Optional[float] = None
    official_price: Optional[float] = None
    official_price_date: Optional[str] = None
    preopen_price: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    year_high: Optional[float] = None
    year_low: Optional[float] = None
    last_volume: Optional[float] = None
    volume: Optional[float] = None
    trades: Optional[int] = None
    turnover: Optional[float] = None

    maturity: Optional[str] = None           # ISO date
    accrual_start: Optional[str] = None      # ISO date ("data godimento")
    coupon_period_pct: Optional[float] = None
    coupon_annual_pct: Optional[float] = None
    coupon_frequency: str = ""
    bond_kind: str = ""                      # "Titolo Con Cedole Tf", ...
    quotation: str = ""                      # "Corso Secco", ...
    min_lot: Optional[float] = None

    source: str = "Borsa Italiana"
    source_url: str = ""
    fetched_at: str = ""


# ── Label (normalised) → BondQuote field.  MOT and EuroTLX use different wording.
_TEXT_FIELDS: dict[str, str] = {
    "nome": "name",
    "mercato": "market",
    "tipologia": "instrument_type",
    "emittente": "issuer",
    "valuta di negoziazione": "currency",
    "fase di mercato": "market_phase",
    "frequenza di pagamento": "coupon_frequency",
    "tipo bond": "bond_kind",
    "modalita di negoziazione": "quotation",
}
_NUMBER_FIELDS: dict[str, str] = {
    "prezzo ultimo contratto": "last_price",
    "var %": "change_pct",
    "var assoluta": "change_abs",
    "prezzo di riferimento": "reference_price",
    "prezzo ufficiale": "official_price",
    "pre-apertura": "preopen_price",
    "max oggi": "day_high",
    "min oggi": "day_low",
    "max anno": "year_high",
    "massimo dell'anno": "year_high",
    "min anno": "year_low",
    "minimo dell'anno": "year_low",
    "volume ultimo": "last_volume",
    "quantita ultimo contratto": "last_volume",
    "volume totale": "volume",
    "volume giornaliero": "volume",
    "numero contratti": "trades",
    "controvalore": "turnover",
    "controvalore giornaliero": "turnover",
    "tasso cedola periodale": "coupon_period_pct",
    "tasso cedola su base annua": "coupon_annual_pct",
    "lotto minimo": "min_lot",
}
_DATE_FIELDS: dict[str, str] = {
    "scadenza": "maturity",
    "data di scadenza": "maturity",
    "data godimento": "accrual_start",
    "data pr ufficiale": "official_price_date",
}
_DATETIME_FIELDS: dict[str, str] = {
    "data - ora ultimo contratto": "last_trade_at",
    "data e ora": "last_trade_at",
}


class _DataTableParser(HTMLParser):
    """Collect ``[label, value]`` rows from ``table.m-table.-clear-m`` tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._table_depth = 0
        self._row: Optional[list[str]] = None
        self._cell: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag == "table":
            classes = (dict(attrs).get("class") or "").split()
            if self._table_depth or ("m-table" in classes and "-clear-m" in classes):
                self._table_depth += 1
        elif not self._table_depth:
            return
        elif tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if not self._table_depth:
            return
        if tag == "table":
            self._table_depth -= 1
        elif tag == "td" and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _norm_label(label: str) -> str:
    """Lower-case, accent-free, single-spaced label (``Quantità`` → ``quantita``)."""
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return " ".join(ascii_label.lower().rstrip(":").split())


def _parse_it_number(raw: str) -> Optional[float]:
    """Parse an Italian-formatted number (``9.020.000`` / ``79,49422`` / ``-0,19``)."""
    cleaned = raw.strip().replace("%", "").replace(".", "").replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", cleaned):
        return None
    return float(cleaned)


def _parse_it_date(raw: str) -> Optional[str]:
    """``01/09/46`` or ``15/05/2051`` or ``25-09-2026`` → ISO date."""
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_it_datetime(raw: str) -> Optional[str]:
    """``25/09/26 - 17.15.29`` (MOT) or ``25-09-2026 15:43`` (EuroTLX) → ISO datetime."""
    cleaned = re.sub(r"\s*-\s*", " ", raw.strip(), count=1) if "/" in raw else raw.strip()
    for fmt in ("%d/%m/%y %H.%M.%S", "%d/%m/%Y %H.%M.%S", "%d-%m-%Y %H:%M", "%d/%m/%y %H:%M"):
        try:
            return datetime.strptime(cleaned, fmt).isoformat()
        except ValueError:
            continue
    return None


def _decode(content: bytes) -> str:
    """MOT pages are UTF-8, EuroTLX pages are cp1252."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _rows_to_quote(isin: str, rows: list[list[str]], route: str, url: str) -> BondQuote:
    """Map the scraped label/value rows onto a :class:`BondQuote`."""
    values: dict[str, object] = {}
    for row in rows:
        if len(row) < 2 or not row[1]:
            continue
        label, raw = _norm_label(row[0]), row[1]
        if label in _TEXT_FIELDS:
            values[_TEXT_FIELDS[label]] = raw
        elif label in _NUMBER_FIELDS:
            num = _parse_it_number(raw)
            if num is not None:
                field = _NUMBER_FIELDS[label]
                values[field] = int(num) if field == "trades" else num
        elif label in _DATE_FIELDS:
            values[_DATE_FIELDS[label]] = _parse_it_date(raw)
        elif label in _DATETIME_FIELDS:
            values[_DATETIME_FIELDS[label]] = _parse_it_datetime(raw)

    quote = BondQuote.model_validate(
        {
            **values,
            "isin": isin,
            "source_url": url,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    if not quote.market:
        quote.market = route
    quote.price = next(
        (p for p in (quote.last_price, quote.reference_price, quote.official_price) if p),
        None,
    )
    return quote


def _fetch_route(isin: str, route: str, url_tpl: str) -> Optional[BondQuote]:
    """Download and parse one Borsa Italiana route; ``None`` if the ISIN isn't there."""
    url = url_tpl.format(isin=isin)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
    except requests.RequestException as exc:
        logger.warning("Borsa Italiana %s request failed for %s: %s", route, isin, exc)
        return None
    if resp.status_code != 200 or _NOT_FOUND_MARKER in resp.url:
        return None

    parser = _DataTableParser()
    parser.feed(_decode(resp.content))
    if not any(_norm_label(r[0]) == "nome" for r in parser.rows if r):
        return None
    return _rows_to_quote(isin, parser.rows, route, url)


def fetch_bond_quote(isin: str) -> Optional[BondQuote]:
    """Market data for a bond listed on MOT/ExtraMOT/EuroTLX.

    Args:
        isin: 12-char ISIN.

    Returns:
        The quote, or ``None`` if the bond is not listed on Borsa Italiana
        (or the site is unreachable).  Results — including misses — are cached
        for 5 minutes.
    """
    isin = isin.strip().upper()
    cached = _quote_cache.get(isin)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    quote: Optional[BondQuote] = None
    for route, url_tpl in _ROUTES:
        quote = _fetch_route(isin, route, url_tpl)
        if quote is not None:
            break

    _quote_cache[isin] = (time.time(), quote)
    return quote
