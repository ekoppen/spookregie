# Beheerpagina — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bouw de FastAPI-backend die de beheerpagina straks bedient: media-opslag (content-addressed, hergebruikt door mirror/scare-node uit plan 1), MQTT-brug (config publiceren, status/logs lezen), HA-proxy (WLED), een tijdvenster-scheduler, en wachtwoord-auth. Dit is plan 2 van 3 — plan 3 (frontend) volgt zodra deze API's in werkende code vastliggen.

**Architecture:** Eén FastAPI-app (`admin/app/`) met een laag pure/testbare modules (config, auth, media-opslag, MQTT-state-tracking, HA-client, scheduler-logica, websocket-hub) en een dunne laag routers die ze aan HTTP/WebSocket-endpoints koppelt. SQLite (stdlib `sqlite3`) voor persistente config/media-metadata; node-status/logs zijn alleen in-memory (live, niet opgeslagen). Volgt exact het contract dat plan 1 al in werkende code heeft vastgelegd — zie hieronder.

**Tech Stack:** Python 3, FastAPI + Uvicorn + python-multipart (nieuw voor dit project — dit is een nieuwe webservice, geen uitbreiding van de bestaande nodes), `paho-mqtt` (al een dependency), stdlib `sqlite3`/`hashlib`/`secrets`/`urllib` voor de rest — geen ORM, geen aparte databaseserver, geen wachtwoord-hashing-library (constant-time vergelijking van één gedeeld wachtwoord uit een env var volstaat).

**Spec:** `docs/superpowers/specs/2026-08-16-beheerpagina-design.md`

**Bevestigd contract uit plan 1 (werkende code, niet opnieuw verzinnen):**

- `shared/mqtt_contract.py` topics: `config/mirror`, `control/mirror/preview`, `control/mirror/test-trigger`, `config/scare/{zone}`, `control/scare/{zone}/test-trigger`, `system/sleep` (payload `"on"`/`"off"`, retained), `status/{node}` (retained, MQTT last-will, payload `"online"`/`"offline"`), `log/{node}`, `mirror/triggered`, `scare/{zone}/triggered`.
- `config/mirror` en `control/mirror/preview` payload (JSON): `{"effect": str, "params": dict, "overlay_hash": str|None, "scale": float, "position": [x, y]}`.
- `config/scare/{zone}` payload (JSON): `{"enabled_hashes": [str, ...]}` — **geen** `enabled_filenames` (die is in plan 1 bewust uit het contract verwijderd).
- `log/{node}` payload (JSON, van `shared/logging_setup.py`): `{"ts": float, "level": str, "msg": str}`.
- Media-endpoint dat de nodes al aanroepen: `GET {BACKEND_URL}/api/media/<hash>` — moet ruwe bytes teruggeven die exact hashen tot `<hash>` (sha256 hex), max 50MB, **zonder auth** (nodes hebben geen login-flow). Nodes valideren dit zelf al (`shared/media_sync.py`) — de backend hoeft alleen correct te serveren.
- Node-omgevingsvariabelen die al bestaan en waar deze backend zich naar moet gedragen: `BACKEND_URL` (nodes lezen dit), `MQTT_HOST`/`MQTT_PORT`/`MQTT_USER`/`MQTT_PASS` (dezelfde broker als de nodes).

## Global Constraints

- Nieuwe pip-dependencies zijn hier toegestaan (in tegenstelling tot plan 1) — dit is een nieuwe, losstaande service. Wel: geen dependency toevoegen voor iets dat een paar regels stdlib ook doet (ORM, wachtwoord-hashing-library, aparte scheduler-library — allemaal met stdlib te doen op deze schaal).
- `GET /api/media/<hash>` blijft het enige endpoint zonder auth-check — alle andere routes vereisen een geldige sessie.
- Wachtwoord/sessie-auth: één gedeeld wachtwoord uit een env var, vergeleken met `secrets.compare_digest`; sessies zijn willekeurige tokens in een in-memory set (geen database-persistentie nodig — een herstart van de backend logt iedereen uit, dat is acceptabel voor dit hobbyproject).
- Tijdvenster-scheduler vervangt de oude HA-automation uit plan 0 volledig (die YAML is al verwijderd) — deze backend is nu de enige plek die `system/sleep` op basis van een schema publiceert.
- Pure logica (auth-vergelijking, media-hashing/opslag-paden, MQTT-state-tracking, scheduler-tijdvergelijking, HA-request-opbouw, websocket-hub) krijgt volledige pytest-dekking met FastAPI's `TestClient` en injecteerbare fakes — geen echte MQTT-broker, HA-instantie of netwerkcalls nodig in de tests.

---

## File Structure

```
admin/
├── app/
│   ├── __init__.py
│   ├── config.py            # Settings uit env vars
│   ├── auth.py                # wachtwoord-check + sessie-tokens
│   ├── db.py                    # SQLite schema + connectie
│   ├── media.py                   # content-addressed opslag (hergebruikt shared.media_sync.content_hash)
│   ├── mqtt_state.py                # NodeStatusTracker: pure state-logica uit inkomende MQTT-berichten
│   ├── mqtt_bridge.py                 # MqttBridge: paho-wrapper (connect/subscribe/publish), glue
│   ├── ha_client.py                     # HA REST-wrapper
│   ├── scheduler.py                       # tijdvenster: pure tijd-logica + achtergrondlus
│   ├── websocket_hub.py                     # broadcaster voor live status/logs naar browsers
│   ├── main.py                                # FastAPI-app, startup/shutdown, auth-dependency
│   └── routers/
│       ├── __init__.py
│       ├── auth.py                              # POST /api/login, /api/logout
│       ├── media.py                               # media CRUD + het door nodes gebruikte download-endpoint
│       ├── mirror.py                                # mirror-config/preview/test
│       ├── scare.py                                   # scare-config/test per zone
│       ├── nodes.py                                     # node-statuslijst
│       ├── schedule.py                                    # tijdvenster instellen
│       ├── ha.py                                            # WLED-proxy
│       └── ws.py                                              # WebSocket voor live status/logs
├── requirements.txt
└── run.py                                                       # entrypoint (uvicorn.run(...))
tests/
├── test_admin_config.py
├── test_admin_auth.py
├── test_admin_db.py
├── test_admin_media.py
├── test_admin_mqtt_state.py
├── test_admin_ha_client.py
├── test_admin_scheduler.py
├── test_admin_websocket_hub.py
├── test_admin_routes_auth.py
├── test_admin_routes_media.py
├── test_admin_routes_mirror_scare.py
└── test_admin_routes_nodes_schedule_ha.py
```

---

### Task 1: Config + auth

**Files:**
- Create: `admin/app/__init__.py`
- Create: `admin/app/config.py`
- Create: `admin/app/auth.py`
- Test: `tests/test_admin_config.py`
- Test: `tests/test_admin_auth.py`

**Interfaces:**
- Produces:
  - `admin.app.config.Settings` — dataclass/namespace met `admin_password: str`, `mqtt_host: str`, `mqtt_port: int`, `mqtt_user: str`, `mqtt_pass: str`, `ha_url: str`, `ha_token: str`, `db_path: str`, `media_dir: str`, `port: int`
  - `admin.app.config.get_settings() -> Settings` (leest env vars, met defaults)
  - `admin.app.auth.check_password(password: str, expected: str) -> bool`
  - `admin.app.auth.SessionStore` met `.create() -> str`, `.is_valid(token: str) -> bool`, `.revoke(token: str)`

- [ ] **Step 1: Maak de package-structuur**

```bash
mkdir -p admin/app/routers
touch admin/app/__init__.py admin/app/routers/__init__.py
```

- [ ] **Step 2: Schrijf de falende tests**

`tests/test_admin_config.py`:
```python
import os
from admin.app.config import get_settings


def test_get_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "geheim123")
    monkeypatch.setenv("MQTT_HOST", "test-broker")
    monkeypatch.setenv("MQTT_PORT", "1884")

    settings = get_settings()

    assert settings.admin_password == "geheim123"
    assert settings.mqtt_host == "test-broker"
    assert settings.mqtt_port == 1884


def test_get_settings_has_sane_defaults(monkeypatch):
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("MQTT_PORT", raising=False)

    settings = get_settings()

    assert settings.mqtt_host == "homeassistant.local"
    assert settings.mqtt_port == 1883
    assert settings.port == 8000
```

