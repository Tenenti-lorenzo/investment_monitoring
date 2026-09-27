"""Pure risk/return math on daily return series (no I/O).

Conventions: returns are simple daily returns as fractions; every value
returned inside a model is in percent unless noted otherwise.
"""

import math
from datetime import date

import numpy as np
import pandas as pd

from backend.analysis_models import (
    Alternative,
    Correlation,
    Distribution,
    Frontier,
    FrontierWeights,
    MonteCarlo,
    Point,
    RiskMetrics,
    Share,
)

TRADING_DAYS = 252


def round_opt(x: float | None, nd: int = 2) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), nd)


def _pct(x: float, nd: int = 2) -> float:
    return round(float(x) * 100, nd) if math.isfinite(x) else 0.0


def growth_index(returns: pd.Series, base: float = 100.0) -> pd.Series:
    """Compound daily returns into an index starting at `base`."""
    return base * (1 + returns.fillna(0)).cumprod()


def drawdown(index: pd.Series) -> pd.Series:
    """Drawdown of an index as a fraction: (value − running max) / running max."""
    peak = index.cummax()
    return index / peak - 1


def cagr(returns: pd.Series) -> float:
    """Compound annual growth rate of a daily return series (fraction)."""
    n = len(returns)
    if n == 0:
        return 0.0
    total = float((1 + returns).prod())
    return total ** (TRADING_DAYS / n) - 1 if total > 0 else -1.0


