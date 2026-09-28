"""/api/portfolio/* (analyze, P&L, performance, save/load) and document extraction."""

from types import SimpleNamespace

import pandas as pd
import pytest
from fakes import FakeTicker, bdays, ticker_factory

from backend import main
from backend.bond_market import BondQuote

# ─── /api/portfolio/analyze ───────────────────────────────────────────────────


def h(ticker, category, allocation, **kw):
    return {
        "isin": kw.pop("isin", ""),
        "name": ticker,
        "ticker": ticker,
        "category": category,
        "allocation": allocation,
        **kw,
    }


@pytest.fixture
def analyze_body() -> dict:
    return {
        "holdings": [
            h("SWDA", "ETF Azionario", 60, currency="USD", ter=0.2, geography={"Nord America": 100}),
            h("BTP", "Obbligazioni", 30, currency="EUR", geography={"Europa": 100}),
        ],
        "liquidita": 10,
    }


def test_analyze_when_mixed_then_category_geography_currency_exposures(client, auth_headers, analyze_body):
    body = client.post("/api/portfolio/analyze", json=analyze_body, headers=auth_headers).json()
    assert body["total"] == 100
    assert body["category_pct"] == {"ETF Azionario": 60.0, "Obbligazioni": 30.0, "Liquidità": 10.0}
    assert body["geography"] == {"Nord America": 66.7, "Europa": 33.3}  # liquidity has no geography
    assert body["currency_exposure"] == {"USD": 60.0, "EUR": 40.0}
    und = body["underlying_currency_exposure"]
    assert und["USD"] == pytest.approx(57.0) and und["CAD"] == pytest.approx(3.0)  # NA = 95/5 USD/CAD
    assert und["EUR"] == pytest.approx(40.0)


def test_analyze_when_mixed_then_heuristic_metrics_and_ter(client, auth_headers, analyze_body):
    m = client.post("/api/portfolio/analyze", json=analyze_body, headers=auth_headers).json()["metrics"]
    low = round(0.6 * 7 + 0.3 * 3 + 0.1 * 1.5, 1)
    high = round(0.6 * 11 + 0.3 * 5 + 0.1 * 2, 1)
    assert m["expected_return"] == f"{low}% – {high}%"
    assert m["aggressiveness"] == "Moderato"  # 0.6 − 0.3×0.5 = 0.45
    assert m["ter_medio"] == 0.2


@pytest.mark.parametrize(
    "alloc,label",
    [(10, "Conservativo"), (40, "Moderato"), (60, "Moderatamente Aggressivo"), (100, "Aggressivo")],
)
def test_analyze_when_equity_share_varies_then_aggressiveness_bucket(client, auth_headers, alloc, label):
    body = {"holdings": [h("EQ", "Azioni", alloc)], "liquidita": 100 - alloc}
    res = client.post("/api/portfolio/analyze", json=body, headers=auth_headers).json()
    assert res["metrics"]["aggressiveness"] == label


def test_analyze_when_etf_without_ter_then_fetched_and_returned_in_map(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "_fetch_ter_full", lambda ticker, isin="": 0.07)
    body = {"holdings": [h("CSPX", "ETF Azionario", 100, yf_ticker="CSPX.L")], "liquidita": 0}
    res = client.post("/api/portfolio/analyze", json=body, headers=auth_headers).json()
    assert res["ter_map"] == {"CSPX": 0.07} and res["metrics"]["ter_medio"] == 0.07


def test_analyze_when_saved_ter_has_legacy_unit_error_then_refetched_and_corrected(
    client, auth_headers, monkeypatch
):
    # Regression: an older version saved 0.20 % as 20.0 → dashboard showed "TER 20.00%"
    # while the weighted average silently ignored it.
    monkeypatch.setattr(main, "_fetch_ter_full", lambda ticker, isin="": 0.2)
    body = {
        "holdings": [
            h("EUNK", "ETF Azionario", 50, yf_ticker="EUNK.DE", ter=20.0),
            h("VWCE", "ETF Azionario", 50, yf_ticker="VWCE.DE", ter=0.19),
        ],
        "liquidita": 0,
    }
    res = client.post("/api/portfolio/analyze", json=body, headers=auth_headers).json()
    assert res["ter_map"] == {"EUNK": 0.2, "VWCE": 0.19}
    assert res["metrics"]["ter_medio"] == pytest.approx(0.195)


