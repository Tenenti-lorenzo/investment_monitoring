"""Dataroma scraper: parsing of real captured pages + caching and failures."""

import pytest
from fakes import FakeResponse, fixture_bytes

from backend import superinvestors as si

PAGES = {
    "/m/managers.php": "dataroma_managers.html",
    "/m/holdings.php?m=BRK": "dataroma_holdings_BRK.html",
    "/m/g/portfolio.php?o=c": "dataroma_grand_portfolio.html",
    "/m/stock.php?sym=AAPL": "dataroma_stock_AAPL.html",
}


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake_get(url, headers=None, timeout=None):
        path = url.removeprefix(si.BASE_URL)
        calls.append(path)
        if path in PAGES:
            return FakeResponse(fixture_bytes(PAGES[path]), url=url)
        if path.startswith("/m/stock.php"):
            return FakeResponse(b"<html><body>no grid</body></html>", url=url)
        return FakeResponse(b"", status_code=404, url=url)

    monkeypatch.setattr(si.requests, "get", fake_get)
    return calls


# ─── Parsing helpers ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$65,950,296,000", 65_950_296_000),
        ("22.04", 22.04),
        ("-8.68%", -8.68),
        ("$2.05 B", 2.05e9),
        ("$310.5 M", 310.5e6),
        ("12 K", 12_000),
        ("$289.36", 289.36),
        ("", None),
        ("—", None),
    ],
)
def test_num_when_dataroma_formats_then_float(raw, expected):
    assert si._num(raw) == (pytest.approx(expected) if expected is not None else None)


def test_int_split_and_query_helpers():
    assert si._int("1,234") == 1234 and si._int("n/a") is None
    assert si._split_symbol_name("AAPL - Apple Inc.") == ("AAPL", "Apple Inc.")
    assert si._split_symbol_name("BRK.B") == ("BRK.B", "")
    assert si._query_param("/m/holdings.php?m=BRK&x=1", "m") == "BRK"
    assert si._query_param("/m/holdings.php", "m") == ""


def test_grid_parser_when_header_rows_without_links_then_skipped():
    html = """<table id="grid"><tr><td>Header</td><td>x</td></tr>
              <tr><td><a href="/m/holdings.php?m=AB">A&amp;B</a></td><td>1<br>2</td></tr></table>"""
    rows = si._grid(html)
    assert len(rows) == 1
    assert rows[0][0].text == "A&B" and rows[0][0].href == "/m/holdings.php?m=AB"
    assert rows[0][1].text == "1 2"


# ─── Real pages ───────────────────────────────────────────────────────────────


def test_list_managers_when_real_page_then_code_value_and_top_holdings(http):
    managers = si.list_managers()
    assert len(managers) == 5  # fixture trimmed to the first 5 managers
    first = managers[0]
    assert first.name == "Abrams Bison Investments"
    assert first.code == "ABI"
    assert first.portfolio_value == pytest.approx(2.05e9)
    assert first.num_stocks == 11
    assert first.top_holdings[:2] == ["SNX", "AMAT"]


def test_manager_portfolio_when_brk_then_header_and_holdings(http):
    p = si.fetch_manager_portfolio("brk")
    assert p.code == "BRK"
    assert p.name == "Warren Buffett - Berkshire Hathaway"
    assert (p.period, p.portfolio_date) == ("Q2 2026", "30 Jun 2026")
    assert p.num_stocks == 29 and len(p.holdings) == 29
    assert p.portfolio_value == pytest.approx(299_253_558_000)
    aapl = p.holdings[0]
    assert (aapl.symbol, aapl.name) == ("AAPL", "Apple Inc.")
    assert aapl.pct == 22.04 and aapl.shares == 227_917_808
    assert aapl.reported_price == 289.36 and aapl.value == 65_950_296_000
    assert aapl.current_price == 341.07 and aapl.change_vs_reported_pct == 17.87
    assert (aapl.low_52w, aapl.high_52w) == (242.76, 345.34)
    assert sum(h.pct for h in p.holdings) == pytest.approx(100, abs=0.5)


def test_consensus_when_real_page_then_ranked_stocks_and_limit(http):
    stocks = si.fetch_consensus(limit=5)
    assert len(stocks) == 5
    msft = stocks[0]
    assert (msft.symbol, msft.name) == ("MSFT", "Microsoft Corp.")
    assert msft.ownership_count == 37 and msft.pct_all == pytest.approx(1.779)
    assert msft.hold_price == 373.02 and msft.current_price == 516.17
    assert len(si.fetch_consensus(limit=100)) > 50
    assert http.count("/m/g/portfolio.php?o=c") == 1  # cached


def test_stock_ownership_when_aapl_then_owners_name_and_sector(http):
    s = si.fetch_stock_ownership("aapl")
    assert (s.symbol, s.name, s.sector) == ("AAPL", "Apple Inc.", "Technology")
    assert s.ownership_count == len(s.owners) == 22
    top = s.owners[0]
    assert top.manager_code == "HH"
    assert top.manager == "Duan Yongping - H&H International Investment"
    assert top.pct == 41.05 and top.activity == "Reduce 6.38%"
    assert top.shares == 27_098_707 and top.value == 7_841_282_000


def test_stock_ownership_when_nobody_owns_then_none(http):
    assert si.fetch_stock_ownership("ZZZZ") is None


def test_manager_when_unknown_page_then_none(monkeypatch):
    monkeypatch.setattr(si.requests, "get", lambda *a, **k: FakeResponse(b"<html></html>"))
    assert si.fetch_manager_portfolio("NOPE") is None


def test_overlap_when_symbols_repeat_or_missing_then_deduped_sorted_and_skipped(http):
    res = si.fetch_portfolio_overlap(["aapl", "AAPL ", "ZZZZ", ""])
    assert [r.symbol for r in res] == ["AAPL"]
    assert http.count("/m/stock.php?sym=AAPL") == 1


def test_failures_when_site_down_then_empty_and_not_cached(monkeypatch):
    calls = []

    def down(url, **k):
        calls.append(url)
        return FakeResponse(b"", status_code=503)

    monkeypatch.setattr(si.requests, "get", down)
    assert si.list_managers() == []
    assert si.list_managers() == []
    assert len(calls) == 2  # empty results are retried, never cached
