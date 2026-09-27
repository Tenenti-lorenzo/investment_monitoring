"""Deep portfolio analysis: since-purchase performance (TWR/MWR), P&L
attribution, risk metrics, correlation, frontier, Monte Carlo and
alternative allocations.

Two views are computed on purpose:
  * since-purchase — actual positions from their purchase date, used for
    what the investor earned (value vs invested, TWR, MWR, drift);
  * lookback window — current weights held constant over the last N years,
    used for risk statistics that need a long, uniform history.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

from backend import portfolio_metrics as pm
from backend.analysis_models import (
    AllocationOverTime,
    Alternatives,
    AnalysisHolding,
    ClassPL,
    DeepAnalysisRequest,
    DeepAnalysisResponse,
    EquityCurve,
    HoldingPL,
    NamedSeries,
    ReturnSummary,
)
from backend.bond_market import fetch_bond_quote
from backend.exceptions import InsufficientDataError
from backend.price_history import PriceHistory, fetch_price_history

logger = logging.getLogger(__name__)

NOTIONAL_TOTAL = 10_000.0
LIQUIDITY = "Liquidità"


class _Position:
    """A resolved holding: quantity, start date, cost and current value in EUR."""

    def __init__(
        self,
        h: AnalysisHolding,
        qty: float,
        start: pd.Timestamp,
        assumed: bool,
        cost: float,
        value: float,
        price_fx: tuple[float, float],
        has_history: bool,
    ) -> None:
        self.h, self.qty, self.start, self.assumed = h, qty, start, assumed
        self.cost, self.value, self.has_history = cost, value, has_history
        self.price_effect, self.fx_effect = price_fx

    @property
    def key(self) -> str:
        return self.h.yf_ticker or self.h.ticker


# ─── Input resolution ─────────────────────────────────────────────────────────


def parse_date(raw: str | None) -> date | None:
    """Parse an ISO (YYYY-MM-DD) or Italian (DD/MM/YYYY) date; None if invalid."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw.strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def _is_bond(h: AnalysisHolding) -> bool:
    return h.category == "Obbligazioni" and bool(h.isin)


def _eur_amount(h: AnalysisHolding, notional: bool) -> float:
    if notional:
        return h.allocation / 100 * NOTIONAL_TOTAL
    return float(h.amount or 0)


def _quote_currency(ticker: str) -> str | None:
    try:
        return getattr(yf.Ticker(ticker).fast_info, "currency", None)
    except Exception:  # noqa: BLE001 — Yahoo failures degrade to EUR
        return None


def _resolve_currencies(tickers: dict[str, str | None]) -> dict[str, str | None]:
    missing = [t for t, c in tickers.items() if not c]
    if missing:
        with ThreadPoolExecutor(max_workers=min(8, len(missing))) as ex:
            for t, c in zip(missing, ex.map(_quote_currency, missing), strict=True):
                tickers[t] = c
    return tickers


def _market_position(
    h: AnalysisHolding, ph: PriceHistory, start: pd.Timestamp, assumed: bool, notional: bool
) -> _Position | None:
    key = h.yf_ticker or h.ticker
    eur, loc, fx = ph.eur[key].dropna(), ph.local[key], ph.fx[key]
    if eur.empty:
        return None
    start = max(start, eur.index[0])
    start = eur.index[eur.index.searchsorted(start)] if start <= eur.index[-1] else eur.index[-1]
    last_eur, last_loc, last_fx = float(eur.iloc[-1]), float(loc.dropna().iloc[-1]), float(fx.iloc[-1])
    qty = float(h.quantity) if h.quantity else _eur_amount(h, notional) / last_eur
    if qty <= 0:
        return None
    p0 = float(h.purchase_price) if h.purchase_price else float(loc.loc[start])
    fx0 = float(fx.loc[start])
    cost, value = qty * p0 / fx0, qty * last_eur
    price_fx = (qty * (last_loc - p0) / fx0, qty * last_loc * (1 / last_fx - 1 / fx0))
    return _Position(h, qty, start, assumed, cost, value, price_fx, True)