`tests/test_admin_auth.py`:
```python
from admin.app.auth import check_password, SessionStore


def test_check_password_matches():
    assert check_password("geheim123", "geheim123") is True


def test_check_password_does_not_match():
    assert check_password("verkeerd", "geheim123") is False


def test_session_store_create_and_validate():
    store = SessionStore()
    token = store.create()

    assert store.is_valid(token) is True
    assert store.is_valid("een-willekeurig-ander-token") is False


def test_session_store_revoke():
    store = SessionStore()
    token = store.create()
    store.revoke(token)

    assert store.is_valid(token) is False
```

- [ ] **Step 3: Run de tests, verwacht FAIL**

Run: `pytest tests/test_admin_config.py tests/test_admin_auth.py -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'admin.app.config'` (en later `.auth`)

- [ ] **Step 4: Implementeer `admin/app/config.py`**

```python
import os
from dataclasses import dataclass


@dataclass
class Settings:
    admin_password: str
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_pass: str
    ha_url: str
    ha_token: str
    db_path: str
    media_dir: str
    port: int


def get_settings():
    return Settings(
        admin_password=os.environ.get("ADMIN_PASSWORD", "halloween"),
        mqtt_host=os.environ.get("MQTT_HOST", "homeassistant.local"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_pass=os.environ.get("MQTT_PASS", ""),
        ha_url=os.environ.get("HA_URL", "http://homeassistant.local:8123"),
        ha_token=os.environ.get("HA_TOKEN", ""),
        db_path=os.environ.get("ADMIN_DB_PATH", "./admin.db"),
        media_dir=os.environ.get("ADMIN_MEDIA_DIR", "./media_store"),
        port=int(os.environ.get("ADMIN_PORT", "8000")),
    )
```

- [ ] **Step 5: Implementeer `admin/app/auth.py`**

```python
import secrets
import threading


def check_password(password, expected):
    return secrets.compare_digest(password, expected)


class SessionStore:
    """Houdt geldige sessie-tokens in-memory bij. Geen persistentie nodig:
    een herstart van de backend logt iedereen uit, prima voor dit
    hobbyproject. Lock omdat FastAPI requests op verschillende threads
    kunnen landen."""

    def __init__(self):
        self._tokens = set()
        self._lock = threading.Lock()

    def create(self):
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens.add(token)
        return token

    def is_valid(self, token):
        with self._lock:
            return token in self._tokens

    def revoke(self, token):
        with self._lock:
            self._tokens.discard(token)
```

- [ ] **Step 6: Run de tests, verwacht PASS**

Run: `pytest tests/test_admin_config.py tests/test_admin_auth.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Commit**

```bash
git add admin/app/__init__.py admin/app/routers/__init__.py admin/app/config.py admin/app/auth.py tests/test_admin_config.py tests/test_admin_auth.py
git commit -m "feat: backend-configuratie en wachtwoord/sessie-auth"
```

---

### Task 2: SQLite-laag + media-opslag

**Files:**
- Create: `admin/app/db.py`
- Create: `admin/app/media.py`
- Test: `tests/test_admin_db.py`
- Test: `tests/test_admin_media.py`

**Interfaces:**
- Consumes: `shared.media_sync.content_hash(data: bytes) -> str` (Plan 1, hergebruiken — niet opnieuw implementeren)
- Produces:
  - `admin.app.db.init_db(path: str) -> sqlite3.Connection`
  - `admin.app.media.save_media(conn, media_dir: str, data: bytes, filename: str, category: str) -> str` (hash)
  - `admin.app.media.get_media_path(media_dir: str, hash_: str) -> str | None`
  - `admin.app.media.list_media(conn, category: str | None = None) -> list[dict]`
  - `admin.app.media.delete_media(conn, media_dir: str, hash_: str) -> bool`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_admin_db.py`:
```python
from admin.app.db import init_db


def test_init_db_creates_expected_tables(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert {"media", "scare_zone_config", "mirror_config", "schedule"} <= tables


def test_init_db_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = init_db(path)  # tweede keer mag niet crashen

    assert conn is not None
```

`tests/test_admin_media.py`:
```python
from admin.app.db import init_db
from admin.app.media import save_media, get_media_path, list_media, delete_media
from shared.media_sync import content_hash


def test_save_media_stores_file_and_returns_hash(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")
    data = b"fake-png-bytes"

    result_hash = save_media(conn, media_dir, data, "spook.png", "mirror_overlay")

    assert result_hash == content_hash(data)
    assert get_media_path(media_dir, result_hash) is not None
    with open(get_media_path(media_dir, result_hash), "rb") as f:
        assert f.read() == data


def test_get_media_path_returns_none_for_unknown_hash(tmp_path):
    media_dir = str(tmp_path / "media")
    assert get_media_path(media_dir, "a" * 64) is None


def test_list_media_filters_by_category(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")
    save_media(conn, media_dir, b"overlay-data", "spook.png", "mirror_overlay")
    save_media(conn, media_dir, b"audio-data", "gil.wav", "scare_audio")

    overlays = list_media(conn, category="mirror_overlay")

    assert len(overlays) == 1
    assert overlays[0]["filename"] == "spook.png"
    assert overlays[0]["category"] == "mirror_overlay"


def test_list_media_without_category_returns_all(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")
    save_media(conn, media_dir, b"overlay-data", "spook.png", "mirror_overlay")
    save_media(conn, media_dir, b"audio-data", "gil.wav", "scare_audio")

    assert len(list_media(conn)) == 2


def test_delete_media_removes_file_and_row(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")
    h = save_media(conn, media_dir, b"data", "x.wav", "scare_audio")

    deleted = delete_media(conn, media_dir, h)

    assert deleted is True
    assert get_media_path(media_dir, h) is None
    assert list_media(conn) == []


def test_delete_media_returns_false_for_unknown_hash(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")

    assert delete_media(conn, media_dir, "a" * 64) is False
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_admin_db.py tests/test_admin_media.py -v`
Expected: FAIL met `ModuleNotFoundError`

- [ ] **Step 3: Implementeer `admin/app/db.py`**

```python
import sqlite3


def init_db(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS media (
            hash TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            category TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scare_zone_config (
            zone TEXT PRIMARY KEY,
            enabled_hashes TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mirror_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            effect TEXT NOT NULL DEFAULT 'xray',
            params TEXT NOT NULL DEFAULT '{}',
            overlay_hash TEXT,
            scale REAL NOT NULL DEFAULT 1.0,
            position TEXT NOT NULL DEFAULT '[0.5, 0.5]'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            on_time TEXT NOT NULL DEFAULT '18:00',
            off_time TEXT NOT NULL DEFAULT '22:00',
            enabled INTEGER NOT NULL DEFAULT 1
        )"""
    )
    conn.commit()
    return conn
```

- [ ] **Step 4: Implementeer `admin/app/media.py`**

```python
import os
import time

from shared.media_sync import content_hash


def save_media(conn, media_dir, data, filename, category):
    os.makedirs(media_dir, exist_ok=True)
    hash_ = content_hash(data)
    with open(os.path.join(media_dir, hash_), "wb") as f:
        f.write(data)
    conn.execute(
        "INSERT OR REPLACE INTO media (hash, filename, category, uploaded_at) VALUES (?, ?, ?, ?)",
        (hash_, filename, category, str(time.time())),
    )
    conn.commit()
    return hash_


def get_media_path(media_dir, hash_):
    path = os.path.join(media_dir, hash_)
    return path if os.path.exists(path) else None


def list_media(conn, category=None):
    if category is not None:
        rows = conn.execute(
            "SELECT hash, filename, category, uploaded_at FROM media WHERE category = ? ORDER BY uploaded_at DESC",
            (category,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT hash, filename, category, uploaded_at FROM media ORDER BY uploaded_at DESC"
        ).fetchall()
    return [
        {"hash": r[0], "filename": r[1], "category": r[2], "uploaded_at": r[3]}
        for r in rows
    ]


def delete_media(conn, media_dir, hash_):
    path = get_media_path(media_dir, hash_)
    cursor = conn.execute("DELETE FROM media WHERE hash = ?", (hash_,))
    conn.commit()
    if path is not None:
        os.remove(path)
    return cursor.rowcount > 0
```

