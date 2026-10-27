"""/api/auth/*, rotating sessions, lockout and password reset."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from backend import main

PASSWORD = "correct-horse-1"


def register(client, username="mario", email="mario@example.com", password=PASSWORD):
    return client.post(
        "/api/auth/register", json={"username": username, "email": email, "password": password}
    )


def login(client, username="mario", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def claims(token: str) -> dict:
    return jwt.decode(token, main.SECRET_KEY, algorithms=["HS256"])


# ─── Registration ─────────────────────────────────────────────────────────────


def test_register_when_valid_then_session_token_and_user_stored(client, fake_db):
    res = register(client, username="  mario ", email=" Mario@Example.com ")
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "mario"
    c = claims(body["token"])
    assert c["sub"] == "mario" and ("mario", c["sid"]) in fake_db.sessions
    user = fake_db.users["mario"]
    assert user["email"] == "mario@example.com"
    assert user["hashed_password"] != PASSWORD  # bcrypt hash, never plain text


def test_register_when_password_shorter_than_10_then_400(client, fake_db):
    assert register(client, password="123456789").status_code == 400
    assert not fake_db.users


@pytest.mark.parametrize(
    "fields",
    [
        {"username": "   "},
        {"username": "ab"},
        {"username": "mario rossi"},
        {"email": "not-an-email"},
        {"email": ""},
    ],
)
def test_register_when_invalid_username_or_email_then_400(client, fake_db, fields):
    assert register(client, **fields).status_code == 400
    assert not fake_db.users


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


# ─── Login & lockout ──────────────────────────────────────────────────────────


def test_login_when_credentials_valid_then_token(client):
    register(client)
    res = login(client)
    assert res.status_code == 200 and res.json()["username"] == "mario"


@pytest.mark.parametrize("username,password", [("mario", "wrong-password"), ("ghost", PASSWORD)])
def test_login_when_wrong_password_or_unknown_user_then_401(client, username, password):
    register(client)
    assert login(client, username, password).status_code == 401


def test_login_when_unknown_user_then_bcrypt_still_runs(client, monkeypatch):
    checked: list[str] = []
    real = main._verify_pw
    monkeypatch.setattr(main, "_verify_pw", lambda p, h: checked.append(h) or real(p, h))
    assert login(client, "ghost").status_code == 401
    assert checked == [main._DUMMY_HASH]  # no timing shortcut for unknown usernames


def test_login_when_5_wrong_passwords_then_locked_even_with_right_one(client, fake_db):
    register(client)
    codes = [login(client, password="wrong-password").status_code for _ in range(main.MAX_FAILED_LOGINS)]
    assert codes == [401] * (main.MAX_FAILED_LOGINS - 1) + [429]
    res = login(client)
    assert res.status_code == 429 and "riprova tra 15 minuti" in res.json()["detail"]


def test_login_when_lock_expired_then_ok_and_counter_cleared(client, fake_db):
    register(client)
    fake_db.users["mario"].update(failed_logins=3, lock_until=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    assert login(client).status_code == 200
    assert "failed_logins" not in fake_db.users["mario"] and "lock_until" not in fake_db.users["mario"]


# ─── Rotating session ─────────────────────────────────────────────────────────


def test_session_token_when_issued_then_expires_in_15_minutes(client):
    register(client)
    left = datetime.fromtimestamp(claims(login(client).json()["token"])["exp"], UTC) - datetime.now(UTC)
    assert timedelta(minutes=14) < left <= timedelta(minutes=15)


def test_protected_when_token_used_then_rotated_to_new_15_minute_token(client, fake_db):
    register(client)
    t0 = login(client).json()["token"]
    res = client.get("/api/auth/me", headers=bearer(t0))
    t1 = res.headers[main.REFRESH_HEADER]
    assert res.status_code == 200
    assert claims(t1)["sid"] == claims(t0)["sid"] and claims(t1)["jti"] != claims(t0)["jti"]
    session = fake_db.sessions[("mario", claims(t0)["sid"])]
    assert session["jti"] == claims(t1)["jti"]
    assert session["expires_at"] - time.time() > 14 * 60  # activity resets the 15-minute idle timer


def test_protected_when_parallel_request_uses_just_replaced_token_then_accepted(client):
    register(client)
    t0 = login(client).json()["token"]
    t1 = client.get("/api/auth/me", headers=bearer(t0)).headers[main.REFRESH_HEADER]
    res = client.get("/api/auth/me", headers=bearer(t0))  # inside the grace window
    assert res.status_code == 200
    assert claims(res.headers[main.REFRESH_HEADER])["jti"] == claims(t1)["jti"]


def test_protected_when_slow_request_carries_token_two_rotations_old_then_accepted(client):
    register(client)
    t0 = login(client).json()["token"]
    t1 = client.get("/api/auth/me", headers=bearer(t0)).headers[main.REFRESH_HEADER]
    t2 = client.get("/api/auth/me", headers=bearer(t1)).headers[main.REFRESH_HEADER]
    res = client.get("/api/auth/me", headers=bearer(t0))
    assert res.status_code == 200 and claims(res.headers[main.REFRESH_HEADER])["jti"] == claims(t2)["jti"]


def test_protected_when_replaced_token_replayed_after_grace_then_session_revoked(client, fake_db):
    register(client)
    t0 = login(client).json()["token"]
    t1 = client.get("/api/auth/me", headers=bearer(t0)).headers[main.REFRESH_HEADER]
    for r in fake_db.sessions[("mario", claims(t0)["sid"])]["retired"]:
        r["until"] = int(time.time()) - 1
    assert client.get("/api/auth/me", headers=bearer(t0)).status_code == 401  # stolen copy
    assert client.get("/api/auth/me", headers=bearer(t1)).status_code == 401  # whole session dead


def test_protected_when_idle_more_than_15_minutes_then_401(client, fake_db):
    register(client)
    t0 = login(client).json()["token"]
    fake_db.sessions[("mario", claims(t0)["sid"])]["expires_at"] = int(time.time()) - 1
    assert client.get("/api/auth/me", headers=bearer(t0)).status_code == 401


def test_logout_when_called_then_token_stops_working(client):
    register(client)
    t0 = login(client).json()["token"]
    assert client.post("/api/auth/logout", headers=bearer(t0)).status_code == 200
    assert client.get("/api/auth/me", headers=bearer(t0)).status_code == 401


def test_me_when_authenticated_then_profile(client, auth_headers):
    register(client)
    res = client.get("/api/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"username": "mario", "email": "mario@example.com", "created_at": "2026-01-01"}


def test_me_when_user_deleted_then_404(client, auth_headers):
    assert client.get("/api/auth/me", headers=auth_headers).status_code == 404


def test_protected_when_no_token_then_rejected(client):
    assert client.get("/api/auth/me").status_code in (401, 403)


def _forged(**payload) -> str:
    return jwt.encode(payload, main.SECRET_KEY, algorithm="HS256")


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        jwt.encode({"sub": "mario", "sid": "s", "jti": "j"}, "another-secret"),
        _forged(sub="mario", exp=datetime.now(UTC) + timedelta(hours=1)),  # legacy token: no session
        _forged(sub="mario", sid="unknown", jti="j", exp=datetime.now(UTC) + timedelta(hours=1)),
        _forged(sub="mario", sid="s", jti="j", exp=datetime.now(UTC) - timedelta(hours=1)),
    ],
)
def test_protected_when_invalid_forged_or_sessionless_token_then_401(client, fake_db, token):
    res = client.get("/api/auth/me", headers=bearer(token))
    assert res.status_code == 401
    assert main.REFRESH_HEADER not in res.headers


# ─── Password reset ───────────────────────────────────────────────────────────

GENERIC = "Se l'email è registrata riceverai a breve un link per reimpostare la password."


@pytest.fixture
def no_dev_link(monkeypatch):
    monkeypatch.delenv("AUTH_DEV_RESET_LINK", raising=False)


@pytest.mark.usefixtures("no_dev_link")
@pytest.mark.parametrize("delivered", [True, False])
def test_forgot_when_unknown_or_known_email_then_identical_answer(client, monkeypatch, delivered):
    monkeypatch.setattr(main, "send_reset_email", lambda to, url: delivered)
    register(client)
    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    known = client.post("/api/auth/forgot-password", json={"email": "mario@example.com"})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json() == {"status": "ok", "message": GENERIC}


def test_forgot_when_dev_link_enabled_then_reset_link_and_only_hash_saved(client, fake_db, monkeypatch):
    monkeypatch.setenv("AUTH_DEV_RESET_LINK", "true")
    register(client)
    url = client.post("/api/auth/forgot-password", json={"email": "MARIO@example.com"}).json()["reset_url"]
    token = url.split("reset_token=")[1]
    assert fake_db.users["mario"]["reset_token_hash"] == main._hash_reset_token(token)
    assert token not in str(fake_db.users["mario"])  # plaintext token never stored


def test_forgot_when_dev_link_set_on_aws_then_ignored(client, monkeypatch):
    monkeypatch.setenv("AUTH_DEV_RESET_LINK", "true")
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "portfoliolab")
    monkeypatch.setattr(main, "send_reset_email", lambda to, url: True)
    register(client)
    res = client.post("/api/auth/forgot-password", json={"email": "mario@example.com"})
    assert "reset_url" not in res.json()


@pytest.mark.usefixtures("no_dev_link")
def test_forgot_when_email_sent_then_link_goes_only_to_account_mailbox(client, fake_db, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(main, "send_reset_email", lambda to, url: sent.append((to, url)) or True)
    register(client)
    client.post("/api/auth/forgot-password", json={"email": " MARIO@example.com "})
    [(to, url)] = sent
    assert to == "mario@example.com" and url.startswith("http://localhost:8000/login?reset_token=")
    assert fake_db.users["mario"]["reset_token_hash"] == main._hash_reset_token(url.split("=")[1])


def _set_token(fake_db, token="tok", delta=timedelta(hours=1)):
    fake_db.set_reset_token("mario", main._hash_reset_token(token), (datetime.now(UTC) + delta).isoformat())


def test_reset_when_valid_token_then_password_changed_token_burnt_sessions_revoked(client, fake_db):
    register(client)
    old_session = login(client).json()["token"]
    _set_token(fake_db)
    res = client.post("/api/auth/reset-password", json={"token": "tok", "new_password": "brand-new-pass"})
    assert res.status_code == 200
    assert "reset_token_hash" not in fake_db.users["mario"]
    assert client.get("/api/auth/me", headers=bearer(old_session)).status_code == 401
    assert login(client, password="brand-new-pass").status_code == 200
    again = client.post("/api/auth/reset-password", json={"token": "tok", "new_password": "another-pass1"})
    assert again.status_code == 400  # single use


@pytest.mark.parametrize(
    "token,delta,password",
    [
        ("wrong", timedelta(hours=1), "brand-new-pass"),  # unknown token
        ("tok", timedelta(hours=-1), "brand-new-pass"),  # expired
        ("tok", timedelta(hours=1), "short123"),  # under 10 characters
    ],
)
def test_reset_when_invalid_expired_or_short_then_400(client, fake_db, token, delta, password):
    register(client)
    _set_token(fake_db, delta=delta)
    res = client.post("/api/auth/reset-password", json={"token": token, "new_password": password})
    assert res.status_code == 400


# ─── Startup key check ────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["", "short-key", "x" * 31])
def test_load_secret_key_when_missing_or_weak_on_aws_then_refuses_to_start(monkeypatch, key):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "portfoliolab")
    monkeypatch.setenv("SECRET_KEY", key)
    with pytest.raises(main.ConfigurationError):
        main._load_secret_key()


def test_load_secret_key_when_missing_locally_then_random_key(monkeypatch):
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    a, b = main._load_secret_key(), main._load_secret_key()
    assert len(a) >= 32 and a != b