def _static_position(h: AnalysisHolding, start: pd.Timestamp, assumed: bool, notional: bool) -> _Position:
    """Holding without daily history (bonds, failed tickers): valued once."""
    value = _eur_amount(h, notional)
    cost = value
    if _is_bond(h) and h.quantity:
        quote = fetch_bond_quote(h.isin)
        if quote and quote.price:
            value = float(h.quantity) * quote.price / 100
        cost = float(h.quantity) * float(h.purchase_price) / 100 if h.purchase_price else value
    return _Position(h, h.quantity or 0.0, start, assumed, cost, value, (value - cost, 0.0), False)


def _resolve_positions(
    req: DeepAnalysisRequest, notional: bool, window_start: date
) -> tuple[list[_Position], PriceHistory, str | None]:
    dates = {id(h): parse_date(h.purchase_date) for h in req.holdings}
    earliest = min([window_start, *[d for d in dates.values() if d]])
    earliest = max(earliest, date.today() - timedelta(days=365 * 12))
    market = [h for h in req.holdings if h.yf_ticker and not _is_bond(h)]
    currencies = _resolve_currencies(
        {
            **{b: None for b in {req.benchmark, req.equity_proxy, req.bond_proxy}},
            **{h.yf_ticker: h.currency for h in market if h.yf_ticker},
        }
    )
    ph = fetch_price_history(currencies, earliest - timedelta(days=7))
    if ph.eur.empty:
        raise InsufficientDataError("Nessuno storico prezzi disponibile da Yahoo Finance")
    default_start = pd.Timestamp(window_start)
    positions: list[_Position] = []
    for h in req.holdings:
        d = dates[id(h)]
        start = pd.Timestamp(d) if d else default_start
        pos = None
        if h in market and h.yf_ticker in ph.eur:
            pos = _market_position(h, ph, start, d is None, notional)
        positions.append(pos or _static_position(h, start, d is None, notional))
    bench = req.benchmark if req.benchmark in ph.eur else None
    return positions, ph, bench


# ─── Since-purchase view ──────────────────────────────────────────────────────


def _value_frame(positions: list[_Position], ph: PriceHistory, idx: pd.DatetimeIndex) -> pd.DataFrame:
    cols = {}
    for i, p in enumerate(positions):
        active = idx >= p.start
        if p.has_history:
            px = ph.eur[p.key].reindex(idx).ffill()
            cols[i] = (px * p.qty).where(active, 0.0).fillna(0.0)
        else:
            cols[i] = pd.Series(p.value, index=idx).where(active, 0.0)
    return pd.DataFrame(cols, index=idx)


def _since_purchase(
    positions: list[_Position], ph: PriceHistory, liq: float, bench: str | None
) -> tuple[EquityCurve, pd.DataFrame, pd.Timestamp]:
    market = [p for p in positions if p.has_history]
    t0 = min(p.start for p in market)
    idx = ph.index[ph.index >= t0]
    values = _value_frame(positions, ph, idx)
    mkt_cols = [i for i, p in enumerate(positions) if p.has_history]
    v = values[mkt_cols].sum(axis=1) + liq
    invested = pd.Series(liq, index=idx)
    new_money = pd.Series(0.0, index=idx)
    new_money.iloc[0] += liq
    for i in mkt_cols:
        p = positions[i]
        invested += (idx >= p.start) * p.cost
        new_money.loc[p.start] += values.at[p.start, i]
    prev = v.shift(1)
    r = ((v - new_money) / prev - 1).where(prev > 0, 0.0).fillna(0.0)
    twr_idx = pm.growth_index(r)
    dd = pm.drawdown(twr_idx) * 100
    b = ph.eur[bench].reindex(idx).ffill() if bench else None
    b_idx = (b / b.dropna().iloc[0] * 100) if b is not None and not b.dropna().empty else None

    keep = _thin(len(idx), 500)
    curve = EquityCurve(
        dates=[str(idx[i].date()) for i in keep],
        value=[round(float(v.iloc[i]), 2) for i in keep],
        invested=[round(float(invested.iloc[i]), 2) for i in keep],
        twr_index=[round(float(twr_idx.iloc[i]), 2) for i in keep],
        drawdown=[round(float(dd.iloc[i]), 2) for i in keep],
        benchmark_index=[pm.round_opt(float(b_idx.iloc[i])) if b_idx is not None else None for i in keep],
    )
    return curve, values, t0


def _thin(n: int, max_points: int) -> list[int]:
    if n <= max_points:
        return list(range(n))
    step = n / max_points
    keep = sorted({int(i * step) for i in range(max_points)} | {n - 1})
    return keep