- [ ] **Step 5: Run de tests, verwacht PASS**

Run: `pytest tests/test_admin_db.py tests/test_admin_media.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add admin/app/db.py admin/app/media.py tests/test_admin_db.py tests/test_admin_media.py
git commit -m "feat: SQLite-schema en content-addressed media-opslag"
```

---

### Task 3: MQTT-state-tracking (pure logica)

**Files:**
- Create: `admin/app/mqtt_state.py`
- Test: `tests/test_admin_mqtt_state.py`

**Interfaces:**
- Produces: `admin.app.mqtt_state.NodeStatusTracker` met `.handle_message(topic: str, payload: str)`, `.get_nodes() -> dict[str, dict]`, `.get_recent_logs(node: str | None = None, limit: int = 100) -> list[dict]`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_admin_mqtt_state.py`:
```python
import json
from admin.app.mqtt_state import NodeStatusTracker


def test_status_message_updates_node_state():
    tracker = NodeStatusTracker()

    tracker.handle_message("status/mirror", "online")

    nodes = tracker.get_nodes()
    assert nodes["mirror"]["status"] == "online"


def test_status_offline_updates_state():
    tracker = NodeStatusTracker()
    tracker.handle_message("status/mirror", "online")

    tracker.handle_message("status/mirror", "offline")

    assert tracker.get_nodes()["mirror"]["status"] == "offline"


def test_log_message_is_recorded():
    tracker = NodeStatusTracker()
    payload = json.dumps({"ts": 123.0, "level": "INFO", "msg": "mirror-node gestart"})

    tracker.handle_message("log/mirror", payload)

    logs = tracker.get_recent_logs()
    assert len(logs) == 1
    assert logs[0]["msg"] == "mirror-node gestart"
    assert logs[0]["node"] == "mirror"


def test_get_recent_logs_filters_by_node():
    tracker = NodeStatusTracker()
    tracker.handle_message("log/mirror", json.dumps({"ts": 1.0, "level": "INFO", "msg": "a"}))
    tracker.handle_message("log/scare-zone-a", json.dumps({"ts": 2.0, "level": "INFO", "msg": "b"}))

    mirror_logs = tracker.get_recent_logs(node="mirror")

    assert len(mirror_logs) == 1
    assert mirror_logs[0]["msg"] == "a"


def test_get_recent_logs_respects_limit():
    tracker = NodeStatusTracker()
    for i in range(10):
        tracker.handle_message("log/mirror", json.dumps({"ts": float(i), "level": "INFO", "msg": str(i)}))

    logs = tracker.get_recent_logs(limit=3)

    assert len(logs) == 3


def test_unrelated_topic_is_ignored_without_crashing():
    tracker = NodeStatusTracker()

    tracker.handle_message("mirror/triggered", '{"ts": 1.0}')  # geen crash

    assert tracker.get_nodes() == {}


def test_malformed_log_payload_does_not_crash():
    tracker = NodeStatusTracker()

    tracker.handle_message("log/mirror", "dit is geen JSON")

    assert tracker.get_recent_logs() == []
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_admin_mqtt_state.py -v`
Expected: FAIL met `ModuleNotFoundError`

- [ ] **Step 3: Implementeer `admin/app/mqtt_state.py`**

```python
import json
import re
import threading

_STATUS_RE = re.compile(r"^status/(.+)$")
_LOG_RE = re.compile(r"^log/(.+)$")


class NodeStatusTracker:
    """Houdt bij welke nodes online/offline zijn en hun recente logregels,
    puur op basis van binnenkomende MQTT-berichten. Geen eigen MQTT-verbinding
    — de MqttBridge (glue-laag) roept `handle_message` aan voor elk bericht."""

    def __init__(self, max_logs_per_node=200):
        self._nodes = {}
        self._logs = []
        self._max_logs_per_node = max_logs_per_node
        self._lock = threading.Lock()

    def handle_message(self, topic, payload):
        status_match = _STATUS_RE.match(topic)
        if status_match:
            node = status_match.group(1)
            with self._lock:
                self._nodes.setdefault(node, {})["status"] = payload
            return

        log_match = _LOG_RE.match(topic)
        if log_match:
            node = log_match.group(1)
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return
            if not isinstance(data, dict):
                return
            entry = {
                "node": node,
                "ts": data.get("ts"),
                "level": data.get("level"),
                "msg": data.get("msg"),
            }
            with self._lock:
                self._logs.append(entry)
                if len(self._logs) > self._max_logs_per_node * 20:
                    self._logs = self._logs[-(self._max_logs_per_node * 10):]
            return

    def get_nodes(self):
        with self._lock:
            return {k: dict(v) for k, v in self._nodes.items()}

    def get_recent_logs(self, node=None, limit=100):
        with self._lock:
            logs = self._logs if node is None else [l for l in self._logs if l["node"] == node]
            return logs[-limit:]
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_admin_mqtt_state.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add admin/app/mqtt_state.py tests/test_admin_mqtt_state.py
git commit -m "feat: pure MQTT-status/log-tracking voor het dashboard"
```

---

### Task 4: MQTT-bridge (glue)

**Files:**
- Create: `admin/app/mqtt_bridge.py`

**Interfaces:**
- Consumes:
  - `admin.app.mqtt_state.NodeStatusTracker` (Task 3)
  - `shared.mqtt_contract.*` topic-helpers (Plan 1)
- Produces: `admin.app.mqtt_bridge.MqttBridge(settings, tracker, ws_hub=None, loop=None)` met `.start()`, `.stop()`, `.publish_mirror_config(config: dict)`, `.publish_mirror_preview(config: dict)`, `.publish_mirror_test()`, `.publish_scare_config(zone: str, enabled_hashes: list[str])`, `.publish_scare_test(zone: str)`, `.publish_sleep(is_sleeping: bool)`

`ws_hub`/`loop` zijn optioneel en pas vanaf Task 12 daadwerkelijk gebruikt
(live status/logs doorzetten naar de browser via WebSocket) — de constructor
accepteert ze nu al (duck-typed, geen import van `websocket_hub` nodig) zodat
`mqtt_bridge.py` na deze taak nooit meer gewijzigd hoeft te worden.

Glue-code (echte MQTT-verbinding) — geen geautomatiseerde test, conform de bestaande projectconventie. Verificatie gebeurt handmatig zodra de backend draait tegen een echte broker (Step 3 hieronder), en indirect via de router-tests in latere taken (die een fake/mock `MqttBridge` injecteren).

- [ ] **Step 1: Implementeer `admin/app/mqtt_bridge.py`**

```python
import asyncio
import json

import paho.mqtt.client as mqtt

from shared.mqtt_contract import (
    SLEEP_PAYLOAD_ON,
    SLEEP_PAYLOAD_OFF,
    TOPIC_SYSTEM_SLEEP,
    TOPIC_CONFIG_MIRROR,
    TOPIC_CONTROL_MIRROR_PREVIEW,
    TOPIC_CONTROL_MIRROR_TEST,
    TOPIC_MIRROR_TRIGGERED,
    scare_topic,
    config_scare_topic,
    control_scare_test_topic,
)

_STATUS_WILDCARD = "status/+"
_LOG_WILDCARD = "log/+"
_SCARE_TRIGGERED_WILDCARD = "scare/+/triggered"


