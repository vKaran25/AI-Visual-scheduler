"""Integration tests use a dedicated PostgreSQL database, never the developer database."""

import os

import pytest

TEST_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://scheduler@127.0.0.1:54329/scheduler_test")
os.environ["DATABASE_URL"] = TEST_URL
os.environ["DATABASE_DIRECT_URL"] = TEST_URL
os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-at-least-thirty-two-bytes"
os.environ["COOKIE_SECURE"] = "false"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["GOOGLE_TOKEN_ENCRYPTION_KEY"] = "Z2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2dnZ2c="


@pytest.fixture(scope="session")
def postgres():
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from app.db.session import engine

    url = make_url(TEST_URL)
    if not (url.database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name a dedicated database ending in _test")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Configure TEST_DATABASE_URL for PostgreSQL integration tests")
    from app.db.migrate import main

    main()
    yield engine


@pytest.fixture
def db(postgres):
    from sqlalchemy import text
    from sqlmodel import Session

    with postgres.begin() as conn:
        conn.execute(text('TRUNCATE TABLE "user" RESTART IDENTITY CASCADE'))
    with Session(postgres, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def user(db):
    from app.db.models import User

    row = User(
        email="calendar@example.com", password_hash="not-used", timezone="UTC", timezone_confirmed=True
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/signup", json={"email": "browser@example.com", "password": "password123"}
        )
        assert response.status_code == 200, response.text
        assert client.put("/api/me/timezone", json={"timezone": "UTC"}).status_code == 200
        yield client


@pytest.fixture
def graph(postgres):
    from app.agents.graph import build_graph
    from app.runtime.checkpoints import checkpoint_store

    with checkpoint_store() as saver:
        yield build_graph(saver)
