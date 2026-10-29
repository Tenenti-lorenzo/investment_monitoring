"""Net worth: values hand-entered assets (mortgage amortisation included) and adds
them to the saved market portfolios. Pure functions, no I/O."""

import calendar
import math
from datetime import date

from backend.wealth_models import (
    AssetValuation,
    CategoryTotal,
    Mortgage,
    MortgageStatus,
    NetWorthSummary,
    OtherAsset,
    PortfolioValuation,
    SavedPortfolio,
    WealthCategory,
)

__all__ = ["build_net_worth", "implied_years", "mortgage_status", "value_asset", "value_saved_portfolio"]


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + end.month - start.month
    return months - (1 if end.day < start.day else 0)


# Bank and app may round differently: within this gap the instalments agree.
PAYMENT_TOLERANCE_PCT = 1.0
PAYMENT_TOLERANCE_EUR = 2.0


def implied_years(principal: float, annual_rate_pct: float, payment: float) -> float | None:
    """Duration that repays `principal` with constant `payment`; None if it never does."""
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return principal / payment / 12
    if payment <= principal * r:  # instalment does not even cover the interest
        return None
    return -math.log(1 - principal * r / payment) / math.log(1 + r) / 12


def mortgage_status(m: Mortgage, today: date, share: float = 1.0) -> MortgageStatus:
    """Residual debt of a constant-instalment mortgage after the instalments paid by `today`.

    Args:
        m: Loan terms; `balance_override` replaces the computed balance.
        today: Valuation date.
        share: Fraction of the loan owed by the user (ownership).

    Returns:
        Balance, instalment and schedule, scaled to `share`.
    """
    n = m.years * 12
    r = m.annual_rate_pct / 100 / 12
    payment = m.principal * r / (1 - (1 + r) ** -n) if r > 0 else m.principal / n
    paid = min(max(_months_between(m.start_date, today), 0), n)
    if m.balance_override is not None:
        balance = m.balance_override
    elif r > 0:
        growth = (1 + r) ** paid
        balance = m.principal * growth - payment * (growth - 1) / r
    else:
        balance = m.principal - payment * paid
    balance = max(balance, 0.0)
    consistent = years = None
    if m.monthly_payment is not None:
        tolerance = max(PAYMENT_TOLERANCE_EUR, payment * PAYMENT_TOLERANCE_PCT / 100)
        consistent = abs(m.monthly_payment - payment) <= tolerance
        n_implied = implied_years(m.principal, m.annual_rate_pct, m.monthly_payment)
        years = round(n_implied, 1) if n_implied is not None else None
    return MortgageStatus(
        balance=round(balance * share, 2),
        monthly_payment=round(payment * share, 2),
        months_paid=paid,
        months_left=n - paid,
        end_date=_add_months(m.start_date, n),
        repaid_pct=round(max(0.0, 1 - balance / m.principal) * 100, 1),
        from_statement=m.balance_override is not None,
        declared_payment=round(m.monthly_payment * share, 2) if m.monthly_payment is not None else None,
        payment_consistent=consistent,
        implied_years=years,
    )


def value_asset(asset: OtherAsset, today: date) -> AssetValuation:
    """User's share of an asset, net of its mortgage."""
    share = asset.ownership_pct / 100
    gross = round(asset.current_value * share, 2)
    mortgage = mortgage_status(asset.mortgage, today, share) if asset.mortgage else None
    liability = mortgage.balance if mortgage else 0.0
    invested = round(asset.invested * share, 2) if asset.invested is not None else None
    return AssetValuation(
        asset_id=asset.asset_id or "",
        kind=asset.kind,
        name=asset.name,
        provider=asset.provider,
        gross_value=gross,
        liability=liability,
        net_value=round(gross - liability, 2),
        invested=invested,
        gain=round(gross - invested, 2) if invested is not None else None,
        mortgage=mortgage,
    )


def value_saved_portfolio(p: SavedPortfolio) -> PortfolioValuation:
    """EUR value as saved on the dashboard (declared amounts, not live prices)."""
    if p.inputMode == "amount":
        value: float | None = sum(h.amount or 0.0 for h in p.holdings) + p.liquidita
    else:
        value = p.portfolioTotal if p.portfolioTotal > 0 else None
    return PortfolioValuation(
        portfolio_id=p.portfolio_id,
        name=p.name,
        value=round(value, 2) if value is not None else None,
        saved_at=p.savedAt,
    )


def build_net_worth(
    assets: list[OtherAsset], portfolios: list[PortfolioValuation], today: date
) -> NetWorthSummary:
    """Totals per category and overall: assets, liabilities (mortgages), net worth."""
    valuations = [value_asset(a, today) for a in assets]
    rows: list[tuple[WealthCategory, float, float]] = [
        (WealthCategory.PORTFOLIO, p.value or 0.0, 0.0) for p in portfolios
    ]
    rows += [(WealthCategory(v.kind.value), v.gross_value, v.liability) for v in valuations]

    total_assets = sum(g for _, g, _ in rows)
    total_liabilities = sum(lia for _, _, lia in rows)
    categories = []
    for cat in WealthCategory:
        mine = [(g, lia) for c, g, lia in rows if c == cat]
        if not mine:
            continue
        gross, liab = sum(g for g, _ in mine), sum(lia for _, lia in mine)
        categories.append(CategoryTotal(
            category=cat,
            gross=round(gross, 2),
            liabilities=round(liab, 2),
            net=round(gross - liab, 2),
            share_pct=round(gross / total_assets * 100, 1) if total_assets > 0 else 0.0,
            count=len(mine),
        ))
    return NetWorthSummary(
        as_of=today,
        total_assets=round(total_assets, 2),
        total_liabilities=round(total_liabilities, 2),
        net_worth=round(total_assets - total_liabilities, 2),
        liquid_assets=round(sum(p.value or 0.0 for p in portfolios), 2),
        categories=categories,
        assets=sorted(valuations, key=lambda v: v.gross_value, reverse=True),
        portfolios=portfolios,
    )
