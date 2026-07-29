from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_DB = Path(tempfile.gettempdir()) / f"helpdesk_portfolio_tests_{os.getpid()}.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ["APP_ENV"] = "testing"
os.environ["FLASK_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-ci-only"
os.environ["CREDENTIAL_ENCRYPTION_KEY"] = "test-encryption-key-for-ci"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["ENABLE_DEMO_AUTH"] = "true"
os.environ["DEMO_ADMIN_USERNAME"] = "demo_admin"
os.environ["DEMO_ADMIN_PASSWORD"] = "change-me-local"
os.environ["DEMO_USER_USERNAME"] = "demo_user"
os.environ["DEMO_USER_PASSWORD"] = "change-me-local"
os.environ["SOCKETIO_ASYNC_MODE"] = "threading"

from app import app, db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database_file():
    TEST_DB.unlink(missing_ok=True)
    yield
    TEST_DB.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def clean_database():
    with app.app_context():
        db.drop_all()
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


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
