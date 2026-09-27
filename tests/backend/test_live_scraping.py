"""Live checks against the real sites — skipped by default.

Run with ``uv run pytest -m live``. They fail when a site changes layout
(the offline tests keep passing on the captured fixtures), so run them
periodically or before a release; refresh ``tests/fixtures`` when they break.
"""

from datetime import date, timedelta

import pytest

from backend import bond_market, main, superinvestors
from backend.price_history import fetch_price_history

pytestmark = pytest.mark.live


def test_live_borsa_italiana_mot_btp_then_name_price_maturity():
    q = bond_market.fetch_bond_quote("IT0005436693")
    assert q is not None and q.market
    assert "Btp" in q.name and q.maturity == "2031-08-01"
    assert q.price and 50 < q.price < 150


def test_live_borsa_italiana_eurotlx_treasury_then_quote():
    q = bond_market.fetch_bond_quote("US912810TD00")
    assert q is not None and q.currency == "USD" and q.coupon_annual_pct == 2.25


def test_live_borsa_italiana_unknown_isin_then_none():
    assert bond_market.fetch_bond_quote("XS0000000000") is None


def test_live_dataroma_managers_and_brk_portfolio():
    managers = superinvestors.list_managers()
    assert len(managers) > 40 and any(m.code == "BRK" for m in managers)
    brk = superinvestors.fetch_manager_portfolio("BRK")
    assert brk and brk.holdings and brk.holdings[0].pct and brk.num_stocks


def test_live_dataroma_consensus_and_stock_ownership():
    assert len(superinvestors.fetch_consensus(10)) == 10
    aapl = superinvestors.fetch_stock_ownership("AAPL")
    assert aapl and aapl.ownership_count > 0 and aapl.sector


def test_live_justetf_ter_for_msci_world():
    ter = main._fetch_ter_justetf("IE00B4L5Y983")
    assert ter is not None and 0 < ter < 1


def test_live_openfigi_resolves_ucits_etf_to_eur_listing():
    items = main.openfigi_items("IE00B4L5Y983")
    assert items
    assert main.isin_to_ticker("IE00B4L5Y983", items)["exchCode"] in main._EUR_EXCH_PRIORITY


def test_live_yahoo_prices_converted_to_eur():
    ph = fetch_price_history({"SWDA.MI": "EUR", "MSFT": "USD"}, date.today() - timedelta(days=30))
    assert {"SWDA.MI", "MSFT"} <= set(ph.eur.columns)
    assert (ph.fx["MSFT"] > 0.5).all()
