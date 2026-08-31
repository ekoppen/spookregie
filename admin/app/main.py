import asyncio
import os

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from shared.logging_setup import setup_logging
from shared.media_sync import is_content_hash
from admin.app.config import get_settings
from admin.app.auth import SessionStore
from admin.app.db import init_db
from admin.app.mqtt_state import NodeStatusTracker
from admin.app.mqtt_bridge import MqttBridge
from admin.app.mirror_process import MirrorProcessManager
from admin.app.runtime_settings import read_runtime_settings
from admin.app.scheduler import Scheduler
from admin.app.ha_trigger_poller import HaTriggerPoller
from admin.app.websocket_hub import WebSocketHub
from admin.app.routers import auth as auth_router
from admin.app.routers import media as media_router
from admin.app.routers import mirror as mirror_router
from admin.app.routers import players as players_router
from admin.app.routers import scare as scare_router
from admin.app.routers import nodes as nodes_router
from admin.app.routers import schedule as schedule_router
from admin.app.routers import ha as ha_router
from admin.app.routers import ws as ws_router
from admin.app.routers import settings as settings_router
from admin.app.routers import node_config as node_config_router
from admin.app.routers import mirror_process as mirror_process_router
from admin.app.routers import mirror_scare_video as mirror_scare_video_router
from admin.app.routers import triggers as triggers_router
from admin.app.routers import outputs as outputs_router
from admin.app.routers import output_connections as output_connections_router
from admin.app.routers import sources as sources_router
from admin.app.routers import preview as preview_router
from admin.app.routers.mirror_scare_video import read_enabled_hashes
from admin.app.routers.schedule import read_schedule
from admin.app.graph_publish import publish_graph

_PUBLIC_EXACT_PATHS = {"/api/login", "/docs", "/openapi.json", "/api/node-config"}


def _is_public_media_download(path, method):
    """Alleen GET /api/media/<64-char hash> (en zijn /audio-companion)
    zijn publiek. Een simpele startswith("/api/media/") zou ook
    toekomstige beheer-endpoints onder dat pad (bijv. een
    lijst-endpoint) per ongeluk publiek maken."""
    if method != "GET":
        return False
    prefix = "/api/media/"
    if not path.startswith(prefix):
        return False
    remainder = path[len(prefix):]
    if remainder.endswith("/audio"):
        return is_content_hash(remainder[: -len("/audio")])
    return "/" not in remainder and is_content_hash(remainder)


def _get_schedule_from_db(conn):
    def get_schedule():
        s = read_schedule(conn)
        return (s["on_time"], s["off_time"], s["enabled"])
    return get_schedule


def _get_watched_ha_entities_from_db(conn):
    def get_watched():
        trigger_rows = conn.execute(
            "SELECT DISTINCT ha_entity_id FROM triggers WHERE kind = 'ha_sensor' AND ha_entity_id IS NOT NULL"
        ).fetchall()
        repeat_while_rows = conn.execute(
            "SELECT DISTINCT repeat_while_ha_entity_id FROM players "
            "WHERE playback_mode = 'repeat_while' AND repeat_while_ha_entity_id IS NOT NULL"
        ).fetchall()
        return list({r[0] for r in trigger_rows} | {r[0] for r in repeat_while_rows})
    return get_watched


def create_app(settings=None):
    settings = settings or get_settings()
    app = FastAPI()
    app.state.settings = settings
    os.makedirs(settings.log_dir, exist_ok=True)
    app.state.logger = setup_logging("beheerpagina", settings.log_dir)
    app.state.sessions = SessionStore()
    app.state.db = init_db(settings.db_path)
    app.state.runtime_settings = read_runtime_settings(app.state.db)
    app.state.tracker = NodeStatusTracker()
    app.state.ws_hub = WebSocketHub()

    def _republish_retained_config():
        # Zonder dit blijft een net herstarte mirror-node (of een broker-
        # reconnect) zwart: config/mirror/graph en config/mirror/scare-video
        # zijn retained topics die alleen bij een CRUD-actie op de
        # beheerpagina gepubliceerd worden, nooit uit zichzelf.
        publish_graph(app.state.db, app.state.bridge)
        app.state.bridge.publish_mirror_scare_video_config(read_enabled_hashes(app.state.db))

    app.state.bridge = MqttBridge(
        app.state.runtime_settings, app.state.tracker, ws_hub=app.state.ws_hub, logger=app.state.logger,
        on_connect_extra=_republish_retained_config,
    )
    app.state.mirror_process = MirrorProcessManager(
        app.state.runtime_settings,
        ws_hub=app.state.ws_hub,
        log_dir=os.path.join(settings.log_dir, "mirror-node"),
    )
    app.state.scheduler = Scheduler(
        app.state.bridge, _get_schedule_from_db(app.state.db), logger=app.state.logger
    )
    app.state.ha_trigger_poller = HaTriggerPoller(
        app.state.bridge, lambda: app.state.runtime_settings,
        _get_watched_ha_entities_from_db(app.state.db), logger=app.state.logger,
    )

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
    app.include_router(players_router.router)
    app.include_router(triggers_router.router)
    app.include_router(scare_router.router)
    app.include_router(nodes_router.router)
    app.include_router(schedule_router.router)
    app.include_router(ha_router.router)
    app.include_router(ws_router.router)
    app.include_router(settings_router.router)
    app.include_router(node_config_router.router)
    app.include_router(mirror_process_router.router)
    app.include_router(mirror_scare_video_router.router)
    app.include_router(outputs_router.router)
    app.include_router(output_connections_router.router)
    app.include_router(sources_router.router)
    app.include_router(preview_router.router)

    frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if os.path.isdir(frontend_dist):
        assets_dir = os.path.join(frontend_dist, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        # Catch-all i.p.v. StaticFiles(html=True): die laatste serveert
        # index.html alleen op "/" en mapp-paden, waardoor client-side routes
        # zoals /login of /mirror 404'en (breekt refresh, bookmarks en de
        # 401-redirect naar /login). Moet ná alle include_router-calls staan
        # zodat /api/... eerst matcht.
        @app.get("/{full_path:path}")
        def serve_spa(full_path: str):
            return FileResponse(os.path.join(frontend_dist, "index.html"))

    @app.on_event("startup")
    def _startup():
        # De event loop bestaat pas als uvicorn al gestart is, dus de bridge
        # krijgt hem hier pas (niet in create_app) — bekende FastAPI-volgorde,
        # geen ontwerpfout.
        app.state.bridge._loop = asyncio.get_event_loop()
        app.state.mirror_process._loop = asyncio.get_event_loop()
        app.state.bridge.start()
        app.state.scheduler.start()
        app.state.ha_trigger_poller.start()

    @app.on_event("shutdown")
    def _shutdown():
        app.state.ha_trigger_poller.stop()
        app.state.scheduler.stop()
        app.state.bridge.stop()
        app.state.mirror_process.stop()

    return app
