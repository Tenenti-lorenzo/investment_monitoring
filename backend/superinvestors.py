"""Superinvestor portfolios (13F filings) scraped from Dataroma.

Dataroma (https://www.dataroma.com) tracks ~80 value investors (Buffett,
Ackman, Pabrai, ...) from their quarterly SEC 13F filings.  No API: the
public pages are plain HTML and every dataset lives in ``<table id="grid">``.

Pages used:
  * ``/m/managers.php``            – list of superinvestors + top-10 holdings
  * ``/m/holdings.php?m=<code>``   – full portfolio of one manager
  * ``/m/g/portfolio.php?o=c``     – "grand portfolio", most-owned stocks
  * ``/m/stock.php?sym=<symbol>``  – which managers own a given stock

13F data changes once per quarter (45 days after quarter end), so results are
cached for 6 hours.  Only US-listed equities are covered.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from typing import Callable, Optional, TypeVar

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

BASE_URL = "https://www.dataroma.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
}
_CACHE_TTL = 6 * 3600
_cache: dict[str, tuple[float, object]] = {}
_T = TypeVar("_T")


# ── Pydantic contracts ───────────────────────────────────────────────────────

class Manager(BaseModel):
    """A superinvestor tracked by Dataroma."""

    code: str
    name: str
    portfolio_value: Optional[float] = None   # USD
    num_stocks: Optional[int] = None
    top_holdings: list[str] = []               # symbols, largest first


class ManagerHolding(BaseModel):
    """One position of a manager's 13F portfolio."""

    symbol: str
    name: str = ""
    pct: Optional[float] = None                # % of the manager's portfolio
    activity: str = ""                         # "Add 45.24%", "Reduce 5.89%", "Buy", ...
    shares: Optional[float] = None
    reported_price: Optional[float] = None     # price at 13F date
    value: Optional[float] = None              # USD
    current_price: Optional[float] = None
    change_vs_reported_pct: Optional[float] = None
    low_52w: Optional[float] = None
    high_52w: Optional[float] = None


class ManagerPortfolio(BaseModel):
    """Full 13F portfolio of a manager."""

    code: str
    name: str = ""
    period: str = ""                           # "Q2 2026"
    portfolio_date: str = ""                   # "30 Jun 2026"
    num_stocks: Optional[int] = None
    portfolio_value: Optional[float] = None
    holdings: list[ManagerHolding] = []
    source_url: str = ""


class ConsensusStock(BaseModel):
    """A stock of the Dataroma "grand portfolio" (aggregated across managers)."""

    symbol: str
    name: str = ""
    pct_all: Optional[float] = None            # % of all superinvestor portfolios
    ownership_count: Optional[int] = None
    hold_price: Optional[float] = None
    max_pct: Optional[float] = None            # max weight in a single portfolio
    current_price: Optional[float] = None
    low_52w: Optional[float] = None
    pct_above_low: Optional[float] = None
    high_52w: Optional[float] = None


class StockOwner(BaseModel):
    """A manager holding a given stock."""

    manager_code: str
    manager: str
    pct: Optional[float] = None
    activity: str = ""
    shares: Optional[float] = None
    value: Optional[float] = None


class StockOwnership(BaseModel):
    """Which superinvestors own a stock."""

    symbol: str
    name: str = ""
    sector: str = ""
    ownership_count: int = 0
    owners: list[StockOwner] = []
    source_url: str = ""


# ── HTML parsing ─────────────────────────────────────────────────────────────

class _Cell(BaseModel):
    text: str = ""
    href: str = ""                             # first link in the cell


