"""Notification endpoints: listing, unread counts, read/read-all, isolation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import Notification

from tests.role_helpers import login_as, make_sqlite_session, seed_tenant

PERIOD = "2026-03"


@pytest.fixture
def db_session():
    session = make_sqlite_session()
    yield session
    session.close()


@pytest.fixture
def tenant(db_session):
    return seed_tenant(db_session)


@pytest.fixture
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _add_notification(db, user, *, type="escalation_created", minutes_ago=0, read=False):
    n = Notification(
        user_id=user.id,
        type=type,
        payload={"actor_name": "Someone", "period": PERIOD},
        period=PERIOD,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        read_at=datetime.now(timezone.utc) if read else None,
    )
    db.add(n)
    db.commit()
    return n


def test_list_newest_first_with_unread_count(client, db_session, tenant):
    user = tenant["accountant"]
    old = _add_notification(db_session, user, minutes_ago=60)
    new = _add_notification(db_session, user, minutes_ago=1)
    mid_read = _add_notification(db_session, user, minutes_ago=30, read=True)

    login_as(user)
    resp = client.get("/api/v1/notifications")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [n["id"] for n in data["items"]] == [str(new.id), str(mid_read.id), str(old.id)]
    assert data["unread_count"] == 2


def test_unread_only_filter(client, db_session, tenant):
    user = tenant["accountant"]
    _add_notification(db_session, user, read=True)
    unread = _add_notification(db_session, user)

    login_as(user)
    data = client.get("/api/v1/notifications?unread_only=true").json()
    assert [n["id"] for n in data["items"]] == [str(unread.id)]


def test_mark_read_and_owner_isolation(client, db_session, tenant):
    mine = _add_notification(db_session, tenant["accountant"])
    theirs = _add_notification(db_session, tenant["admin"])

    login_as(tenant["accountant"])
    assert client.post(f"/api/v1/notifications/{mine.id}/read").status_code == 200
    db_session.refresh(mine)
    assert mine.read_at is not None

    # Someone else's notification → 404; and it stays unread.
    assert client.post(f"/api/v1/notifications/{theirs.id}/read").status_code == 404
    db_session.refresh(theirs)
    assert theirs.read_at is None


def test_read_all(client, db_session, tenant):
    user = tenant["accountant"]
    _add_notification(db_session, user)
    _add_notification(db_session, user)
    _add_notification(db_session, user, read=True)
    other = _add_notification(db_session, tenant["admin"])

    login_as(user)
    resp = client.post("/api/v1/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json() == {"marked": 2}
    assert client.get("/api/v1/notifications").json()["unread_count"] == 0

    # Other users' rows untouched.
    db_session.refresh(other)
    assert other.read_at is None


def test_user_only_sees_own_rows(client, db_session, tenant):
    _add_notification(db_session, tenant["admin"])
    login_as(tenant["accountant"])
    data = client.get("/api/v1/notifications").json()
    assert data["items"] == []
    assert data["unread_count"] == 0