def _summary(
    positions: list[_Position], liq: float, curve: EquityCurve, t0: pd.Timestamp, as_of: date
) -> ReturnSummary:
    invested = sum(p.cost for p in positions) + liq
    current = sum(p.value for p in positions) + liq
    flows = [(p.start.date(), -p.cost) for p in positions if p.cost > 0]
    if liq > 0:
        flows.append((t0.date(), -liq))
    flows.append((as_of, current))
    mwr = pm.xirr(flows)
    twr = curve.twr_index[-1] / 100 - 1
    days = (as_of - t0.date()).days
    twr_ann = (1 + twr) ** (365 / days) - 1 if days >= 365 else None
    return ReturnSummary(
        start_date=str(t0.date()),
        invested=round(invested, 2),
        current_value=round(current, 2),
        pl_eur=round(current - invested, 2),
        pl_pct=round((current / invested - 1) * 100, 2) if invested else 0.0,
        twr=round(twr * 100, 2),
        twr_annualized=round(twr_ann * 100, 2) if twr_ann is not None else None,
        mwr=round(mwr * 100, 2) if mwr is not None else None,
    )


def _attribution(positions: list[_Position], liq: float) -> tuple[list[HoldingPL], list[ClassPL]]:
    invested = sum(p.cost for p in positions) + liq
    current = sum(p.value for p in positions) + liq
    rows = [
        HoldingPL(
            ticker=p.h.ticker,
            name=p.h.name,
            category=p.h.category,
            currency=p.h.currency or "EUR",
            cost=round(p.cost, 2),
            value=round(p.value, 2),
            pl_eur=round(p.value - p.cost, 2),
            pl_pct=round((p.value / p.cost - 1) * 100, 2) if p.cost else None,
            price_effect=round(p.price_effect, 2),
            fx_effect=round(p.fx_effect, 2),
            contribution_pp=round((p.value - p.cost) / invested * 100, 2) if invested else 0.0,
            weight_pct=round(p.value / current * 100, 2) if current else 0.0,
            start_date=str(p.start.date()),
            date_assumed=p.assumed,
        )
        for p in positions
    ]

    groups: dict[str, list[float]] = {}
    for p in positions:
        g = groups.setdefault(p.h.category, [0.0, 0.0])
        g[0] += p.cost
        g[1] += p.value
    if liq > 0:
        groups[LIQUIDITY] = [liq, liq]
    classes = []
    for cat, (cost, value) in sorted(groups.items(), key=lambda kv: -kv[1][1]):
        tgt = cost / invested * 100 if invested else 0.0
        now = value / current * 100 if current else 0.0
        classes.append(
            ClassPL(
                category=cat,
                cost=round(cost, 2),
                value=round(value, 2),
                pl_eur=round(value - cost, 2),
                pl_pct=round((value / cost - 1) * 100, 2) if cost else None,
                contribution_pp=round((value - cost) / invested * 100, 2) if invested else 0.0,
                weight_target_pct=round(tgt, 2),
                weight_now_pct=round(now, 2),
                drift_pp=round(now - tgt, 2),
            )
        )
    return rows, classes


def _allocation_over_time(positions: list[_Position], values: pd.DataFrame, liq: float) -> AllocationOverTime:
    by_cat: dict[str, pd.Series] = {}
    for i, p in enumerate(positions):
        by_cat[p.h.category] = by_cat.get(p.h.category, 0) + values[i]
    if liq > 0:
        by_cat[LIQUIDITY] = pd.Series(liq, index=values.index)
    frame = pd.DataFrame(by_cat)
    share = frame.div(frame.sum(axis=1).replace(0, float("nan")), axis=0) * 100
    keep = _thin(len(share), 160)
    return AllocationOverTime(
        dates=[str(share.index[i].date()) for i in keep],
        series=[
            NamedSeries(name=c, values=[pm.round_opt(float(share[c].iloc[i]), 1) for i in keep])
            for c in share.columns
        ],
    )


# ─── Lookback-window view ─────────────────────────────────────────────────────