class _GridParser(HTMLParser):
    """Collect the rows of ``<table id="grid">`` as lists of cells."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_Cell]] = []
        self._depth = 0
        self._row: Optional[list[_Cell]] = None
        self._text: Optional[list[str]] = None
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag == "table":
            if self._depth or dict(attrs).get("id") == "grid":
                self._depth += 1
            return
        if not self._depth:
            return
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._text, self._href = [], ""
        elif tag == "a" and self._text is not None and not self._href:
            self._href = dict(attrs).get("href") or ""
        elif tag == "br" and self._text is not None:
            self._text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag == "table":
            self._depth -= 1
        elif tag == "td" and self._row is not None and self._text is not None:
            self._row.append(_Cell(text=" ".join("".join(self._text).split()), href=self._href))
            self._text = None
        elif tag == "tr" and self._row is not None:
            # Header rows have no link in the first two cells.
            if any(c.href for c in self._row[:2]):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)


def _num(raw: str) -> Optional[float]:
    """``$65,950,296,000`` / ``22.04`` / ``-8.68%`` / ``$2.05 B`` → float."""
    m = re.search(r"(-?[\d,]*\.?\d+)\s*([BMK])?\b", raw.replace("$", ""))
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    return round(value * {"B": 1e9, "M": 1e6, "K": 1e3}.get(m.group(2) or "", 1), 4)


def _int(raw: str) -> Optional[int]:
    value = _num(raw)
    return int(value) if value is not None else None


def _query_param(href: str, key: str) -> str:
    m = re.search(rf"[?&]{key}=([^&]+)", href)
    return m.group(1) if m else ""


def _split_symbol_name(text: str) -> tuple[str, str]:
    """``AAPL - Apple Inc.`` → (``AAPL``, ``Apple Inc.``)."""
    symbol, _, name = text.partition(" - ")
    return symbol.strip(), name.strip()


def _html_span(html: str, element_id: str) -> str:
    m = re.search(rf'id="{element_id}"[^>]*>(.*?)<', html, re.S)
    return " ".join(m.group(1).split()) if m else ""


def _labelled_span(html: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}\s*<span>(.*?)</span>", html, re.S)
    return m.group(1).strip() if m else ""


# ── Fetching ─────────────────────────────────────────────────────────────────

def _get_html(path: str) -> Optional[str]:
    try:
        resp = requests.get(f"{BASE_URL}{path}", headers=_HEADERS, timeout=10)
    except requests.RequestException as exc:
        logger.warning("Dataroma request failed for %s: %s", path, exc)
        return None
    if resp.status_code != 200:
        logger.warning("Dataroma %s returned HTTP %s", path, resp.status_code)
        return None
    return resp.content.decode("utf-8", errors="replace")


def _cached(key: str, loader: Callable[[], _T]) -> _T:
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]  # type: ignore[return-value]
    value = loader()
    if value:  # don't cache failures / empty pages
        _cache[key] = (time.time(), value)
    return value


def _grid(html: str) -> list[list[_Cell]]:
    parser = _GridParser()
    parser.feed(html)
    return parser.rows


# ── Public API ───────────────────────────────────────────────────────────────

def list_managers() -> list[Manager]:
    """All superinvestors tracked by Dataroma, alphabetically."""

    def load() -> list[Manager]:
        html = _get_html("/m/managers.php")
        if html is None:
            return []
        managers = []
        for row in _grid(html):
            if len(row) < 3 or "holdings.php" not in row[0].href:
                continue
            managers.append(Manager(
                code=_query_param(row[0].href, "m"),
                name=row[0].text,
                portfolio_value=_num(row[1].text),
                num_stocks=_int(row[2].text),
                top_holdings=[_query_param(c.href, "sym") for c in row[3:] if c.href],
            ))
        return managers

    return _cached("managers", load)


def fetch_manager_portfolio(code: str) -> Optional[ManagerPortfolio]:
    """Full 13F portfolio of manager ``code`` (e.g. ``BRK``); ``None`` if unknown."""
    code = code.strip().upper()

    def load() -> Optional[ManagerPortfolio]:
        path = f"/m/holdings.php?m={code}"
        html = _get_html(path)
        if html is None:
            return None
        holdings = []
        for row in _grid(html):
            if len(row) < 12:
                continue
            symbol, name = _split_symbol_name(row[1].text)
            holdings.append(ManagerHolding(
                symbol=symbol, name=name,
                pct=_num(row[2].text), activity=row[3].text,
                shares=_num(row[4].text), reported_price=_num(row[5].text),
                value=_num(row[6].text), current_price=_num(row[8].text),
                change_vs_reported_pct=_num(row[9].text),
                low_52w=_num(row[10].text), high_52w=_num(row[11].text),
            ))
        name = _html_span(html, "f_name")
        if not name and not holdings:
            return None
        return ManagerPortfolio(
            code=code, name=name,
            period=_labelled_span(html, "Period:"),
            portfolio_date=_labelled_span(html, "Portfolio date:"),
            num_stocks=_int(_labelled_span(html, "No. of stocks:")),
            portfolio_value=_num(_labelled_span(html, "Portfolio value:")),
            holdings=holdings,
            source_url=f"{BASE_URL}{path}",
        )

    return _cached(f"manager:{code}", load)


def fetch_consensus(limit: int = 50) -> list[ConsensusStock]:
    """Most-owned stocks across all superinvestors (Dataroma grand portfolio)."""

    def load() -> list[ConsensusStock]:
        html = _get_html("/m/g/portfolio.php?o=c")
        if html is None:
            return []
        stocks = []
        for row in _grid(html):
            if len(row) < 10:
                continue
            stocks.append(ConsensusStock(
                symbol=row[0].text, name=row[1].text,
                pct_all=_num(row[2].text), ownership_count=_int(row[3].text),
                hold_price=_num(row[4].text), max_pct=_num(row[5].text),
                current_price=_num(row[6].text), low_52w=_num(row[7].text),
                pct_above_low=_num(row[8].text), high_52w=_num(row[9].text),
            ))
        return stocks

    return _cached("consensus", load)[:limit]


def fetch_stock_ownership(symbol: str) -> Optional[StockOwnership]:
    """Superinvestors owning ``symbol`` (US ticker); ``None`` if nobody owns it."""
    symbol = symbol.strip().upper().replace("/", ".")

    def load() -> Optional[StockOwnership]:
        path = f"/m/stock.php?sym={symbol}"
        html = _get_html(path)
        if html is None:
            return None
        owners = []
        for row in _grid(html):
            if len(row) < 6:
                continue
            owners.append(StockOwner(
                manager_code=_query_param(row[1].href, "m"), manager=row[1].text,
                pct=_num(row[2].text), activity=row[3].text,
                shares=_num(row[4].text), value=_num(row[5].text),
            ))
        if not owners:
            return None
        title = _html_span(html, "st_name")          # "Apple Inc. (AAPL)"
        sector = re.search(r"Sector:</td><td><b>(.*?)</b>", html)
        return StockOwnership(
            symbol=symbol,
            name=re.sub(r"\s*\([^)]*\)\s*$", "", title),
            sector=sector.group(1) if sector else "",
            ownership_count=len(owners),
            owners=owners,
            source_url=f"{BASE_URL}{path}",
        )

    return _cached(f"stock:{symbol}", load)


def fetch_portfolio_overlap(symbols: list[str]) -> list[StockOwnership]:
    """Superinvestor ownership for each of the user's ``symbols`` (misses skipped)."""
    unique = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch_stock_ownership, unique))
    return sorted(
        (r for r in results if r is not None),
        key=lambda r: r.ownership_count,
        reverse=True,
    )
