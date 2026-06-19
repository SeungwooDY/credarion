"""Shared pytest fixtures.

Authentication is enforced on every data router at the app level. The existing
test suite exercises those routers directly with its own in-memory SQLite DB,
so we install an autouse override that authenticates each request as a
superuser principal. Superusers bypass per-org scoping, which keeps the
pre-auth tests behaving exactly as before. Dedicated auth behavior is covered
in test_auth.py, which clears this override where it needs the real dependency.
"""
from __future__ import annotations

import uuid

import pytest

from app.auth_deps import get_current_user
from app.main import app
from app.models import Account, User


def make_superuser() -> User:
    """A detached superuser User suitable for dependency overrides."""
    account = Account(
        id=uuid.uuid4(), name="Test Account", plan="enterprise", subscription_status="active"
    )
    user = User(
        id=uuid.uuid4(),
        account_id=account.id,
        email="test-superuser@credarion.test",
        hashed_password="x",
        full_name="Test Superuser",
        is_active=True,
        is_superuser=True,
    )
    user.account = account
    return user


@pytest.fixture(autouse=True)
def authenticate_as_superuser():
    """Authenticate every request as a superuser unless a test overrides it."""
    app.dependency_overrides[get_current_user] = make_superuser
    yield
    app.dependency_overrides.pop(get_current_user, None)
