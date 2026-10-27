"""backend.database: user lookups by scan must follow pagination."""

from typing import Any

import pytest

from backend import database


class PagedTable:
    """DynamoDB Table stand-in: one filtered item per page, as a scan returns them."""

    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        i = kwargs.get("ExclusiveStartKey", {}).get("page", 0)
        resp: dict[str, Any] = {"Items": self.pages[i]}
        if i + 1 < len(self.pages):
            resp["LastEvaluatedKey"] = {"page": i + 1}
        return resp


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> PagedTable:
    t = PagedTable([[], [], [{"username": "mario", "email": "m@x.it", "reset_token": "tok"}]])
    monkeypatch.setattr(database, "_table", lambda: t)
    return t


def test_get_user_by_email_when_match_on_later_page_then_found(table):
    assert database.get_user_by_email("m@x.it")["username"] == "mario"
    assert len(table.calls) == 3


def test_get_user_by_reset_token_when_match_on_later_page_then_found(table):
    assert database.get_user_by_reset_token("tok")["username"] == "mario"


def test_get_user_by_email_when_no_page_matches_then_none(monkeypatch):
    t = PagedTable([[], []])
    monkeypatch.setattr(database, "_table", lambda: t)
    assert database.get_user_by_email("ghost@x.it") is None
    assert len(t.calls) == 2
