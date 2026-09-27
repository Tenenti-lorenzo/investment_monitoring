"""Look-through (X-Ray) of a portfolio: what ETFs and funds really hold.

Aggregates asset classes, sectors, geography, currencies, underlying
positions and ETF overlap, bond duration/credit and running costs.
Data comes from Yahoo `funds_data` (ETFs), `info` (stocks) and
Borsa Italiana (single bonds).
"""

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutTimeout
from datetime import date
from itertools import combinations

import yfinance as yf
from pydantic import BaseModel

from backend.analysis_models import (
    AnalysisHolding,
    BondDetail,
    CostDetail,
    DeepAnalysisRequest,
    LookThroughResponse,
    OverlapPair,
    Share,
    UnderlyingExposure,
)
from backend.bond_market import fetch_bond_quote
from backend.price_history import normalize_currency

logger = logging.getLogger(__name__)

SECTOR_LABELS = {
    "technology": "Tecnologia",
    "financialservices": "Finanza",
    "healthcare": "Salute",
    "industrials": "Industria",
    "consumercyclical": "Beni voluttuari",
    "communicationservices": "Comunicazioni",
    "consumerdefensive": "Beni di prima necessità",
    "energy": "Energia",
    "basicmaterials": "Materiali",
    "utilities": "Utility",
    "realestate": "Immobiliare",
}
RATING_ORDER = ["aaa", "aa", "a", "bbb", "bb", "b", "below_b", "other"]
_ASSET_KEYS = {
    "stockPosition": "Azioni",
    "bondPosition": "Obbligazioni",
    "cashPosition": "Liquidità",
    "preferredPosition": "Altro",
    "convertiblePosition": "Altro",
    "otherPosition": "Altro",
}
_FETCH_TIMEOUT_S = 15.0


class InstrumentProfile(BaseModel):
    """What one instrument contributes to the look-through (weights sum to 1)."""

    asset_classes: dict[str, float] = {}
    sectors: dict[str, float] = {}
    top_holdings: dict[str, tuple[str, float]] = {}  # symbol → (name, weight)
    ratings: dict[str, float] = {}
    duration: float | None = None
    ter: float | None = None
    bond: BondDetail | None = None


def _sector_key(raw: str) -> str:
    return re.sub(r"[^a-z]", "", raw.lower())


def _base_symbol(ticker: str) -> str:
    return ticker.split(".")[0].upper()


# ─── Bond math ────────────────────────────────────────────────────────────────


def bond_yield_duration(
    price: float, coupon_pct: float, years: float, freq: int = 1
) -> tuple[float, float] | None:
    """Yield to maturity and modified duration of a plain fixed-coupon bond.

    Args:
        price: Clean price ("corso secco"), % of nominal.
        coupon_pct: Annual coupon, % of nominal.
        years: Years to maturity.
        freq: Coupons per year.

    Returns:
        (ytm %, modified duration in years), or None if inputs are invalid.

    The cash flows are discounted against the dirty price: accrued interest is
    estimated assuming regular coupon periods ending at maturity. Without it
    the yield is overstated just before each coupon date.
    """
    if price <= 0 or years <= 0:
        return None
    n = max(1, math.ceil(years * freq))
    c = coupon_pct / freq
    times = [years - (n - k) / freq for k in range(1, n + 1)]  # years from today
    cfs = [c] * (n - 1) + [c + 100]
    elapsed = 1 - times[0] * freq  # fraction of the current coupon period already accrued
    price = price + c * elapsed

    def pv(y: float) -> float:
        return float(sum(cf / (1 + y / freq) ** (t * freq) for cf, t in zip(cfs, times, strict=True)))

    lo, hi = -0.5, 1.0
    if (pv(lo) - price) * (pv(hi) - price) > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if (pv(mid) - price) * (pv(lo) - price) <= 0:
            hi = mid
        else:
            lo = mid
    y = (lo + hi) / 2
    total = pv(y)
    mac = sum(t * cf / (1 + y / freq) ** (t * freq) for cf, t in zip(cfs, times, strict=True)) / total
    return round(y * 100, 2), round(mac / (1 + y / freq), 2)


