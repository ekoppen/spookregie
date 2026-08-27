# Beheerpagina — Instellingen-pagina (runtime-config) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MQTT-, Home Assistant- en mirror-stream-instellingen worden beheerbaar vanuit de beheerpagina zelf (nieuwe "Instellingen"-pagina), met directe toepassing — geen servicerestart of frontend-rebuild meer nodig om tegen een echte spiegel-node te testen.

**Architecture:** Nieuwe `app_settings`-tabel in de bestaande SQLite-db (`admin.db`), zelfde lazy-default patroon als `mirror_config`/`schedule` (geen rij = env-var-afgeleide defaults, pas een echte rij na de eerste keer opslaan). Nieuwe `/api/settings`-router. `MqttBridge` krijgt een `reconfigure()`-methode zodat een opgeslagen wijziging de lopende broker-verbinding meteen vervangt. Frontend krijgt een nieuwe pagina + route die het formulier toont en `MirrorPage` haalt zijn stream-URL voortaan hiervandaan i.p.v. uit een build-time env var.

**Tech Stack:** FastAPI + sqlite3 (backend, ongewijzigd), React + TypeScript + Vite (frontend, ongewijzigd), pytest (backend-tests), TypeScript-compiler-check (frontend, geen nieuwe E2E-suite).

**Spec:** `docs/superpowers/specs/2026-08-27-beheerpagina-instellingen-design.md`

## Global Constraints

- Geen UI voor `ADMIN_PASSWORD`, `ADMIN_PORT`, `ADMIN_DB_PATH`, `ADMIN_MEDIA_DIR`, `LOG_DIR` — die blijven env-var.
- `mqtt_pass`/`ha_token` komen nooit in platte tekst terug in een `GET`-response; leeg/afwezig bij een `PUT` betekent "laat ongewijzigd".
- Geen "test verbinding"-knop of synchrone connectiviteitscheck bij opslaan.
- Geen encryptie van secrets in de database (zelfde trust-niveau als de huidige env vars).
- Bestaande codepatronen volgen: singleton-rij-tabel + lazy default (zoals `mirror_config`/`schedule`), `FakeBridge`-teststijl, Nederlandse foutmeldingen.

---

## Task 1: Runtime-settings — database + module

**Files:**
- Modify: `admin/app/db.py`
- Create: `admin/app/runtime_settings.py`
- Test: `tests/test_admin_runtime_settings.py`

**Interfaces:**
- Produces: `RuntimeSettings` (dataclass: `mqtt_host: str`, `mqtt_port: int`, `mqtt_user: str`, `mqtt_pass: str`, `ha_url: str`, `ha_token: str`, `mirror_stream_url: str`), `read_runtime_settings(conn) -> RuntimeSettings`, `write_runtime_settings(conn, **updates) -> RuntimeSettings`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_runtime_settings.py`:

```python
from admin.app.db import init_db
from admin.app.runtime_settings import read_runtime_settings, write_runtime_settings


def test_read_without_row_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "env-broker")
    monkeypatch.setenv("MQTT_PORT", "1899")
    monkeypatch.delenv("MQTT_USER", raising=False)
    conn = init_db(str(tmp_path / "test.db"))

    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "env-broker"
    assert settings.mqtt_port == 1899
    assert settings.mqtt_user == ""
    assert settings.mirror_stream_url == ""


def test_read_without_row_uses_sane_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("MQTT_PORT", raising=False)
    conn = init_db(str(tmp_path / "test.db"))

    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "homeassistant.local"
    assert settings.mqtt_port == 1883
    assert settings.ha_url == "http://homeassistant.local:8123"