def _window_returns(
    positions: list[_Position], ph: PriceHistory, liq: float, window_start: date
) -> tuple[pd.Series, pd.DataFrame, pd.Series]:
    """Daily returns of the current weights held constant over the window."""
    market = [p for p in positions if p.has_history]
    total = sum(p.value for p in market) + liq
    idx = ph.index[ph.index >= pd.Timestamp(window_start)]
    rets = pd.DataFrame(
        {p.h.ticker: ph.eur[p.key].reindex(idx).pct_change(fill_method=None) for p in market}
    ).iloc[1:]
    w = pd.Series([p.value / total for p in market], index=[p.h.ticker for p in market])
    w = w.groupby(level=0).sum()  # same ticker held twice → one asset
    num = (rets.fillna(0) * w).sum(axis=1)
    den = (rets.notna() * w).sum(axis=1) + liq / total
    return (num / den).dropna(), rets, w


def _alternatives(req: DeepAnalysisRequest, ph: PriceHistory, port: pd.Series) -> Alternatives:
    frames = {"Il tuo portafoglio": port}
    if req.equity_proxy in ph.eur and req.bond_proxy in ph.eur:
        eq = ph.eur[req.equity_proxy].pct_change(fill_method=None)
        bd = ph.eur[req.bond_proxy].pct_change(fill_method=None)
        for label, a in (("100% azionario", 1.0), ("80/20", 0.8), ("60/40", 0.6)):
            frames[label] = a * eq + (1 - a) * bd
    joined = pd.DataFrame(frames).reindex(port.index).dropna()
    if not joined.empty:
        joined.iloc[0] = 0.0  # first date is the base: every line starts at exactly 10,000
    keep = _thin(len(joined), 400)
    items = []
    for name in joined.columns:
        alt = pm.alternative(name, joined[name], req.risk_free)
        alt.values = [alt.values[i] for i in keep]
        items.append(alt)
    return Alternatives(dates=[str(joined.index[i].date()) for i in keep], items=items)


def _top_columns(rets: pd.DataFrame, w: pd.Series, limit: int = 12) -> pd.DataFrame:
    dense = [c for c in rets.columns if rets[c].notna().mean() >= 0.8]
    top = w.reindex(dense).sort_values(ascending=False).index[:limit]
    return rets[list(top)]


# ─── Entry point ──────────────────────────────────────────────────────────────


def run_deep_analysis(req: DeepAnalysisRequest) -> DeepAnalysisResponse:
    """Run the full deep analysis for a portfolio.

    Raises:
        InsufficientDataError: when no holding has usable price history.
    """
    notional = not any(h.amount or h.quantity for h in req.holdings)
    liq = req.liquidita
    window_start = date.today() - timedelta(days=365 * req.lookback_years)
    positions, ph, bench = _resolve_positions(req, notional, window_start)
    if not any(p.has_history for p in positions):
        raise InsufficientDataError("Nessuno strumento con storico prezzi utilizzabile")

    as_of = ph.index[-1].date()
    curve, values, t0 = _since_purchase(positions, ph, liq, bench)
    holdings, classes = _attribution(positions, liq)
    port, rets, w = _window_returns(positions, ph, liq, window_start)
    if len(port) < 30:
        raise InsufficientDataError("Storico troppo breve per le metriche di rischio")
    bench_r = ph.eur[bench].pct_change(fill_method=None).reindex(port.index) if bench else None
    top = _top_columns(rets, w)
    summary = _summary(positions, liq, curve, t0, as_of)
    total = summary.current_value
    covered = sum(p.value for p in positions if p.has_history) + liq

    return DeepAnalysisResponse(
        as_of=str(as_of),
        coverage_pct=round(covered / total * 100, 1) if total else 0.0,
        excluded=[p.h.ticker for p in positions if not p.has_history],
        assumed_dates=[p.h.ticker for p in positions if p.assumed],
        notional=notional,
        summary=summary,
        risk=pm.risk_metrics(port, req.risk_free, bench_r),
        benchmark_risk=pm.risk_metrics(bench_r.dropna(), req.risk_free) if bench_r is not None else None,
        benchmark=bench or "",
        equity_curve=curve,
        holdings=holdings,
        classes=classes,
        allocation_over_time=_allocation_over_time(positions, values, liq),
        correlation=pm.correlation(top),
        frontier=pm.efficient_frontier(top, w, req.risk_free),
        distribution=pm.distribution(port),
        monte_carlo=pm.monte_carlo(port, total),
        alternatives=_alternatives(req, ph, port),
    )
