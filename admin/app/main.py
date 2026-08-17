import re

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from admin.app.config import get_settings
from admin.app.auth import SessionStore
from admin.app.db import init_db
from admin.app.mqtt_state import NodeStatusTracker
from admin.app.mqtt_bridge import MqttBridge
from admin.app.scheduler import Scheduler
from admin.app.websocket_hub import WebSocketHub
from admin.app.routers import auth as auth_router
from admin.app.routers import media as media_router
from admin.app.routers import mirror as mirror_router
from admin.app.routers import scare as scare_router
from admin.app.routers import nodes as nodes_router
from admin.app.routers import schedule as schedule_router
from admin.app.routers import ha as ha_router

_PUBLIC_EXACT_PATHS = {"/api/login", "/docs", "/openapi.json"}
# ponytail: same hash-format check as media.py's _HASH_RE, kept local to avoid
# importing a private helper across modules.
_MEDIA_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_public_media_download(path, method):
    """Alleen GET /api/media/<64-char hash> is publiek. Een simpele
    startswith("/api/media/") zou ook toekomstige beheer-endpoints onder
    dat pad (bijv. een lijst-endpoint) per ongeluk publiek maken."""
    if method != "GET":
        return False
    prefix = "/api/media/"
    if not path.startswith(prefix):
        return False
    remainder = path[len(prefix):]
    return "/" not in remainder and bool(_MEDIA_HASH_RE.match(remainder))


def _get_schedule_from_db(conn):
    def get_schedule():
        row = conn.execute(
            "SELECT on_time, off_time, enabled FROM schedule WHERE id = 1"
        ).fetchone()
        if row is None:
            return ("18:00", "22:00", True)
        return (row[0], row[1], bool(row[2]))
    return get_schedule


def create_app(settings=None):
    settings = settings or get_settings()
    app = FastAPI()
    app.state.settings = settings
    app.state.sessions = SessionStore()
    app.state.db = init_db(settings.db_path)
    app.state.tracker = NodeStatusTracker()
    app.state.bridge = MqttBridge(settings, app.state.tracker)
    app.state.ws_hub = WebSocketHub()
    app.state.scheduler = Scheduler(app.state.bridge, _get_schedule_from_db(app.state.db))

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC_EXACT_PATHS or _is_public_media_download(path, request.method):
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)
        token = request.cookies.get("session")
        if not token or not app.state.sessions.is_valid(token):
            return JSONResponse(status_code=401, content={"detail": "niet ingelogd"})
        return await call_next(request)

    app.include_router(auth_router.router)
    app.include_router(media_router.router)
    app.include_router(mirror_router.router)
    app.include_router(scare_router.router)
    app.include_router(nodes_router.router)
    app.include_router(schedule_router.router)
    app.include_router(ha_router.router)

    @app.on_event("startup")
    def _startup():
        app.state.bridge.start()
        app.state.scheduler.start()

    @app.on_event("shutdown")
    def _shutdown():
        app.state.scheduler.stop()
        app.state.bridge.stop()

    return app
