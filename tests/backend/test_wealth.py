"""Net-worth valuation: mortgage amortisation, ownership share, saved portfolios."""

from datetime import date

import pytest

from backend.wealth import (
    build_net_worth,
    mortgage_status,
    value_asset,
    value_saved_portfolio,
)
from backend.wealth_models import (
    AssetKind,
    Mortgage,
    OtherAsset,
    PortfolioValuation,
    SavedHolding,
    SavedPortfolio,
    WealthCategory,
)

LOAN = Mortgage(principal=200_000, annual_rate_pct=3.0, years=25, start_date=date(2020, 1, 15))


def test_mortgage_when_just_started_then_full_balance_and_standard_instalment():
    s = mortgage_status(LOAN, date(2020, 1, 20))
    assert s.months_paid == 0 and s.months_left == 300
    assert s.balance == 200_000
    assert s.monthly_payment == pytest.approx(948.42, abs=0.01)  # standard annuity formula
    assert s.end_date == date(2045, 1, 15)


def test_mortgage_when_five_years_paid_then_balance_matches_amortisation_table():
    s = mortgage_status(LOAN, date(2025, 1, 15))
    assert s.months_paid == 60
    assert s.balance == pytest.approx(171_011, abs=1)  # PV of the 240 instalments left
    assert s.repaid_pct == pytest.approx(14.5, abs=0.1)


def test_mortgage_when_day_not_reached_then_instalment_not_counted():
    assert mortgage_status(LOAN, date(2025, 1, 14)).months_paid == 59


def test_mortgage_when_past_end_then_paid_off():
    s = mortgage_status(LOAN, date(2050, 1, 1))
    assert s.balance == 0 and s.months_left == 0 and s.repaid_pct == 100


def test_mortgage_when_zero_rate_then_linear():
    loan = Mortgage(principal=12_000, annual_rate_pct=0, years=1, start_date=date(2026, 1, 1))
    s = mortgage_status(loan, date(2026, 7, 1))
    assert s.monthly_payment == 1000 and s.balance == 6000


def test_mortgage_when_statement_balance_given_then_it_wins():
    loan = LOAN.model_copy(update={"balance_override": 150_000})
    s = mortgage_status(loan, date(2025, 1, 15))
    assert s.balance == 150_000 and s.from_statement


def test_value_asset_when_half_owned_house_then_value_and_debt_halved():
    house = OtherAsset(
        asset_id="a" * 32, kind=AssetKind.REAL_ESTATE, name="Casa", current_value=400_000,
        invested=300_000, ownership_pct=50, mortgage=LOAN.model_copy(update={"balance_override": 100_000}),
    )
    v = value_asset(house, date(2026, 1, 1))
    assert v.gross_value == 200_000 and v.liability == 50_000 and v.net_value == 150_000
    assert v.gain == 50_000
    assert v.mortgage is not None and v.mortgage.monthly_payment == pytest.approx(474.21, abs=0.01)


def test_saved_portfolio_when_amount_mode_then_sum_plus_cash():
    p = SavedPortfolio(portfolio_id="p1", inputMode="amount", liquidita=500,
                       holdings=[SavedHolding(amount=1000), SavedHolding(amount=None)])
    assert value_saved_portfolio(p).value == 1500


def test_saved_portfolio_when_pct_mode_then_declared_total_or_none():
    assert value_saved_portfolio(SavedPortfolio(portfolio_id="p", portfolioTotal=80_000)).value == 80_000
    assert value_saved_portfolio(SavedPortfolio(portfolio_id="p")).value is None


def test_net_worth_when_mixed_then_categories_and_totals():
    assets = [
        OtherAsset(asset_id="a" * 32, kind=AssetKind.REAL_ESTATE, name="Casa", current_value=300_000,
                   mortgage=LOAN.model_copy(update={"balance_override": 120_000})),
        OtherAsset(asset_id="b" * 32, kind=AssetKind.PENSION_FUND, name="Fondo", current_value=40_000),
        OtherAsset(asset_id="c" * 32, kind=AssetKind.LIFE_INSURANCE, name="Polizza", current_value=60_000),
    ]
    portfolios = [PortfolioValuation(portfolio_id="p1", name="ETF", value=100_000, saved_at="")]
    s = build_net_worth(assets, portfolios, date(2026, 1, 1))
    assert s.total_assets == 500_000 and s.total_liabilities == 120_000 and s.net_worth == 380_000
    assert s.liquid_assets == 100_000
    cats = {c.category: c for c in s.categories}
    assert list(cats) == [WealthCategory.PORTFOLIO, WealthCategory.LIFE_INSURANCE,
                          WealthCategory.PENSION_FUND, WealthCategory.REAL_ESTATE]
    assert cats[WealthCategory.REAL_ESTATE].net == 180_000
    assert cats[WealthCategory.REAL_ESTATE].share_pct == 60.0
    assert [a.name for a in s.assets] == ["Casa", "Polizza", "Fondo"]


def test_net_worth_when_nothing_then_zeros():
    s = build_net_worth([], [], date(2026, 1, 1))
    assert s.net_worth == 0 and s.categories == []


def test_mortgage_when_declared_payment_matches_then_consistent():
    s = mortgage_status(LOAN.model_copy(update={"monthly_payment": 948.0}), date(2025, 1, 15))
    assert s.payment_consistent is True
    assert s.implied_years == pytest.approx(25.0, abs=0.1)


def test_mortgage_when_declared_payment_differs_then_flagged_with_implied_duration():
    s = mortgage_status(LOAN.model_copy(update={"monthly_payment": 1109.0}), date(2025, 1, 15))
    assert s.payment_consistent is False
    assert s.implied_years == pytest.approx(20.0, abs=0.1)  # 1109 €/month repays 200k at 3% in 20 years


def test_mortgage_when_payment_below_interest_then_no_implied_duration():
    s = mortgage_status(LOAN.model_copy(update={"monthly_payment": 400.0}), date(2025, 1, 15))
    assert s.payment_consistent is False and s.implied_years is None


def test_mortgage_when_nothing_declared_then_no_check():
    s = mortgage_status(LOAN, date(2025, 1, 15))
    assert s.payment_consistent is None and s.declared_payment is None