def test_analyze_when_empty_then_400(client, auth_headers):
    res = client.post("/api/portfolio/analyze", json={"holdings": [], "liquidita": 0}, headers=auth_headers)
    assert res.status_code == 400


# ─── /api/portfolio/pl ────────────────────────────────────────────────────────


def test_pl_when_stock_and_bond_then_values_costs_and_totals(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main.yf, "Ticker", ticker_factory({"MSFT": FakeTicker(last_price=120.0)}))
    monkeypatch.setattr(main, "fetch_bond_quote", lambda isin: BondQuote(isin=isin, price=90.0))
    body = {
        "holdings": [
            {
                "ticker": "MSFT",
                "yf_ticker": "MSFT",
                "name": "Microsoft",
                "quantity": 10,
                "purchase_price": 100,
            },
            {
                "ticker": "BTP",
                "isin": "IT0005436693",
                "category": "Obbligazioni",
                "quantity": 1000,
                "purchase_price": 95,
            },
            {"ticker": "NOQTY", "yf_ticker": "NOQTY"},  # no quantity → skipped
        ]
    }
    res = client.post("/api/portfolio/pl", json=body, headers=auth_headers).json()
    by = {r["ticker"]: r for r in res["holdings"]}
    assert by["MSFT"]["current_value"] == 1200 and by["MSFT"]["pl_eur"] == 200 and by["MSFT"]["pl_pct"] == 20
    assert by["BTP"]["current_value"] == 900 and by["BTP"]["pl_eur"] == -50  # % of nominal
    assert res["total_value"] == 2100 and res["total_cost"] == 1950
    assert res["total_pl_eur"] == 150 and res["total_pl_pct"] == pytest.approx(7.69, abs=0.01)


def test_pl_when_price_unavailable_then_holding_dropped(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main.yf, "Ticker", ticker_factory({}))
    body = {"holdings": [{"ticker": "X", "yf_ticker": "X", "quantity": 1, "purchase_price": 1}]}
    res = client.post("/api/portfolio/pl", json=body, headers=auth_headers).json()
    assert res["holdings"] == [] and res["total_pl_eur"] is None


# ─── /api/portfolio/performance ───────────────────────────────────────────────


def test_performance_when_histories_then_value_series_and_return(client, auth_headers, monkeypatch):
    idx = bdays(10)
    monkeypatch.setattr(
        main.yf,
        "Ticker",
        ticker_factory(
            {
                "AAA": FakeTicker(history=pd.Series([100.0] * 9 + [110.0], index=idx)),
                "BBB": FakeTicker(history=pd.Series([50.0] * 10, index=idx)),
                "EMPTY": FakeTicker(),
            }
        ),
    )
    body = {
        "holdings": [
            {"yf_ticker": "AAA", "amount": 1100},
            {"yf_ticker": "BBB", "amount": 500},
            {"yf_ticker": "EMPTY", "amount": 400},
        ],
        "liquidita": 100,
    }
    res = client.post("/api/portfolio/performance", json=body, headers=auth_headers).json()
    # amounts are today's values: AAA was worth 1000 at the start
    assert res["initial_value"] == 1600 and res["current_value"] == 1700
    assert res["return_pct"] == pytest.approx(6.25)
    assert res["covered_pct"] == 80.0 and res["failed_tickers"] == ["EMPTY"]
    assert len(res["dates"]) == len(res["values"]) == 10


def test_performance_when_nothing_covered_then_empty_series(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main.yf, "Ticker", ticker_factory({}))
    res = client.post(
        "/api/portfolio/performance",
        json={"holdings": [{"yf_ticker": "X", "amount": 1}]},
        headers=auth_headers,
    ).json()
    assert res["dates"] == [] and res["failed_tickers"] == ["X"]


