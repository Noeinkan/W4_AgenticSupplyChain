"""Owner login for the hosted deployment: one email, one password hash, a signed cookie.

There is a single user, so there is no user table: the email and a Werkzeug
password hash come from the environment (``SITE_LOGIN_EMAIL``,
``SITE_LOGIN_PASSWORD_HASH``), set in the server's ``.env``. The plain password
never reaches the server. Verification uses only the standard library, so the
image needs nothing beyond ``requirements.txt``.

The cookie is signed with a key derived from the hash, so changing the password
signs every browser out. Five wrong tries from one IP lock the form for fifteen
minutes. The gate is a pure ASGI middleware so the SSE run stream passes
through it unbuffered.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote

COOKIE_NAME = "sc_owner"
SESSION_SECONDS = 14 * 24 * 3600
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
EXEMPT_PATHS = ("/health", "/health/", "/robots.txt")


class LoginConfigError(RuntimeError):
    """The login cannot work, so the site must not start."""


def verify_werkzeug_hash(stored: str, password: str) -> bool:
    """Check ``password`` against a Werkzeug ``scrypt:`` or ``pbkdf2:`` hash."""
    try:
        method, salt, expected = stored.split("$", 2)
        kind, *params = method.split(":")
        secret = password.encode()
        if kind == "scrypt":
            n, r, p = (int(x) for x in params)
            actual = hashlib.scrypt(
                secret, salt=salt.encode(), n=n, r=r, p=p, maxmem=132 * n * r * p
            ).hex()
        elif kind == "pbkdf2":
            digest, iterations = params[0], int(params[1])
            actual = hashlib.pbkdf2_hmac(digest, secret, salt.encode(), iterations).hex()
        else:
            return False
    except (ValueError, IndexError):
        return False
    return hmac.compare_digest(actual, expected)


@dataclass
class OwnerLogin:
    email: str
    password_hash: str
    _failures: dict[str, list[float]] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_env(cls) -> "OwnerLogin":
        email = os.environ.get("SITE_LOGIN_EMAIL", "").strip().lower()
        password_hash = os.environ.get("SITE_LOGIN_PASSWORD_HASH", "").strip().strip("'\"")
        missing = [
            name
            for name, value in (("SITE_LOGIN_EMAIL", email), ("SITE_LOGIN_PASSWORD_HASH", password_hash))
            if not value
        ]
        if missing:
            raise LoginConfigError(f"refusing to serve the dashboard without a login: {', '.join(missing)} unset")
        if not password_hash.startswith(("scrypt:", "pbkdf2:")):
            raise LoginConfigError("SITE_LOGIN_PASSWORD_HASH is not a Werkzeug hash (scrypt:... or pbkdf2:...)")
        return cls(email=email, password_hash=password_hash)

    # ------------------------------------------------------------ cookie --
    def _key(self) -> bytes:
        return hashlib.sha256(b"sc-owner-cookie\0" + self.password_hash.encode()).digest()

    def issue_token(self, now: float | None = None) -> str:
        expires = int((now or time.time()) + SESSION_SECONDS)
        payload = f"{expires}"
        sig = hmac.new(self._key(), f"{self.email}|{payload}".encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{sig}"

    def token_valid(self, token: str, now: float | None = None) -> bool:
        try:
            payload, sig = token.split(".", 1)
            expires = int(payload)
        except ValueError:
            return False
        if expires < (now or time.time()):
            return False
        expected = hmac.new(self._key(), f"{self.email}|{payload}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)

    # ----------------------------------------------------------- lockout --
    def _recent_failures(self, ip: str, now: float) -> list[float]:
        recent = [t for t in self._failures.get(ip, []) if now - t < LOCK_SECONDS]
        if recent:
            self._failures[ip] = recent
        else:
            self._failures.pop(ip, None)
        return recent

    def locked(self, ip: str) -> bool:
        with self._lock:
            return len(self._recent_failures(ip, time.monotonic())) >= MAX_FAILURES

    def check(self, ip: str, email: str, password: str) -> bool:
        with self._lock:
            now = time.monotonic()
            if len(self._recent_failures(ip, now)) >= MAX_FAILURES:
                return False
            ok = hmac.compare_digest(email.strip().lower(), self.email) and verify_werkzeug_hash(
                self.password_hash, password
            )
            if ok:
                self._failures.pop(ip, None)
            else:
                self._failures.setdefault(ip, []).append(now)
            return ok


class LoginGate:
    """ASGI middleware: every path except the health check needs the owner cookie."""

    def __init__(self, app, login: OwnerLogin):
        self.app = app
        self.login = login

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if path == "/login":
            return await self._login(scope, receive, send, headers)
        if path == "/logout":
            return await _respond(send, 303, b"", [("location", "/login"), ("set-cookie", _clear_cookie())])
        if path in EXEMPT_PATHS or self._signed_in(headers):
            return await self.app(scope, receive, send)
        if scope["method"] == "GET" and not path.startswith("/api/"):
            target = path + ("?" + scope["query_string"].decode("latin-1") if scope["query_string"] else "")
            return await _respond(send, 303, b"", [("location", "/login?next=" + quote(_safe_next(target), safe="/"))])
        return await _respond(send, 401, b'{"detail":"signed out"}', [("content-type", "application/json")])

    def _signed_in(self, headers: dict[str, str]) -> bool:
        for part in headers.get("cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME and self.login.token_valid(value):
                return True
        return False

    async def _login(self, scope, receive, send, headers):
        ip = headers.get("x-real-ip") or (scope.get("client") or ("?",))[0]
        if scope["method"] == "GET":
            query = parse_qs(scope["query_string"].decode("latin-1"))
            target = _safe_next(query.get("next", ["/"])[0])
            return await _page(send, 200, target, locked=self.login.locked(ip))
        if scope["method"] != "POST":
            return await _respond(send, 405, b"", [("allow", "GET, POST")])

        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if len(body) > 16_384:
                return await _respond(send, 413, b"", [])
            if not message.get("more_body"):
                break
        form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}
        target = _safe_next(form.get("next", "/"))
        if self.login.check(ip, form.get("email", ""), form.get("password", "")):
            secure = headers.get("x-forwarded-proto") == "https"
            cookie = (
                f"{COOKIE_NAME}={self.login.issue_token()}; Max-Age={SESSION_SECONDS}; Path=/; "
                f"HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
            )
            return await _respond(send, 303, b"", [("location", target), ("set-cookie", cookie)])
        return await _page(send, 401, target, error=True, locked=self.login.locked(ip))


def _safe_next(target: str) -> str:
    # Only same-site paths: "//evil.com" and "/\evil.com" are other hosts to a browser.
    if not target.startswith("/") or target.startswith(("//", "/\\")) or target.startswith("/login"):
        return "/"
    return target


def _clear_cookie() -> str:
    return f"{COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"


async def _respond(send, status: int, body: bytes, headers: list[tuple[str, str]]):
    raw = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers]
    raw += [(b"cache-control", b"no-store"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": body})


async def _page(send, status: int, target: str, error: bool = False, locked: bool = False):
    if locked:
        message = '<p class="err">Too many wrong tries. Wait 15 minutes and try again.</p>'
    elif error:
        message = '<p class="err">Wrong email or password.</p>'
    else:
        message = ""
    body = _LOGIN_HTML.replace("{{message}}", message).replace("{{next}}", html.escape(target, quote=True))
    await _respond(send, status, body.encode(), [("content-type", "text/html; charset=utf-8")])


_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Supply-Chain Orchestrator — sign in</title>
<style>
  :root { color-scheme: light dark; --bg: #f6f7f9; --card: #fff; --line: #d9dde3; --ink: #1b1f24;
          --muted: #5c6670; --accent: #2a6fdb; --err: #c0392b; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #0d1014; --card: #151a20; --line: #2a3038; --ink: #e6e8eb; --muted: #9aa4ae;
            --accent: #5b9bff; --err: #ff6b6b; }
  }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
         background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, sans-serif; }
  form { width: min(340px, calc(100vw - 32px)); padding: 28px; border: 1px solid var(--line);
         border-radius: 8px; background: var(--card); }
  h1 { margin: 0 0 4px; font-size: 18px; }
  p.sub { margin: 0 0 20px; color: var(--muted); font-size: 13px; }
  label { display: block; margin: 12px 0 4px; font-size: 13px; color: var(--muted); }
  input { box-sizing: border-box; width: 100%; padding: 9px 10px; border: 1px solid var(--line);
          border-radius: 4px; background: var(--bg); color: inherit; font: inherit; }
  button { margin-top: 20px; width: 100%; padding: 10px; border: 0; border-radius: 4px;
           background: var(--accent); color: #fff; font: 600 15px system-ui, sans-serif; cursor: pointer; }
  .err { margin: 12px 0 0; color: var(--err); font-size: 13px; }
</style></head>
<body><form method="post" action="/login">
  <h1>Supply-Chain Resilience Orchestrator</h1>
  <p class="sub">Owner sign-in</p>
  <input type="hidden" name="next" value="{{next}}">
  <label for="email">Email</label>
  <input id="email" name="email" type="email" autocomplete="username" required autofocus>
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password" required>
  {{message}}
  <button type="submit">Sign in</button>
</form></body></html>
"""