def _bond_profile(h: AnalysisHolding) -> InstrumentProfile:
    quote = fetch_bond_quote(h.isin)
    detail = BondDetail(ticker=h.ticker, name=h.name, weight_pct=0.0, kind="Obbligazione")
    if quote:
        detail.maturity, detail.coupon_pct, detail.price = (
            quote.maturity,
            quote.coupon_annual_pct,
            quote.price,
        )
        if quote.maturity:
            years = (date.fromisoformat(quote.maturity[:10]) - date.today()).days / 365.25
            detail.years_to_maturity = round(years, 2)
            freq = 1
            if quote.coupon_period_pct and quote.coupon_annual_pct:
                freq = max(1, round(quote.coupon_annual_pct / quote.coupon_period_pct))
            yd = bond_yield_duration(quote.price or 0, quote.coupon_annual_pct or 0, years, freq)
            if yd:
                detail.ytm_pct, detail.duration = yd
                if quote.coupon_annual_pct is None:  # coupon unknown: duration ≈ ok, yield is not
                    detail.ytm_pct = None
    return InstrumentProfile(asset_classes={"Obbligazioni": 1.0}, duration=detail.duration, bond=detail)


# ─── Per-instrument profiles ──────────────────────────────────────────────────


def _etf_profile(h: AnalysisHolding) -> InstrumentProfile:
    fd = yf.Ticker(h.yf_ticker or h.ticker).funds_data
    prof = InstrumentProfile()
    ac: dict[str, float] = {}
    for k, v in (fd.asset_classes or {}).items():
        if k in _ASSET_KEYS and v:
            ac[_ASSET_KEYS[k]] = ac.get(_ASSET_KEYS[k], 0.0) + float(v)
    prof.asset_classes = ac
    prof.sectors = {
        SECTOR_LABELS.get(_sector_key(k), k): float(v) for k, v in (fd.sector_weightings or {}).items() if v
    }
    th = fd.top_holdings
    if th is not None and not th.empty:
        prof.top_holdings = {
            _base_symbol(str(s)): (str(r["Name"]), float(r["Holding Percent"])) for s, r in th.iterrows()
        }
    prof.ratings = {k: float(v) for k, v in (fd.bond_ratings or {}).items() if k in RATING_ORDER and v}
    dur = _fund_field(fd, "bond_holdings", "Duration")
    ter = _fund_field(fd, "fund_operations", "Annual Report Expense Ratio")
    prof.duration = round(dur, 2) if dur is not None else None
    prof.ter = round(ter * 100, 3) if ter is not None else None
    return prof


def _fund_field(fd: object, table: str, row: str) -> float | None:
    """Read one numeric cell (first column) of a Yahoo funds_data table."""
    try:
        raw = getattr(fd, table).iloc[:, 0].get(row)
        val = float(raw)
    except Exception as e:  # noqa: BLE001 — optional field, often missing
        logger.debug("funds_data %s/%s unavailable: %s", table, row, e)
        return None
    return val if math.isfinite(val) else None


def _stock_profile(h: AnalysisHolding) -> InstrumentProfile:
    info = yf.Ticker(h.yf_ticker or h.ticker).info or {}
    sector = info.get("sector")
    sectors = {SECTOR_LABELS.get(_sector_key(sector), sector): 1.0} if sector else {}
    sym = _base_symbol(h.ticker)
    return InstrumentProfile(
        asset_classes={"Azioni": 1.0}, sectors=sectors, top_holdings={sym: (h.name or sym, 1.0)}
    )


def _fallback_profile(h: AnalysisHolding) -> InstrumentProfile:
    cat = h.category
    if cat in ("Azioni", "ETF Azionario"):
        return InstrumentProfile(asset_classes={"Azioni": 1.0})
    if cat in ("Obbligazioni", "ETF Obbligazionario"):
        return InstrumentProfile(asset_classes={"Obbligazioni": 1.0})
    if cat == "Criptovalute":
        return InstrumentProfile(asset_classes={"Cripto": 1.0})
    return InstrumentProfile(asset_classes={"Altro": 1.0})


