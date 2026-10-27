"""backend.captcha and its enforcement on /api/auth/*."""

import pytest

from backend import captcha
from backend.captcha import SiteVerifyResponse


@pytest.fixture
def captcha_on(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Enable captcha; Google answers per token: 'human-<action>' ok, 'bot' low score."""
    monkeypatch.setenv("RECAPTCHA_SECRET", "test-secret")
    monkeypatch.setenv("RECAPTCHA_SITE_KEY", "site-key")
    seen: list[str] = []

    def siteverify(token: str) -> SiteVerifyResponse | None:
        seen.append(token)
        if token == "outage":
            return None
        if token == "bot":
            return SiteVerifyResponse(success=True, score=0.1, action="register")
        if token == "expired":
            return SiteVerifyResponse.model_validate({"success": False, "error-codes": ["timeout-or-duplicate"]})
        return SiteVerifyResponse(success=True, score=0.9, action=token.removeprefix("human-"))

    monkeypatch.setattr(captcha, "_siteverify", siteverify)
    return seen


def test_verify_when_secret_missing_then_disabled_and_passes(monkeypatch):
    monkeypatch.delenv("RECAPTCHA_SECRET", raising=False)
    assert captcha.verify_captcha("", "login") is True
    assert captcha.public_config().recaptcha_site_key is None


@pytest.mark.parametrize(
    "token,expected",
    [
        ("human-login", True),
        ("", False),  # no token
        ("bot", False),  # score below threshold
        ("human-register", False),  # token minted for another action
        ("expired", False),
        ("outage", False),  # fail closed
    ],
)
def test_verify_when_enabled_then_only_human_token_for_same_action_passes(captcha_on, token, expected):
    assert captcha.verify_captcha(token, "login") is expected


def test_verify_when_empty_token_then_google_not_called(captcha_on):
    captcha.verify_captcha("", "login")
    assert captcha_on == []


def test_api_config_when_enabled_then_exposes_only_site_key(client, captcha_on):
    res = client.get("/api/auth/config")
    assert res.json() == {"recaptcha_site_key": "site-key"}
    assert "test-secret" not in res.text


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/auth/register", {"username": "mario", "email": "m@example.com", "password": "secret1"}),
        ("/api/auth/login", {"username": "mario", "password": "secret1"}),
        ("/api/auth/forgot-password", {"email": "m@example.com"}),
    ],
)
def test_auth_when_captcha_missing_or_bot_then_403(client, fake_db, captcha_on, path, body):
    assert client.post(path, json=body).status_code == 403
    assert client.post(path, json={**body, "captcha_token": "bot"}).status_code == 403
    assert not fake_db.users


def test_register_when_human_token_then_account_created(client, fake_db, captcha_on):
    body = {"username": "mario", "email": "m@example.com", "password": "secret1", "captcha_token": "human-register"}
    assert client.post("/api/auth/register", json=body).status_code == 200
    assert "mario" in fake_db.users
