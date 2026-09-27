"""The suite must never hit the network by accident."""

import pytest
import requests
import yfinance


def test_guard_when_http_attempted_in_unit_test_then_raises():
    with pytest.raises(RuntimeError, match="Network access is disabled"):
        requests.get("https://example.com", timeout=1)


def test_guard_when_yahoo_attempted_in_unit_test_then_raises():
    with pytest.raises(RuntimeError, match="Network access is disabled"):
        yfinance.Ticker("AAPL")
