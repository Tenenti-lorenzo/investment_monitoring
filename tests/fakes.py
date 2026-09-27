"""Test doubles for the external services (HTTP, Yahoo Finance, DynamoDB).

Nothing here touches the network: every scraper is fed captured HTML from
``tests/fixtures`` and every market-data call returns synthetic frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.price_history import PriceHistory

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ─── HTTP ─────────────────────────────────────────────────────────────────────


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(
        self, content: bytes | str = b"", status_code: int = 200, url: str = "", json_data: Any = None
    ) -> None:
        self.content = content.encode() if isinstance(content, str) else content
        self.status_code = status_code
        self.url = url
        self._json = json_data

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return self._json


# ─── Yahoo Finance ────────────────────────────────────────────────────────────


@dataclass
class FakeFastInfo:
    last_price: float | None = None
    currency: str | None = None


@dataclass
class FakeFundsData:
    asset_classes: dict[str, float] = field(default_factory=dict)
    sector_weightings: dict[str, float] = field(default_factory=dict)
    top_holdings: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=["Name", "Holding Percent"])
    )
    bond_ratings: dict[str, float] = field(default_factory=dict)
    bond_holdings: pd.DataFrame = field(default_factory=pd.DataFrame)
    fund_operations: pd.DataFrame = field(default_factory=pd.DataFrame)
    fund_overview: dict[str, Any] = field(default_factory=dict)


def top_holdings(rows: dict[str, tuple[str, float]]) -> pd.DataFrame:
    """{symbol: (name, weight fraction)} → Yahoo ``top_holdings`` frame."""
    df = pd.DataFrame([{"Symbol": s, "Name": n, "Holding Percent": w} for s, (n, w) in rows.items()])
    return df.set_index("Symbol")


class FakeTicker:
    def __init__(
        self,
        info: dict[str, Any] | None = None,
        last_price: float | None = None,
        currency: str | None = None,
        funds_data: FakeFundsData | None = None,
        history: pd.Series | None = None,
    ) -> None:
        self.info = info if info is not None else {}
        self.fast_info = FakeFastInfo(last_price, currency)
        self.funds_data = funds_data or FakeFundsData()
        self._history = history

    def history(self, period: str = "1y") -> pd.DataFrame:
        if self._history is None:
            return pd.DataFrame({"Close": pd.Series(dtype=float)})
        return pd.DataFrame({"Close": self._history})


def ticker_factory(tickers: dict[str, FakeTicker]):
    """Replacement for ``yf.Ticker``: unknown symbols get an empty ticker."""
    return lambda symbol: tickers.get(symbol, FakeTicker())


# ─── Price history ────────────────────────────────────────────────────────────


def bdays(n: int, end: date | None = None) -> pd.DatetimeIndex:
    last = pd.offsets.BDay().rollback(pd.Timestamp(end or date.today()))  # weekend → Friday
    return pd.bdate_range(end=last, periods=n)


def make_history(local: dict[str, pd.Series], fx: dict[str, pd.Series] | None = None) -> PriceHistory:
    """Build a PriceHistory from local prices and optional FX (currency per EUR)."""
    fx = fx or {}
    idx = next(iter(local.values())).index
    rates = {t: fx.get(t, pd.Series(1.0, index=idx)) for t in local}
    loc = pd.DataFrame(local)
    rate = pd.DataFrame(rates)
    return PriceHistory(loc, loc / rate, rate)


def random_walk(
    idx: pd.DatetimeIndex, start: float = 100.0, vol: float = 0.01, drift: float = 0.0004, seed: int = 1
) -> pd.Series:
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, len(idx))
    r[0] = 0.0
    return pd.Series(start * np.cumprod(1 + r), index=idx)


# ─── DynamoDB ─────────────────────────────────────────────────────────────────


class FakeDB:
    """In-memory replacement for backend.database (users + portfolios)."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.portfolios: dict[tuple[str, str], dict[str, Any]] = {}
        self._next = 0

    # users
    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return self.users.get(username)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return next((u for u in self.users.values() if u["email"] == email), None)

    def get_user_by_reset_token(self, token: str) -> dict[str, Any] | None:
        return next((u for u in self.users.values() if u.get("reset_token") == token), None)

    def create_user(self, username: str, email: str, hashed_password: str) -> None:
        if self.get_user_by_email(email):
            raise ValueError("email_exists")
        if username in self.users:
            raise ValueError("username_exists")
        self.users[username] = {
            "username": username,
            "email": email,
            "hashed_password": hashed_password,
            "created_at": "2026-01-01",
        }

    def set_reset_token(self, username: str, token: str, expires: str) -> None:
        self.users[username].update(reset_token=token, reset_token_expires=expires)

    def set_password(self, username: str, hashed_password: str) -> None:
        u = self.users[username]
        u["hashed_password"] = hashed_password
        u.pop("reset_token", None)
        u.pop("reset_token_expires", None)

    # portfolios
    def save_portfolio_dynamo(self, username: str, name: str, data: dict[str, Any]) -> str:
        self._next += 1
        pid = f"p{self._next}"
        self.portfolios[(username, pid)] = {"name": name, "data": data}
        return pid

    def list_portfolios_dynamo(self, username: str) -> list[dict[str, Any]]:
        return [
            {
                "portfolio_id": pid,
                "name": v["name"],
                "savedAt": v["data"].get("savedAt", ""),
                "holdings_count": len(v["data"].get("holdings", [])),
            }
            for (u, pid), v in self.portfolios.items()
            if u == username
        ]

    def load_portfolio_dynamo(self, username: str, pid: str) -> dict[str, Any] | None:
        item = self.portfolios.get((username, pid))
        if item is None:
            return None
        return {**item["data"], "portfolio_id": pid, "name": item["name"]}

    def delete_portfolio_dynamo(self, username: str, pid: str) -> None:
        self.portfolios.pop((username, pid), None)
