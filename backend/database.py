import os
import json as _json
import uuid
import boto3
from datetime import datetime, timezone
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr, Key

TABLE_NAME       = os.getenv("DYNAMODB_TABLE",            "portfoliolab_users")
PORTFOLIOS_TABLE = os.getenv("DYNAMODB_PORTFOLIOS_TABLE", "portfoliolab_portfolios")
_REGION          = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "eu-central-1"))


def _table():
    return boto3.resource("dynamodb", region_name=_REGION).Table(TABLE_NAME)

def _ptable():
    return boto3.resource("dynamodb", region_name=_REGION).Table(PORTFOLIOS_TABLE)


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


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user_by_username(username: str) -> dict | None:
    resp = _table().get_item(Key={"username": username})
    return resp.get("Item")

def get_user_by_email(email: str) -> dict | None:
    resp = _table().scan(FilterExpression=Attr("email").eq(email))
    items = resp.get("Items", [])
    return items[0] if items else None

def get_user_by_reset_token(token: str) -> dict | None:
    resp = _table().scan(FilterExpression=Attr("reset_token").eq(token))
    items = resp.get("Items", [])
    return items[0] if items else None

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

def set_reset_token(username: str, token: str, expires: str) -> None:
    _table().update_item(
        Key={"username": username},
        UpdateExpression="SET reset_token = :t, reset_token_expires = :e",
        ExpressionAttributeValues={":t": token, ":e": expires},
    )

def set_password(username: str, hashed_password: str) -> None:
    _table().update_item(
        Key={"username": username},
        UpdateExpression="SET hashed_password = :p REMOVE reset_token, reset_token_expires",
        ExpressionAttributeValues={":p": hashed_password},
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
