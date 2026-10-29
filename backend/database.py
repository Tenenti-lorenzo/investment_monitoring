import os
import json as _json
import logging
import uuid
import boto3
from datetime import datetime, timedelta, timezone
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr, Key
from pydantic import ValidationError

from backend.wealth_models import OtherAsset

logger = logging.getLogger(__name__)

TABLE_NAME       = os.getenv("DYNAMODB_TABLE",            "portfoliolab_users")
PORTFOLIOS_TABLE = os.getenv("DYNAMODB_PORTFOLIOS_TABLE", "portfoliolab_portfolios")
SESSIONS_TABLE   = os.getenv("DYNAMODB_SESSIONS_TABLE",   "portfoliolab_sessions")
ASSETS_TABLE     = os.getenv("DYNAMODB_ASSETS_TABLE",     "portfoliolab_assets")
_REGION          = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "eu-central-1"))

# Global secondary indexes on the users table (terraform/dynamodb.tf). Tables
# created before them still work: lookups fall back to a paginated scan.
EMAIL_INDEX = "email-index"
RESET_INDEX = "reset_token_hash-index"


def _table():
    return boto3.resource("dynamodb", region_name=_REGION).Table(TABLE_NAME)

def _ptable():
    return boto3.resource("dynamodb", region_name=_REGION).Table(PORTFOLIOS_TABLE)

def _atable():
    return boto3.resource("dynamodb", region_name=_REGION).Table(ASSETS_TABLE)


def _ensure_table(client, name: str, key_schema: list, attr_defs: list) -> None:
    try:
        client.describe_table(TableName=name)
    except client.exceptions.ResourceNotFoundException:
        client.create_table(
            TableName=name,
            KeySchema=key_schema,
            AttributeDefinitions=attr_defs,
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=name)