def risk_metrics(returns: pd.Series, rf: float, bench: pd.Series | None = None) -> RiskMetrics:
    """Compute the standard risk/return statistics of a daily return series.

    Args:
        returns: Daily simple returns.
        rf: Annual risk-free rate (fraction).
        bench: Optional benchmark daily returns for beta/correlation.

    Returns:
        RiskMetrics in percent units (ratios are unit-less).
    """
    r = returns.dropna()
    growth = cagr(r)
    vol = float(r.std() * math.sqrt(TRADING_DAYS))
    excess = float(r.mean() * TRADING_DAYS - rf)
    rf_d = rf / TRADING_DAYS
    downside = float(np.sqrt(np.mean(np.minimum(r - rf_d, 0) ** 2)) * math.sqrt(TRADING_DAYS))
    dd = drawdown(growth_index(r))
    max_dd = float(dd.min()) if len(dd) else 0.0
    tail = r[r <= r.quantile(0.05)]

    beta = corr = None
    if bench is not None:
        joined = pd.concat([r, bench], axis=1, join="inner").dropna()
        if len(joined) > 20 and joined.iloc[:, 1].var() > 0:
            cov = joined.cov().iloc[0, 1]
            beta = round_opt(cov / joined.iloc[:, 1].var())
            corr = round_opt(joined.corr().iloc[0, 1])

    return RiskMetrics(
        cagr=_pct(growth),
        volatility=_pct(vol),
        max_drawdown=_pct(max_dd),
        max_dd_date=str(dd.idxmin().date()) if len(dd) else None,
        sharpe=round_opt(excess / vol) if vol > 0 else None,
        sortino=round_opt(excess / downside) if downside > 0 else None,
        calmar=round_opt(growth / abs(max_dd)) if max_dd < 0 else None,
        beta=beta,
        correlation_benchmark=corr,
        var_95=_pct(-float(r.quantile(0.05))),
        cvar_95=_pct(-float(tail.mean())) if len(tail) else 0.0,
        skew=round_opt(float(r.skew())) or 0.0,
        kurtosis=round_opt(float(r.kurt())) or 0.0,
        best_day=_pct(float(r.max())),
        worst_day=_pct(float(r.min())),
        positive_days_pct=_pct(float((r > 0).mean()), 1),
    )


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Money-weighted return (XIRR) of dated cash flows, as an annual fraction.

    Outflows (investments) are negative, the final value is positive.
    Solved by bisection on NPV, which is monotone for this flow shape.

    Returns:
        The annual rate, or None if undefined or the span is under 30 days.
    """
    if len(flows) < 2:
        return None
    t0 = min(d for d, _ in flows)
    span = (max(d for d, _ in flows) - t0).days
    if span < 30 or not any(v < 0 for _, v in flows) or not any(v > 0 for _, v in flows):
        return None

    def npv(rate: float) -> float:
        return float(sum(v / (1 + rate) ** ((d - t0).days / 365.0) for d, v in flows))

    lo, hi = -0.9999, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def correlation(returns: pd.DataFrame, window: int = 63, step: int = 5) -> Correlation | None:
    """Correlation matrix plus rolling average pairwise correlation.

    Args:
        returns: Daily returns, one column per asset.
        window: Rolling window in trading days (63 ≈ one quarter).
        step: Sample every `step` days to keep the payload small.
    """
    df = returns.dropna(how="all")
    if df.shape[1] < 2 or len(df) < window + 5:
        return None
    mat = df.corr()
    n = df.shape[1]
    iu = np.triu_indices(n, k=1)
    dates, avg = [], []
    for end in range(window, len(df) + 1, step):
        c = df.iloc[end - window : end].corr().to_numpy()[iu]
        c = c[np.isfinite(c)]
        dates.append(str(df.index[end - 1].date()))
        avg.append(round_opt(float(c.mean())) if len(c) else None)
    return Correlation(
        labels=list(df.columns),
        matrix=[[round_opt(v) for v in row] for row in mat.to_numpy()],
        rolling_dates=dates,
        rolling_avg=avg,
        window_days=window,
    )


def _point(w: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> tuple[float, float]:
    return float(np.sqrt(w @ cov @ w)), float(w @ mu)


def efficient_frontier(
    returns: pd.DataFrame,
    weights: pd.Series,
    rf: float,
    samples: int = 5000,
    seed: int = 42,
) -> Frontier | None:
    """Long-only frontier by random sampling of portfolio weights.

    Args:
        returns: Daily returns of the risky assets (columns).
        weights: Current weights of those assets (renormalised internally).
        rf: Annual risk-free rate (fraction).
    """
    df = returns.dropna()
    if df.shape[1] < 2 or len(df) < 60:
        return None
    mu = df.mean().to_numpy() * TRADING_DAYS
    cov = df.cov().to_numpy() * TRADING_DAYS
    n = df.shape[1]
    rng = np.random.default_rng(seed)
    w = np.vstack(
        [
            rng.dirichlet(np.ones(n), samples // 2),
            rng.dirichlet(np.full(n, 0.25), samples // 2),  # corner-heavy
            np.eye(n),
        ]
    )
    vol = np.sqrt(np.einsum("ij,jk,ik->i", w, cov, w))
    ret = w @ mu
    # Zero-variance portfolios (e.g. flat prices) have no defined Sharpe: rank them last.
    sharpe = np.divide(ret - rf, vol, out=np.full_like(ret, -np.inf), where=vol > 0)

    order = np.argsort(vol)
    front, best = [], -np.inf
    for i in order:
        if ret[i] > best:
            best = ret[i]
            front.append(Point(vol=_pct(vol[i]), ret=_pct(ret[i])))

    def pick(i: int, label: str) -> FrontierWeights:
        shares = [Share(label=a, pct=_pct(x, 1)) for a, x in zip(df.columns, w[i], strict=True) if x >= 0.005]
        return FrontierWeights(
            label=label,
            point=Point(vol=_pct(vol[i]), ret=_pct(ret[i])),
            weights=sorted(shares, key=lambda s: -s.pct),
        )

    cur = weights.reindex(df.columns).fillna(0).to_numpy()
    cur = cur / cur.sum() if cur.sum() > 0 else np.full(n, 1 / n)
    cv, cr = _point(cur, mu, cov)
    thin = rng.choice(len(w), size=min(1200, len(w)), replace=False)
    return Frontier(
        cloud=[Point(vol=_pct(vol[i]), ret=_pct(ret[i])) for i in thin],
        frontier=front,
        current=Point(vol=_pct(cv), ret=_pct(cr)),
        min_vol=pick(int(np.argmin(vol)), "Minima volatilità"),
        max_sharpe=pick(int(np.argmax(sharpe)), "Massimo Sharpe"),
        assets=list(df.columns),
    )


def distribution(returns: pd.Series, bins: int = 40) -> Distribution:
    """Histogram of daily returns (%) with the matching normal-fit counts."""
    r = returns.dropna().to_numpy() * 100
    counts, edges = np.histogram(r, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    width = edges[1] - edges[0]
    m, s = float(r.mean()), float(r.std())
    pdf = np.exp(-((centers - m) ** 2) / (2 * s * s)) / (s * math.sqrt(2 * math.pi)) if s > 0 else 0 * centers
    return Distribution(
        centers=[round(float(c), 3) for c in centers],
        counts=[int(c) for c in counts],
        normal=[round(float(x), 2) for x in pdf * len(r) * width],
    )


def monte_carlo(
    returns: pd.Series,
    initial: float,
    years: int = 10,
    paths: int = 2000,
    seed: int = 7,
) -> MonteCarlo:
    """Monthly log-normal simulation calibrated on historical daily returns.

    Assumes future returns keep the historical mean and volatility — a strong
    assumption, surfaced to the user alongside the chart.
    """
    log_r = np.log1p(returns.dropna().to_numpy())
    mu = float(log_r.mean() * TRADING_DAYS)
    sigma = float(log_r.std() * math.sqrt(TRADING_DAYS))
    months = years * 12
    rng = np.random.default_rng(seed)
    steps = rng.normal(mu / 12, sigma / math.sqrt(12), size=(paths, months))
    values = initial * np.exp(np.concatenate([np.zeros((paths, 1)), steps.cumsum(axis=1)], axis=1))
    q = np.percentile(values, [5, 25, 50, 75, 95], axis=0)

    def row(i: int) -> list[float]:
        return [round(float(v), 0) for v in q[i]]

    return MonteCarlo(
        horizon_years=years,
        months=list(range(months + 1)),
        p5=row(0),
        p25=row(1),
        p50=row(2),
        p75=row(3),
        p95=row(4),
        initial=round(initial, 2),
        prob_loss=_pct(float((values[:, -1] < initial).mean()), 1),
        mu=_pct(math.expm1(mu)),
        sigma=_pct(sigma),
    )


def alternative(name: str, returns: pd.Series, rf: float, start: float = 10_000) -> Alternative:
    """Growth of `start` EUR plus headline stats for one allocation."""
    m = risk_metrics(returns, rf)
    return Alternative(
        name=name,
        values=[round(float(v), 0) for v in growth_index(returns, start)],
        cagr=m.cagr,
        volatility=m.volatility,
        max_drawdown=m.max_drawdown,
        sharpe=m.sharpe,
    )
