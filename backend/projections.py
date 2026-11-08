"""Forward-looking views of hand-entered assets: pension-fund Monte Carlo to
retirement and deterministic life-policy projections. Pure functions, no I/O."""

import math
from datetime import date

import numpy as np

from backend.exceptions import ProjectionInputError
from backend.projection_models import (
    PensionScenario,
    PensionSimulation,
    Percentiles,
    PolicyProjection,
)
from backend.wealth_models import AssetKind, InsuranceBranch, OtherAsset, PensionProfile

__all__ = ["POLICY_DEFAULT_RETURN", "PROFILE_ASSUMPTIONS", "project_policy", "simulate_pension"]

# Long-run (expected return %, volatility %) per line, net of fund costs and of
# the yearly 20% tax on returns. Rough market-consensus figures, not forecasts.
PROFILE_ASSUMPTIONS: dict[PensionProfile, tuple[float, float]] = {
    PensionProfile.CONSERVATIVE: (2.0, 3.5),
    PensionProfile.BALANCED: (3.5, 8.0),
    PensionProfile.DYNAMIC: (5.0, 13.0),
}
INFLATION_PCT = 2.0  # ECB target, used to express results in today's euros
PATHS = 2000
SEED = 7

# Expected yearly return when the user leaves it blank.
POLICY_DEFAULT_RETURN: dict[InsuranceBranch, float] = {
    InsuranceBranch.RAMO_I: 2.5,  # recent gestioni separate yields, net of fees
    InsuranceBranch.RAMO_III: 4.5,
    InsuranceBranch.OTHER: 3.0,
}
MULTIRAMO_DEFAULT_RAMO_I_SHARE = 50.0
POLICY_DEFAULT_HORIZON = 10
POLICY_MAX_HORIZON = 60  # caps a far-future maturity date (payload and loop size)


def _percentiles(values: np.ndarray) -> Percentiles:
    p5, p25, p50, p75, p95 = (round(float(v), 0) for v in np.percentile(values, [5, 25, 50, 75, 95]))
    return Percentiles(p5=p5, p25=p25, p50=p50, p75=p75, p95=p95)


def _simulate_profile(
    profile: PensionProfile, start: float, monthly: float, months: int, z: np.ndarray
) -> np.ndarray:
    """Monthly log-normal paths with contributions at month end; returns yearly values (paths × years+1)."""
    mu, sigma = (x / 100 for x in PROFILE_ASSUMPTIONS[profile])
    drift = (math.log1p(mu) - sigma**2 / 2) / 12  # mean annual growth = mu
    growth = np.exp(drift + sigma / math.sqrt(12) * z)
    values = np.full(z.shape[0], start, dtype=float)
    yearly = [values.copy()]
    for t in range(months):
        values = values * growth[:, t] + monthly
        if (t + 1) % 12 == 0:
            yearly.append(values.copy())
    return np.stack(yearly, axis=1)


def _scenario(
    profile: PensionProfile, yearly: np.ndarray, paid_final: float, tax: float, years: int
) -> PensionScenario:
    q = np.percentile(yearly, [5, 25, 50, 75, 95], axis=0)
    final = yearly[:, -1]
    net = final * (1 - tax / 100)
    mu, sigma = PROFILE_ASSUMPTIONS[profile]
    net_p = _percentiles(net)

    def row(i: int) -> list[float]:
        return [round(float(v), 0) for v in q[i]]

    return PensionScenario(
        profile=profile,
        mu_pct=mu,
        sigma_pct=sigma,
        p5=row(0),
        p25=row(1),
        p50=row(2),
        p75=row(3),
        p95=row(4),
        gross_at_retirement=_percentiles(final),
        net_at_retirement=net_p,
        net_real_p50=round(net_p.p50 / (1 + INFLATION_PCT / 100) ** years, 0),
        prob_below_paid=round(float((net < paid_final).mean()) * 100, 1),
    )


