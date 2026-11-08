"""Custom exceptions for the analysis services."""


class InsufficientDataError(Exception):
    """Raised when there is not enough price history to run an analysis."""


class ConfigurationError(Exception):
    """Raised at startup when a security-critical setting is missing or unsafe."""
