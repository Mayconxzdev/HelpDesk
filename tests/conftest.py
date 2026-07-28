from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_DB = Path(tempfile.gettempdir()) / "helpdesk_portfolio_tests.db"
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-that-is-long-enough-for-ci-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "test-encryption-key-for-ci")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("ENABLE_DEMO_AUTH", "true")
os.environ.setdefault("DEMO_ADMIN_USERNAME", "demo_admin")
os.environ.setdefault("DEMO_ADMIN_PASSWORD", "change-me-local")
os.environ.setdefault("DEMO_USER_USERNAME", "demo_user")
os.environ.setdefault("DEMO_USER_PASSWORD", "change-me-local")
os.environ.setdefault("SOCKETIO_ASYNC_MODE", "threading")

from app import app, db  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    with app.app_context():
        db.drop_all()
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture()
def authenticated_client(client):
    response = client.post(
        "/login",
        json={"username": "demo_admin", "password": "change-me-local"},
    )
    assert response.status_code == 200
    return client


@pytest.fixture()
def regular_user_client(client):
    response = client.post(
        "/login",
        json={"username": "demo_user", "password": "change-me-local"},
    )
    assert response.status_code == 200
    return client