class MqttBridge:
    """Verbindt de backend met dezelfde broker als de nodes. Leest
    status/log/trigger-topics door naar de NodeStatusTracker (en, als
    `ws_hub`/`loop` zijn ingesteld, ook live naar verbonden browsers via
    WebSocket — zie Task 12); publiceert config/control-berichten wanneer
    de beheerpagina iets wijzigt."""

    def __init__(self, settings, tracker, ws_hub=None, loop=None):
        self._settings = settings
        self._tracker = tracker
        self._ws_hub = ws_hub
        self._loop = loop
        self._client = mqtt.Client(client_id="beheerpagina-backend")
        if settings.mqtt_user:
            self._client.username_pw_set(settings.mqtt_user, settings.mqtt_pass)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            return
        client.subscribe(_STATUS_WILDCARD)
        client.subscribe(_LOG_WILDCARD)
        client.subscribe(TOPIC_MIRROR_TRIGGERED)
        client.subscribe(_SCARE_TRIGGERED_WILDCARD)

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode()
            self._tracker.handle_message(msg.topic, payload)
            self._broadcast_to_websockets(msg.topic, payload)
        except Exception:
            pass  # nooit de MQTT-netwerkthread laten crashen

    def _broadcast_to_websockets(self, topic, payload):
        if self._ws_hub is None or self._loop is None:
            return
        if topic.startswith("status/"):
            kind = "status"
        elif topic.startswith("log/"):
            kind = "log"
        else:
            return
        asyncio.run_coroutine_threadsafe(
            self._ws_hub.broadcast({"type": kind, "topic": topic, "payload": payload}),
            self._loop,
        )

    def start(self):
        self._client.connect_async(self._settings.mqtt_host, self._settings.mqtt_port)
        self._client.loop_start()

    def stop(self):
        self._client.loop_stop()

    def publish_mirror_config(self, config):
        self._client.publish(TOPIC_CONFIG_MIRROR, json.dumps(config), retain=True)

    def publish_mirror_preview(self, config):
        self._client.publish(TOPIC_CONTROL_MIRROR_PREVIEW, json.dumps(config))

    def publish_mirror_test(self):
        self._client.publish(TOPIC_CONTROL_MIRROR_TEST, "{}")

    def publish_scare_config(self, zone, enabled_hashes):
        self._client.publish(
            config_scare_topic(zone),
            json.dumps({"enabled_hashes": enabled_hashes}),
            retain=True,
        )

    def publish_scare_test(self, zone):
        self._client.publish(control_scare_test_topic(zone), "{}")

    def publish_sleep(self, is_sleeping):
        payload = SLEEP_PAYLOAD_ON if is_sleeping else SLEEP_PAYLOAD_OFF
        self._client.publish(TOPIC_SYSTEM_SLEEP, payload, retain=True)
```

- [ ] **Step 2: Syntax-/importcontrole**

Run: `python3 -c "import ast; ast.parse(open('admin/app/mqtt_bridge.py').read())"`
Expected: geen output

Run: `python3 -c "from admin.app.mqtt_bridge import MqttBridge"` (in de venv met `paho-mqtt` geïnstalleerd)
Expected: geen output

- [ ] **Step 3: Commit**

```bash
git add admin/app/mqtt_bridge.py
git commit -m "feat: MQTT-brug tussen backend en de bestaande nodes"
```

---

### Task 5: Home Assistant-client

**Files:**
- Create: `admin/app/ha_client.py`
- Test: `tests/test_admin_ha_client.py`

**Interfaces:**
- Produces:
  - `admin.app.ha_client.get_states(ha_url: str, ha_token: str, fetch=None) -> list[dict]`
  - `admin.app.ha_client.call_service(ha_url: str, ha_token: str, domain: str, service: str, data: dict, fetch=None) -> None`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_admin_ha_client.py`:
```python
import json
from admin.app.ha_client import get_states, call_service


def test_get_states_calls_correct_url_and_parses_json():
    calls = []

    def fake_fetch(url, method="GET", headers=None, body=None):
        calls.append((url, method, headers))
        return json.dumps([{"entity_id": "light.wled_voortuin", "state": "on"}]).encode()

    result = get_states("http://ha.local:8123", "mytoken", fetch=fake_fetch)

    assert result == [{"entity_id": "light.wled_voortuin", "state": "on"}]
    assert calls[0][0] == "http://ha.local:8123/api/states"
    assert calls[0][1] == "GET"
    assert calls[0][2]["Authorization"] == "Bearer mytoken"


def test_get_states_returns_empty_list_on_failure():
    def failing_fetch(url, method="GET", headers=None, body=None):
        raise OSError("HA onbereikbaar")

    result = get_states("http://ha.local:8123", "mytoken", fetch=failing_fetch)

    assert result == []


def test_call_service_posts_correct_body():
    calls = []

    def fake_fetch(url, method="GET", headers=None, body=None):
        calls.append((url, method, headers, body))
        return b"{}"

    call_service(
        "http://ha.local:8123", "mytoken", "light", "turn_on",
        {"entity_id": "light.wled_voortuin"}, fetch=fake_fetch,
    )

    url, method, headers, body = calls[0]
    assert url == "http://ha.local:8123/api/services/light/turn_on"
    assert method == "POST"
    assert json.loads(body) == {"entity_id": "light.wled_voortuin"}


def test_call_service_swallows_failure():
    def failing_fetch(url, method="GET", headers=None, body=None):
        raise OSError("HA onbereikbaar")

    call_service("http://ha.local:8123", "mytoken", "light", "turn_on", {}, fetch=failing_fetch)
    # geen exception naar buiten -> test slaagt als er niets gecrasht is
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_admin_ha_client.py -v`
Expected: FAIL met `ModuleNotFoundError`

- [ ] **Step 3: Implementeer `admin/app/ha_client.py`**

```python
import json
import urllib.request


def _default_fetch(url, method="GET", headers=None, body=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read()


def get_states(ha_url, ha_token, fetch=None):
    fetch = fetch or _default_fetch
    headers = {"Authorization": f"Bearer {ha_token}"}
    try:
        data = fetch(f"{ha_url}/api/states", method="GET", headers=headers)
        return json.loads(data)
    except Exception:
        return []


def call_service(ha_url, ha_token, domain, service, data, fetch=None):
    fetch = fetch or _default_fetch
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode()
    try:
        fetch(f"{ha_url}/api/services/{domain}/{service}", method="POST", headers=headers, body=body)
    except Exception:
        pass
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_admin_ha_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add admin/app/ha_client.py tests/test_admin_ha_client.py
git commit -m "feat: dunne Home Assistant REST-client voor WLED-status/bediening"
```

---

### Task 6: Tijdvenster-scheduler

**Files:**
- Create: `admin/app/scheduler.py`
- Test: `tests/test_admin_scheduler.py`

**Interfaces:**
- Consumes: `admin.app.mqtt_bridge.MqttBridge.publish_sleep(is_sleeping: bool)` (Task 4, alleen in de achtergrondlus, niet in de pure functie)
- Produces:
  - `admin.app.scheduler.should_be_sleeping(now: str, on_time: str, off_time: str) -> bool` (pure, `now`/`on_time`/`off_time` als `"HH:MM"`-strings)
  - `admin.app.scheduler.Scheduler(bridge, get_schedule)` met `.start()`, `.stop()` — `get_schedule` is een callable die `(on_time, off_time, enabled)` teruggeeft (uit de DB, zie Task 10)

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_admin_scheduler.py`:
```python
from admin.app.scheduler import should_be_sleeping


def test_should_be_sleeping_within_window_is_awake():
    assert should_be_sleeping("19:00", "18:00", "22:00") is False


def test_should_be_sleeping_before_window_is_asleep():
    assert should_be_sleeping("10:00", "18:00", "22:00") is True


def test_should_be_sleeping_after_window_is_asleep():
    assert should_be_sleeping("23:00", "18:00", "22:00") is True


def test_should_be_sleeping_at_exact_on_time_is_awake():
    assert should_be_sleeping("18:00", "18:00", "22:00") is False


def test_should_be_sleeping_at_exact_off_time_is_asleep():
    assert should_be_sleeping("22:00", "18:00", "22:00") is True


def test_should_be_sleeping_handles_overnight_window():
    # bijv. aan om 22:00, uit om 02:00 (loopt over middernacht)
    assert should_be_sleeping("23:30", "22:00", "02:00") is False
    assert should_be_sleeping("03:00", "22:00", "02:00") is True
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_admin_scheduler.py -v`
Expected: FAIL met `ModuleNotFoundError`

- [ ] **Step 3: Implementeer `admin/app/scheduler.py`**

```python
import threading
import time
from datetime import datetime