def simulate_pension(asset: OtherAsset, today: date, paths: int = PATHS, seed: int = SEED) -> PensionSimulation:
    """Monte Carlo of a pension position to retirement, for every investment line.

    All lines share the same random draws, so differences come from the line only.

    Raises:
        ProjectionInputError: not a pension fund, missing birth year / tax rate /
            line, or already at retirement age.
    """
    if asset.kind != AssetKind.PENSION_FUND:
        raise ProjectionInputError("La simulazione vale solo per i fondi pensione")
    missing = [label for label, v in (("anno di nascita", asset.birth_year), ("tasse alla pensione", asset.tax_pct),
                                      ("profilo di investimento", asset.pension_profile)) if v is None]
    if missing:
        raise ProjectionInputError("Per la simulazione servono: " + ", ".join(missing))
    assert asset.birth_year is not None and asset.tax_pct is not None and asset.pension_profile is not None
    age = today.year - asset.birth_year
    years = asset.retirement_age - age
    if years <= 0:
        raise ProjectionInputError("Età pensionabile già raggiunta: nessuna proiezione")

    annual = asset.annual_contribution or 0.0
    start = asset.current_value
    paid_start = asset.invested if asset.invested is not None else start
    paid = [round(paid_start + annual * k, 0) for k in range(years + 1)]
    z = np.random.default_rng(seed).standard_normal((paths, years * 12))
    scenarios = [
        _scenario(p, _simulate_profile(p, start, annual / 12, years * 12, z), paid[-1], asset.tax_pct, years)
        for p in PensionProfile
    ]
    return PensionSimulation(
        asset_id=asset.asset_id or "",
        name=asset.name,
        current_age=age,
        retirement_age=asset.retirement_age,
        years_to_retirement=years,
        years=[today.year + k for k in range(years + 1)],
        paid=paid,
        annual_contribution=annual,
        tax_pct=asset.tax_pct,
        inflation_pct=INFLATION_PCT,
        paths=paths,
        chosen=asset.pension_profile,
        scenarios=scenarios,
    )


def _policy_return(asset: OtherAsset) -> tuple[float, bool]:
    """(expected yearly return %, is_default)."""
    if asset.expected_return_pct is not None:
        return asset.expected_return_pct, False
    if asset.insurance_branch == InsuranceBranch.MULTIRAMO:
        share = (asset.ramo_i_share_pct if asset.ramo_i_share_pct is not None else MULTIRAMO_DEFAULT_RAMO_I_SHARE) / 100
        blended = share * POLICY_DEFAULT_RETURN[InsuranceBranch.RAMO_I] \
            + (1 - share) * POLICY_DEFAULT_RETURN[InsuranceBranch.RAMO_III]
        return round(blended, 2), True
    return POLICY_DEFAULT_RETURN.get(asset.insurance_branch or InsuranceBranch.OTHER, 3.0), True


def _guaranteed_share(asset: OtherAsset) -> float | None:
    if asset.insurance_branch == InsuranceBranch.RAMO_I:
        return 1.0
    if asset.insurance_branch == InsuranceBranch.MULTIRAMO:
        return (asset.ramo_i_share_pct if asset.ramo_i_share_pct is not None else MULTIRAMO_DEFAULT_RAMO_I_SHARE) / 100
    return None


def project_policy(asset: OtherAsset, today: date) -> PolicyProjection:
    """Yearly value to maturity (or 10 years) at the expected return, premiums paid at year start.

    Ramo I guarantees the premiums paid (typical contract: check yours); a
    multiramo guarantees only its Ramo I share. TCM has no savings component.
    """
    premium = asset.annual_contribution or 0.0
    paid_now = asset.invested if asset.invested is not None else asset.current_value
    from_maturity = asset.maturity_date is not None and asset.maturity_date.year > today.year
    rate: float | None = None
    is_default = False
    years: list[int] = []
    value: list[float] = []
    paid: list[float] = []
    guaranteed: list[float] | None = None
    if asset.insurance_branch != InsuranceBranch.TCM:
        rate, is_default = _policy_return(asset)
        horizon = min(asset.maturity_date.year - today.year
                      if from_maturity and asset.maturity_date else POLICY_DEFAULT_HORIZON, POLICY_MAX_HORIZON)
        value, paid = [asset.current_value], [paid_now]
        for _ in range(horizon):
            value.append((value[-1] + premium) * (1 + rate / 100))
            paid.append(paid[-1] + premium)
        years = [today.year + k for k in range(horizon + 1)]
        share = _guaranteed_share(asset)
        guaranteed = [round(p * share, 0) for p in paid] if share is not None else None
    return PolicyProjection(
        asset_id=asset.asset_id or "",
        name=asset.name,
        branch=asset.insurance_branch,
        current_value=asset.current_value,
        paid_so_far=paid_now,
        annual_premium=premium,
        insured_capital=asset.insured_capital,
        expected_return_pct=rate,
        return_is_default=is_default,
        horizon_from_maturity=from_maturity,
        years=years,
        value=[round(v, 0) for v in value],
        paid=[round(p, 0) for p in paid],
        guaranteed=guaranteed,
    )
