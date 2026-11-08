"""DynamoDB persistence of login sessions (server-side half of the rotating JWT).

One item per session, keyed ``(username, sid)``:

* ``jti``        – id of the only token currently valid for the session;
* ``retired``    – the last few tokens rotated away, each with the epoch second
  until which it is still accepted, so parallel requests sent with an older
  token do not log the user out;
* ``expires_at`` – epoch seconds of idle expiry, also the table's TTL attribute.

Deleting the item revokes the session immediately (logout, password reset,
detected token replay).
"""
from __future__ import annotations

from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from backend.database import _REGION, SESSIONS_TABLE


def _stable() -> Any:
    return boto3.resource("dynamodb", region_name=_REGION).Table(SESSIONS_TABLE)


def create_session(username: str, sid: str, jti: str, expires_at: int) -> None:
    _stable().put_item(Item={"username": username, "sid": sid, "jti": jti, "expires_at": expires_at})


def get_session(username: str, sid: str) -> dict[str, Any] | None:
    item = _stable().get_item(Key={"username": username, "sid": sid}, ConsistentRead=True).get("Item")
    if not item:
        return None
    # DynamoDB numbers come back as Decimal
    retired = [{"jti": r["jti"], "until": int(r["until"])} for r in item.get("retired", [])]
    return {**item, "expires_at": int(item["expires_at"]), "retired": retired}


def rotate_session(
    username: str, sid: str, old_jti: str, new_jti: str, retired: list[dict[str, Any]], expires_at: int
) -> bool:
    """Swap ``old_jti`` for ``new_jti``; False if another request rotated it first."""
    try:
        _stable().update_item(
            Key={"username": username, "sid": sid},
            UpdateExpression="SET jti = :new, retired = :r, expires_at = :e",
            ConditionExpression="jti = :old",
            ExpressionAttributeValues={":new": new_jti, ":old": old_jti, ":r": retired, ":e": expires_at},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


def delete_session(username: str, sid: str) -> None:
    _stable().delete_item(Key={"username": username, "sid": sid})


def delete_user_sessions(username: str) -> None:
    """Revoke every session of ``username`` (e.g. after a password reset)."""
    table = _stable()
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("username").eq(username), "ProjectionExpression": "sid"}
    with table.batch_writer() as batch:
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                batch.delete_item(Key={"username": username, "sid": item["sid"]})
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
