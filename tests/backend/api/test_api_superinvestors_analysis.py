"""/api/superinvestors*, /api/analysis/* and the static pages."""

import pytest
from fakes import FakeResponse, bdays, fixture_bytes, make_history, random_walk

from backend import deep_analysis, main, superinvestors
from backend.exceptions import InsufficientDataError
from backend.superinvestors import ConsensusStock, Manager

# ─── Superinvestors ───────────────────────────────────────────────────────────


def test_superinvestors_list_when_available_then_managers(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "list_managers", lambda: [Manager(code="BRK", name="Buffett")])
    assert client.get("/api/superinvestors", headers=auth_headers).json()[0]["code"] == "BRK"


def test_superinvestors_list_when_dataroma_down_then_502(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "list_managers", lambda: [])
    assert client.get("/api/superinvestors", headers=auth_headers).status_code == 502


def test_consensus_when_limit_given_then_forwarded_and_validated(client, auth_headers, monkeypatch):
    seen = {}

    def fake(limit):
        seen["limit"] = limit
        return [ConsensusStock(symbol="MSFT")]

    monkeypatch.setattr(main, "fetch_consensus", fake)
    assert client.get("/api/superinvestors/consensus?limit=7", headers=auth_headers).status_code == 200
    assert seen["limit"] == 7
    assert client.get("/api/superinvestors/consensus?limit=0", headers=auth_headers).status_code == 422
    monkeypatch.setattr(main, "fetch_consensus", lambda limit: [])
    assert client.get("/api/superinvestors/consensus", headers=auth_headers).status_code == 502


def test_manager_portfolio_when_scraped_end_to_end_then_holdings(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        superinvestors.requests,
        "get",
        lambda url, **k: FakeResponse(fixture_bytes("dataroma_holdings_BRK.html")),
    )
    body = client.get("/api/superinvestors/brk", headers=auth_headers).json()
    assert body["code"] == "BRK" and len(body["holdings"]) == 29


@pytest.mark.parametrize("code", ["BAD$", "WAYTOOLONGCODE1"])
def test_manager_portfolio_when_code_invalid_then_400(client, auth_headers, code):
    assert client.get(f"/api/superinvestors/{code}", headers=auth_headers).status_code == 400


def test_manager_portfolio_when_unknown_then_404(client, auth_headers, monkeypatch):
    monkeypatch.setattr(main, "fetch_manager_portfolio", lambda code: None)
    assert client.get("/api/superinvestors/NOPE", headers=auth_headers).status_code == 404


def test_overlap_when_many_symbols_then_capped_at_40(client, auth_headers, monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "fetch_portfolio_overlap", lambda s: seen.setdefault("n", len(s)) and [])
    res = client.post(
        "/api/superinvestors/overlap", json={"symbols": [f"S{i}" for i in range(60)]}, headers=auth_headers
    )
    assert res.status_code == 200 and seen["n"] == 40


# ─── Deep analysis / look-through ─────────────────────────────────────────────


@pytest.fixture
def market(monkeypatch: pytest.MonkeyPatch) -> None:
    idx = bdays(300)
    ph = make_history(
        {
            "AAA": random_walk(idx, seed=1),
            "BBB": random_walk(idx, seed=2, vol=0.004),
            "SWDA.MI": random_walk(idx, seed=3),
            "IEAG.MI": random_walk(idx, seed=4, vol=0.003),
        }
    )
    monkeypatch.setattr(deep_analysis, "fetch_price_history", lambda cur, start: ph)
    monkeypatch.setattr(deep_analysis, "_resolve_currencies", lambda t: t)


BODY = {
    "holdings": [
        {"ticker": "AAA", "yf_ticker": "AAA", "category": "Azioni", "currency": "EUR", "amount": 6000},
        {
            "ticker": "BBB",
            "yf_ticker": "BBB",
            "category": "ETF Obbligazionario",
            "currency": "EUR",
            "amount": 3000,
        },
    ],
    "liquidita": 1000,
    "lookback_years": 1,
}


def test_deep_when_valid_then_full_report(client, auth_headers, market):
    res = client.post("/api/analysis/deep", json=BODY, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["current_value"] == pytest.approx(10_000)
    assert {c["category"] for c in body["classes"]} == {"Azioni", "ETF Obbligazionario", "Liquidità"}
    for key in (
        "equity_curve",
        "risk",
        "correlation",
        "frontier",
        "distribution",
        "monte_carlo",
        "alternatives",
        "allocation_over_time",
    ):
        assert body[key] is not None, key
    assert len(body["alternatives"]["items"]) == 4


@pytest.mark.parametrize(
    "patch", [{"lookback_years": 0}, {"lookback_years": 11}, {"risk_free": 0.5}, {"liquidita": -1}]
)
def test_deep_when_parameters_out_of_range_then_422(client, auth_headers, patch):
    assert client.post("/api/analysis/deep", json={**BODY, **patch}, headers=auth_headers).status_code == 422


def test_deep_when_empty_then_400(client, auth_headers):
    res = client.post("/api/analysis/deep", json={"holdings": []}, headers=auth_headers)
    assert res.status_code == 400


def test_deep_when_insufficient_history_then_422_with_message(client, auth_headers, monkeypatch):
    def fail(req):
        raise InsufficientDataError("Storico troppo breve")

    monkeypatch.setattr(main, "run_deep_analysis", fail)
    res = client.post("/api/analysis/deep", json=BODY, headers=auth_headers)
    assert res.status_code == 422 and res.json()["detail"] == "Storico troppo breve"


def test_look_through_when_yahoo_unavailable_then_fallback_report(client, auth_headers):
    res = client.post("/api/analysis/look-through", json=BODY, headers=auth_headers)
    assert res.status_code == 200
    classes = {s["label"]: s["pct"] for s in res.json()["asset_classes"]}
    assert classes == {"Azioni": 60.0, "Obbligazioni": 30.0, "Liquidità": 10.0}


def test_look_through_when_empty_then_400(client, auth_headers):
    assert (
        client.post("/api/analysis/look-through", json={"holdings": []}, headers=auth_headers).status_code
        == 400
    )


def test_analysis_when_not_authenticated_then_rejected(client):
    assert client.post("/api/analysis/deep", json=BODY).status_code in (401, 403)


# ─── Static pages ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,marker", [("/", "PortfolioLab"), ("/login", "<html"), ("/analisi", "Analisi approfondita")]
)
def test_static_pages_when_requested_then_html(client, path, marker):
    res = client.get(path)
    assert res.status_code == 200 and marker in res.text


def test_static_assets_when_requested_then_served(client):
    for asset in ("/static/js/analisi.js", "/static/js/analisi-charts.js", "/static/css/analisi.css"):
        assert client.get(asset).status_code == 200, asset