def _to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def should_be_sleeping(now, on_time, off_time):
    """`now`/`on_time`/`off_time` zijn 'HH:MM'-strings. Ondersteunt een
    venster dat over middernacht loopt (bijv. aan=22:00, uit=02:00)."""
    now_m = _to_minutes(now)
    on_m = _to_minutes(on_time)
    off_m = _to_minutes(off_time)

    if on_m <= off_m:
        return not (on_m <= now_m < off_m)
    # venster loopt over middernacht
    return not (now_m >= on_m or now_m < off_m)


class Scheduler:
    """Controleert elke minuut het ingestelde tijdvenster en publiceert
    system/sleep bij iedere check (retained, dus idempotent/robuust tegen
    herstarts) — vervangt de oude HA-tijdvenster-automation volledig."""

    def __init__(self, bridge, get_schedule, check_interval=60):
        self._bridge = bridge
        self._get_schedule = get_schedule
        self._check_interval = check_interval
        self._stop_event = threading.Event()
        self._thread = None

    def _loop(self):
        while not self._stop_event.is_set():
            on_time, off_time, enabled = self._get_schedule()
            if enabled:
                now = datetime.now().strftime("%H:%M")
                self._bridge.publish_sleep(should_be_sleeping(now, on_time, off_time))
            self._stop_event.wait(self._check_interval)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_admin_scheduler.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add admin/app/scheduler.py tests/test_admin_scheduler.py
git commit -m "feat: tijdvenster-scheduler (vervangt de oude HA-automation)"
```

---

### Task 7: WebSocket-hub

**Files:**
- Create: `admin/app/websocket_hub.py`
- Test: `tests/test_admin_websocket_hub.py`

**Interfaces:**
- Produces: `admin.app.websocket_hub.WebSocketHub` met `.register(ws)`, `.unregister(ws)`, `async .broadcast(message: dict)`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_admin_websocket_hub.py`:
```python
import asyncio
import pytest
from admin.app.websocket_hub import WebSocketHub


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def test_register_and_broadcast_sends_to_all():
    hub = WebSocketHub()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    hub.register(ws1)
    hub.register(ws2)

    asyncio.run(hub.broadcast({"type": "status", "node": "mirror"}))

    assert ws1.sent == [{"type": "status", "node": "mirror"}]
    assert ws2.sent == [{"type": "status", "node": "mirror"}]


def test_unregister_stops_delivery():
    hub = WebSocketHub()
    ws = FakeWebSocket()
    hub.register(ws)
    hub.unregister(ws)

    asyncio.run(hub.broadcast({"type": "status"}))

    assert ws.sent == []


def test_broadcast_to_failing_client_does_not_break_others():
    hub = WebSocketHub()

    class FailingWebSocket:
        async def send_json(self, data):
            raise ConnectionError("weg")

    ok_ws = FakeWebSocket()
    hub.register(FailingWebSocket())
    hub.register(ok_ws)

    asyncio.run(hub.broadcast({"type": "status"}))

    assert ok_ws.sent == [{"type": "status"}]
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_admin_websocket_hub.py -v`
Expected: FAIL met `ModuleNotFoundError`

- [ ] **Step 3: Implementeer `admin/app/websocket_hub.py`**

```python
class WebSocketHub:
    """Houdt actieve browser-WebSockets bij en zendt berichten naar allemaal.
    Eén trage/kapotte client mag de andere niet raken."""

    def __init__(self):
        self._clients = set()

    def register(self, ws):
        self._clients.add(ws)

    def unregister(self, ws):
        self._clients.discard(ws)

    async def broadcast(self, message):
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                self._clients.discard(ws)
```

- [ ] **Step 4: Run de tests, verwacht PASS**

Run: `pytest tests/test_admin_websocket_hub.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add admin/app/websocket_hub.py tests/test_admin_websocket_hub.py
git commit -m "feat: WebSocket-hub voor live status/logs naar de browser"
```

---

### Task 8: FastAPI-app + auth-routes

**Files:**
- Create: `admin/app/main.py`
- Create: `admin/app/routers/auth.py`
- Create: `admin/requirements.txt`
- Create: `admin/run.py`
- Test: `tests/test_admin_routes_auth.py`

**Interfaces:**
- Consumes: `admin.app.config.get_settings` (Task 1), `admin.app.auth.{check_password, SessionStore}` (Task 1), `admin.app.db.init_db` (Task 2), `admin.app.mqtt_bridge.MqttBridge` (Task 4), `admin.app.mqtt_state.NodeStatusTracker` (Task 3), `admin.app.scheduler.Scheduler` (Task 6), `admin.app.websocket_hub.WebSocketHub` (Task 7)
- Produces: `admin.app.main.create_app(settings=None) -> FastAPI`, `admin.app.main.get_current_session` (FastAPI dependency die de sessie-cookie checkt), routers gemonteerd op `/api/...`

- [ ] **Step 1: Schrijf de falende test**

`tests/test_admin_routes_auth.py`:
```python
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


def _test_settings(tmp_path):
    return Settings(
        admin_password="testwachtwoord",
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )


def test_login_with_correct_password_sets_cookie(tmp_path):
    app = create_app(settings=_test_settings(tmp_path))
    client = TestClient(app)

    response = client.post("/api/login", json={"password": "testwachtwoord"})

    assert response.status_code == 200
    assert "session" in response.cookies


def test_login_with_wrong_password_is_rejected(tmp_path):
    app = create_app(settings=_test_settings(tmp_path))
    client = TestClient(app)

    response = client.post("/api/login", json={"password": "verkeerd"})

    assert response.status_code == 401
    assert "session" not in response.cookies


def test_protected_route_requires_session(tmp_path):
    app = create_app(settings=_test_settings(tmp_path))
    client = TestClient(app)

    response = client.get("/api/nodes")

    assert response.status_code == 401


def test_logout_revokes_session(tmp_path):
    app = create_app(settings=_test_settings(tmp_path))
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})

    client.post("/api/logout")
    response = client.get("/api/nodes")

    assert response.status_code == 401
```

- [ ] **Step 2: Run de test, verwacht FAIL**

Run: `pytest tests/test_admin_routes_auth.py -v`
Expected: FAIL met `ModuleNotFoundError`

- [ ] **Step 3: Implementeer `admin/app/routers/auth.py`**

```python
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from admin.app.auth import check_password

router = APIRouter()


class LoginRequest(BaseModel):
    password: str


@router.post("/api/login")
def login(body: LoginRequest, request: Request, response: Response):
    settings = request.app.state.settings
    if not check_password(body.password, settings.admin_password):
        return Response(status_code=401)
    token = request.app.state.sessions.create()
    response.set_cookie("session", token, httponly=True)
    return {"ok": True}


@router.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("session")
    if token:
        request.app.state.sessions.revoke(token)
    response.delete_cookie("session")
    return {"ok": True}
```

- [ ] **Step 4: Implementeer `admin/app/main.py`**

```python
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
        public_paths = ("/api/login", "/docs", "/openapi.json")
        if request.url.path.startswith("/api/media/") and request.method == "GET":
            return await call_next(request)  # media-download is publiek, geen auth
        if any(request.url.path.startswith(p) for p in public_paths):
            return await call_next(request)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        token = request.cookies.get("session")
        if not token or not app.state.sessions.is_valid(token):
            return JSONResponse(status_code=401, content={"detail": "niet ingelogd"})
        return await call_next(request)

    app.include_router(auth_router.router)

    @app.on_event("startup")
    def _startup():
        app.state.bridge.start()
        app.state.scheduler.start()

    @app.on_event("shutdown")
    def _shutdown():
        app.state.scheduler.stop()
        app.state.bridge.stop()

    return app
```

- [ ] **Step 5: `admin/requirements.txt` en `admin/run.py`**

`admin/requirements.txt`:
```
fastapi
uvicorn[standard]
python-multipart
```

`admin/run.py`:
```python
import uvicorn

from admin.app.config import get_settings
from admin.app.main import create_app

settings = get_settings()
app = create_app(settings)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
```

