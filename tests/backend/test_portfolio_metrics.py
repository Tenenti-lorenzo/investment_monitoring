"""Risk/return indices: known-answer tests on hand-built series."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fakes import bdays

from backend import portfolio_metrics as pm

TD = pm.TRADING_DAYS


def series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=bdays(len(values)))


# ─── Helpers ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected", [(1.23456, 1.23), (float("nan"), None), (float("inf"), None), (None, None)]
)
def test_round_opt_when_value_given_then_rounds_or_none(value, expected):
    assert pm.round_opt(value) == expected


def test_growth_index_when_returns_compound_then_base_times_product():
    idx = pm.growth_index(series([0.0, 0.10, -0.50]), base=100)
    assert idx.tolist() == pytest.approx([100.0, 110.0, 55.0])


def test_drawdown_when_price_falls_and_recovers_then_fraction_from_running_max():
    dd = pm.drawdown(series([100, 120, 90, 130, 117]))
    assert dd.tolist() == pytest.approx([0.0, 0.0, -0.25, 0.0, -0.10])


# ─── CAGR ─────────────────────────────────────────────────────────────────────


def test_cagr_when_one_year_of_constant_returns_then_equals_compounded_year():
    r = series([0.001] * TD)
    assert pm.cagr(r) == pytest.approx(1.001**TD - 1)


def test_cagr_when_half_year_then_annualised():
    r = series([0.001] * (TD // 2))
    assert pm.cagr(r) == pytest.approx(1.001**TD - 1, rel=1e-9)


def test_cagr_when_total_loss_then_minus_one_and_empty_then_zero():
    assert pm.cagr(series([0.0, -1.0])) == -1.0
    assert pm.cagr(pd.Series(dtype=float)) == 0.0


# ─── Risk metrics ─────────────────────────────────────────────────────────────


@pytest.fixture
def noisy_returns() -> pd.Series:
    rng = np.random.default_rng(3)
    return series(list(rng.normal(0.0005, 0.01, 500)))


def test_risk_metrics_when_series_given_then_volatility_is_annualised_sample_std(noisy_returns):
    m = pm.risk_metrics(noisy_returns, rf=0.0)
    assert m.volatility == pytest.approx(noisy_returns.std() * math.sqrt(TD) * 100, abs=0.01)


def test_risk_metrics_when_rf_given_then_sharpe_is_excess_mean_over_vol(noisy_returns):
    rf = 0.02
    m = pm.risk_metrics(noisy_returns, rf=rf)
    vol = noisy_returns.std() * math.sqrt(TD)
    assert m.sharpe == pytest.approx((noisy_returns.mean() * TD - rf) / vol, abs=0.01)


def test_risk_metrics_when_rf_given_then_sortino_uses_only_downside_deviation(noisy_returns):
    rf = 0.02
    m = pm.risk_metrics(noisy_returns, rf=rf)
    below = np.minimum(noisy_returns - rf / TD, 0)
    downside = math.sqrt(float((below**2).mean())) * math.sqrt(TD)
    assert m.sortino == pytest.approx((noisy_returns.mean() * TD - rf) / downside, abs=0.01)
    assert m.sortino > m.sharpe  # downside deviation < total volatility for symmetric noise


def test_risk_metrics_when_known_path_then_max_drawdown_date_and_calmar():
    r = series([0.0, 0.20, -0.25, 0.10])  # index 100 → 120 → 90 → 99
    m = pm.risk_metrics(r, rf=0.0)
    assert m.max_drawdown == pytest.approx(-25.0)
    assert m.max_dd_date == str(r.index[2].date())
    assert m.calmar == pytest.approx(round(pm.cagr(r) / 0.25, 2))


def test_risk_metrics_when_returns_are_twice_benchmark_then_beta_two_and_corr_one(noisy_returns):
    m = pm.risk_metrics(2 * noisy_returns, rf=0.0, bench=noisy_returns)
    assert m.beta == pytest.approx(2.0)
    assert m.correlation_benchmark == pytest.approx(1.0)


def test_risk_metrics_when_returns_are_negated_benchmark_then_beta_minus_one(noisy_returns):
    m = pm.risk_metrics(-noisy_returns, rf=0.0, bench=noisy_returns)
    assert m.beta == pytest.approx(-1.0)
    assert m.correlation_benchmark == pytest.approx(-1.0)


def test_risk_metrics_when_benchmark_too_short_then_beta_none():
    r = series([0.01, -0.01] * 5)
    assert pm.risk_metrics(r, 0.0, bench=r).beta is None


def test_risk_metrics_when_constant_returns_then_ratios_undefined():
    m = pm.risk_metrics(series([0.001] * 50), rf=0.0)
    assert m.volatility == 0.0
    assert m.sharpe is None and m.sortino is None and m.calmar is None


def test_risk_metrics_when_twenty_returns_then_var_cvar_are_left_tail():
    values = [-0.05, -0.04] + [0.01] * 18
    r = series(values)
    m = pm.risk_metrics(r, rf=0.0)
    assert m.var_95 == pytest.approx(-r.quantile(0.05) * 100)
    assert m.cvar_95 == pytest.approx(5.0)  # only the worst day is ≤ the 5% quantile
    assert m.cvar_95 >= m.var_95


def test_risk_metrics_when_series_given_then_shape_and_day_stats(noisy_returns):
    m = pm.risk_metrics(noisy_returns, rf=0.0)
    assert m.skew == pytest.approx(noisy_returns.skew(), abs=0.01)
    assert m.kurtosis == pytest.approx(noisy_returns.kurt(), abs=0.01)
    assert m.best_day == pytest.approx(noisy_returns.max() * 100, abs=0.01)
    assert m.worst_day == pytest.approx(noisy_returns.min() * 100, abs=0.01)
    assert m.positive_days_pct == pytest.approx((noisy_returns > 0).mean() * 100, abs=0.1)


# ─── XIRR (money-weighted return) ─────────────────────────────────────────────


def test_xirr_when_single_flow_over_365_days_then_simple_return():
    rate = pm.xirr([(date(2025, 1, 1), -100), (date(2026, 1, 1), 110)])
    assert rate == pytest.approx(0.10, abs=1e-6)


def test_xirr_when_multiple_flows_then_npv_is_zero_at_solution():
    flows = [
        (date(2024, 1, 10), -1000),
        (date(2024, 7, 1), -500),
        (date(2025, 3, 1), 250),
        (date(2026, 1, 10), 1600),
    ]
    rate = pm.xirr(flows)
    t0 = flows[0][0]
    npv = sum(v / (1 + rate) ** ((d - t0).days / 365) for d, v in flows)
    assert npv == pytest.approx(0.0, abs=1e-4)


def test_xirr_when_loss_then_negative_rate():
    assert pm.xirr([(date(2025, 1, 1), -100), (date(2026, 1, 1), 80)]) == pytest.approx(-0.2, abs=1e-6)


@pytest.mark.parametrize(
    "flows",
    [
        [],
        [(date(2025, 1, 1), -100)],
        [(date(2025, 1, 1), -100), (date(2025, 1, 20), 110)],  # span < 30 days
        [(date(2025, 1, 1), 100), (date(2026, 1, 1), 110)],  # no outflow
        [(date(2025, 1, 1), -100), (date(2026, 1, 1), -110)],  # no inflow
    ],
)
def test_xirr_when_undefined_then_none(flows):
    assert pm.xirr(flows) is None


# ─── Correlation ──────────────────────────────────────────────────────────────


def test_correlation_when_assets_move_together_or_opposite_then_plus_minus_one():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 0.01, 200)
    df = pd.DataFrame({"A": a, "B": 2 * a, "C": -a}, index=bdays(200))
    c = pm.correlation(df, window=63, step=5)
    assert c.labels == ["A", "B", "C"]
    assert c.matrix[0][1] == pytest.approx(1.0)
    assert c.matrix[0][2] == pytest.approx(-1.0)
    # avg of pairwise corr (1, -1, -1) = -1/3 in every window
    assert all(v == pytest.approx(-0.33, abs=0.01) for v in c.rolling_avg)
    assert len(c.rolling_dates) == len(c.rolling_avg) == len(range(63, 201, 5))


def test_correlation_when_single_asset_or_short_history_then_none():
    idx = bdays(200)
    assert pm.correlation(pd.DataFrame({"A": np.ones(200)}, index=idx)) is None
    short = pd.DataFrame({"A": np.arange(30.0), "B": np.arange(30.0)}, index=bdays(30))
    assert pm.correlation(short, window=63) is None


# ─── Efficient frontier ───────────────────────────────────────────────────────


@pytest.fixture
def two_assets() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    idx = bdays(500)
    return pd.DataFrame(
        {"LOW": rng.normal(0.0002, 0.003, 500), "HIGH": rng.normal(0.0008, 0.015, 500)}, index=idx
    )


def test_frontier_when_sampled_then_upper_envelope_is_monotone(two_assets):
    f = pm.efficient_frontier(two_assets, pd.Series({"LOW": 0.5, "HIGH": 0.5}), rf=0.0)
    vols = [p.vol for p in f.frontier]
    rets = [p.ret for p in f.frontier]
    assert vols == sorted(vols)
    assert rets == sorted(rets)


def test_frontier_when_sampled_then_min_vol_and_max_sharpe_are_extremes(two_assets):
    rf = 0.01
    f = pm.efficient_frontier(two_assets, pd.Series({"LOW": 0.5, "HIGH": 0.5}), rf=rf)
    assert f.min_vol.point.vol <= min(p.vol for p in f.cloud) + 1e-9
    best = (f.max_sharpe.point.ret - rf * 100) / f.max_sharpe.point.vol
    assert all((p.ret - rf * 100) / p.vol <= best + 1e-9 for p in f.cloud)
    assert sum(s.pct for s in f.max_sharpe.weights) == pytest.approx(100, abs=1.5)


def test_frontier_when_current_weights_given_then_point_matches_portfolio_stats(two_assets):
    w = pd.Series({"LOW": 0.25, "HIGH": 0.75})
    f = pm.efficient_frontier(two_assets, w, rf=0.0)
    mu = two_assets.mean().to_numpy() * TD
    cov = two_assets.cov().to_numpy() * TD
    wv = w.reindex(two_assets.columns).to_numpy()
    assert f.current.ret == pytest.approx(wv @ mu * 100, abs=0.01)
    assert f.current.vol == pytest.approx(math.sqrt(wv @ cov @ wv) * 100, abs=0.01)


def test_frontier_when_single_asset_then_none():
    df = pd.DataFrame({"A": np.random.default_rng(1).normal(0, 0.01, 100)}, index=bdays(100))
    assert pm.efficient_frontier(df, pd.Series({"A": 1.0}), 0.0) is None


# ─── Distribution / Monte Carlo / alternatives ────────────────────────────────


def test_distribution_when_histogram_then_counts_and_normal_cover_all_days(noisy_returns):
    d = pm.distribution(noisy_returns, bins=30)
    assert len(d.centers) == len(d.counts) == len(d.normal) == 30
    assert sum(d.counts) == len(noisy_returns)
    assert sum(d.normal) == pytest.approx(len(noisy_returns), rel=0.05)


def test_monte_carlo_when_zero_volatility_then_all_percentiles_follow_drift():
    r = series([0.001] * 300)
    mc = pm.monte_carlo(r, initial=1000, years=2, paths=50)
    expected = 1000 * math.exp(math.log1p(0.001) * TD * 2)
    for band in (mc.p5, mc.p25, mc.p50, mc.p75, mc.p95):
        assert band[0] == 1000
        assert band[-1] == pytest.approx(expected, rel=1e-3)
    assert mc.prob_loss == 0.0
    assert mc.sigma == 0.0
    assert mc.months == list(range(25))


def test_monte_carlo_when_noisy_then_bands_ordered_and_reproducible(noisy_returns):
    a = pm.monte_carlo(noisy_returns, initial=10_000)
    b = pm.monte_carlo(noisy_returns, initial=10_000)
    assert a.p50 == b.p50  # seeded
    assert all(
        p5 <= p25 <= p50 <= p75 <= p95
        for p5, p25, p50, p75, p95 in zip(a.p5, a.p25, a.p50, a.p75, a.p95, strict=True)
    )
    assert 0 <= a.prob_loss <= 100


def test_monte_carlo_when_negative_drift_then_loss_likely():
    r = series(list(np.random.default_rng(5).normal(-0.002, 0.01, 500)))
    assert pm.monte_carlo(r, initial=100).prob_loss > 50


def test_alternative_when_returns_given_then_growth_of_10k_and_stats():
    r = series([0.0, 0.10, -0.10])
    alt = pm.alternative("Mix", r, rf=0.0)
    assert alt.name == "Mix"
    assert alt.values == [10_000, 11_000, 9_900]
    assert alt.max_drawdown == pytest.approx(-10.0)