def test_write_then_read_roundtrip(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    write_runtime_settings(conn, mqtt_host="pi-broker", mqtt_port=1884)
    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "pi-broker"
    assert settings.mqtt_port == 1884


def test_write_only_updates_given_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("HA_URL", "http://ha.local:8123")
    conn = init_db(str(tmp_path / "test.db"))
    write_runtime_settings(conn, mqtt_host="pi-broker")

    write_runtime_settings(conn, mqtt_user="operator")
    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "pi-broker"
    assert settings.mqtt_user == "operator"
    assert settings.ha_url == "http://ha.local:8123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_admin_runtime_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'admin.app.runtime_settings'`

- [ ] **Step 3: Add the `app_settings` table to `db.py`**

In `admin/app/db.py`, add this table (same style as `mirror_config`/`schedule`) right before the final `conn.commit()`:

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mqtt_host TEXT NOT NULL,
            mqtt_port INTEGER NOT NULL,
            mqtt_user TEXT NOT NULL DEFAULT '',
            mqtt_pass TEXT NOT NULL DEFAULT '',
            ha_url TEXT NOT NULL,
            ha_token TEXT NOT NULL DEFAULT '',
            mirror_stream_url TEXT NOT NULL DEFAULT ''
        )"""
    )
```

- [ ] **Step 4: Create `admin/app/runtime_settings.py`**

```python
import os
from dataclasses import asdict, dataclass


@dataclass
class RuntimeSettings:
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_pass: str
    ha_url: str
    ha_token: str
    mirror_stream_url: str


def _env_defaults() -> RuntimeSettings:
    """Zelfde variabelenamen/defaults als config.get_settings() vroeger
    gebruikte voor deze velden -- alleen gelezen zolang er nog geen
    app_settings-rij is (eerste-opstart-seed van een bestaande deploy)."""
    return RuntimeSettings(
        mqtt_host=os.environ.get("MQTT_HOST", "homeassistant.local"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_pass=os.environ.get("MQTT_PASS", ""),
        ha_url=os.environ.get("HA_URL", "http://homeassistant.local:8123"),
        ha_token=os.environ.get("HA_TOKEN", ""),
        mirror_stream_url="",
    )


def read_runtime_settings(conn) -> RuntimeSettings:
    row = conn.execute(
        "SELECT mqtt_host, mqtt_port, mqtt_user, mqtt_pass, ha_url, ha_token, mirror_stream_url "
        "FROM app_settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return _env_defaults()
    return RuntimeSettings(*row)


def write_runtime_settings(conn, **updates) -> RuntimeSettings:
    """Overschrijft alleen de meegegeven velden t.o.v. de huidige effectieve
    waarden (DB-rij, of env-defaults als er nog geen rij is) en persisteert
    de volledige rij -- zelfde aanpak als put_mirror_config."""
    current = read_runtime_settings(conn)
    result = RuntimeSettings(**{**asdict(current), **updates})
    conn.execute(
        """INSERT INTO app_settings
               (id, mqtt_host, mqtt_port, mqtt_user, mqtt_pass, ha_url, ha_token, mirror_stream_url)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               mqtt_host=excluded.mqtt_host, mqtt_port=excluded.mqtt_port,
               mqtt_user=excluded.mqtt_user, mqtt_pass=excluded.mqtt_pass,
               ha_url=excluded.ha_url, ha_token=excluded.ha_token,
               mirror_stream_url=excluded.mirror_stream_url""",
        (
            result.mqtt_host, result.mqtt_port, result.mqtt_user, result.mqtt_pass,
            result.ha_url, result.ha_token, result.mirror_stream_url,
        ),
    )
    conn.commit()
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_runtime_settings.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add admin/app/db.py admin/app/runtime_settings.py tests/test_admin_runtime_settings.py
git commit -m "feat: app_settings-tabel en runtime-settings-module"
```

---

## Task 2: Trim boot-time `Settings`, wire `runtime_settings` into the app

**Files:**
- Modify: `admin/app/config.py`
- Modify: `admin/app/main.py`
- Modify: `admin/app/routers/ha.py`
- Modify: `tests/test_admin_config.py`
- Modify: `tests/test_admin_routes_auth.py`
- Modify: `tests/test_admin_routes_mirror_scare.py`
- Modify: `tests/test_admin_routes_media.py`
- Modify: `tests/test_admin_routes_nodes_schedule_ha.py`

**Interfaces:**
- Consumes: `RuntimeSettings`, `read_runtime_settings(conn)` from Task 1.
- Produces: `app.state.runtime_settings` (a `RuntimeSettings` instance, refreshed by Task 4's `PUT /api/settings` and consumed by Task 3's `MqttBridge`).

- [ ] **Step 1: Trim `Settings` in `admin/app/config.py`**

Replace the whole file with:

```python
import os
from dataclasses import dataclass


@dataclass
class Settings:
    admin_password: str
    db_path: str
    media_dir: str
    port: int
    # Zelfde LOG_DIR-conventie als de nodes; default achteraan zodat bestaande
    # aanroepen zonder log_dir blijven werken.
    log_dir: str = "./logs"


def get_settings():
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        raise RuntimeError(
            "ADMIN_PASSWORD moet ingesteld zijn (geen standaardwaarde om veiligheidsredenen)"
        )
    return Settings(
        admin_password=admin_password,
        db_path=os.environ.get("ADMIN_DB_PATH", "./admin.db"),
        media_dir=os.environ.get("ADMIN_MEDIA_DIR", "./media_store"),
        port=int(os.environ.get("ADMIN_PORT", "8000")),
        log_dir=os.environ.get("LOG_DIR", "./logs"),
    )
```

(MQTT/HA-velden zijn verhuisd naar `runtime_settings.py` uit Task 1 — `get_settings()` leest ze niet meer.)

- [ ] **Step 2: Update `tests/test_admin_config.py`**

Replace the whole file with:

```python
import pytest
from admin.app.config import get_settings


def test_get_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "geheim123")

    settings = get_settings()

    assert settings.admin_password == "geheim123"


def test_get_settings_has_sane_defaults(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "iets")

    settings = get_settings()

    assert settings.port == 8000


def test_get_settings_raises_without_admin_password(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with pytest.raises(RuntimeError):
        get_settings()
```

(De mqtt_host/mqtt_port-assertions zijn verhuisd naar `tests/test_admin_runtime_settings.py` in Task 1.)

- [ ] **Step 3: Drop the mqtt/ha kwargs from `Settings(...)` in the four route test files**

In each of `tests/test_admin_routes_auth.py`, `tests/test_admin_routes_mirror_scare.py`, `tests/test_admin_routes_media.py`, `tests/test_admin_routes_nodes_schedule_ha.py`, find:

```python
        admin_password="testwachtwoord",
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
```

(in `test_admin_routes_nodes_schedule_ha.py` `ha_token` is `"testtoken"` instead of `""`) and replace with:

```python
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
```

in all four files.

`test_admin_routes_nodes_schedule_ha.py`'s `test_ha_states_proxies_to_ha_client` asserts specific `ha_url`/`ha_token` values inside `fake_get_states` (`"http://localhost:8123"` / `"testtoken"`). Those used to come from the `Settings(...)` object built in `_client()`; now `routers/ha.py` reads `app.state.runtime_settings` instead (Step 5 below), which `_client()` no longer populates with those values. Add the import and set it explicitly in that one test:

Add near the top of `test_admin_routes_nodes_schedule_ha.py`:

```python
from admin.app.runtime_settings import RuntimeSettings
```

In `test_ha_states_proxies_to_ha_client`, right after `client, app, _ = _client(tmp_path)`, add:

```python
    app.state.runtime_settings = RuntimeSettings(
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="testtoken", mirror_stream_url="",
    )
```

(`test_ha_service_proxies_to_ha_client` doesn't assert on `ha_url`/`ha_token` values, so it needs no change.)

- [ ] **Step 4: Wire `app.state.runtime_settings` into `admin/app/main.py`**

Add the import near the other `admin.app` imports:

```python
from admin.app.runtime_settings import read_runtime_settings
```

In `create_app`, right after `app.state.db = init_db(settings.db_path)`, add:

```python
    app.state.runtime_settings = read_runtime_settings(app.state.db)
```

Change the `MqttBridge(...)` construction from:

```python
    app.state.bridge = MqttBridge(
        settings, app.state.tracker, ws_hub=app.state.ws_hub, logger=app.state.logger
    )
```

to:

```python
    app.state.bridge = MqttBridge(
        app.state.runtime_settings, app.state.tracker, ws_hub=app.state.ws_hub, logger=app.state.logger
    )
```

- [ ] **Step 5: Point `admin/app/routers/ha.py` at `runtime_settings`**

Replace both occurrences of `settings = request.app.state.settings` with `settings = request.app.state.runtime_settings` (one in `ha_states`, one in `ha_service`).

- [ ] **Step 6: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests PASS (Task 3/4's router and bridge changes don't exist yet, but nothing currently in the tree should reference the removed `Settings` fields anymore).

- [ ] **Step 7: Commit**

```bash
git add admin/app/config.py admin/app/main.py admin/app/routers/ha.py tests/test_admin_config.py tests/test_admin_routes_auth.py tests/test_admin_routes_mirror_scare.py tests/test_admin_routes_media.py tests/test_admin_routes_nodes_schedule_ha.py
git commit -m "refactor: MQTT/HA-config verhuist van Settings naar runtime_settings"
```

---

## Task 3: `MqttBridge.reconfigure`

**Files:**
- Modify: `admin/app/mqtt_bridge.py`
- Test: `tests/test_admin_mqtt_bridge.py`

**Interfaces:**
- Consumes: `RuntimeSettings` from Task 1.
- Produces: `MqttBridge(runtime_settings, tracker, ws_hub=None, loop=None, logger=None)` (constructor now takes a `RuntimeSettings`), `MqttBridge.reconfigure(runtime_settings) -> None` (used by Task 4's `PUT /api/settings`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_mqtt_bridge.py`:

```python
import admin.app.mqtt_bridge as mqtt_bridge_module
from admin.app.mqtt_bridge import MqttBridge
from admin.app.runtime_settings import RuntimeSettings


class FakeMqttClient:
    instances = []

    def __init__(self, client_id=None):
        self.client_id = client_id
        self.username = None
        self.password = None
        self.connected_to = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        FakeMqttClient.instances.append(self)

    def username_pw_set(self, username, password):
        self.username = username
        self.password = password

    def reconnect_delay_set(self, min_delay=1, max_delay=30):
        pass

    def connect_async(self, host, port):
        self.connected_to = (host, port)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True


def _settings(**overrides):
    base = dict(
        mqtt_host="broker-a", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="", mirror_stream_url="",
    )
    base.update(overrides)
    return RuntimeSettings(**base)


def test_start_connects_with_configured_host_and_port(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_host="broker-a", mqtt_port=1883), tracker=object())
    bridge.start()

    assert bridge._client.connected_to == ("broker-a", 1883)


def test_reconfigure_disconnects_old_client_and_connects_new_one(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(), tracker=object())
    bridge.start()
    old_client = bridge._client

    bridge.reconfigure(_settings(mqtt_host="broker-b", mqtt_port=1884, mqtt_user="op", mqtt_pass="geheim"))

    assert old_client.loop_stopped is True
    assert old_client.disconnected is True
    new_client = bridge._client
    assert new_client is not old_client
    assert new_client.connected_to == ("broker-b", 1884)
    assert new_client.username == "op"
    assert new_client.password == "geheim"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_admin_mqtt_bridge.py -v`
Expected: FAIL — `MqttBridge` has no `reconfigure` method (`AttributeError`)

- [ ] **Step 3: Add `reconfigure` and a shared `_build_client` helper to `admin/app/mqtt_bridge.py`**

Replace the `__init__` method:

```python
    def __init__(self, settings, tracker, ws_hub=None, loop=None, logger=None):
        self._settings = settings
        self._tracker = tracker
        self._ws_hub = ws_hub
        self._loop = loop
        self._logger = logger
        self._client = self._build_client(settings)
```

Add a new method right after `__init__` (before `_log`):

```python
    def _build_client(self, settings):
        client = mqtt.Client(client_id="beheerpagina-backend")
        if settings.mqtt_user:
            client.username_pw_set(settings.mqtt_user, settings.mqtt_pass)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        return client
```

Add `reconfigure` right after `stop`:

```python
    def reconfigure(self, settings):
        """Herverbindt met nieuwe broker-instellingen zonder het hele proces
        te herstarten -- aangeroepen na een succesvolle PUT /api/settings."""
        self._settings = settings
        self._client.loop_stop()
        self._client.disconnect()
        self._client = self._build_client(settings)
        self.start()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_mqtt_bridge.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add admin/app/mqtt_bridge.py tests/test_admin_mqtt_bridge.py
git commit -m "feat: MqttBridge.reconfigure voor live herverbinden na instellingenwijziging"
```

---

## Task 4: `/api/settings` router

**Files:**
- Create: `admin/app/routers/settings.py`
- Modify: `admin/app/main.py`
- Test: `tests/test_admin_routes_settings.py`

**Interfaces:**
- Consumes: `read_runtime_settings`, `write_runtime_settings` (Task 1), `app.state.bridge.reconfigure` (Task 3).
- Produces: `GET /api/settings`, `PUT /api/settings` — consumed by the frontend in Task 5/6.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_routes_settings.py`:

```python
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeBridge:
    def __init__(self):
        self.reconfigured_with = None

    def start(self):
        pass

    def stop(self):
        pass

    def reconfigure(self, runtime_settings):
        self.reconfigured_with = runtime_settings


def _client(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    bridge = FakeBridge()
    app.state.bridge = bridge
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app, bridge


def test_get_settings_never_returns_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "seed-broker")
    client, app, _ = _client(tmp_path)

    response = client.get("/api/settings")

    body = response.json()
    assert body["mqtt_host"] == "seed-broker"
    assert "mqtt_pass" not in body
    assert "ha_token" not in body
    assert body["mqtt_pass_set"] is False
    assert body["ha_token_set"] is False


def test_put_settings_persists_and_reconfigures_bridge(tmp_path):
    client, app, bridge = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1884, "mqtt_user": "operator",
        "mqtt_pass": "geheim", "ha_url": "http://ha.local:8123",
        "ha_token": "token123", "mirror_stream_url": "http://mirror.local:8091/stream",
    })

    assert response.status_code == 200
    assert bridge.reconfigured_with.mqtt_host == "pi-broker"
    assert bridge.reconfigured_with.mqtt_pass == "geheim"

    get_response = client.get("/api/settings")
    body = get_response.json()
    assert body["mqtt_host"] == "pi-broker"
    assert body["mirror_stream_url"] == "http://mirror.local:8091/stream"
    assert body["mqtt_pass_set"] is True
    assert body["ha_token_set"] is True


def test_put_settings_blank_secret_keeps_existing_value(tmp_path):
    client, app, bridge = _client(tmp_path)
    client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_user": "",
        "mqtt_pass": "geheim", "ha_url": "", "ha_token": "", "mirror_stream_url": "",
    })

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_user": "",
        "mqtt_pass": "", "ha_url": "", "ha_token": "", "mirror_stream_url": "",
    })

    assert response.status_code == 200
    assert bridge.reconfigured_with.mqtt_pass == "geheim"


def test_put_settings_rejects_invalid_port(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={"mqtt_host": "pi-broker", "mqtt_port": 99999})

    assert response.status_code == 400


def test_put_settings_rejects_missing_host(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={"mqtt_host": "", "mqtt_port": 1883})

    assert response.status_code == 400


def test_put_settings_rejects_malformed_url(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "ha_url": "not-a-url",
    })

    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_settings.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Create `admin/app/routers/settings.py`**

```python
from fastapi import APIRouter, HTTPException, Request

from admin.app.runtime_settings import read_runtime_settings, write_runtime_settings

router = APIRouter()


def _validate_url(value, field_name):
    if value and not (value.startswith("http://") or value.startswith("https://")):
        raise HTTPException(status_code=400, detail=f"{field_name} moet leeg zijn of met http(s):// beginnen")


@router.get("/api/settings")
def get_settings_route(request: Request):
    settings = read_runtime_settings(request.app.state.db)
    return {
        "mqtt_host": settings.mqtt_host,
        "mqtt_port": settings.mqtt_port,
        "mqtt_user": settings.mqtt_user,
        "ha_url": settings.ha_url,
        "mirror_stream_url": settings.mirror_stream_url,
        "mqtt_pass_set": bool(settings.mqtt_pass),
        "ha_token_set": bool(settings.ha_token),
    }


@router.put("/api/settings")
async def put_settings_route(request: Request):
    body = await request.json()

    mqtt_host = str(body.get("mqtt_host", "")).strip()
    if not mqtt_host:
        raise HTTPException(status_code=400, detail="mqtt_host mag niet leeg zijn")

    try:
        mqtt_port = int(body.get("mqtt_port"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="mqtt_port moet een getal zijn")
    if not (1 <= mqtt_port <= 65535):
        raise HTTPException(status_code=400, detail="mqtt_port moet tussen 1 en 65535 liggen")

    ha_url = str(body.get("ha_url", "")).strip()
    mirror_stream_url = str(body.get("mirror_stream_url", "")).strip()
    _validate_url(ha_url, "ha_url")
    _validate_url(mirror_stream_url, "mirror_stream_url")

    updates = {
        "mqtt_host": mqtt_host,
        "mqtt_port": mqtt_port,
        "mqtt_user": str(body.get("mqtt_user", "")),
        "ha_url": ha_url,
        "mirror_stream_url": mirror_stream_url,
    }
    mqtt_pass = body.get("mqtt_pass")
    if mqtt_pass:
        updates["mqtt_pass"] = mqtt_pass
    ha_token = body.get("ha_token")
    if ha_token:
        updates["ha_token"] = ha_token

    db = request.app.state.db
    new_settings = write_runtime_settings(db, **updates)
    request.app.state.runtime_settings = new_settings
    request.app.state.bridge.reconfigure(new_settings)

    return {"ok": True}
```

- [ ] **Step 4: Wire the router into `admin/app/main.py`**

Add the import next to the other router imports:

```python
from admin.app.routers import settings as settings_router
```

Add the include next to the other `app.include_router(...)` calls:

```python
    app.include_router(settings_router.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_settings.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add admin/app/routers/settings.py admin/app/main.py tests/test_admin_routes_settings.py
git commit -m "feat: /api/settings endpoint (GET/PUT) voor MQTT/HA/mirror-stream-config"
```

---

## Task 5: Frontend — Instellingen-pagina

**Files:**
- Modify: `admin/frontend/src/types.ts`
- Create: `admin/frontend/src/api/settings.ts`
- Create: `admin/frontend/src/pages/SettingsPage.tsx`
- Create: `admin/frontend/src/pages/SettingsPage.css`
- Modify: `admin/frontend/src/components/Layout.tsx`
- Modify: `admin/frontend/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/settings`, `PUT /api/settings` (Task 4).
- Produces: `AppSettings`, `AppSettingsUpdate` types and `getSettings()`/`putSettings()` functions — reused by Task 6's `MirrorPage`.

- [ ] **Step 1: Add types to `admin/frontend/src/types.ts`**

Append at the end of the file:

```ts
export interface AppSettings {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  ha_url: string;
  mirror_stream_url: string;
  mqtt_pass_set: boolean;
  ha_token_set: boolean;
}

export interface AppSettingsUpdate {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  mqtt_pass?: string;
  ha_url: string;
  ha_token?: string;
  mirror_stream_url: string;
}
```

- [ ] **Step 2: Create `admin/frontend/src/api/settings.ts`**

```ts
import { apiFetch } from "./client";
import type { AppSettings, AppSettingsUpdate } from "../types";

export function getSettings(): Promise<AppSettings> {
  return apiFetch<AppSettings>("/api/settings");
}

export function putSettings(update: AppSettingsUpdate): Promise<void> {
  return apiFetch("/api/settings", {
    method: "PUT",
    body: JSON.stringify(update),
  });
}
```

- [ ] **Step 3: Create `admin/frontend/src/pages/SettingsPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { getSettings, putSettings } from "../api/settings";
import type { AppSettings } from "../types";
import "./SettingsPage.css";

interface FormState {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  mqtt_pass: string;
  ha_url: string;
  ha_token: string;
  mirror_stream_url: string;
}

const EMPTY_FORM: FormState = {
  mqtt_host: "",
  mqtt_port: 1883,
  mqtt_user: "",
  mqtt_pass: "",
  ha_url: "",
  ha_token: "",
  mirror_stream_url: "",
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSettings()
      .then((result) => {
        setSettings(result);
        setForm({
          mqtt_host: result.mqtt_host,
          mqtt_port: result.mqtt_port,
          mqtt_user: result.mqtt_user,
          mqtt_pass: "",
          ha_url: result.ha_url,
          ha_token: "",
          mirror_stream_url: result.mirror_stream_url,
        });
        setError(null);
      })
      .catch(() => setError("Instellingen konden niet worden geladen."));
  }, []);

  function update(patch: Partial<FormState>) {
    setForm((prev) => ({ ...prev, ...patch }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await putSettings({
        mqtt_host: form.mqtt_host,
        mqtt_port: form.mqtt_port,
        mqtt_user: form.mqtt_user,
        ...(form.mqtt_pass ? { mqtt_pass: form.mqtt_pass } : {}),
        ha_url: form.ha_url,
        ...(form.ha_token ? { ha_token: form.ha_token } : {}),
        mirror_stream_url: form.mirror_stream_url,
      });
      const refreshed = await getSettings();
      setSettings(refreshed);
      setForm((prev) => ({ ...prev, mqtt_pass: "", ha_token: "" }));
      setError(null);
      setNotice("Instellingen opgeslagen.");
      window.setTimeout(() => setNotice(null), 3000);
    } catch {
      setError("Opslaan is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="settings-page">
      <header className="settings-header">
        <p className="settings-eyebrow">
          <span className="settings-eyebrow__led" aria-hidden="true" />
          Systeem
        </p>
        <h1 className="settings-heading">Instellingen</h1>
      </header>

      {error && (
        <p className="settings-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="settings-notice" role="status">
          {notice}
        </p>
      )}

      {!settings ? (
        <p className="settings-loading">Laden…</p>
      ) : (
        <>
          <section className="settings-panel">
            <p className="settings-panel__eyebrow">MQTT-broker</p>
            <div className="settings-grid">
              <label className="settings-field">
                <span className="settings-field__label">Host</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.mqtt_host}
                  onChange={(e) => update({ mqtt_host: e.target.value })}
                />
              </label>
              <label className="settings-field">
                <span className="settings-field__label">Poort</span>
                <input
                  className="settings-field__input"
                  type="number"
                  value={form.mqtt_port}
                  onChange={(e) => update({ mqtt_port: parseInt(e.target.value, 10) || 0 })}
                />
              </label>
              <label className="settings-field">
                <span className="settings-field__label">Gebruikersnaam</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.mqtt_user}
                  onChange={(e) => update({ mqtt_user: e.target.value })}
                />
              </label>
              <label className="settings-field">
                <span className="settings-field__label">Wachtwoord</span>
                <input
                  className="settings-field__input"
                  type="password"
                  value={form.mqtt_pass}
                  placeholder={
                    settings.mqtt_pass_set ? "•••• (ingesteld, laat leeg om te behouden)" : "niet ingesteld"
                  }
                  onChange={(e) => update({ mqtt_pass: e.target.value })}
                />
              </label>
            </div>
          </section>

          <section className="settings-panel">
            <p className="settings-panel__eyebrow">Home Assistant</p>
            <div className="settings-grid">
              <label className="settings-field settings-field--wide">
                <span className="settings-field__label">URL</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.ha_url}
                  placeholder="http://homeassistant.local:8123"
                  onChange={(e) => update({ ha_url: e.target.value })}
                />
              </label>
              <label className="settings-field settings-field--wide">
                <span className="settings-field__label">Token</span>
                <input
                  className="settings-field__input"
                  type="password"
                  value={form.ha_token}
                  placeholder={
                    settings.ha_token_set ? "•••• (ingesteld, laat leeg om te behouden)" : "niet ingesteld"
                  }
                  onChange={(e) => update({ ha_token: e.target.value })}
                />
              </label>
            </div>
          </section>

          <section className="settings-panel">
            <p className="settings-panel__eyebrow">Spiegel-node</p>
            <div className="settings-grid">
              <label className="settings-field settings-field--wide">
                <span className="settings-field__label">Live-preview-stream-URL</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.mirror_stream_url}
                  placeholder="http://mirror-node.local:8091/stream"
                  onChange={(e) => update({ mirror_stream_url: e.target.value })}
                />
              </label>
            </div>
          </section>

          <div className="settings-actions">
            <button className="settings-save" type="button" onClick={handleSave} disabled={saving}>
              {saving ? "Bezig…" : "Opslaan"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create `admin/frontend/src/pages/SettingsPage.css`**

```css
.settings-page {
  --void: #0b0b0f;
  --panel: #16151c;
  --panel-edge: #2a2733;
  --ember: #ff6a1f;
  --ember-dim: #c94f12;
  --signal: #ffb84d;
  --bone: #e8e3d8;
  --ash: #8b8794;
  --alarm: #ff5c5c;

  min-height: 100vh;
  padding: 2rem 1.5rem 3rem;
  max-width: 960px;
  margin: 0 auto;
  background:
    radial-gradient(ellipse 60% 35% at 50% 0%, rgba(255, 106, 31, 0.06), transparent 70%),
    var(--void);
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: var(--bone);
}

.settings-header {
  margin-bottom: 1.75rem;
}

.settings-eyebrow {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.5rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ash);
}

.settings-eyebrow__led {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--signal);
  box-shadow: 0 0 6px 1px rgba(255, 184, 77, 0.7);
}

.settings-heading {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--bone);
}

.settings-loading {
  color: var(--ash);
}

.settings-error {
  margin: 0 0 1.5rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 92, 92, 0.08);
  border: 1px solid var(--alarm);
  border-radius: 6px;
  font-size: 0.85rem;
  color: var(--alarm);
}

.settings-notice {
  margin: 0 0 1.5rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 184, 77, 0.08);
  border: 1px solid var(--signal);
  border-radius: 6px;
  font-size: 0.85rem;
  color: var(--signal);
}

.settings-panel {
  margin-bottom: 1.5rem;
  padding: 1.25rem;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 10px;
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.03) inset,
    0 12px 40px rgba(0, 0, 0, 0.4);
}

.settings-panel__eyebrow {
  margin: 0 0 1rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ash);
}

.settings-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 1.25rem;
}

.settings-field {
  display: block;
  flex: 0 0 auto;
}

.settings-field--wide {
  flex: 1 1 320px;
}

.settings-field__label {
  display: block;
  margin-bottom: 0.4rem;
  font-size: 0.75rem;
  letter-spacing: 0.04em;
  color: var(--ash);
}

.settings-field__input {
  width: 100%;
  min-width: 10rem;
  padding: 0.6rem 0.7rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 6px;
  color: var(--bone);
  font-size: 0.9rem;
  color-scheme: dark;
}

.settings-field__input:focus {
  outline: 2px solid var(--ember);
  outline-offset: 2px;
  border-color: var(--ember-dim);
}

.settings-actions {
  display: flex;
  gap: 1rem;
}

.settings-save {
  padding: 0.75rem 1.5rem;
  background: var(--ember);
  border: none;
  border-radius: 6px;
  color: var(--void);
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.settings-save:hover:not(:disabled) {
  background: var(--ember-dim);
}

.settings-save:focus-visible {
  outline: 2px solid var(--bone);
  outline-offset: 2px;
}

.settings-save:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 5: Add the nav link in `admin/frontend/src/components/Layout.tsx`**

Change the `links` array from:

```ts
const links = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/mirror", label: "Mirror", end: false },
  { to: "/scare", label: "Scare", end: false },
  { to: "/ha", label: "Home Assistant", end: false },
  { to: "/logs", label: "Logs", end: false },
];
```

to:

```ts
const links = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/mirror", label: "Mirror", end: false },
  { to: "/scare", label: "Scare", end: false },
  { to: "/ha", label: "Home Assistant", end: false },
  { to: "/logs", label: "Logs", end: false },
  { to: "/settings", label: "Instellingen", end: false },
];
```

- [ ] **Step 6: Add the route in `admin/frontend/src/App.tsx`**

Add the import:

```tsx
import SettingsPage from "./pages/SettingsPage";
```

Add the route, right after the `/logs` route:

```tsx
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
```

- [ ] **Step 7: Type-check and build the frontend**

Run: `cd admin/frontend && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add admin/frontend/src/types.ts admin/frontend/src/api/settings.ts admin/frontend/src/pages/SettingsPage.tsx admin/frontend/src/pages/SettingsPage.css admin/frontend/src/components/Layout.tsx admin/frontend/src/App.tsx
git commit -m "feat: Instellingen-pagina (MQTT/HA/mirror-stream)"
```

---

## Task 6: `MirrorPage` reads the stream URL from `/api/settings`

**Files:**
- Modify: `admin/frontend/src/pages/MirrorPage.tsx`

**Interfaces:**
- Consumes: `getSettings()` from Task 5.

- [ ] **Step 1: Remove the build-time env var and fetch the stream URL at runtime**

In `admin/frontend/src/pages/MirrorPage.tsx`, remove this line:

```ts
const STREAM_URL = import.meta.env.VITE_MIRROR_STREAM_URL ?? "";
```

Add the import:

```ts
import { getSettings } from "../api/settings";
```

Add a new piece of state right after the existing `useState` calls:

```ts
  const [streamUrl, setStreamUrl] = useState("");
```

In the existing `useEffect` that loads the mirror config, add a settings fetch alongside it:

```tsx
  useEffect(() => {
    getMirrorConfig()
      .then((result) => {
        setConfig(result);
        setError(null);
      })
      .catch(() => setError("Spiegelconfiguratie kon niet worden geladen."));
    getSettings()
      .then((result) => setStreamUrl(result.mirror_stream_url))
      .catch(() => {
        /* live preview blijft dan gewoon "niet beschikbaar" tonen */
      });
  }, []);
```

- [ ] **Step 2: Use `streamUrl` instead of `STREAM_URL` in the render**

Replace:

```tsx
            {STREAM_URL ? (
              <OverlayCanvas
                streamUrl={STREAM_URL}
                overlayUrl={config.overlay_hash ? `/api/media/${config.overlay_hash}` : null}
                scale={config.scale}
                position={config.position}
                onPositionChange={(position) => update({ position })}
                onScaleChange={(scale) => update({ scale })}
              />
            ) : (
              <p className="mirror-stream-missing" role="alert">
                Live preview niet beschikbaar — VITE_MIRROR_STREAM_URL is niet ingesteld bij het
                bouwen van de frontend.
              </p>
            )}
```

with:

```tsx
            {streamUrl ? (
              <OverlayCanvas
                streamUrl={streamUrl}
                overlayUrl={config.overlay_hash ? `/api/media/${config.overlay_hash}` : null}
                scale={config.scale}
                position={config.position}
                onPositionChange={(position) => update({ position })}
                onScaleChange={(scale) => update({ scale })}
              />
            ) : (
              <p className="mirror-stream-missing" role="alert">
                Live preview niet beschikbaar — de mirror-stream-URL is nog niet ingesteld op de
                Instellingen-pagina.
              </p>
            )}
```

- [ ] **Step 3: Type-check and build the frontend**

Run: `cd admin/frontend && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Manual check**

Run: `cd admin/frontend && npm run dev` (with the backend also running, see README), open `/settings`, fill in a `mirror_stream_url`, save, then open `/mirror` and confirm the live-preview panel switches from the "niet beschikbaar" message to attempting the stream — without any rebuild.

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/pages/MirrorPage.tsx
git commit -m "feat: MirrorPage haalt stream-URL runtime op i.p.v. build-time env var"
```

---

## Task 7: Remove the now-obsolete build-time plumbing

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Delete: `admin/frontend/.env.example`
- Modify: `README.md`

**Interfaces:**
- None (docs/build-config only, no code interfaces).

- [ ] **Step 1: Simplify `Dockerfile`**

Remove these 5 lines from the `frontend-build` stage:

```dockerfile
# VITE_MIRROR_STREAM_URL wordt door Vite bij het bouwen in de JS-bundle
# gebakken (niet pas bij het opstarten gelezen) — vandaar een build-ARG
# in plaats van een runtime env var. Wijzig je 'm, dan moet je opnieuw
# bouwen: `docker compose build`.
ARG VITE_MIRROR_STREAM_URL=""
ENV VITE_MIRROR_STREAM_URL=${VITE_MIRROR_STREAM_URL}

```

so the stage starts directly with `WORKDIR /build` followed by the `COPY package.json...` line.

- [ ] **Step 2: Simplify `docker-compose.yml`**

Remove the `args:` block under `build:`:

```yaml
    build:
      context: .
      dockerfile: Dockerfile
      args:
        # Bij wijziging: `docker compose build` (nieuwe waarde wordt pas
        # meegenomen bij een echte rebuild, niet bij alleen `up`).
        VITE_MIRROR_STREAM_URL: ${VITE_MIRROR_STREAM_URL:-}
```

becomes:

```yaml
    build:
      context: .
      dockerfile: Dockerfile
```

- [ ] **Step 3: Remove `VITE_MIRROR_STREAM_URL` from `.env.example`**

Remove:

```
# URL van de mirror-node's eigen MJPEG-live-preview-endpoint. Wordt bij het
# BOUWEN in de frontend gebakken (Vite build-time var) — na een wijziging
# hier moet je `docker compose build` draaien, niet alleen `up`.
VITE_MIRROR_STREAM_URL=http://mirror-node.local:8091/stream
```

Add, right below the existing `MQTT_HOST`/`MQTT_PORT`/`MQTT_USER`/`MQTT_PASS` block:

```
# MQTT/HA hierboven zijn alleen de eerste-opstart-seed: na de eerste keer
# opslaan op de Instellingen-pagina in de beheerpagina zelf is de database
# leidend en wordt hier verder niet meer naar gekeken.
```

- [ ] **Step 4: Delete `admin/frontend/.env.example`**

That file exists solely for `VITE_MIRROR_STREAM_URL`; with the variable gone, delete it:

```bash
git rm admin/frontend/.env.example
```

- [ ] **Step 5: Update `README.md`**

Remove this bullet from the systemd deployment section:

```
cp admin/frontend/.env.example admin/frontend/.env
# admin/frontend/.env: VITE_MIRROR_STREAM_URL naar het echte mirror-node-
# LAN-adres zetten vóór de build — Vite-env-variabelen worden bij het bouwen
# vastgebakken, niet bij het draaien.
```

so the systemd code block goes directly from `sudo python3 -m pip install -r admin/requirements.txt` to `cd admin/frontend && npm install && npm run build && cd ../..`.

Replace this paragraph in the Docker section:

```
`VITE_MIRROR_STREAM_URL` (het LAN-adres van de mirror-node's live-preview-
stream) wordt bij het **bouwen** van het image in de frontend vastgebakken.
Wijzig je die waarde in `.env`, dan volstaat `docker compose up -d` niet —
draai `docker compose build` (of `up -d --build`) opnieuw.
```

with:

```
De mirror-stream-URL, MQTT- en HA-verbinding stel je in via de
Instellingen-pagina in de beheerpagina zelf, nadat de container draait —
geen rebuild nodig.
```

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml .env.example README.md
git commit -m "docs: verwijder VITE_MIRROR_STREAM_URL build-time plumbing"
```

---

## Task 8: Whole-feature verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 2: Build the frontend**

Run: `cd admin/frontend && npm run build`
Expected: Succeeds, no TypeScript errors.

- [ ] **Step 3: Run the frontend unit tests**

Run: `cd admin/frontend && npm run test`
Expected: All tests PASS (no new frontend unit tests were added by this plan — this just confirms nothing existing broke).

- [ ] **Step 4: Manual smoke test with `npm run dev`**

Start the backend (`ADMIN_PASSWORD=devpass python -m admin.run`) and `cd admin/frontend && npm run dev`. Log in, open `/settings`, set an MQTT host/port that differs from the running default, save, and confirm (via the backend logs) that the bridge attempted to reconnect to the new host — without restarting the backend process. Then set a `mirror_stream_url` and confirm `/mirror`'s live-preview panel picks it up without a rebuild.

- [ ] **Step 5: Final whole-branch review**

Dispatch a final review pass over every file touched by Tasks 1–7 (same convention as the earlier 3-plan admin-tool feature): check for leftover references to the removed `Settings.mqtt_*`/`Settings.ha_*` fields, leftover `VITE_MIRROR_STREAM_URL` references anywhere in the tree, and that secrets never leak into a `GET /api/settings` response.

Run: `grep -rn "VITE_MIRROR_STREAM_URL" --include=*.py --include=*.ts --include=*.tsx --include=*.md --include=Dockerfile --include=*.yml . 2>/dev/null | grep -v node_modules`
Expected: no output.
