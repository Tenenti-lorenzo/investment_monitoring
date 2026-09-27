"""/api/search and /api/bond/quote."""

import pytest
from fakes import FakeFundsData, FakeTicker, ticker_factory, top_holdings

from backend import main
from backend.bond_market import BondQuote
from backend.bonds import SovereignRisk

ETF_ISIN = "IE00B4L5Y983"
BTP_ISIN = "IT0005436693"


@pytest.fixture
def figi(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    table: dict[str, list[dict]] = {
        ETF_ISIN: [
            {
                "ticker": "EUNL",
                "exchCode": "GR",
                "securityType": "ETP",
                "marketSector": "Equity",
                "name": "ISHARES CORE MSCI WORLD",
            }
        ],
        BTP_ISIN: [
            {
                "ticker": "BTPS",
                "exchCode": "MI",
                "securityType": "BTP",
                "marketSector": "Govt",
                "securityType2": "Bond",
                "name": "BTPS 0.6 08/01/31",
            }
        ],
    }
    monkeypatch.setattr(main, "openfigi_items", lambda isin: table.get(isin, []))
    return table


def test_search_when_crypto_symbol_then_mapped_to_eur_pair(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        main.yf,
        "Ticker",
        ticker_factory(
            {
                "BTC-EUR": FakeTicker(
                    info={
                        "quoteType": "CRYPTOCURRENCY",
                        "longName": "Bitcoin EUR",
                        "regularMarketPrice": 55000.0,
                        "currency": "EUR",
                    }
                )
            }
        ),
    )
    body = client.get("/api/search?q=btc", headers=auth_headers).json()
    assert body["yf_ticker"] == "BTC-EUR"
    assert body["category"] == "Criptovalute" and body["price"] == 55000.0


def test_search_when_etf_isin_then_resolved_classified_with_ter_and_composition(
    client, auth_headers, figi, monkeypatch
):
    etf = FakeTicker(
        info={
            "quoteType": "ETF",
            "longName": "iShares Core MSCI World UCITS ETF",
            "category": "Global Large-Cap Blend Equity",
            "netExpenseRatio": 0.002,
            "regularMarketPrice": 110.5,
            "currency": "EUR",
        },
        funds_data=FakeFundsData(top_holdings=top_holdings({"NVDA": ("NVIDIA Corp", 0.054)})),
    )
    monkeypatch.setattr(main.yf, "Ticker", ticker_factory({"EUNL.DE": etf}))
    body = client.get(f"/api/search?q={ETF_ISIN.lower()}", headers=auth_headers).json()
    assert body["isin"] == ETF_ISIN and body["yf_ticker"] == "EUNL.DE" and body["exch"] == "GR"
    assert body["category"] == "ETF Azionario"
    assert body["ter"] == 0.2
    assert body["geography"]["Nord America"] == 68
    assert body["composition"] == [{"name": "NVIDIA Corp", "weight": 5.4}]
    assert body["isin_mismatch"] is False


def test_search_when_etf_ter_missing_on_yahoo_then_justetf_scraped(client, auth_headers, figi, monkeypatch):
    etf = FakeTicker(info={"quoteType": "ETF", "longName": "iShares Core MSCI World UCITS ETF"})
    monkeypatch.setattr(main.yf, "Ticker", ticker_factory({"EUNL.DE": etf}))
    monkeypatch.setattr(main, "_fetch_ter_justetf", lambda isin: 0.2)
    assert client.get(f"/api/search?q={ETF_ISIN}", headers=auth_headers).json()["ter"] == 0.2


def test_search_when_government_bond_isin_then_bond_payload_with_market_and_risk(
    client, auth_headers, figi, monkeypatch
):
    monkeypatch.setattr(
        main,
        "fetch_bond_quote",
        lambda isin: BondQuote(
            isin=isin, name="Btp Tf 0,6% Ag31 Eur", price=85.41, currency="EUR", market="MOT"
        ),
    )
    monkeypatch.setattr(
        main,
        "fetch_sovereign_risk",
        lambda iso2, cur: SovereignRisk(country=iso2, yield_10y=3.6, bund_spread_bps=100, risk_tier="Basso"),
    )
    body = client.get(f"/api/search?q={BTP_ISIN}", headers=auth_headers).json()
    assert body["category"] == "Obbligazioni" and body["quoteType"] == "BOND"
    assert body["name"] == "Btp Tf 0,6% Ag31 Eur" and body["price"] == 85.41
    assert body["price_unit"] == "pct_of_par" and body["exch"] == "MOT"
    assert body["bond_type"] == "Governativo" and body["issuer_country"] == "IT"
    assert body["sovereign_risk"]["risk_tier"] == "Basso"
    assert body["market_data"]["price"] == 85.41


def test_search_when_bond_not_listed_in_milan_then_manual_price(client, auth_headers, figi, monkeypatch):
    monkeypatch.setattr(main, "fetch_bond_quote", lambda isin: None)
    monkeypatch.setattr(main, "fetch_sovereign_risk", lambda iso2, cur: SovereignRisk(country=iso2))
    body = client.get(f"/api/search?q={BTP_ISIN}", headers=auth_headers).json()
    assert body["price"] is None and body["name"] == "BTPS 0.6 08/01/31"
    assert "manualmente" in body["description"]


def test_search_when_isin_unknown_to_openfigi_then_404(client, auth_headers, figi):
    assert client.get("/api/search?q=XS0000000000", headers=auth_headers).status_code == 404


def test_search_when_ticker_unknown_to_yahoo_then_404(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main.yf, "Ticker", ticker_factory({}))
    assert client.get("/api/search?q=NOPE", headers=auth_headers).status_code == 404


def test_search_when_commodity_etc_behind_etf_isin_then_mismatch_flag(
    client, auth_headers, figi, monkeypatch
):
    etc = FakeTicker(info={"quoteType": "ETF", "longName": "WisdomTree Heating Oil"})
    monkeypatch.setattr(main.yf, "Ticker", ticker_factory({"EUNL.DE": etc}))
    assert client.get(f"/api/search?q={ETF_ISIN}", headers=auth_headers).json()["isin_mismatch"] is True


def test_search_when_not_authenticated_then_rejected(client):
    assert client.get("/api/search?q=AAPL").status_code in (401, 403)


# ─── /api/bond/quote ──────────────────────────────────────────────────────────


def test_bond_quote_when_listed_then_quote(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "fetch_bond_quote", lambda isin: BondQuote(isin=isin, price=99.5))
    res = client.get(f"/api/bond/quote/{BTP_ISIN.lower()}", headers=auth_headers)
    assert res.status_code == 200 and res.json()["isin"] == BTP_ISIN and res.json()["price"] == 99.5


def test_bond_quote_when_invalid_isin_then_400(client, auth_headers):
    assert client.get("/api/bond/quote/123", headers=auth_headers).status_code == 400


def test_bond_quote_when_not_listed_then_404(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "fetch_bond_quote", lambda isin: None)
    assert client.get(f"/api/bond/quote/{BTP_ISIN}", headers=auth_headers).status_code == 404
