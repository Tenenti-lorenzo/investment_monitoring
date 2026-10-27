"""backend.fx_rates and GET /api/fx/{currency}."""

import pytest
from fakes import FakeTicker, ticker_factory

from backend import fx_rates


@pytest.fixture
def yahoo_fx(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """EURUSD 1.10, EURGBP 0.85; returns the list of symbols requested."""
    calls: list[str] = []
    tickers = {"EURUSD=X": FakeTicker(last_price=1.10), "EURGBP=X": FakeTicker(last_price=0.85)}
    factory = ticker_factory(tickers)

    def ticker(symbol: str) -> FakeTicker:
        calls.append(symbol)
        return factory(symbol)

    monkeypatch.setattr(fx_rates.yf, "Ticker", ticker)
    return calls


def test_fetch_eur_rate_when_eur_then_one_without_lookup(yahoo_fx):
    assert fx_rates.fetch_eur_rate("EUR").per_eur == 1.0
    assert yahoo_fx == []


def test_fetch_eur_rate_when_usd_then_yahoo_pair_and_cached(yahoo_fx):
    assert fx_rates.fetch_eur_rate("USD").per_eur == 1.10
    fx_rates.fetch_eur_rate("USD")
    assert yahoo_fx == ["EURUSD=X"]


def test_fetch_eur_rate_when_pence_then_gbp_times_100(yahoo_fx):
    assert fx_rates.fetch_eur_rate("GBp").per_eur == pytest.approx(85.0)


def test_fetch_eur_rate_when_pair_unavailable_then_none_and_not_cached(yahoo_fx):
    assert fx_rates.fetch_eur_rate("CHF").per_eur is None
    fx_rates.fetch_eur_rate("CHF")
    assert yahoo_fx == ["EURCHF=X", "EURCHF=X"]


def test_api_fx_when_authenticated_then_rate(client, auth_headers, yahoo_fx):
    res = client.get("/api/fx/USD", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["per_eur"] == 1.10


@pytest.mark.parametrize("currency", ["US", "USDX", "U$D"])
def test_api_fx_when_malformed_currency_then_400(client, auth_headers, currency):
    assert client.get(f"/api/fx/{currency}", headers=auth_headers).status_code == 400
