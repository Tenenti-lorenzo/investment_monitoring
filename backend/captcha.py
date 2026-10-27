"""Google reCAPTCHA v3 check for the public auth endpoints (bot protection).

The browser gets an invisible token per action (``login``, ``register``,
``forgot``) and sends it with the request; the server verifies it with
Google's ``siteverify`` API and rejects low scores.

Enabled when ``RECAPTCHA_SECRET`` is set (in AWS it comes from Secrets
Manager). Locally, without it, verification is skipped so dev and tests work
unchanged. On AWS Lambda a missing secret is a misconfiguration and every
check fails (closed), as does a Google outage: bots are never let through.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
_TIMEOUT_S = 5


class SiteVerifyResponse(BaseModel):
    """Google ``siteverify`` reply (only the fields used here)."""

    success: bool
    score: float = 0.0
    action: str = ""
    error_codes: list[str] = Field(default_factory=list, alias="error-codes")


class CaptchaConfig(BaseModel):
    """Public config for the login page: no site key means captcha disabled."""

    recaptcha_site_key: Optional[str] = None


def captcha_enabled() -> bool:
    return bool(os.getenv("RECAPTCHA_SECRET"))


def _on_aws() -> bool:
    return bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def public_config() -> CaptchaConfig:
    site_key = os.getenv("RECAPTCHA_SITE_KEY") or None
    return CaptchaConfig(recaptcha_site_key=site_key if captcha_enabled() else None)


def _min_score() -> float:
    try:
        return float(os.getenv("RECAPTCHA_MIN_SCORE", "0.5"))
    except ValueError:
        return 0.5


def _siteverify(token: str) -> Optional[SiteVerifyResponse]:
    try:
        resp = requests.post(
            _VERIFY_URL,
            data={"secret": os.environ["RECAPTCHA_SECRET"], "response": token},
            timeout=_TIMEOUT_S,
        )
        return SiteVerifyResponse.model_validate(resp.json())
    except (requests.RequestException, ValueError, ValidationError):
        logger.warning("reCAPTCHA siteverify call failed", exc_info=True)
        return None


def verify_captcha(token: str, action: str) -> bool:
    """True if ``token`` proves a human performed ``action`` (or captcha is off).

    Args:
        token: Token produced by ``grecaptcha.execute`` in the browser.
        action: Expected action name; a token minted for another action is rejected.
    """
    if not captcha_enabled():
        if _on_aws():
            logger.error("RECAPTCHA_SECRET missing on AWS: rejecting %s (fail closed)", action)
            return False
        return True
    if not token:
        return False
    result = _siteverify(token)
    if result is None or not result.success:
        return False
    if result.action != action:
        logger.info("reCAPTCHA action mismatch: expected %s got %s", action, result.action)
        return False
    return result.score >= _min_score()


if not captcha_enabled():
    if _on_aws():
        logger.error("RECAPTCHA_SECRET not set: login, sign-up and password reset will be rejected")
    else:
        logger.warning("RECAPTCHA_SECRET not set: bot protection disabled (local development)")
