"""Look-through (X-Ray): bond math, ETF profiles, overlap, costs, aggregation."""

import math

import pandas as pd
import pytest
import yfinance
from fakes import FakeFundsData, FakeTicker, ticker_factory, top_holdings

from backend import look_through as lt
from backend.analysis_models import AnalysisHolding, DeepAnalysisRequest
from backend.bond_market import BondQuote

# ─── Bond yield / duration ────────────────────────────────────────────────────


def test_bond_math_when_par_bond_then_yield_equals_coupon_and_textbook_duration():
    ytm, dur = lt.bond_yield_duration(price=100, coupon_pct=5, years=5, freq=1)
    assert ytm == pytest.approx(5.0, abs=0.01)
    mac = sum(t * 5 / 1.05**t for t in range(1, 6)) + 5 * 100 / 1.05**5
    assert dur == pytest.approx(round(mac / 100 / 1.05, 2), abs=0.01)  # 4.33


def test_bond_math_when_zero_coupon_then_duration_is_maturity_over_one_plus_y():
    price = 100 / 1.04**3
    ytm, dur = lt.bond_yield_duration(price, 0, 3, 1)
    assert ytm == pytest.approx(4.0, abs=0.01)
    assert dur == pytest.approx(3 / 1.04, abs=0.01)


@pytest.mark.parametrize("years", [10.001, 9.75, 9.51, 9.999])
def test_bond_math_when_par_bond_mid_coupon_period_then_accrued_keeps_yield_at_coupon(years):
    # Regression: clean price vs full coupons overstated the yield right before a coupon date.
    ytm, _ = lt.bond_yield_duration(100, 4, years, 2)
    assert ytm == pytest.approx(4.0, abs=0.02)


def test_bond_math_when_below_par_then_yield_above_coupon():
    ytm, _ = lt.bond_yield_duration(90, 2, 6, 2)
    assert ytm > 2


def test_bond_math_when_semiannual_then_modified_duration_below_maturity():
    _, dur = lt.bond_yield_duration(100, 4, 10, 2)
    assert 7.5 < dur < 10


@pytest.mark.parametrize("price,years", [(0, 5), (100, 0), (-1, 5), (1e6, 5)])
def test_bond_math_when_invalid_inputs_then_none(price, years):
    assert lt.bond_yield_duration(price, 3, years) is None


def test_bond_profile_when_quote_found_then_detail_with_yield_duration(monkeypatch):
    monkeypatch.setattr(
        lt,
        "fetch_bond_quote",
        lambda isin: BondQuote(
            isin=isin, price=100.0, maturity="2036-09-27", coupon_annual_pct=4.0, coupon_period_pct=2.0
        ),
    )
    prof = lt._bond_profile(AnalysisHolding(ticker="B", isin="IT1", category="Obbligazioni"))
    assert prof.asset_classes == {"Obbligazioni": 1.0}
    assert prof.bond.coupon_pct == 4.0 and prof.bond.ytm_pct == pytest.approx(4.0, abs=0.1)
    assert prof.duration == prof.bond.duration and prof.duration > 7


def test_bond_profile_when_coupon_unknown_then_duration_kept_yield_hidden(monkeypatch):
    monkeypatch.setattr(
        lt,
        "fetch_bond_quote",
        lambda isin: BondQuote(isin=isin, price=85.41, maturity="2031-08-01", coupon_period_pct=0.3),
    )
    prof = lt._bond_profile(AnalysisHolding(ticker="B", isin="IT1", category="Obbligazioni"))
    assert prof.bond.ytm_pct is None
    assert prof.bond.duration is not None


# ─── Instrument profiles ──────────────────────────────────────────────────────


def world_etf() -> FakeTicker:
    return FakeTicker(
        funds_data=FakeFundsData(
            asset_classes={"stockPosition": 0.99, "cashPosition": 0.01, "bondPosition": 0.0},
            sector_weightings={"technology": 0.30, "financial_services": 0.16, "realestate": 0.02},
            top_holdings=top_holdings({"AAPL": ("Apple Inc", 0.05), "MSFT": ("Microsoft Corp", 0.03)}),
            fund_operations=pd.DataFrame({"X": [0.002]}, index=["Annual Report Expense Ratio"]),
        )
    )


def bond_etf() -> FakeTicker:
    return FakeTicker(
        funds_data=FakeFundsData(
            asset_classes={"bondPosition": 1.0},
            bond_ratings={"aaa": 0.3, "a": 0.5, "bbb": 0.2, "us_government": 0.7},
            bond_holdings=pd.DataFrame({"X": [6.5, 9.0]}, index=["Duration", "Maturity"]),
        )
    )