# ─── Save / list / load / delete ──────────────────────────────────────────────


def test_save_list_load_delete_when_round_trip_then_consistent(client, auth_headers):
    payload = {
        "name": "PAC",
        "holdings": [{"ticker": "SWDA", "amount": 100}],
        "liquidita": 5,
        "inputMode": "amount",
        "pac_entries": [{"ticker": "SWDA", "amount": 100}],
    }
    saved = client.post("/api/portfolio/save", json=payload, headers=auth_headers).json()
    assert saved["status"] == "saved" and saved["savedAt"]
    pid = saved["portfolio_id"]

    listing = client.get("/api/portfolio/list", headers=auth_headers).json()
    assert listing == [{"portfolio_id": pid, "name": "PAC", "savedAt": saved["savedAt"], "holdings_count": 1}]

    loaded = client.get(f"/api/portfolio/load/{pid}", headers=auth_headers).json()
    assert loaded["holdings"] == payload["holdings"] and loaded["pac_entries"] == payload["pac_entries"]
    assert loaded["portfolio_id"] == pid and loaded["inputMode"] == "amount"

    assert client.delete(f"/api/portfolio/saved/{pid}", headers=auth_headers).json() == {"status": "deleted"}
    assert client.get(f"/api/portfolio/load/{pid}", headers=auth_headers).status_code == 404


def test_portfolios_when_other_user_then_not_visible(client, auth_headers):
    pid = client.post("/api/portfolio/save", json={"holdings": []}, headers=auth_headers).json()[
        "portfolio_id"
    ]
    other = {"Authorization": f"Bearer {main._create_token('luigi')}"}
    assert client.get("/api/portfolio/list", headers=other).json() == []
    assert client.get(f"/api/portfolio/load/{pid}", headers=other).status_code == 404


# ─── /api/extract-from-documents ──────────────────────────────────────────────


class FakeAnthropic:
    last_request: dict = {}

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        FakeAnthropic.last_request = kwargs
        return SimpleNamespace(content=[SimpleNamespace(text=self.reply)])


def use_llm(monkeypatch, reply: str) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(main.anthropic, "Anthropic", lambda api_key: FakeAnthropic(reply))


def test_extract_when_llm_returns_json_then_items(client, auth_headers, monkeypatch):
    use_llm(
        monkeypatch,
        'Ecco: {"items": [{"isin": "IE00B4L5Y983", "name": "iShares", "quantity": 10.5, '
        '"value": 3500, "coupon": null}]} fine',
    )
    files = [
        ("files", ("estratto.pdf", b"%PDF-1.4 fake", "application/pdf")),
        ("files", ("note.txt", b"IE00B4L5Y983 10 quote", "text/plain")),
    ]
    res = client.post("/api/extract-from-documents", files=files, headers=auth_headers)
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["isin"] == "IE00B4L5Y983" and item["quantity"] == 10.5 and item["value"] == 3500
    blocks = FakeAnthropic.last_request["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["document", "text", "text"]
    assert blocks[0]["source"]["media_type"] == "application/pdf"


@pytest.mark.parametrize("reply", ["nessun JSON qui", '{"items": [{"quantity": "tante"}]}', "{rotto"])
def test_extract_when_llm_reply_invalid_then_500(client, auth_headers, monkeypatch, reply):
    use_llm(monkeypatch, reply)
    files = [("files", ("a.txt", b"x", "text/plain"))]
    assert client.post("/api/extract-from-documents", files=files, headers=auth_headers).status_code == 500


def test_extract_when_no_api_key_then_400(client, auth_headers, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    files = [("files", ("a.txt", b"x", "text/plain"))]
    assert client.post("/api/extract-from-documents", files=files, headers=auth_headers).status_code == 400


def test_extract_when_files_empty_then_400(client, auth_headers, monkeypatch):
    use_llm(monkeypatch, "{}")
    files = [("files", ("vuoto.pdf", b"", "application/pdf"))]
    assert client.post("/api/extract-from-documents", files=files, headers=auth_headers).status_code == 400
