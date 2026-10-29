"""Pension Monte Carlo and life-policy projections."""

from datetime import date

import pytest

from backend.exceptions import ProjectionInputError
from backend.projections import project_policy, simulate_pension
from backend.wealth_models import AssetKind, InsuranceBranch, OtherAsset, PensionProfile

TODAY = date(2026, 10, 29)


def fund(**kw) -> OtherAsset:
    base = {"asset_id": "a" * 32, "kind": AssetKind.PENSION_FUND, "name": "Fondo", "current_value": 20_000,
                "invested": 18_000, "annual_contribution": 3_000, "birth_year": 1991, "retirement_age": 67,
                "tax_pct": 15, "pension_profile": PensionProfile.BALANCED}
    return OtherAsset(**{**base, **kw})


def policy(branch: InsuranceBranch, **kw) -> OtherAsset:
    base = {"asset_id": "b" * 32, "kind": AssetKind.LIFE_INSURANCE, "name": "Polizza", "current_value": 10_000,
                "invested": 9_000, "annual_contribution": 1_000, "insurance_branch": branch}
    return OtherAsset(**{**base, **kw})


def test_pension_when_complete_then_three_lines_to_retirement():
    sim = simulate_pension(fund(), TODAY, paths=500)
    assert sim.current_age == 35 and sim.years_to_retirement == 32
    assert sim.years[0] == 2026 and sim.years[-1] == 2058 and len(sim.paid) == 33
    assert sim.paid[-1] == 18_000 + 3_000 * 32
    assert [s.profile for s in sim.scenarios] == list(PensionProfile)
    for s in sim.scenarios:
        assert len(s.p50) == 33 and s.p50[0] == 20_000
        g = s.gross_at_retirement
        assert g.p5 <= g.p25 <= g.p50 <= g.p75 <= g.p95
        assert s.net_at_retirement.p50 == pytest.approx(g.p50 * 0.85, abs=1)
        assert s.net_real_p50 < s.net_at_retirement.p50


def test_pension_when_riskier_line_then_wider_spread():
    by = {s.profile: s.gross_at_retirement for s in simulate_pension(fund(), TODAY, paths=1000).scenarios}
    spread = {p: v.p95 - v.p5 for p, v in by.items()}
    assert spread[PensionProfile.CONSERVATIVE] < spread[PensionProfile.BALANCED] < spread[PensionProfile.DYNAMIC]
    assert by[PensionProfile.CONSERVATIVE].p50 < by[PensionProfile.DYNAMIC].p50


def test_pension_when_seeded_then_reproducible():
    a = simulate_pension(fund(), TODAY, paths=200)
    b = simulate_pension(fund(), TODAY, paths=200)
    assert a.scenarios[2].p50 == b.scenarios[2].p50


def test_pension_when_data_missing_then_lists_it():
    with pytest.raises(ProjectionInputError, match="anno di nascita.*tasse"):
        simulate_pension(fund(birth_year=None, tax_pct=None), TODAY)


def test_pension_when_already_retired_then_error():
    with pytest.raises(ProjectionInputError, match="già"):
        simulate_pension(fund(birth_year=1950), TODAY)


def test_policy_when_ramo_i_then_compounds_and_guarantees_premiums():
    p = project_policy(policy(InsuranceBranch.RAMO_I, maturity_date=date(2029, 6, 1)), TODAY)
    assert p.years == [2026, 2027, 2028, 2029]
    assert p.expected_return_pct == 2.5 and p.return_is_default and p.horizon_from_maturity
    assert p.value[1] == round(11_000 * 1.025)
    assert p.paid == [9_000, 10_000, 11_000, 12_000] and p.guaranteed == p.paid


def test_policy_when_multiramo_then_blended_return_and_partial_guarantee():
    p = project_policy(policy(InsuranceBranch.MULTIRAMO, ramo_i_share_pct=30), TODAY)
    assert p.expected_return_pct == pytest.approx(0.3 * 2.5 + 0.7 * 4.5)
    assert len(p.years) == 11 and not p.horizon_from_maturity
    assert p.guaranteed is not None and p.guaranteed[0] == 2_700


def test_policy_when_user_return_then_used_and_no_guarantee_on_unit_linked():
    p = project_policy(policy(InsuranceBranch.RAMO_III, expected_return_pct=6), TODAY)
    assert p.expected_return_pct == 6 and not p.return_is_default and p.guaranteed is None


def test_policy_when_tcm_then_protection_only():
    p = project_policy(policy(InsuranceBranch.TCM, current_value=0, insured_capital=250_000), TODAY)
    assert p.years == [] and p.expected_return_pct is None and p.insured_capital == 250_000
