"""backend.session_store against a minimal DynamoDB Table stand-in."""

from decimal import Decimal
from typing import Any

import pytest
from botocore.exceptions import ClientError

from backend import session_store


class FakeSessionsTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def put_item(self, Item: dict[str, Any]) -> None:
        self.items[(Item["username"], Item["sid"])] = {**Item, "expires_at": Decimal(Item["expires_at"])}

    def get_item(self, Key: dict[str, str], ConsistentRead: bool) -> dict[str, Any]:
        item = self.items.get((Key["username"], Key["sid"]))
        return {"Item": item} if item else {}

    def update_item(self, Key: dict[str, str], ExpressionAttributeValues: dict[str, Any], **_: Any) -> None:
        item = self.items[(Key["username"], Key["sid"])]
        v = ExpressionAttributeValues
        if item["jti"] != v[":old"]:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        retired = [{"jti": r["jti"], "until": Decimal(r["until"])} for r in v[":r"]]
        item.update(jti=v[":new"], retired=retired, expires_at=Decimal(v[":e"]))

    def query(self, KeyConditionExpression: Any, **_: Any) -> dict[str, Any]:
        username = KeyConditionExpression.get_expression()["values"][1]
        return {"Items": [{"sid": sid} for (u, sid) in self.items if u == username]}

    def delete_item(self, Key: dict[str, str]) -> None:
        self.items.pop((Key["username"], Key["sid"]), None)

    def batch_writer(self) -> "FakeSessionsTable":
        return self

    def __enter__(self) -> "FakeSessionsTable":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> FakeSessionsTable:
    t = FakeSessionsTable()
    monkeypatch.setattr(session_store, "_stable", lambda: t)
    return t


def test_get_session_when_stored_then_numbers_are_ints(table):
    session_store.create_session("mario", "s1", "j1", 1000)
    s = session_store.get_session("mario", "s1")
    assert s["expires_at"] == 1000 and isinstance(s["expires_at"], int) and s["retired"] == []


def test_rotate_session_when_jti_already_rotated_then_false(table):
    session_store.create_session("mario", "s1", "j1", 1000)
    retired = [{"jti": "j1", "until": 1030}]
    assert session_store.rotate_session("mario", "s1", "j1", "j2", retired, 1900) is True
    assert session_store.rotate_session("mario", "s1", "j1", "j3", retired, 1900) is False
    s = session_store.get_session("mario", "s1")
    assert s["jti"] == "j2" and s["retired"] == retired and isinstance(s["retired"][0]["until"], int)


def test_delete_user_sessions_when_called_then_only_that_user_cleared(table):
    for sid in ("a", "b"):
        session_store.create_session("mario", sid, "j", 1000)
    session_store.create_session("luigi", "c", "j", 1000)
    session_store.delete_user_sessions("mario")
    assert list(table.items) == [("luigi", "c")]