def init_db() -> None:
    client = boto3.client("dynamodb", region_name=_REGION)
    _ensure_table(
        client, TABLE_NAME,
        [{"AttributeName": "username", "KeyType": "HASH"}],
        [{"AttributeName": "username", "AttributeType": "S"}],
    )
    _ensure_table(
        client, PORTFOLIOS_TABLE,
        [
            {"AttributeName": "username",     "KeyType": "HASH"},
            {"AttributeName": "portfolio_id", "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "username",     "AttributeType": "S"},
            {"AttributeName": "portfolio_id", "AttributeType": "S"},
        ],
    )
    _ensure_table(
        client, SESSIONS_TABLE,
        [
            {"AttributeName": "username", "KeyType": "HASH"},
            {"AttributeName": "sid",      "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "username", "AttributeType": "S"},
            {"AttributeName": "sid",      "AttributeType": "S"},
        ],
    )
    _ensure_table(
        client, ASSETS_TABLE,
        [
            {"AttributeName": "username", "KeyType": "HASH"},
            {"AttributeName": "asset_id", "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "username", "AttributeType": "S"},
            {"AttributeName": "asset_id", "AttributeType": "S"},
        ],
    )
    try:  # DynamoDB deletes idle sessions by itself (Terraform sets this in AWS)
        client.update_time_to_live(
            TableName=SESSIONS_TABLE,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
        )
    except ClientError:
        pass  # already enabled


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user_by_username(username: str) -> dict | None:
    resp = _table().get_item(Key={"username": username})
    return resp.get("Item")

def _scan_first(condition) -> dict | None:
    # A scan reads at most 1 MB per page and filters afterwards, so a match can
    # sit on any page: follow LastEvaluatedKey until found or exhausted.
    table, kwargs = _table(), {"FilterExpression": condition}
    while True:
        resp = table.scan(**kwargs)
        if resp.get("Items"):
            return resp["Items"][0]
        if "LastEvaluatedKey" not in resp:
            return None
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

def _lookup_first(index: str, attr: str, value: str) -> dict | None:
    try:
        resp = _table().query(IndexName=index, KeyConditionExpression=Key(attr).eq(value), Limit=1)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("ValidationException", "ResourceNotFoundException"):
            raise
        return _scan_first(Attr(attr).eq(value))  # index not created yet
    items = resp.get("Items", [])
    return items[0] if items else None

def get_user_by_email(email: str) -> dict | None:
    return _lookup_first(EMAIL_INDEX, "email", email)

def get_user_by_reset_token(token_hash: str) -> dict | None:
    """Look up by the SHA-256 of the reset token: the token itself is never stored."""
    return _lookup_first(RESET_INDEX, "reset_token_hash", token_hash)

def create_user(username: str, email: str, hashed_password: str) -> None:
    if get_user_by_email(email):
        raise ValueError("email_exists")
    try:
        _table().put_item(
            Item={
                "username":        username,
                "email":           email,
                "hashed_password": hashed_password,
                "created_at":      datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_not_exists(username)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ValueError("username_exists")
        raise

def set_reset_token(username: str, token_hash: str, expires: str) -> None:
    _table().update_item(
        Key={"username": username},
        UpdateExpression="SET reset_token_hash = :t, reset_token_expires = :e REMOVE reset_token",
        ExpressionAttributeValues={":t": token_hash, ":e": expires},
    )

def set_password(username: str, hashed_password: str) -> None:
    """New password: also burns the reset token and clears any login lockout."""
    _table().update_item(
        Key={"username": username},
        UpdateExpression=(
            "SET hashed_password = :p "
            "REMOVE reset_token, reset_token_hash, reset_token_expires, failed_logins, lock_until"
        ),
        ExpressionAttributeValues={":p": hashed_password},
    )


# ── Login lockout ─────────────────────────────────────────────────────────────

def register_failed_login(username: str, max_attempts: int, lock_minutes: int) -> str | None:
    """Count a wrong password; at ``max_attempts`` lock the account.

    Returns the ISO lock expiry when this failure triggered the lock, else None.
    """
    try:
        resp = _table().update_item(
            Key={"username": username},
            UpdateExpression="ADD failed_logins :one",
            ConditionExpression="attribute_exists(username)",  # never create items for unknown users
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise
    if int(resp["Attributes"]["failed_logins"]) < max_attempts:
        return None
    until = (datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)).isoformat()
    _table().update_item(
        Key={"username": username},
        UpdateExpression="SET lock_until = :u, failed_logins = :zero",
        ExpressionAttributeValues={":u": until, ":zero": 0},
    )
    return until

def clear_failed_logins(username: str) -> None:
    _table().update_item(
        Key={"username": username},
        UpdateExpression="REMOVE failed_logins, lock_until",
    )


# ── Portfolios ────────────────────────────────────────────────────────────────

def save_portfolio_dynamo(username: str, name: str, portfolio_data: dict) -> str:
    pid      = str(uuid.uuid4())
    saved_at = portfolio_data.get("savedAt") or datetime.now(timezone.utc).isoformat()
    _ptable().put_item(Item={
        "username":       username,
        "portfolio_id":   pid,
        "name":           name,
        "data":           _json.dumps(portfolio_data, default=str),
        "savedAt":        saved_at,
        "holdings_count": str(len(portfolio_data.get("holdings", []))),
    })
    return pid

def list_portfolios_dynamo(username: str) -> list:
    resp  = _ptable().query(KeyConditionExpression=Key("username").eq(username))
    items = resp.get("Items", [])
    return sorted(
        [{
            "portfolio_id":   i["portfolio_id"],
            "name":           i.get("name", "Portafoglio"),
            "savedAt":        i.get("savedAt", ""),
            "holdings_count": int(i.get("holdings_count", 0)),
        } for i in items],
        key=lambda x: x["savedAt"],
        reverse=True,
    )

def load_portfolio_dynamo(username: str, portfolio_id: str) -> dict | None:
    resp = _ptable().get_item(Key={"username": username, "portfolio_id": portfolio_id})
    item = resp.get("Item")
    if not item:
        return None
    data = _json.loads(item["data"])
    data["portfolio_id"] = item["portfolio_id"]
    data["name"]         = item.get("name", "Portafoglio")
    return data

def delete_portfolio_dynamo(username: str, portfolio_id: str) -> None:
    _ptable().delete_item(Key={"username": username, "portfolio_id": portfolio_id})


# ── Other assets (life insurance, pension, real estate, private) ──────────────

def save_asset_dynamo(username: str, asset: OtherAsset) -> None:
    """Insert or replace; ``asset.asset_id`` must be set. Stored as JSON (no Decimal juggling)."""
    _atable().put_item(Item={
        "username": username,
        "asset_id": asset.asset_id,
        "data":     asset.model_dump_json(),
    })

def list_assets_dynamo(username: str) -> list[OtherAsset]:
    table, kwargs = _atable(), {"KeyConditionExpression": Key("username").eq(username)}
    assets = []
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            try:
                assets.append(OtherAsset.model_validate_json(item["data"]))
            except ValidationError:
                logger.warning("Skipping invalid stored asset %s of %s", item.get("asset_id"), username)
        if "LastEvaluatedKey" not in resp:
            return assets
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

def delete_asset_dynamo(username: str, asset_id: str) -> None:
    _atable().delete_item(Key={"username": username, "asset_id": asset_id})
