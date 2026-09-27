"""Pydantic contracts for the deep portfolio analysis endpoints.

Only data classes live here: no I/O, no computation.
"""

from pydantic import BaseModel, Field

# ─── Request ──────────────────────────────────────────────────────────────────


class AnalysisHolding(BaseModel):
    """One position as held by the client.

    `purchase_price` is expressed in the instrument's trading currency
    (bonds: % of nominal). `amount` is the EUR value used when no quantity
    is known.
    """

    isin: str = ""
    ticker: str
    yf_ticker: str | None = None
    name: str = ""
    category: str = "Altro"
    currency: str | None = None
    geography: dict[str, float] | None = None
    ter: float | None = None
    allocation: float = 0.0
    amount: float | None = None
    quantity: float | None = None
    purchase_price: float | None = None
    purchase_date: str | None = None


class DeepAnalysisRequest(BaseModel):
    """Input of `/api/analysis/deep` and `/api/analysis/look-through`."""

    holdings: list[AnalysisHolding]
    liquidita: float = Field(0.0, ge=0)  # EUR
    lookback_years: int = Field(3, ge=1, le=10)
    risk_free: float = Field(0.02, ge=0, le=0.2)
    benchmark: str = "SWDA.MI"
    equity_proxy: str = "SWDA.MI"
    bond_proxy: str = "IEAG.MI"


# ─── Shared building blocks ───────────────────────────────────────────────────


class NamedSeries(BaseModel):
    name: str
    values: list[float | None]


class Point(BaseModel):
    vol: float
    ret: float


class Share(BaseModel):
    label: str
    pct: float


# ─── Deep analysis response ───────────────────────────────────────────────────


class ReturnSummary(BaseModel):
    """What the investor actually earned since purchase."""

    start_date: str
    invested: float
    current_value: float
    pl_eur: float
    pl_pct: float
    twr: float  # cumulative time-weighted return, %
    twr_annualized: float | None  # %, None when < 1 year
    mwr: float | None  # XIRR, % per year


class RiskMetrics(BaseModel):
    """Risk/return statistics of a daily return series (percent units)."""

    cagr: float
    volatility: float
    max_drawdown: float
    max_dd_date: str | None = None
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    beta: float | None = None
    correlation_benchmark: float | None = None
    var_95: float  # daily historical VaR, %
    cvar_95: float  # daily expected shortfall, %
    skew: float
    kurtosis: float  # excess kurtosis
    best_day: float
    worst_day: float
    positive_days_pct: float


class EquityCurve(BaseModel):
    """Since-purchase curves: market value, invested capital, drawdown."""

    dates: list[str]
    value: list[float]
    invested: list[float]
    twr_index: list[float]  # base 100
    drawdown: list[float]  # %, from the TWR index
    benchmark_index: list[float | None]  # base 100, same dates


class HoldingPL(BaseModel):
    ticker: str
    name: str
    category: str
    currency: str
    cost: float
    value: float
    pl_eur: float
    pl_pct: float | None
    price_effect: float
    fx_effect: float
    contribution_pp: float  # pl_eur / total invested, in p.p.
    weight_pct: float
    start_date: str | None
    date_assumed: bool


class ClassPL(BaseModel):
    category: str
    cost: float
    value: float
    pl_eur: float
    pl_pct: float | None
    contribution_pp: float
    weight_target_pct: float  # share of invested capital
    weight_now_pct: float  # share of current value
    drift_pp: float


class AllocationOverTime(BaseModel):
    dates: list[str]
    series: list[NamedSeries]  # % of portfolio value by category


class Correlation(BaseModel):
    labels: list[str]
    matrix: list[list[float | None]]
    rolling_dates: list[str]
    rolling_avg: list[float | None]  # avg pairwise corr, 63-day window
    window_days: int


class FrontierWeights(BaseModel):
    label: str
    point: Point
    weights: list[Share]


class Frontier(BaseModel):
    cloud: list[Point]
    frontier: list[Point]
    current: Point
    min_vol: FrontierWeights
    max_sharpe: FrontierWeights
    assets: list[str]


class Distribution(BaseModel):
    centers: list[float]  # daily return bin centers, %
    counts: list[int]
    normal: list[float]  # expected count under a normal fit


class MonteCarlo(BaseModel):
    horizon_years: int
    months: list[int]
    p5: list[float]
    p25: list[float]
    p50: list[float]
    p75: list[float]
    p95: list[float]
    initial: float
    prob_loss: float  # % of paths below initial at horizon
    mu: float  # annual drift used, %
    sigma: float  # annual vol used, %


class Alternative(BaseModel):
    name: str
    values: list[float]  # growth of 10,000 EUR
    cagr: float
    volatility: float
    max_drawdown: float
    sharpe: float | None


class Alternatives(BaseModel):
    dates: list[str]
    items: list[Alternative]


class DeepAnalysisResponse(BaseModel):
    as_of: str
    coverage_pct: float  # share of value with price history
    excluded: list[str]  # tickers without usable history
    assumed_dates: list[str]  # tickers with no purchase date
    notional: bool  # True when amounts were derived from %
    summary: ReturnSummary
    risk: RiskMetrics  # current weights, lookback window
    benchmark_risk: RiskMetrics | None
    benchmark: str
    equity_curve: EquityCurve
    holdings: list[HoldingPL]
    classes: list[ClassPL]
    allocation_over_time: AllocationOverTime
    correlation: Correlation | None
    frontier: Frontier | None
    distribution: Distribution
    monte_carlo: MonteCarlo
    alternatives: Alternatives


# ─── Look-through response ────────────────────────────────────────────────────


class UnderlyingExposure(BaseModel):
    symbol: str
    name: str
    weight_pct: float  # share of total portfolio
    sources: list[str]  # instruments that hold it


class OverlapPair(BaseModel):
    a: str
    b: str
    overlap_pct: float  # sum of min weights over known top holdings


class BondDetail(BaseModel):
    ticker: str
    name: str
    weight_pct: float
    kind: str  # "Obbligazione" | "ETF Obbligazionario"
    maturity: str | None = None
    years_to_maturity: float | None = None
    coupon_pct: float | None = None
    price: float | None = None
    ytm_pct: float | None = None
    duration: float | None = None  # modified duration, years
    credit: list[Share] = []


class CostDetail(BaseModel):
    ticker: str
    name: str
    value: float
    ter: float | None
    annual_cost: float | None


class LookThroughResponse(BaseModel):
    asset_classes: list[Share]
    sectors: list[Share]
    geography: list[Share]
    currencies: list[Share]
    hedged_pct: float
    top_exposures: list[UnderlyingExposure]
    overlaps: list[OverlapPair]
    bonds: list[BondDetail]
    portfolio_duration: float | None
    credit_quality: list[Share]
    costs: list[CostDetail]
    ter_weighted: float | None
    annual_cost: float
    cost_10y: float  # cumulative TER drag over 10y at 0% growth
    coverage_note: str
