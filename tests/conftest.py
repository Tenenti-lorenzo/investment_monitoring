"""Shared fixtures: offline guard, cache reset, fake DB and an authenticated API client.

Importing ``backend.main`` normally touches AWS (Secrets Manager, DynamoDB
table creation): both are neutralised here *before* the import.
"""

import os

os.environ["SECRETS_ARN"] = ""  # load_dotenv() never overrides an existing var
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import backend.database as database  # noqa: E402

database.init_db = lambda: None  # no DynamoDB on import

import pytest  # noqa: E402
import requests  # noqa: E402
import yfinance  # noqa: E402
from fakes import FakeDB  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import bond_market, bonds, main, superinvestors  # noqa: E402

_DB_FUNCS = (
    "get_user_by_username",
    "get_user_by_email",
    "get_user_by_reset_token",
    "create_user",
    "set_reset_token",
    "set_password",
    "save_portfolio_dynamo",
    "list_portfolios_dynamo",
    "load_portfolio_dynamo",
    "delete_portfolio_dynamo",
)


def _blocked(*args: object, **kwargs: object) -> None:
    raise RuntimeError("Network access is disabled in unit tests (mark the test with @pytest.mark.live)")


@pytest.fixture(autouse=True)
def offline(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Block HTTP and Yahoo Finance unless the test is marked ``live``."""
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setattr(requests.sessions.Session, "request", _blocked)
    monkeypatch.setattr(yfinance, "Ticker", _blocked)
    monkeypatch.setattr(yfinance, "download", _blocked)


@pytest.fixture(autouse=True)
def clear_caches() -> None:
    """Module-level scraper caches must not leak between tests."""
    bond_market._quote_cache.clear()
    superinvestors._cache.clear()
    bonds._yield_cache.clear()


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeDB:
    db = FakeDB()
    for name in _DB_FUNCS:
        monkeypatch.setattr(main, name, getattr(db, name))
    return db


@pytest.fixture
def client(fake_db: FakeDB) -> TestClient:
    """Unauthenticated client (fake DB wired in)."""
    return TestClient(main.app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {main._create_token('mario')}"}
