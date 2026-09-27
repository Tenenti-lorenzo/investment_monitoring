"""/api/auth/* and JWT protection."""

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from backend import main


def register(client, username="mario", email="mario@example.com", password="secret1"):
    return client.post(
        "/api/auth/register", json={"username": username, "email": email, "password": password}
    )


def test_register_when_valid_then_token_and_user_stored(client, fake_db):
    res = register(client, username="  mario ", email=" Mario@Example.com ")
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "mario" and body["token"]
    assert jwt.decode(body["token"], main.SECRET_KEY, algorithms=["HS256"])["sub"] == "mario"
    user = fake_db.users["mario"]
    assert user["email"] == "mario@example.com"
    assert user["hashed_password"] != "secret1"  # bcrypt hash, never plain text


def test_register_when_short_password_then_400(client):
    assert register(client, password="12345").status_code == 400


@pytest.mark.parametrize(
    "second",
    [
        {"username": "mario", "email": "other@example.com"},
        {"username": "luigi", "email": "mario@example.com"},
    ],
)
def test_register_when_username_or_email_taken_then_400(client, second):
    register(client)
    assert register(client, **second).status_code == 400


def test_login_when_credentials_valid_then_token(client):
    register(client)
    res = client.post("/api/auth/login", json={"username": "mario", "password": "secret1"})
    assert res.status_code == 200 and res.json()["username"] == "mario"


@pytest.mark.parametrize("username,password", [("mario", "wrong!"), ("ghost", "secret1")])
def test_login_when_wrong_password_or_unknown_user_then_401(client, username, password):
    register(client)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 401


def test_me_when_authenticated_then_profile(client, auth_headers):
    register(client)
    res = client.get("/api/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"username": "mario", "email": "mario@example.com", "created_at": "2026-01-01"}


def test_me_when_user_deleted_then_404(client, auth_headers):
    assert client.get("/api/auth/me", headers=auth_headers).status_code == 404


def test_protected_when_no_token_then_rejected(client):
    assert client.get("/api/auth/me").status_code in (401, 403)


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        jwt.encode({"sub": "mario", "exp": datetime.now(UTC) - timedelta(hours=1)}, "test-secret-key"),
        jwt.encode({"sub": "mario"}, "another-secret"),
        jwt.encode({"exp": datetime.now(UTC) + timedelta(hours=1)}, "test-secret-key"),  # no sub
    ],
)
def test_protected_when_invalid_expired_or_forged_token_then_401(client, token):
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


# ─── Password reset ───────────────────────────────────────────────────────────


def test_forgot_when_unknown_email_then_generic_ok_without_link(client):
    res = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert res.status_code == 200 and "reset_url" not in res.json()


def test_forgot_when_known_email_without_smtp_then_reset_link_and_token_saved(client, fake_db, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    register(client)
    res = client.post("/api/auth/forgot-password", json={"email": "MARIO@example.com"})
    token = fake_db.users["mario"]["reset_token"]
    assert res.json()["reset_url"].endswith(f"/login?reset_token={token}")


def test_reset_when_valid_token_then_password_changed_and_token_cleared(client, fake_db):
    register(client)
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    fake_db.set_reset_token("mario", "tok", expires)
    res = client.post("/api/auth/reset-password", json={"token": "tok", "new_password": "newpass1"})
    assert res.status_code == 200
    assert "reset_token" not in fake_db.users["mario"]
    login = client.post("/api/auth/login", json={"username": "mario", "password": "newpass1"})
    assert login.status_code == 200


@pytest.mark.parametrize(
    "token,delta,password",
    [
        ("wrong", timedelta(hours=1), "newpass1"),  # unknown token
        ("tok", timedelta(hours=-1), "newpass1"),  # expired
        ("tok", timedelta(hours=1), "123"),  # too short
    ],
)
def test_reset_when_invalid_expired_or_short_then_400(client, fake_db, token, delta, password):
    register(client)
    fake_db.set_reset_token("mario", "tok", (datetime.now(UTC) + delta).isoformat())
    res = client.post("/api/auth/reset-password", json={"token": token, "new_password": password})
    assert res.status_code == 400
