"""EUR conversion of Yahoo prices (FX pairs, minor units, weekends)."""

import pandas as pd
import pytest
import yfinance

from backend import price_history as ph


def yahoo_close(close: pd.DataFrame) -> pd.DataFrame:
    """Shape of ``yf.download(list)``: MultiIndex columns (field, ticker)."""
    close = close.copy()
    close.columns = pd.MultiIndex.from_product([["Close"], close.columns])
    return close


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("USD", ("USD", 1.0)),
        ("eur", ("EUR", 1.0)),
        (None, ("EUR", 1.0)),
        ("", ("EUR", 1.0)),
        ("GBp", ("GBP", 0.01)),
        ("GBX", ("GBP", 0.01)),
        ("ZAc", ("ZAR", 0.01)),
        ("ILA", ("ILS", 0.01)),
    ],
)
def test_normalize_currency_when_minor_units_then_major_iso_and_factor(raw, expected):
    assert ph.normalize_currency(raw) == expected


@pytest.fixture
def downloaded(monkeypatch: pytest.MonkeyPatch) -> dict:
    idx = pd.to_datetime(["2026-09-24", "2026-09-25", "2026-09-26", "2026-09-28"])  # 26 = Saturday
    close = pd.DataFrame(
        {
            "AAA": [100.0, 102.0, 999.0, 104.0],  # EUR
            "US1": [50.0, 55.0, 999.0, 60.0],  # USD
            "UK1": [2000.0, 2100.0, 999.0, 2200.0],  # GBp (pence)
            "EURUSD=X": [1.10, 1.10, 1.10, 1.20],
            "EURGBP=X": [0.80, 0.80, 0.80, 0.80],
        },
        index=idx,
    )
    calls: dict = {}

    def fake_download(tickers, **kwargs):
        calls["tickers"] = tickers
        calls["kwargs"] = kwargs
        return yahoo_close(close)

    monkeypatch.setattr(yfinance, "download", fake_download)
    return calls


def test_fetch_when_mixed_currencies_then_prices_converted_to_eur(downloaded):
    res = ph.fetch_price_history(
        {"AAA": "EUR", "US1": "USD", "UK1": "GBp"}, pd.Timestamp("2026-09-01").date()
    )
    assert set(downloaded["tickers"]) == {"AAA", "US1", "UK1", "EURUSD=X", "EURGBP=X"}
    assert downloaded["kwargs"]["auto_adjust"] is True  # total-return prices
    assert res.eur["AAA"].tolist() == pytest.approx([100, 102, 104])
    assert res.eur["US1"].tolist() == pytest.approx([50 / 1.1, 55 / 1.1, 60 / 1.2])
    assert res.local["UK1"].tolist() == pytest.approx([20.0, 21.0, 22.0])  # pence → pounds
    assert res.eur["UK1"].tolist() == pytest.approx([25.0, 26.25, 27.5])
    assert res.fx["US1"].tolist() == pytest.approx([1.1, 1.1, 1.2])


def test_fetch_when_weekend_rows_present_then_dropped(downloaded):
    res = ph.fetch_price_history({"AAA": "EUR"}, pd.Timestamp("2026-09-01").date())
    assert all(d.dayofweek < 5 for d in res.index)
    assert len(res.index) == 3


def test_fetch_when_fx_pair_missing_then_ticker_skipped(monkeypatch):
    idx = pd.to_datetime(["2026-09-24", "2026-09-25"])
    close = pd.DataFrame({"AAA": [1.0, 2.0], "JP1": [100.0, 110.0]}, index=idx)
    monkeypatch.setattr(yfinance, "download", lambda tickers, **kw: yahoo_close(close))
    res = ph.fetch_price_history({"AAA": "EUR", "JP1": "JPY"}, idx[0].date())
    assert list(res.eur.columns) == ["AAA"]


def test_fetch_when_ticker_has_no_data_then_missing_from_frames(monkeypatch):
    idx = pd.to_datetime(["2026-09-24", "2026-09-25"])
    close = pd.DataFrame({"AAA": [1.0, 2.0], "DEAD": [float("nan")] * 2}, index=idx)
    monkeypatch.setattr(yfinance, "download", lambda tickers, **kw: yahoo_close(close))
    res = ph.fetch_price_history({"AAA": "EUR", "DEAD": "EUR"}, idx[0].date())
    assert "DEAD" not in res.eur


def test_fetch_when_download_empty_then_empty_history(monkeypatch):
    monkeypatch.setattr(yfinance, "download", lambda tickers, **kw: pd.DataFrame())
    res = ph.fetch_price_history({"AAA": "EUR"}, pd.Timestamp("2026-09-01").date())
    assert res.eur.empty and res.local.empty and res.fx.empty