def test_etf_profile_when_funds_data_then_classes_sectors_ter_in_italian(monkeypatch):
    monkeypatch.setattr(yfinance, "Ticker", ticker_factory({"SWDA.MI": world_etf()}))
    prof = lt._etf_profile(AnalysisHolding(ticker="SWDA", yf_ticker="SWDA.MI", category="ETF Azionario"))
    assert prof.asset_classes == {"Azioni": 0.99, "Liquidità": 0.01}
    assert prof.sectors == {"Tecnologia": 0.30, "Finanza": 0.16, "Immobiliare": 0.02}
    assert prof.ter == pytest.approx(0.2)
    assert prof.top_holdings["AAPL"] == ("Apple Inc", 0.05)
    assert prof.duration is None


def test_etf_profile_when_bond_etf_then_ratings_and_duration(monkeypatch):
    monkeypatch.setattr(yfinance, "Ticker", ticker_factory({"IEAG.MI": bond_etf()}))
    prof = lt._etf_profile(
        AnalysisHolding(ticker="IEAG", yf_ticker="IEAG.MI", category="ETF Obbligazionario")
    )
    assert prof.duration == 6.5
    assert prof.ratings == {"aaa": 0.3, "a": 0.5, "bbb": 0.2}  # us_government is not a rating


def test_stock_profile_when_info_sector_then_mapped_and_self_as_holding(monkeypatch):
    monkeypatch.setattr(
        yfinance, "Ticker", ticker_factory({"MSFT": FakeTicker(info={"sector": "Technology"})})
    )
    prof = lt._stock_profile(AnalysisHolding(ticker="MSFT", name="Microsoft", category="Azioni"))
    assert prof.sectors == {"Tecnologia": 1.0}
    assert prof.top_holdings == {"MSFT": ("Microsoft", 1.0)}


@pytest.mark.parametrize(
    "category,expected",
    [
        ("ETF Azionario", "Azioni"),
        ("Obbligazioni", "Obbligazioni"),
        ("ETF Obbligazionario", "Obbligazioni"),
        ("Criptovalute", "Cripto"),
        ("ETF Materie Prime", "Altro"),
    ],
)
def test_profile_when_yahoo_fails_then_fallback_by_category(category, expected):
    # offline guard makes yfinance raise → _profile must degrade, never crash
    prof = lt._profile(AnalysisHolding(ticker="X", yf_ticker="X", category=category))
    assert prof.asset_classes == {expected: 1.0}


# ─── Portfolio aggregation ────────────────────────────────────────────────────


@pytest.fixture
def portfolio(monkeypatch: pytest.MonkeyPatch) -> DeepAnalysisRequest:
    etf_b = FakeTicker(
        funds_data=FakeFundsData(
            asset_classes={"stockPosition": 1.0},
            sector_weightings={"technology": 0.5, "healthcare": 0.5},
            top_holdings=top_holdings({"AAPL": ("Apple Inc", 0.04), "MSFT": ("Microsoft Corp", 0.06)}),
        )
    )
    monkeypatch.setattr(
        yfinance,
        "Ticker",
        ticker_factory(
            {
                "SWDA.MI": world_etf(),
                "SWRD.L": etf_b,
                "IEAG.MI": bond_etf(),
                "AAPL": FakeTicker(info={"sector": "Technology"}),
            }
        ),
    )
    return DeepAnalysisRequest(
        holdings=[
            AnalysisHolding(
                ticker="SWDA",
                yf_ticker="SWDA.MI",
                name="iShares Core MSCI World",
                category="ETF Azionario",
                currency="EUR",
                amount=4000,
                ter=0.2,
                geography={"Nord America": 70, "Europa": 30},
            ),
            AnalysisHolding(
                ticker="SWRD",
                yf_ticker="SWRD.L",
                name="SPDR World EUR Hedged",
                category="ETF Azionario",
                currency="GBp",
                amount=2000,
                ter=0.12,
                geography={"Nord America": 70, "Europa": 30},
            ),
            AnalysisHolding(
                ticker="IEAG",
                yf_ticker="IEAG.MI",
                name="Euro Aggregate",
                category="ETF Obbligazionario",
                currency="EUR",
                amount=3000,
                ter=0.1,
                geography={"Europa": 100},
            ),
            AnalysisHolding(
                ticker="AAPL",
                yf_ticker="AAPL",
                name="Apple",
                category="Azioni",
                currency="USD",
                amount=1000,
                geography={"Nord America": 100},
            ),
        ],
        liquidita=0,
    )


