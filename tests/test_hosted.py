"""
Hosted entry point: the owner login in front of the API and the dashboard bundle.

No secrets come from the environment: each test builds its own login from a
hash computed here, and a temporary directory stands in for ``web/dist``.
"""

import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.hosted.app import create_app
from orchestrator.hosted.login import COOKIE_NAME, LoginConfigError, OwnerLogin, verify_werkzeug_hash

EMAIL = "owner@example.com"
PASSWORD = "correct horse battery staple"


def _scrypt_hash(password: str, salt: str = "s4lt", n: int = 16384, r: int = 8, p: int = 1) -> str:
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=n, r=r, p=p, maxmem=132 * n * r * p).hex()
    return f"scrypt:{n}:{r}:{p}${salt}${digest}"


@pytest.fixture
async def hosted(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>dashboard</title>", encoding="utf-8")
    app = create_app(OwnerLogin(EMAIL, _scrypt_hash(PASSWORD)), dashboard_dir=tmp_path)
    transport = ASGITransport(app=app, client=("203.0.113.7", 1234))
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac


async def _sign_in(client, email=EMAIL, password=PASSWORD, next_="/"):
    return await client.post("/login", data={"email": email, "password": password, "next": next_})


def test_werkzeug_hashes_verify():
    werkzeug = pytest.importorskip("werkzeug.security")
    for method in ("scrypt", "pbkdf2:sha256"):
        stored = werkzeug.generate_password_hash(PASSWORD, method=method)
        assert verify_werkzeug_hash(stored, PASSWORD)
        assert not verify_werkzeug_hash(stored, PASSWORD + "x")


def test_malformed_hash_is_rejected_not_raised():
    assert not verify_werkzeug_hash("scrypt:nonsense", PASSWORD)
    assert not verify_werkzeug_hash("md5$a$b", PASSWORD)


def test_missing_secrets_refuse_to_start(monkeypatch):
    monkeypatch.delenv("SITE_LOGIN_EMAIL", raising=False)
    monkeypatch.delenv("SITE_LOGIN_PASSWORD_HASH", raising=False)
    with pytest.raises(LoginConfigError):
        OwnerLogin.from_env()
    monkeypatch.setenv("SITE_LOGIN_EMAIL", EMAIL)
    monkeypatch.setenv("SITE_LOGIN_PASSWORD_HASH", "plaintext")
    with pytest.raises(LoginConfigError):
        OwnerLogin.from_env()


async def test_health_is_open_everything_else_is_gated(hosted):
    assert (await hosted.get("/health/")).status_code == 200

    page = await hosted.get("/")
    assert page.status_code == 303
    assert page.headers["location"].startswith("/login")

    api = await hosted.get("/api/v1/catalog/overview")
    assert api.status_code == 401

    docs = await hosted.get("/docs")
    assert docs.status_code == 303


async def test_sign_in_unlocks_api_and_dashboard(hosted):
    response = await _sign_in(hosted, next_="/api/v1/catalog/overview")
    assert response.status_code == 303
    assert response.headers["location"] == "/api/v1/catalog/overview"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" not in cookie and "SameSite=Lax" in cookie

    assert (await hosted.get("/api/v1/catalog/overview")).status_code == 200
    page = await hosted.get("/")
    assert page.status_code == 200 and "dashboard" in page.text
    assert (await hosted.get("/assets/missing.js")).status_code == 404

    await hosted.get("/logout")
    hosted.cookies.clear()
    assert (await hosted.get("/api/v1/catalog/overview")).status_code == 401


async def test_secure_cookie_behind_https_proxy(hosted):
    response = await hosted.post(
        "/login",
        data={"email": EMAIL, "password": PASSWORD},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert "Secure" in response.headers["set-cookie"]


async def test_forged_cookie_is_refused(hosted):
    hosted.cookies.set(COOKIE_NAME, "9999999999.deadbeef")
    assert (await hosted.get("/api/v1/catalog/overview")).status_code == 401


async def test_open_redirect_is_neutralised(hosted):
    response = await _sign_in(hosted, next_="//evil.example/")
    assert response.headers["location"] == "/"


async def test_five_wrong_tries_lock_the_form(hosted):
    for _ in range(5):
        assert (await _sign_in(hosted, password="wrong")).status_code == 401
    locked = await _sign_in(hosted)
    assert locked.status_code == 401
    assert "Too many wrong tries" in locked.text
