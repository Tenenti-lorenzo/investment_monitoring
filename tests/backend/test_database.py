"""backend.database: user lookups (index query, scan fallback) and login lockout."""

from typing import Any

import pytest
from botocore.exceptions import ClientError

from backend import database

MARIO = {"username": "mario", "email": "m@x.it", "reset_token_hash": "h"}


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "Op")


class FakeTable:
    """DynamoDB Table stand-in: GSI query (optionally missing) + paged scan."""

    def __init__(self, pages: list[list[dict[str, Any]]], has_index: bool = True) -> None:
        self.pages, self.has_index = pages, has_index
        self.scans: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.failed = 0

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        if not self.has_index:
            raise _client_error("ValidationException")
        return {"Items": [i for page in self.pages for i in page][:1]}

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        self.scans.append(kwargs)
        i = kwargs.get("ExclusiveStartKey", {}).get("page", 0)
        resp: dict[str, Any] = {"Items": self.pages[i]}
        if i + 1 < len(self.pages):
            resp["LastEvaluatedKey"] = {"page": i + 1}
        return resp

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        if kwargs["UpdateExpression"].startswith("ADD"):
            self.failed += 1
            return {"Attributes": {"failed_logins": self.failed}}
        return {}


def use(monkeypatch: pytest.MonkeyPatch, table: FakeTable) -> FakeTable:
    monkeypatch.setattr(database, "_table", lambda: table)
    return table


def test_get_user_by_email_when_index_exists_then_query_not_scan(monkeypatch):
    t = use(monkeypatch, FakeTable([[MARIO]]))
    assert database.get_user_by_email("m@x.it")["username"] == "mario"
    assert t.queries[0]["IndexName"] == database.EMAIL_INDEX and t.scans == []


def test_get_user_by_reset_token_when_index_missing_then_paged_scan_finds_later_page(monkeypatch):
    t = use(monkeypatch, FakeTable([[], [], [MARIO]], has_index=False))
    assert database.get_user_by_reset_token("h")["username"] == "mario"
    assert len(t.scans) == 3


def test_get_user_by_email_when_no_page_matches_then_none(monkeypatch):
    t = use(monkeypatch, FakeTable([[], []], has_index=False))
    assert database.get_user_by_email("ghost@x.it") is None
    assert len(t.scans) == 2


def test_register_failed_login_when_threshold_reached_then_lock_set(monkeypatch):
    t = use(monkeypatch, FakeTable([]))
    results = [database.register_failed_login("mario", 3, 15) for _ in range(3)]
    assert results[:2] == [None, None] and results[2] is not None
    assert "lock_until" in t.updates[-1]["UpdateExpression"]


def test_register_failed_login_when_unknown_user_then_no_item_created(monkeypatch):
    t = use(monkeypatch, FakeTable([]))

    def reject(**kwargs: Any) -> None:
        raise _client_error("ConditionalCheckFailedException")

    t.update_item = reject  # type: ignore[method-assign]
    assert database.register_failed_login("ghost", 3, 15) is None