def test_look_through_when_mixed_then_asset_classes_sum_to_100(portfolio):
    res = lt.run_look_through(portfolio)
    classes = {s.label: s.pct for s in res.asset_classes}
    assert sum(classes.values()) == pytest.approx(100, abs=0.1)
    assert classes["Obbligazioni"] == pytest.approx(30.0)
    assert classes["Azioni"] == pytest.approx((4000 * 0.99 + 2000 + 1000) / 100, abs=0.01)


def test_look_through_when_same_stock_in_many_funds_then_exposure_aggregated(portfolio):
    res = lt.run_look_through(portfolio)
    aapl = next(e for e in res.top_exposures if e.symbol == "AAPL")
    # direct 1000 + 4000×5% + 2000×4% = 1280 on 10000
    assert aapl.weight_pct == pytest.approx(12.8)
    assert set(aapl.sources) == {"SWDA", "SWRD", "AAPL"}


def test_overlap_when_two_etfs_share_holdings_then_sum_of_min_weights(portfolio):
    res = lt.run_look_through(portfolio)
    pair = res.overlaps[0]
    assert {pair.a, pair.b} == {"SWDA", "SWRD"}
    assert pair.overlap_pct == pytest.approx(min(5, 4) + min(3, 6))


def test_costs_when_ters_known_then_annual_weighted_and_10y(portfolio):
    res = lt.run_look_through(portfolio)
    annual = 4000 * 0.002 + 2000 * 0.0012 + 3000 * 0.001
    assert res.annual_cost == pytest.approx(annual)
    assert res.ter_weighted == pytest.approx(annual / 10_000 * 100, abs=0.001)
    assert res.cost_10y == pytest.approx(annual * 10)
    stock = next(c for c in res.costs if c.ticker == "AAPL")
    assert stock.ter is None and stock.annual_cost is None


def test_costs_when_stored_ter_implausible_then_yahoo_ter_used(portfolio):
    portfolio.holdings[0].ter = 20.0  # legacy ×100 unit error for a 0.20 % ETF
    res = lt.run_look_through(portfolio)
    swda = next(c for c in res.costs if c.ticker == "SWDA")
    assert swda.ter == pytest.approx(0.2)  # from fund_operations (fraction 0.002)
    assert swda.annual_cost == pytest.approx(8.0)


def test_currency_and_hedging_when_gbp_pence_and_hedged_name_then_normalised(portfolio):
    res = lt.run_look_through(portfolio)
    cur = {s.label: s.pct for s in res.currencies}
    assert cur == {"EUR": 70.0, "GBP": 20.0, "USD": 10.0}
    assert res.hedged_pct == 20.0


def test_bonds_when_bond_etf_then_duration_and_credit_in_rating_order(portfolio):
    res = lt.run_look_through(portfolio)
    assert res.portfolio_duration == 6.5
    assert [s.label for s in res.credit_quality] == ["AAA", "A", "BBB"]
    assert sum(s.pct for s in res.credit_quality) == pytest.approx(100, abs=0.2)
    assert res.bonds[0].kind == "ETF Obbligazionario" and res.bonds[0].weight_pct == 30.0


def test_sectors_and_geography_when_weighted_then_normalised_to_100(portfolio):
    res = lt.run_look_through(portfolio)
    assert sum(s.pct for s in res.sectors) == pytest.approx(100, abs=0.2)
    geo = {s.label: s.pct for s in res.geography}
    assert geo["Europa"] == pytest.approx((4000 * 0.3 + 2000 * 0.3 + 3000) / 100)


@pytest.mark.parametrize(
    "h,expected",
    [
        (AnalysisHolding(ticker="A", amount=500), 500.0),
        (AnalysisHolding(ticker="B", quantity=10, purchase_price=20), 200.0),
        (AnalysisHolding(ticker="C", category="Obbligazioni", quantity=1000, purchase_price=95), 950.0),
        (AnalysisHolding(ticker="D", quantity=3), 0.0),
    ],
)
def test_weights_when_amount_or_quantity_then_eur_value(h, expected):
    other = AnalysisHolding(ticker="Z", amount=1)
    assert lt._weights(DeepAnalysisRequest(holdings=[h, other]))[0] == expected


def test_weights_when_only_percentages_then_notional_10k():
    req = DeepAnalysisRequest(holdings=[AnalysisHolding(ticker="A", allocation=25)])
    assert lt._weights(req) == [2500.0]


def test_fund_field_when_missing_or_nan_then_none():
    fd = FakeFundsData(bond_holdings=pd.DataFrame({"X": [math.nan]}, index=["Duration"]))
    assert lt._fund_field(fd, "bond_holdings", "Duration") is None
    assert lt._fund_field(fd, "fund_operations", "Annual Report Expense Ratio") is None