def _profile(h: AnalysisHolding) -> InstrumentProfile:
    try:
        if h.category == "Obbligazioni" and h.isin:
            return _bond_profile(h)
        if h.category.startswith("ETF") and (h.yf_ticker or h.ticker):
            prof = _etf_profile(h)
            if not prof.asset_classes:
                prof.asset_classes = _fallback_profile(h).asset_classes
            return prof
        if h.category == "Azioni":
            return _stock_profile(h)
    except Exception as e:  # noqa: BLE001 — one bad ticker must not sink the report
        logger.info("look-through failed for %s: %s", h.ticker, e)
    return _fallback_profile(h)


def _fetch_profiles(holdings: list[AnalysisHolding]) -> list[InstrumentProfile]:
    out = [_fallback_profile(h) for h in holdings]
    with ThreadPoolExecutor(max_workers=min(8, len(holdings) or 1)) as ex:
        futures = {ex.submit(_profile, h): i for i, h in enumerate(holdings)}
        try:
            for fut in as_completed(futures, timeout=_FETCH_TIMEOUT_S):
                out[futures[fut]] = fut.result()
        except FutTimeout:
            logger.warning("look-through timed out; partial result")
    return out


# ─── Aggregation ──────────────────────────────────────────────────────────────


def _shares(acc: dict[str, float], total: float, min_pct: float = 0.05) -> list[Share]:
    rows = [Share(label=k, pct=round(v / total * 100, 2)) for k, v in acc.items() if total]
    return sorted([r for r in rows if r.pct >= min_pct], key=lambda s: -s.pct)


def _add(acc: dict[str, float], key: str, v: float) -> None:
    acc[key] = acc.get(key, 0.0) + v


def _weights(req: DeepAnalysisRequest) -> list[float]:
    """EUR value per holding; the client should send `amount` = current value.

    Falls back to quantity × purchase price, then to % allocation on a
    10,000 notional when no amount is known at all.
    """
    if not any(h.amount or h.quantity for h in req.holdings):
        return [h.allocation / 100 * 10_000 for h in req.holdings]
    out = []
    for h in req.holdings:
        if h.amount:
            out.append(float(h.amount))
        elif h.quantity and h.purchase_price:
            unit = 0.01 if h.category == "Obbligazioni" else 1.0
            out.append(float(h.quantity) * float(h.purchase_price) * unit)
        else:
            out.append(0.0)
    return out


def _exposures(
    holdings: list[AnalysisHolding], profiles: list[InstrumentProfile], values: list[float], total: float
) -> tuple[list[UnderlyingExposure], list[OverlapPair]]:
    names: dict[str, str] = {}
    weight: dict[str, float] = {}
    sources: dict[str, list[str]] = {}
    for h, p, v in zip(holdings, profiles, values, strict=True):
        for sym, (name, w) in p.top_holdings.items():
            names.setdefault(sym, name)
            _add(weight, sym, v * w)
            sources.setdefault(sym, []).append(h.ticker)
    top = sorted(weight, key=lambda s: -weight[s])[:20]
    exposures = [
        UnderlyingExposure(
            symbol=s, name=names[s], weight_pct=round(weight[s] / total * 100, 2), sources=sources[s]
        )
        for s in top
    ]
    etfs = [
        (h.ticker, p.top_holdings)
        for h, p in zip(holdings, profiles, strict=True)
        if h.category.startswith("ETF") and p.top_holdings
    ]
    overlaps = []
    for (a, ha), (b, hb) in combinations(etfs, 2):
        common = set(ha) & set(hb)
        pct = sum(min(ha[s][1], hb[s][1]) for s in common) * 100
        if pct > 0:
            overlaps.append(OverlapPair(a=a, b=b, overlap_pct=round(pct, 1)))
    return exposures, sorted(overlaps, key=lambda o: -o.overlap_pct)


