"""Sign-in hardening: limits, revocation on logout, secret strength, health, and demo-seed safety."""

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core import config, rate_limit
from app.demo_seed import is_local_database

PASSWORD = "password123"


def new_client():
    from app.main import app

    return TestClient(app)


def sign_up(client, email):
    response = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response


def test_failed_sign_ins_lock_the_account(db):
    with new_client() as client:
        sign_up(client, "locked@example.com")
        client.post("/api/auth/logout")
        for _ in range(5):
            wrong = client.post(
                "/api/auth/login", json={"email": "locked@example.com", "password": "wrong-pass"}
            )
            assert wrong.status_code == 401
        locked = client.post("/api/auth/login", json={"email": "locked@example.com", "password": PASSWORD})
        assert locked.status_code == 429
        assert "Too many sign-in attempts" in locked.json()["error"]


def test_successful_sign_in_clears_the_failure_count(db):
    with new_client() as client:
        sign_up(client, "clears@example.com")
        client.post("/api/auth/logout")
        for _ in range(4):
            client.post("/api/auth/login", json={"email": "clears@example.com", "password": "wrong-pass"})
        assert (
            client.post(
                "/api/auth/login", json={"email": "clears@example.com", "password": PASSWORD}
            ).status_code
            == 200
        )
        client.post("/api/auth/logout")
        for _ in range(4):
            failed = client.post(
                "/api/auth/login", json={"email": "clears@example.com", "password": "wrong-pass"}
            )
            assert failed.status_code == 401


def test_sign_ups_are_limited_per_client(db):
    with new_client() as client:
        for index in range(rate_limit.SIGN_UPS_PER_CLIENT.limit):
            sign_up(client, f"batch{index}@example.com")
        blocked = client.post(
            "/api/auth/signup", json={"email": "one-more@example.com", "password": PASSWORD}
        )
        assert blocked.status_code == 429
        assert "sign-up attempts" in blocked.json()["error"]


def test_taken_email_gets_the_same_generic_message_as_other_failures(db):
    with new_client() as client:
        sign_up(client, "taken@example.com")
        client.post("/api/auth/logout")
        response = client.post("/api/auth/signup", json={"email": "taken@example.com", "password": PASSWORD})
        assert response.status_code == 400
        assert response.json()["error"] == (
            "Could not create the account. If you already have one, sign in instead."
        )
        assert "registered" not in response.text


def test_logout_revokes_the_token_everywhere(db):
    with new_client() as client:
        sign_up(client, "revoke@example.com")
        old_token = client.cookies.get("access_token")
        assert client.get("/api/me").status_code == 200
        assert client.post("/api/auth/logout").status_code == 200
        client.cookies.set("access_token", old_token)  # a copy of the cookie taken before logout
        assert client.get("/api/me").status_code == 401

        client.cookies.clear()
        assert (
            client.post(
                "/api/auth/login", json={"email": "revoke@example.com", "password": PASSWORD}
            ).status_code
            == 200
        )
        assert client.get("/api/me").status_code == 200


def test_logout_with_an_invalid_cookie_still_succeeds(db):
    with new_client() as client:
        client.cookies.set("access_token", "not-a-token")
        assert client.post("/api/auth/logout").json() == {"success": True}


def test_tokens_without_a_version_are_rejected(db):
    with new_client() as client:
        sign_up(client, "legacy@example.com")
        user_id = int(
            jwt.decode(client.cookies.get("access_token"), options={"verify_signature": False})["sub"]
        )
        legacy = jwt.encode(
            {"sub": str(user_id), "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            config.JWT_SECRET_KEY,
            algorithm=config.JWT_ALGORITHM,
        )
        client.cookies.set("access_token", legacy)
        assert client.get("/api/me").status_code == 401


def test_generated_secret_is_allowed_only_outside_https():
    config.check_jwt_secret("x" * 10, generated=True, cookie_secure=False)
    with pytest.raises(RuntimeError, match="HTTPS"):
        config.check_jwt_secret("x" * 60, generated=True, cookie_secure=True)


@pytest.mark.parametrize(
    "secret",
    ["short-secret", "replace_with_a_long_random_secret_value_here", ""],
)
def test_explicit_secret_must_be_private_and_long(secret):
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        config.check_jwt_secret(secret, generated=False, cookie_secure=False)


def test_strong_explicit_secret_is_accepted():
    config.check_jwt_secret("k7Qz0vN2pLr9sT4wX8yB1cD6fG3hJ5mA", generated=False, cookie_secure=True)


def test_health_reports_a_database_outage(db, monkeypatch):
    from app import main

    class Unreachable:
        def connect(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(main, "engine", Unreachable())
    response = TestClient(main.app).get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_health_reports_ok_with_a_database(db):
    from app.main import app

    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_client_address_uses_the_proxy_appended_hop(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"1.2.3.4, 198.51.100.7")],
            "client": ("10.0.0.2", 1),
        }
    )
    assert rate_limit.client_address(request) == "198.51.100.7"


def test_client_address_ignores_forwarded_headers_without_a_proxy(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", False)
    request = Request(
        {"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4")], "client": ("10.0.0.2", 1)}
    )
    assert rate_limit.client_address(request) == "10.0.0.2"


def test_sliding_window_frees_capacity_after_the_window():
    window = rate_limit.SlidingWindow(limit=2, window_seconds=0.05)
    window.record("key")
    window.record("key")
    assert window.blocked("key")
    time.sleep(0.08)
    assert not window.blocked("key")


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("postgresql+psycopg://u:p@127.0.0.1:5432/app", True),
        ("postgresql+psycopg://u:p@localhost/app", True),
        ("postgresql+psycopg://postgres:@/app?host=/Users/me/.pgdata/cluster", True),
        ("postgresql+psycopg://u:p@ep-cool-123.us-east-2.aws.neon.tech/app?sslmode=require", False),
        ("postgresql+psycopg://u:p@db.example.com:5432/app", False),
    ],
)
def test_demo_seed_recognises_local_databases(url, local):
    assert is_local_database(url) is local
