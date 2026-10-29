"""Pydantic contracts for the forward-looking views of hand-entered assets:
pension-fund Monte Carlo and life-insurance projections.

Only data classes live here: no I/O, no computation.
"""

from pydantic import BaseModel

from backend.wealth_models import InsuranceBranch, PensionProfile


class Percentiles(BaseModel):
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


class PensionScenario(BaseModel):
    """One investment line simulated to retirement. Series are yearly, index 0 = today."""

    profile: PensionProfile
    mu_pct: float  # expected annual return assumed, net of costs and of the yearly tax on returns
    sigma_pct: float  # annual volatility assumed
    p5: list[float]
    p25: list[float]
    p50: list[float]
    p75: list[float]
    p95: list[float]
    gross_at_retirement: Percentiles
    net_at_retirement: Percentiles  # after `tax_pct`
    net_real_p50: float  # median net, in today's euros
    prob_below_paid: float  # % of paths whose net capital ends below the total paid in


class PensionSimulation(BaseModel):
    asset_id: str
    name: str
    current_age: int
    retirement_age: int
    years_to_retirement: int
    years: list[int]  # calendar years of the series
    paid: list[float]  # cumulative contributions (current position counted as paid)
    annual_contribution: float
    tax_pct: float
    inflation_pct: float
    paths: int
    chosen: PensionProfile
    scenarios: list[PensionScenario]


class PolicyProjection(BaseModel):
    """Deterministic projection of one life policy. TCM policies have empty series."""

    asset_id: str
    name: str
    branch: InsuranceBranch | None
    current_value: float
    paid_so_far: float
    annual_premium: float
    insured_capital: float | None
    expected_return_pct: float | None  # None for TCM
    return_is_default: bool  # True: branch default, not typed by the user
    horizon_from_maturity: bool  # False: no maturity date, 10-year horizon
    years: list[int]
    value: list[float]
    paid: list[float]
    guaranteed: list[float] | None  # Ramo I / Ramo I share of a multiramo