def _bonds(
    holdings: list[AnalysisHolding], profiles: list[InstrumentProfile], values: list[float], total: float
) -> tuple[list[BondDetail], float | None, list[Share]]:
    details: list[BondDetail] = []
    ratings: dict[str, float] = {}
    dur_acc = dur_w = 0.0
    for h, p, v in zip(holdings, profiles, values, strict=True):
        bond_w = p.asset_classes.get("Obbligazioni", 0.0) * v
        if bond_w <= 0:
            continue
        d = p.bond or BondDetail(
            ticker=h.ticker, name=h.name, weight_pct=0.0, kind="ETF Obbligazionario", duration=p.duration
        )
        d.weight_pct = round(v / total * 100, 2)
        d.credit = [
            Share(label=k.upper().replace("_", " "), pct=round(p.ratings[k] * 100, 1))
            for k in RATING_ORDER
            if p.ratings.get(k)
        ]
        details.append(d)
        if p.duration is not None:
            dur_acc += p.duration * bond_w
            dur_w += bond_w
        for k, r in p.ratings.items():
            _add(ratings, k.upper().replace("_", " "), r * bond_w)
    rated = sum(ratings.values())
    order = [k.upper().replace("_", " ") for k in RATING_ORDER]
    credit = (
        [Share(label=k, pct=round(ratings[k] / rated * 100, 1)) for k in order if ratings.get(k)]
        if rated
        else []
    )
    return details, (round(dur_acc / dur_w, 2) if dur_w else None), credit


def run_look_through(req: DeepAnalysisRequest) -> LookThroughResponse:
    """Build the look-through report for the given holdings."""
    holdings = req.holdings
    values = _weights(req)
    liq = req.liquidita if any(h.amount or h.quantity for h in holdings) else 0.0
    total = sum(values) + liq or 1.0
    profiles = _fetch_profiles(holdings)

    classes: dict[str, float] = {}
    sectors: dict[str, float] = {}
    geo: dict[str, float] = {}
    cur: dict[str, float] = {}
    hedged = 0.0
    for h, p, v in zip(holdings, profiles, values, strict=True):
        for k, w in p.asset_classes.items():
            _add(classes, k, v * w)
        for k, w in p.sectors.items():
            _add(sectors, k, v * w)
        for k, w in (h.geography or {"N/D": 100}).items():
            _add(geo, k, v * w / 100)
        _add(cur, normalize_currency(h.currency)[0], v)
        if "hedged" in h.name.lower():
            hedged += v
    if liq:
        _add(classes, "Liquidità", liq)
        _add(cur, "EUR", liq)

    exposures, overlaps = _exposures(holdings, profiles, values, total)
    bonds, duration, credit = _bonds(holdings, profiles, values, total)
    costs = []
    for h, p, v in zip(holdings, profiles, values, strict=True):
        ter = h.ter if h.ter is not None else p.ter
        costs.append(
            CostDetail(
                ticker=h.ticker,
                name=h.name,
                value=round(v, 2),
                ter=ter,
                annual_cost=round(v * ter / 100, 2) if ter is not None else None,
            )
        )
    annual = sum(c.annual_cost or 0 for c in costs)
    equity_total = sum(sectors.values())

    return LookThroughResponse(
        asset_classes=_shares(classes, total),
        sectors=_shares(sectors, equity_total) if equity_total else [],
        geography=_shares(geo, sum(geo.values()) or 1.0),
        currencies=_shares(cur, total),
        hedged_pct=round(hedged / total * 100, 2),
        top_exposures=exposures,
        overlaps=overlaps,
        bonds=bonds,
        portfolio_duration=duration,
        credit_quality=credit,
        costs=sorted(costs, key=lambda c: -(c.annual_cost or 0)),
        ter_weighted=round(annual / total * 100, 3) if annual else None,
        annual_cost=round(annual, 2),
        cost_10y=round(annual * 10, 2),
        coverage_note="Le posizioni sottostanti degli ETF includono solo le prime 10 "
        "partecipazioni pubblicate da Yahoo Finance: l'overlap è un limite inferiore.",
    )
