"""Hosted entry point: the API and the built dashboard on one origin, behind the owner login.

    uvicorn orchestrator.hosted.app:app --host 0.0.0.0 --port 8000

Local development keeps using ``orchestrator.main:app`` with the Vite dev
server; nothing here changes it. The login is read first, so a missing secret
stops the process before it serves anything, and the deploy health check fails
instead of the site going live open.
"""

from __future__ import annotations

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from orchestrator.hosted.login import LoginGate, OwnerLogin

API_PREFIXES = ("/api/", "/health", "/docs", "/redoc", "/openapi.json")
DEFAULT_DASHBOARD_DIR = Path(__file__).resolve().parents[3] / "web" / "dist"


class Dispatch:
    """API paths go to FastAPI; everything else is a file from the dashboard bundle."""

    def __init__(self, api, dashboard):
        self.api = api
        self.dashboard = dashboard

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope["path"].startswith(API_PREFIXES):
            return await self.dashboard(scope, receive, send)
        return await self.api(scope, receive, send)


def create_app(login: OwnerLogin | None = None, dashboard_dir: str | Path | None = None):
    login = login or OwnerLogin.from_env()
    from orchestrator.main import app as api

    directory = Path(dashboard_dir or os.environ.get("DASHBOARD_DIR") or DEFAULT_DASHBOARD_DIR)
    # Mounted in an app of its own so a missing file is a 404 response, not an
    # HTTPException escaping to the server as a 500.
    dashboard = Starlette(routes=[Mount("/", StaticFiles(directory=directory, html=True))])
    return LoginGate(Dispatch(api, dashboard), login)


def __getattr__(name: str):
    # Built on first access, so importing this module in tests does not demand the secrets.
    if name == "app":
        return create_app()
    raise AttributeError(name)
