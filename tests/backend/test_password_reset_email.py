"""backend.password_reset_email: transport selection and failure handling."""

import pytest

from backend import password_reset_email as pre


@pytest.fixture(autouse=True)
def no_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("SES_SENDER", "SMTP_HOST", "AUTH_DEV_RESET_LINK"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(pre, "_send_ses", lambda sender, to, url: calls.append(("ses", sender, to, url)))
    monkeypatch.setattr(pre, "_send_smtp", lambda host, to, url: calls.append(("smtp", host, to, url)))
    return calls


def test_send_when_no_transport_configured_then_false(sent):
    assert pre.send_reset_email("a@b.it", "http://x/login?reset_token=t") is False
    assert sent == []


def test_send_when_ses_and_smtp_configured_then_ses_preferred(sent, monkeypatch):
    monkeypatch.setenv("SES_SENDER", "noreply@portfoliolab.it")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    assert pre.send_reset_email("a@b.it", "u") is True
    assert sent == [("ses", "noreply@portfoliolab.it", "a@b.it", "u")]


def test_send_when_only_smtp_configured_then_smtp(sent, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    assert pre.send_reset_email("a@b.it", "u") is True
    assert sent == [("smtp", "smtp.example.com", "a@b.it", "u")]


def test_send_when_transport_raises_then_false(monkeypatch):
    monkeypatch.setenv("SES_SENDER", "noreply@portfoliolab.it")

    def boom(*args: object) -> None:
        raise RuntimeError("SES down")

    monkeypatch.setattr(pre, "_send_ses", boom)
    assert pre.send_reset_email("a@b.it", "u") is False


@pytest.mark.parametrize("value,expected", [("true", True), ("TRUE", True), ("1", False), ("", False)])
def test_dev_reset_link_enabled_when_flag_set_then_only_literal_true(monkeypatch, value, expected):
    monkeypatch.setenv("AUTH_DEV_RESET_LINK", value)
    assert pre.dev_reset_link_enabled() is expected
