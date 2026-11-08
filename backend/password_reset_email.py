"""Delivery of the password-reset link.

The link is a bearer credential: whoever has it can take over the account,
so it must only ever reach the mailbox of the account owner. Two transports,
tried in order:

* **Amazon SES** when ``SES_SENDER`` is set (production on AWS; the sender
  identity must be verified in SES and the Lambda role needs ``ses:SendEmail``).
* **SMTP** when ``SMTP_HOST`` is set (any provider, e.g. Gmail app password).

Only for local development, ``AUTH_DEV_RESET_LINK=true`` lets the API return
the link in the HTTP response instead (see ``backend.main``). The flag is
ignored on AWS Lambda, so a stray env var cannot open account takeover.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

import boto3

logger = logging.getLogger(__name__)

SUBJECT = "Reimposta la tua password – PortfolioLab"


def dev_reset_link_enabled() -> bool:
    """True only when the local-dev escape hatch is explicitly switched on (never on AWS)."""
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return False
    return os.getenv("AUTH_DEV_RESET_LINK", "").lower() == "true"


def _body(reset_url: str) -> str:
    return (
        f"Clicca il link per reimpostare la password:\n\n{reset_url}\n\n"
        "Il link scade tra 1 ora. Se non hai richiesto tu il recupero, ignora questa email."
    )


def _send_ses(sender: str, to: str, reset_url: str) -> None:
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "eu-central-1"))
    boto3.client("sesv2", region_name=region).send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [to]},
        Content={
            "Simple": {
                "Subject": {"Data": SUBJECT, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": _body(reset_url), "Charset": "UTF-8"}},
            }
        },
    )


def _send_smtp(host: str, to: str, reset_url: str) -> None:
    msg = MIMEText(_body(reset_url), _charset="utf-8")
    msg["Subject"] = SUBJECT
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER", "noreply@portfoliolab")
    msg["To"] = to
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as s:
        s.starttls()
        s.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASS", ""))
        s.sendmail(msg["From"], [to], msg.as_string())


def send_reset_email(to: str, reset_url: str) -> bool:
    """Email the reset link to ``to``.

    Args:
        to: Address registered on the account.
        reset_url: Single-use link carrying the reset token.

    Returns:
        True if a transport accepted the message, False if none is configured
        or delivery failed (the failure is logged, never surfaced to the caller).
    """
    ses_sender = os.getenv("SES_SENDER")
    smtp_host = os.getenv("SMTP_HOST")
    try:
        if ses_sender:
            _send_ses(ses_sender, to, reset_url)
            return True
        if smtp_host:
            _send_smtp(smtp_host, to, reset_url)
            return True
    except Exception:
        logger.exception("Password-reset email delivery failed")
        return False
    logger.warning("Password reset requested but no email transport is configured (SES_SENDER / SMTP_HOST)")
    return False