- [ ] **Step 6: Run de test, verwacht PASS**

Run: `pip install -r admin/requirements.txt` (in de venv), dan `pytest tests/test_admin_routes_auth.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Run de volledige suite, verwacht PASS**

Run: `pytest tests/ -v`
Expected: PASS (alle bestaande + nieuwe tests, geen regressies)

- [ ] **Step 8: Commit**

```bash
git add admin/app/main.py admin/app/routers/auth.py admin/requirements.txt admin/run.py tests/test_admin_routes_auth.py
git commit -m "feat: FastAPI-app-skelet met wachtwoord/sessie-auth-middleware"
```

---

### Task 9: Media-routes

**Files:**
- Create: `admin/app/routers/media.py`
- Test: `tests/test_admin_routes_media.py`

**Interfaces:**
- Consumes: `admin.app.media.{save_media, get_media_path, list_media, delete_media}` (Task 2)
- Produces (HTTP): `POST /api/media` (multipart upload, auth), `GET /api/media` (lijst, auth), `GET /api/media/{hash}` (download, **geen auth** — dit is precies het endpoint dat de nodes al aanroepen), `DELETE /api/media/{hash}` (auth)

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_admin_routes_media.py`:
```python
import io
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app
from shared.media_sync import content_hash


def _client(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client


def test_upload_list_download_delete_roundtrip(tmp_path):
    client = _client(tmp_path)
    data = b"fake-overlay-png-bytes"

    upload_resp = client.post(
        "/api/media",
        files={"file": ("spook.png", io.BytesIO(data), "image/png")},
        data={"category": "mirror_overlay"},
    )
    assert upload_resp.status_code == 200
    h = upload_resp.json()["hash"]
    assert h == content_hash(data)

    list_resp = client.get("/api/media")
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["hash"] == h

    # download werkt zonder sessie-cookie (nodes hebben geen login)
    from fastapi.testclient import TestClient as PlainTestClient
    anon_client = PlainTestClient(client.app)
    download_resp = anon_client.get(f"/api/media/{h}")
    assert download_resp.status_code == 200
    assert download_resp.content == data

    delete_resp = client.delete(f"/api/media/{h}")
    assert delete_resp.status_code == 200
    assert client.get("/api/media").json() == []


def test_download_unknown_hash_returns_404(tmp_path):
    client = _client(tmp_path)
    from fastapi.testclient import TestClient as PlainTestClient
    anon_client = PlainTestClient(client.app)

    response = anon_client.get(f"/api/media/{'a' * 64}")

    assert response.status_code == 404


def test_list_can_filter_by_category(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/api/media",
        files={"file": ("spook.png", io.BytesIO(b"overlay"), "image/png")},
        data={"category": "mirror_overlay"},
    )
    client.post(
        "/api/media",
        files={"file": ("gil.wav", io.BytesIO(b"audio"), "audio/wav")},
        data={"category": "scare_audio"},
    )

    response = client.get("/api/media", params={"category": "scare_audio"})

    assert len(response.json()) == 1
    assert response.json()[0]["filename"] == "gil.wav"
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_admin_routes_media.py -v`
Expected: FAIL — router bestaat nog niet / 404 op alle routes

- [ ] **Step 3: Implementeer `admin/app/routers/media.py`**

```python
from fastapi import APIRouter, Request, UploadFile, Form, Response

from admin.app.media import save_media, get_media_path, list_media, delete_media

router = APIRouter()


@router.post("/api/media")
async def upload_media(request: Request, file: UploadFile, category: str = Form(...)):
    data = await file.read()
    h = save_media(request.app.state.db, request.app.state.settings.media_dir, data, file.filename, category)
    return {"hash": h, "filename": file.filename, "category": category}


@router.get("/api/media")
def list_media_route(request: Request, category: str | None = None):
    return list_media(request.app.state.db, category=category)


@router.get("/api/media/{hash_}")
def download_media(hash_: str, request: Request):
    path = get_media_path(request.app.state.settings.media_dir, hash_)
    if path is None:
        return Response(status_code=404)
    with open(path, "rb") as f:
        data = f.read()
    return Response(content=data, media_type="application/octet-stream")


@router.delete("/api/media/{hash_}")
def delete_media_route(hash_: str, request: Request):
    deleted = delete_media(request.app.state.db, request.app.state.settings.media_dir, hash_)
    return {"deleted": deleted}
```

- [ ] **Step 4: Monteer de router en maak `/api/media/{hash}` GET publiek**

Voeg in `admin/app/main.py` toe: `from admin.app.routers import media as media_router` en `app.include_router(media_router.router)`. De auth-middleware maakt `GET /api/media/<hash>` al publiek via de bestaande `request.url.path.startswith("/api/media/")`-check (Task 8) — controleer dat dit ook echt voor dit endpoint geldt en niet per ongeluk óók `POST /api/media` of `GET /api/media` (de lijst, zonder pad-segment erna) publiek maakt. Pas de middleware-check zo nodig aan zodat alleen `GET` op `/api/media/<iets>` (met een pad-segment) publiek is.

- [ ] **Step 5: Run de tests, verwacht PASS**

Run: `pytest tests/test_admin_routes_media.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run de volledige suite, verwacht PASS**

Run: `pytest tests/ -v`

- [ ] **Step 7: Commit**

```bash
git add admin/app/routers/media.py admin/app/main.py tests/test_admin_routes_media.py
git commit -m "feat: media-routes (upload/lijst/download/verwijderen)"
```

---

### Task 10: Mirror- en scare-config-routes

**Files:**
- Create: `admin/app/routers/mirror.py`
- Create: `admin/app/routers/scare.py`
- Test: `tests/test_admin_routes_mirror_scare.py`

**Interfaces:**
- Consumes: `admin.app.mqtt_bridge.MqttBridge.{publish_mirror_config, publish_mirror_preview, publish_mirror_test, publish_scare_config, publish_scare_test}` (Task 4)
- Produces (HTTP):
  - `GET /api/mirror/config`, `PUT /api/mirror/config` (opslaan in DB + publiceren, persistent)
  - `POST /api/mirror/preview` (alleen publiceren, niet opslaan)
  - `POST /api/mirror/test` (test-trigger)
  - `GET /api/scare/{zone}/config`, `PUT /api/scare/{zone}/config` (opslaan + publiceren)
  - `POST /api/scare/{zone}/test`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_admin_routes_mirror_scare.py`:
```python
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeBridge:
    def __init__(self):
        self.calls = []

    def start(self):
        pass

    def stop(self):
        pass

    def publish_mirror_config(self, config):
        self.calls.append(("mirror_config", config))

    def publish_mirror_preview(self, config):
        self.calls.append(("mirror_preview", config))

    def publish_mirror_test(self):
        self.calls.append(("mirror_test",))

    def publish_scare_config(self, zone, enabled_hashes):
        self.calls.append(("scare_config", zone, enabled_hashes))

    def publish_scare_test(self, zone):
        self.calls.append(("scare_test", zone))

    def publish_sleep(self, is_sleeping):
        self.calls.append(("sleep", is_sleeping))


def _client(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()  # vervang de echte MQTT-bridge door een fake
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app.state.bridge


def test_put_mirror_config_saves_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    payload = {"effect": "thermal", "params": {"intensity": 0.8}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]}

    response = client.put("/api/mirror/config", json=payload)

    assert response.status_code == 200
    assert ("mirror_config", payload) in bridge.calls

    get_response = client.get("/api/mirror/config")
    assert get_response.json() == payload


def test_post_mirror_preview_publishes_without_saving(tmp_path):
    client, bridge = _client(tmp_path)
    client.put("/api/mirror/config", json={"effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    preview_payload = {"effect": "contour", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]}

    response = client.post("/api/mirror/preview", json=preview_payload)

    assert response.status_code == 200
    assert ("mirror_preview", preview_payload) in bridge.calls
    # opgeslagen config blijft ongewijzigd
    assert client.get("/api/mirror/config").json()["effect"] == "xray"


def test_post_mirror_test_publishes_test_trigger(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/mirror/test")

    assert response.status_code == 200
    assert ("mirror_test",) in bridge.calls


def test_put_scare_config_saves_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scare/zone-a/config", json={"enabled_hashes": ["a" * 64, "b" * 64]})

    assert response.status_code == 200
    assert ("scare_config", "zone-a", ["a" * 64, "b" * 64]) in bridge.calls
    assert client.get("/api/scare/zone-a/config").json() == {"enabled_hashes": ["a" * 64, "b" * 64]}


def test_get_scare_config_defaults_to_empty(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/scare/zone-b/config")

    assert response.json() == {"enabled_hashes": []}


def test_post_scare_test_publishes(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/scare/zone-a/test")

    assert response.status_code == 200
    assert ("scare_test", "zone-a") in bridge.calls
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_admin_routes_mirror_scare.py -v`
Expected: FAIL

