"""Deep analysis: TWR/MWR, P&L attribution (price vs FX), allocation, risk view."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from fakes import bdays, make_history, random_walk

from backend import deep_analysis as da
from backend.analysis_models import AnalysisHolding, DeepAnalysisRequest
from backend.bond_market import BondQuote
from backend.exceptions import InsufficientDataError

N = 300


@pytest.fixture
def idx() -> pd.DatetimeIndex:
    return bdays(N)


def install(monkeypatch: pytest.MonkeyPatch, ph) -> None:
    monkeypatch.setattr(da, "fetch_price_history", lambda currencies, start: ph)
    monkeypatch.setattr(da, "_resolve_currencies", lambda tickers: tickers)


def holding(ticker: str, **kw) -> AnalysisHolding:
    return AnalysisHolding(
        ticker=ticker,
        yf_ticker=kw.pop("yf_ticker", ticker),
        name=kw.pop("name", ticker),
        category=kw.pop("category", "Azioni"),
        currency=kw.pop("currency", "EUR"),
        **kw,
    )


def day(idx: pd.DatetimeIndex, i: int) -> str:
    return str(idx[i].date())


# ─── parse_date ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-06-15", date(2024, 6, 15)),
        ("15/06/2024", date(2024, 6, 15)),
        ("15-06-2024", date(2024, 6, 15)),
        ("2024-06-15T10:00:00", date(2024, 6, 15)),
        ("", None),
        (None, None),
        ("giugno 2024", None),
    ],
)
def test_parse_date_when_formats_vary_then_iso_italian_or_none(raw, expected):
    assert da.parse_date(raw) == expected


# ─── TWR vs MWR ───────────────────────────────────────────────────────────────


def test_twr_when_money_added_before_a_fall_then_twr_positive_and_mwr_negative(monkeypatch, idx):
    # Price 100 → 150 (day 100) → 120 (end). Buy 1 unit day 0, 10 units at the peak.
    path = np.concatenate([np.linspace(100, 150, 101), np.linspace(150, 120, N - 101)])
    ph = make_history({"AAA": pd.Series(path, index=idx), "BBB": pd.Series(path, index=idx)})
    install(monkeypatch, ph)
    req = DeepAnalysisRequest(
        holdings=[
            holding("AAA", quantity=1, purchase_date=day(idx, 0)),
            holding("BBB", quantity=10, purchase_date=day(idx, 100)),
        ],
        lookback_years=1,
    )

    res = da.run_deep_analysis(req)

    assert res.summary.twr == pytest.approx(20.0, abs=0.01)  # instruments: 100 → 120
    assert res.summary.invested == pytest.approx(100 + 1500)
    assert res.summary.current_value == pytest.approx(11 * 120)
    assert res.summary.pl_eur == pytest.approx(-280)
    assert res.summary.mwr < 0 < res.summary.twr  # bad timing hurts the investor


def test_twr_when_flows_at_constant_growth_then_equals_price_return(monkeypatch, idx):
    path = pd.Series(100 * 1.001 ** np.arange(N), index=idx)
    install(monkeypatch, make_history({"AAA": path, "BBB": path}))
    req = DeepAnalysisRequest(
        holdings=[
            holding("AAA", quantity=5, purchase_date=day(idx, 0)),
            holding("BBB", quantity=50, purchase_date=day(idx, 200)),
        ],
        lookback_years=1,
    )
    res = da.run_deep_analysis(req)
    assert res.summary.twr == pytest.approx((1.001 ** (N - 1) - 1) * 100, abs=0.01)
    assert res.equity_curve.drawdown == pytest.approx([0.0] * len(res.equity_curve.drawdown))


def test_equity_curve_when_positions_start_later_then_invested_steps_up(monkeypatch, idx):
    path = pd.Series(100.0, index=idx)
    install(monkeypatch, make_history({"AAA": path, "BBB": path}))
    req = DeepAnalysisRequest(
        holdings=[
            holding("AAA", quantity=1, purchase_date=day(idx, 0)),
            holding("BBB", quantity=2, purchase_date=day(idx, 150)),
        ],
        liquidita=50,
    )
    curve = da.run_deep_analysis(req).equity_curve
    assert curve.invested[0] == pytest.approx(150)  # 100 + cash
    assert curve.invested[-1] == pytest.approx(350)
    assert curve.value == pytest.approx(curve.invested)  # flat prices


def test_purchase_price_when_given_then_cost_uses_it_not_market(monkeypatch, idx):
    install(monkeypatch, make_history({"AAA": pd.Series(100.0, index=idx)}))
    req = DeepAnalysisRequest(
        holdings=[holding("AAA", quantity=10, purchase_price=80, purchase_date=day(idx, 0))]
    )
    h = da.run_deep_analysis(req).holdings[0]
    assert h.cost == pytest.approx(800)
    assert h.value == pytest.approx(1000)
    assert h.pl_pct == pytest.approx(25.0)


# ─── Price vs FX attribution ──────────────────────────────────────────────────


def test_attribution_when_only_fx_moves_then_all_pl_is_fx_effect(monkeypatch, idx):
    usd_price = pd.Series(100.0, index=idx)
    eurusd = pd.Series(np.linspace(1.0, 1.25, N), index=idx)  # USD weakens
    install(monkeypatch, make_history({"US": usd_price}, fx={"US": eurusd}))
    req = DeepAnalysisRequest(
        holdings=[holding("US", currency="USD", quantity=10, purchase_date=day(idx, 0))]
    )
    h = da.run_deep_analysis(req).holdings[0]
    assert h.cost == pytest.approx(1000)
    assert h.value == pytest.approx(800)
    assert h.price_effect == pytest.approx(0.0)
    assert h.fx_effect == pytest.approx(-200)


def test_attribution_when_price_and_fx_move_then_effects_reconcile_to_pl(monkeypatch, idx):
    usd_price = pd.Series(np.linspace(100, 130, N), index=idx)
    eurusd = pd.Series(np.linspace(1.10, 1.05, N), index=idx)
    install(monkeypatch, make_history({"US": usd_price}, fx={"US": eurusd}))
    req = DeepAnalysisRequest(holdings=[holding("US", currency="USD", quantity=7, purchase_date=day(idx, 0))])
    h = da.run_deep_analysis(req).holdings[0]
    assert h.price_effect == pytest.approx(7 * 30 / 1.10, abs=0.01)
    assert h.price_effect + h.fx_effect == pytest.approx(h.pl_eur, abs=0.02)


# ─── Classes, drift, allocation over time ─────────────────────────────────────


@pytest.fixture
def mixed_request(idx) -> DeepAnalysisRequest:
    return DeepAnalysisRequest(
        holdings=[
            holding("EQ", category="ETF Azionario", quantity=10, purchase_date=day(idx, 0)),
            holding("BD", category="ETF Obbligazionario", quantity=10, purchase_date=day(idx, 0)),
        ],
        liquidita=500,
    )


def test_classes_when_mixed_then_contributions_sum_to_total_return(monkeypatch, idx, mixed_request):
    install(
        monkeypatch,
        make_history({"EQ": random_walk(idx, seed=1, vol=0.02), "BD": random_walk(idx, seed=2, vol=0.003)}),
    )
    res = da.run_deep_analysis(mixed_request)
    names = [c.category for c in res.classes]
    assert set(names) == {"ETF Azionario", "ETF Obbligazionario", "Liquidità"}
    assert sum(c.contribution_pp for c in res.classes) == pytest.approx(res.summary.pl_pct, abs=0.05)
    assert sum(c.drift_pp for c in res.classes) == pytest.approx(0.0, abs=0.05)
    assert sum(c.weight_now_pct for c in res.classes) == pytest.approx(100, abs=0.05)
    liq = next(c for c in res.classes if c.category == "Liquidità")
    assert liq.pl_eur == 0


def test_allocation_over_time_when_rendered_then_each_date_sums_to_100(monkeypatch, idx, mixed_request):
    install(monkeypatch, make_history({"EQ": random_walk(idx, seed=1), "BD": random_walk(idx, seed=2)}))
    aot = da.run_deep_analysis(mixed_request).allocation_over_time
    for i in range(len(aot.dates)):
        assert sum(s.values[i] for s in aot.series) == pytest.approx(100, abs=0.2)


# ─── Lookback risk view ───────────────────────────────────────────────────────


def test_window_returns_when_half_cash_then_volatility_halves(monkeypatch, idx):
    px = random_walk(idx, seed=4, vol=0.02)
    install(monkeypatch, make_history({"AAA": px}))
    solo = da.run_deep_analysis(DeepAnalysisRequest(holdings=[holding("AAA", amount=1000)]))
    half = da.run_deep_analysis(DeepAnalysisRequest(holdings=[holding("AAA", amount=1000)], liquidita=1000))
    assert half.risk.volatility == pytest.approx(solo.risk.volatility / 2, rel=0.01)
    asset_vol = px.pct_change().dropna().std() * np.sqrt(252) * 100
    assert solo.risk.volatility == pytest.approx(asset_vol, rel=0.01)


def test_run_when_benchmark_and_proxies_present_then_alternatives_and_beta(monkeypatch, idx):
    eq = random_walk(idx, seed=7, vol=0.012)
    ph = make_history({"AAA": eq, "SWDA.MI": eq, "IEAG.MI": random_walk(idx, seed=8, vol=0.003)})
    install(monkeypatch, ph)
    res = da.run_deep_analysis(DeepAnalysisRequest(holdings=[holding("AAA", amount=1000)]))
    assert res.benchmark == "SWDA.MI"
    assert res.risk.beta == pytest.approx(1.0, abs=0.01)
    names = [a.name for a in res.alternatives.items]
    assert names == ["Il tuo portafoglio", "100% azionario", "80/20", "60/40"]
    assert all(a.values[0] == 10_000 for a in res.alternatives.items)
    assert all(len(a.values) == len(res.alternatives.dates) for a in res.alternatives.items)


def test_run_when_no_proxies_then_only_own_portfolio_in_alternatives(monkeypatch, idx):
    install(monkeypatch, make_history({"AAA": random_walk(idx)}))
    res = da.run_deep_analysis(DeepAnalysisRequest(holdings=[holding("AAA", amount=1000)]))
    assert [a.name for a in res.alternatives.items] == ["Il tuo portafoglio"]
    assert res.benchmark == "" and res.benchmark_risk is None


# ─── Static holdings, notional mode, errors ───────────────────────────────────


def test_bond_when_no_history_then_valued_from_quote_and_excluded(monkeypatch, idx):
    install(monkeypatch, make_history({"AAA": random_walk(idx)}))
    monkeypatch.setattr(da, "fetch_bond_quote", lambda isin: BondQuote(isin=isin, price=90.0))
    req = DeepAnalysisRequest(
        holdings=[
            holding("AAA", amount=900),
            AnalysisHolding(
                ticker="BTP", isin="IT0005436693", category="Obbligazioni", quantity=1000, purchase_price=95
            ),
        ]
    )
    res = da.run_deep_analysis(req)
    btp = next(h for h in res.holdings if h.ticker == "BTP")
    assert (btp.cost, btp.value, btp.pl_eur) == (950, 900, -50)
    assert res.excluded == ["BTP"]
    assert res.coverage_pct == pytest.approx(50.0, abs=0.5)


def test_notional_when_only_percentages_then_amounts_on_10k(monkeypatch, idx):
    install(monkeypatch, make_history({"AAA": random_walk(idx), "BBB": random_walk(idx, seed=9)}))
    req = DeepAnalysisRequest(holdings=[holding("AAA", allocation=60), holding("BBB", allocation=40)])
    res = da.run_deep_analysis(req)
    assert res.notional is True
    assert res.summary.current_value == pytest.approx(10_000, abs=1)
    assert res.assumed_dates == ["AAA", "BBB"]


def test_run_when_no_price_history_then_insufficient_data(monkeypatch):
    install(monkeypatch, make_history({"ZZZ": pd.Series([1.0], index=bdays(1))}))
    with pytest.raises(InsufficientDataError):
        da.run_deep_analysis(DeepAnalysisRequest(holdings=[holding("AAA", amount=100)]))


def test_run_when_history_too_short_then_insufficient_data(monkeypatch):
    short = bdays(10)
    install(monkeypatch, make_history({"AAA": random_walk(short)}))
    with pytest.raises(InsufficientDataError):
        da.run_deep_analysis(DeepAnalysisRequest(holdings=[holding("AAA", amount=100)]))


def test_thin_when_series_long_then_keeps_last_point_and_limit():
    keep = da._thin(1000, 100)
    assert keep[-1] == 999 and len(keep) <= 101
    assert da._thin(50, 100) == list(range(50))
