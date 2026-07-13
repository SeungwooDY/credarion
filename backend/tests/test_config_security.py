"""Startup security guard for auth configuration in production."""
from __future__ import annotations

import pytest

from app.config import DEFAULT_AUTH_SECRET, Settings

_DB = "sqlite:///:memory:"


def test_production_rejects_default_secret():
    with pytest.raises(ValueError):
        Settings(
            database_url=_DB,
            app_env="production",
            auth_secret_key=DEFAULT_AUTH_SECRET,
        )


def test_production_forces_secure_cookie():
    s = Settings(
        database_url=_DB,
        app_env="production",
        auth_secret_key="a-strong-unique-production-secret",
        auth_cookie_secure=False,
    )
    assert s.auth_cookie_secure is True


def test_development_allows_default_secret():
    s = Settings(
        database_url=_DB,
        app_env="development",
        auth_secret_key=DEFAULT_AUTH_SECRET,
    )
    # Dev is unaffected: no raise, cookie Secure stays off for http://localhost.
    assert s.auth_cookie_secure is False