- [ ] **Step 3: Implementeer `admin/app/routers/mirror.py`**

```python
import json
from fastapi import APIRouter, Request

router = APIRouter()

_DEFAULT_MIRROR_CONFIG = {"effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]}


@router.get("/api/mirror/config")
def get_mirror_config(request: Request):
    row = request.app.state.db.execute(
        "SELECT effect, params, overlay_hash, scale, position FROM mirror_config WHERE id = 1"
    ).fetchone()
    if row is None:
        return _DEFAULT_MIRROR_CONFIG
    return {
        "effect": row[0],
        "params": json.loads(row[1]),
        "overlay_hash": row[2],
        "scale": row[3],
        "position": json.loads(row[4]),
    }


@router.put("/api/mirror/config")
async def put_mirror_config(request: Request):
    config = await request.json()
    db = request.app.state.db
    db.execute(
        """INSERT INTO mirror_config (id, effect, params, overlay_hash, scale, position)
           VALUES (1, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET effect=excluded.effect, params=excluded.params,
             overlay_hash=excluded.overlay_hash, scale=excluded.scale, position=excluded.position""",
        (
            config.get("effect", "xray"),
            json.dumps(config.get("params", {})),
            config.get("overlay_hash"),
            config.get("scale", 1.0),
            json.dumps(config.get("position", [0.5, 0.5])),
        ),
    )
    db.commit()
    request.app.state.bridge.publish_mirror_config(config)
    return {"ok": True}


@router.post("/api/mirror/preview")
async def post_mirror_preview(request: Request):
    config = await request.json()
    request.app.state.bridge.publish_mirror_preview(config)
    return {"ok": True}


@router.post("/api/mirror/test")
def post_mirror_test(request: Request):
    request.app.state.bridge.publish_mirror_test()
    return {"ok": True}
```

- [ ] **Step 4: Implementeer `admin/app/routers/scare.py`**

```python
import json
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/scare/{zone}/config")
def get_scare_config(zone: str, request: Request):
    row = request.app.state.db.execute(
        "SELECT enabled_hashes FROM scare_zone_config WHERE zone = ?", (zone,)
    ).fetchone()
    if row is None:
        return {"enabled_hashes": []}
    return {"enabled_hashes": json.loads(row[0])}


@router.put("/api/scare/{zone}/config")
async def put_scare_config(zone: str, request: Request):
    body = await request.json()
    enabled_hashes = body.get("enabled_hashes", [])
    db = request.app.state.db
    db.execute(
        """INSERT INTO scare_zone_config (zone, enabled_hashes) VALUES (?, ?)
           ON CONFLICT(zone) DO UPDATE SET enabled_hashes=excluded.enabled_hashes""",
        (zone, json.dumps(enabled_hashes)),
    )
    db.commit()
    request.app.state.bridge.publish_scare_config(zone, enabled_hashes)
    return {"ok": True}


@router.post("/api/scare/{zone}/test")
def post_scare_test(zone: str, request: Request):
    request.app.state.bridge.publish_scare_test(zone)
    return {"ok": True}
```

- [ ] **Step 5: Monteer beide routers in `admin/app/main.py`**

Voeg toe: `from admin.app.routers import mirror as mirror_router, scare as scare_router` en `app.include_router(mirror_router.router)`, `app.include_router(scare_router.router)`.

- [ ] **Step 6: Run de tests, verwacht PASS**

Run: `pytest tests/test_admin_routes_mirror_scare.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Run de volledige suite, verwacht PASS**

Run: `pytest tests/ -v`

- [ ] **Step 8: Commit**

```bash
git add admin/app/routers/mirror.py admin/app/routers/scare.py admin/app/main.py tests/test_admin_routes_mirror_scare.py
git commit -m "feat: mirror- en scare-config-routes (opslaan + publiceren + preview + test)"
```

---

### Task 11: Nodes-, schedule- en HA-routes + noodstop

**Files:**
- Create: `admin/app/routers/nodes.py`
- Create: `admin/app/routers/schedule.py`
- Create: `admin/app/routers/ha.py`
- Test: `tests/test_admin_routes_nodes_schedule_ha.py`

**Interfaces:**
- Consumes: `admin.app.mqtt_state.NodeStatusTracker.get_nodes` (Task 3), `admin.app.ha_client.{get_states, call_service}` (Task 5), `admin.app.mqtt_bridge.MqttBridge.publish_sleep` (Task 4)
- Produces (HTTP): `GET /api/nodes`, `GET /api/schedule`, `PUT /api/schedule`, `POST /api/system/emergency-stop` (publiceert `sleep=true`), `POST /api/system/wake` (publiceert `sleep=false`), `GET /api/ha/states`, `POST /api/ha/service`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_admin_routes_nodes_schedule_ha.py`:
```python
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeBridge:
    def __init__(self):
        self.calls = []

    def start(self):
        pass

    def stop(self):
        pass

    def publish_sleep(self, is_sleeping):
        self.calls.append(("sleep", is_sleeping))


def _client(tmp_path, monkeypatch=None):
    settings = Settings(
        admin_password="testwachtwoord",
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="testtoken",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    bridge = FakeBridge()
    app.state.bridge = bridge
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app, bridge


def test_get_nodes_reflects_tracker_state(tmp_path):
    client, app, _ = _client(tmp_path)
    app.state.tracker.handle_message("status/mirror", "online")

    response = client.get("/api/nodes")

    assert response.json()["mirror"]["status"] == "online"


def test_get_and_put_schedule(tmp_path):
    client, app, _ = _client(tmp_path)

    put_response = client.put("/api/schedule", json={"on_time": "19:00", "off_time": "23:00", "enabled": True})
    assert put_response.status_code == 200

    get_response = client.get("/api/schedule")
    assert get_response.json() == {"on_time": "19:00", "off_time": "23:00", "enabled": True}


def test_emergency_stop_publishes_sleep_on(tmp_path):
    client, app, bridge = _client(tmp_path)

    response = client.post("/api/system/emergency-stop")

    assert response.status_code == 200
    assert ("sleep", True) in bridge.calls


def test_wake_publishes_sleep_off(tmp_path):
    client, app, bridge = _client(tmp_path)

    response = client.post("/api/system/wake")

    assert response.status_code == 200
    assert ("sleep", False) in bridge.calls


def test_ha_states_proxies_to_ha_client(tmp_path, monkeypatch):
    client, app, _ = _client(tmp_path)

    def fake_get_states(ha_url, ha_token, fetch=None):
        assert ha_url == "http://localhost:8123"
        assert ha_token == "testtoken"
        return [{"entity_id": "light.wled_voortuin", "state": "on"}]

    monkeypatch.setattr("admin.app.routers.ha.get_states", fake_get_states)

    response = client.get("/api/ha/states")

    assert response.json() == [{"entity_id": "light.wled_voortuin", "state": "on"}]


def test_ha_service_proxies_to_ha_client(tmp_path, monkeypatch):
    client, app, _ = _client(tmp_path)
    calls = []

    def fake_call_service(ha_url, ha_token, domain, service, data, fetch=None):
        calls.append((domain, service, data))

    monkeypatch.setattr("admin.app.routers.ha.call_service", fake_call_service)

    response = client.post("/api/ha/service", json={"domain": "light", "service": "turn_on", "data": {"entity_id": "light.wled_voortuin"}})

    assert response.status_code == 200
    assert calls == [("light", "turn_on", {"entity_id": "light.wled_voortuin"})]
```

- [ ] **Step 2: Run de tests, verwacht FAIL**

Run: `pytest tests/test_admin_routes_nodes_schedule_ha.py -v`
Expected: FAIL

- [ ] **Step 3: Implementeer `admin/app/routers/nodes.py`**

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/nodes")
def get_nodes(request: Request):
    return request.app.state.tracker.get_nodes()


@router.get("/api/logs")
def get_logs(request: Request, node: str | None = None, limit: int = 100):
    return request.app.state.tracker.get_recent_logs(node=node, limit=limit)
```

- [ ] **Step 4: Implementeer `admin/app/routers/schedule.py`**

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/schedule")
def get_schedule(request: Request):
    row = request.app.state.db.execute(
        "SELECT on_time, off_time, enabled FROM schedule WHERE id = 1"
    ).fetchone()
    if row is None:
        return {"on_time": "18:00", "off_time": "22:00", "enabled": True}
    return {"on_time": row[0], "off_time": row[1], "enabled": bool(row[2])}


@router.put("/api/schedule")
async def put_schedule(request: Request):
    body = await request.json()
    db = request.app.state.db
    db.execute(
        """INSERT INTO schedule (id, on_time, off_time, enabled) VALUES (1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET on_time=excluded.on_time, off_time=excluded.off_time, enabled=excluded.enabled""",
        (body.get("on_time", "18:00"), body.get("off_time", "22:00"), int(bool(body.get("enabled", True)))),
    )
    db.commit()
    return {"ok": True}


@router.post("/api/system/emergency-stop")
def emergency_stop(request: Request):
    request.app.state.bridge.publish_sleep(True)
    return {"ok": True}


@router.post("/api/system/wake")
def wake(request: Request):
    request.app.state.bridge.publish_sleep(False)
    return {"ok": True}
```

(Let op: `/api/system/emergency-stop` en `/api/system/wake` staan in dit bestand omdat ze conceptueel bij het tijdvenster/noodstop-domein horen, niet bij `nodes.py`.)

- [ ] **Step 5: Implementeer `admin/app/routers/ha.py`**

```python
from fastapi import APIRouter, Request

from admin.app.ha_client import get_states, call_service

router = APIRouter()


@router.get("/api/ha/states")
def ha_states(request: Request):
    settings = request.app.state.settings
    return get_states(settings.ha_url, settings.ha_token)


@router.post("/api/ha/service")
async def ha_service(request: Request):
    body = await request.json()
    settings = request.app.state.settings
    call_service(settings.ha_url, settings.ha_token, body["domain"], body["service"], body.get("data", {}))
    return {"ok": True}
```

- [ ] **Step 6: Monteer alle drie routers in `admin/app/main.py`**

Voeg toe: `from admin.app.routers import nodes as nodes_router, schedule as schedule_router, ha as ha_router` en de bijbehorende `app.include_router(...)`-regels.

- [ ] **Step 7: Run de tests, verwacht PASS**

Run: `pytest tests/test_admin_routes_nodes_schedule_ha.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Run de volledige suite, verwacht PASS**

Run: `pytest tests/ -v`

- [ ] **Step 9: Commit**

```bash
git add admin/app/routers/nodes.py admin/app/routers/schedule.py admin/app/routers/ha.py admin/app/main.py tests/test_admin_routes_nodes_schedule_ha.py
git commit -m "feat: node-status, tijdvenster, noodstop en HA-proxy-routes"
```

---

### Task 12: WebSocket-route + koppeling met de MQTT-bridge

**Files:**
- Create: `admin/app/routers/ws.py`
- Modify: `admin/app/main.py` (volledige vervanging — monteert de WebSocket-router en geeft de actieve event loop aan de bridge)

**Interfaces:**
- Consumes: `admin.app.websocket_hub.WebSocketHub` (Task 7), `admin.app.mqtt_bridge.MqttBridge`'s `ws_hub`/`loop`-parameters (al aanwezig sinds Task 4, hier voor het eerst daadwerkelijk gebruikt)
- Produces (HTTP): `WebSocket /api/ws` — stuurt elk binnenkomend status/log-bericht door als JSON

Glue-code (WebSocket-verbinding + achtergrond-koppeling met MQTT) — geen geautomatiseerde test voor de WebSocket-route zelf (vereist een lopende event loop + echte verbinding, niet zinvol te unit-testen); de onderliggende `WebSocketHub`-logica is al in Task 7 getest.

**Bekende, geaccepteerde beperking:** FastAPI's `@app.middleware("http")` (de auth-check uit Task 8) geldt alleen voor gewone HTTP-requests, niet voor WebSocket-verbindingen — `/api/ws` blijft dus zonder sessie-auth, net als het MJPEG-live-preview-endpoint van de mirror-node (plan 1) al zonder auth is. Zelfde risicoklasse (live statusfeed, geen besturingsactie), dus bewust niet apart dichtgetimmerd in dit plan.

- [ ] **Step 1: Implementeer `admin/app/routers/ws.py`**

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    hub = websocket.app.state.ws_hub
    hub.register(websocket)
    try:
        while True:
            await websocket.receive_text()  # we verwachten niets van de client, houdt de verbinding open
    except WebSocketDisconnect:
        hub.unregister(websocket)
```

- [ ] **Step 2: Vervang `admin/app/main.py` volledig door onderstaande inhoud**

Dit is het bestand zoals het na Task 11 hoort te zijn (alle routers t/m `ha_router` gemonteerd, dezelfde middleware) plus de `ws_router` en de event-loop-koppeling:

```python
import asyncio

from fastapi import FastAPI, Request
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
from admin.app.routers import ws as ws_router


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
    app.state.ws_hub = WebSocketHub()
    app.state.bridge = MqttBridge(settings, app.state.tracker, ws_hub=app.state.ws_hub)
    app.state.scheduler = Scheduler(app.state.bridge, _get_schedule_from_db(app.state.db))

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        public_paths = ("/api/login", "/docs", "/openapi.json")
        if request.url.path.startswith("/api/media/") and request.method == "GET":
            return await call_next(request)  # media-download is publiek, geen auth
        if any(request.url.path.startswith(p) for p in public_paths):
            return await call_next(request)
        if not request.url.path.startswith("/api/"):
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
    app.include_router(ws_router.router)

    @app.on_event("startup")
    def _startup():
        # De event loop bestaat pas als uvicorn al gestart is, dus de bridge
        # krijgt hem hier pas (niet in create_app) — bekende FastAPI-volgorde,
        # geen ontwerpfout.
        app.state.bridge._loop = asyncio.get_event_loop()
        app.state.bridge.start()
        app.state.scheduler.start()

    @app.on_event("shutdown")
    def _shutdown():
        app.state.scheduler.stop()
        app.state.bridge.stop()

    return app
```

- [ ] **Step 3: Syntax-/importcontrole + volledige suite**

Run: `python3 -c "import ast; ast.parse(open('admin/app/routers/ws.py').read())"` en hetzelfde voor het vervangen `admin/app/main.py`.
Run: `pytest tests/ -v` — verwacht PASS, geen regressies (deze taak voegt geen nieuwe geautomatiseerde tests toe).

Handmatige verificatie (vereist een lopende broker, later op locatie): start de backend (`python3 -m admin.run`), verbind met een WebSocket-client naar `ws://localhost:8000/api/ws`, publiceer handmatig een `status/mirror`-bericht op de broker, controleer dat het bericht binnenkomt op de WebSocket.

- [ ] **Step 4: Commit**

```bash
git add admin/app/routers/ws.py admin/app/main.py
git commit -m "feat: WebSocket-endpoint voor live status/logs, gekoppeld aan de MQTT-brug"
```

---

## Na dit plan

De backend-API ligt nu vast in werkende, geteste code: auth, media-CRUD (incl. het door de nodes gebruikte publieke download-endpoint), mirror/scare-config met live MQTT-publicatie, node-status, tijdvenster, noodstop, en een HA-proxy voor WLED. Plan 3 (frontend) bouwt hier rechtstreeks op — de exacte JSON-vormen van elke route staan vast in de router-tests in dit plan.
