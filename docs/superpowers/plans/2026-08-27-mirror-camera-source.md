# Mirror-node camera-bron Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mirror_node` kan een netwerkcamera (RTSP/HTTP, elk merk) gebruiken naast de bestaande lokale camera-index, volledig beheerd via de Instellingen-pagina (geen env var nodig voor normaal gebruik), met automatisch herverbinden als de stream tijdens een sessie wegvalt.

**Architecture:** Zelfde patroon als de MQTT-topic-prefix-feature: backend is de bron van waarheid (nieuw veld in `RuntimeSettings`/`app_settings`, beheerd via `/api/settings`), `mirror_node` haalt de waarde bij opstarten op via het al bestaande publieke `GET /api/node-config` (uitgebreid met dit veld), met terugval op een lokale env var als de backend onbereikbaar is. `_open_camera(source)` in `mirror_node/main.py` kiest tussen lokale index en `cv2.VideoCapture(url, cv2.CAP_FFMPEG)`; de hoofdloop heropent de verbinding na een reeks mislukte reads.

**Tech Stack:** Python (FastAPI-backend, OpenCV in mirror_node), React/TypeScript-frontend, pytest. Geen nieuwe dependency — `cv2.VideoCapture` accepteert al een URL naast een index.

**Spec:** `docs/superpowers/specs/2026-08-27-mirror-camera-source-design.md`

## Global Constraints

- Default is `""` (leeg) — bestaande deployments blijven ongewijzigd tot iemand expliciet een camera-bron instelt.
- `mirror_camera_source` is **niet** een secret (net als `mqtt_topic_prefix`/`mirror_stream_url`) — geen masking in `GET /api/settings`, geen extra beveiliging op `/api/node-config`. Expliciet met de gebruiker besproken en bevestigd (vertrouwd LAN).
- Geen live-herconfiguratie van de node — een wijziging vraagt een herstart om 'm op te pikken, zelfde als de topic-prefix.
- `_open_camera` is camera-merk-agnostisch — geen Reolink-specifieke code.
- Reconnect-logica in de hoofdloop van `mirror_node/main.py` blijft, zoals de rest van die loop, handmatig getest op locatie — geen unit-test daarvoor, wel voor `_open_camera` zelf (dat is pure branching-logica).

---

## Task 1: Backend — `mirror_camera_source` in `RuntimeSettings`/`app_settings`

**Files:**
- Modify: `admin/app/db.py`
- Modify: `admin/app/runtime_settings.py`
- Modify: `tests/test_admin_runtime_settings.py`

**Interfaces:**
- Consumes: niets uit eerdere tasks.
- Produces: `RuntimeSettings.mirror_camera_source: str` (default `""`) —
  gebruikt door Task 2 (routers/settings), Task 3 (routers/node_config).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_admin_runtime_settings.py` (the file already imports
`sqlite3`, `init_db`, `read_runtime_settings`, `write_runtime_settings` —
no new imports needed):

```python
def test_read_without_row_defaults_camera_source_to_empty(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    settings = read_runtime_settings(conn)

    assert settings.mirror_camera_source == ""


def test_write_then_read_roundtrip_camera_source(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    write_runtime_settings(conn, mirror_camera_source="rtsp://cam.local/stream1")
    settings = read_runtime_settings(conn)

    assert settings.mirror_camera_source == "rtsp://cam.local/stream1"


def test_init_db_adds_camera_source_column_to_existing_table_without_it(tmp_path):
    """Regressie, zelfde reden als bij mqtt_topic_prefix hierboven:
    app_settings kan al bestaan (uit een eerdere feature) zonder deze
    kolom -- init_db moet 'm alsnog toevoegen aan een bestaande tabel."""
    db_path = str(tmp_path / "old-schema-2.db")
    old_conn = sqlite3.connect(db_path)
    old_conn.execute(
        """CREATE TABLE app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mqtt_host TEXT NOT NULL,
            mqtt_port INTEGER NOT NULL,
            mqtt_user TEXT NOT NULL DEFAULT '',
            mqtt_pass TEXT NOT NULL DEFAULT '',
            ha_url TEXT NOT NULL,
            ha_token TEXT NOT NULL DEFAULT '',
            mirror_stream_url TEXT NOT NULL DEFAULT '',
            mqtt_topic_prefix TEXT NOT NULL DEFAULT ''
        )"""
    )
    old_conn.execute(
        "INSERT INTO app_settings (id, mqtt_host, mqtt_port, ha_url) VALUES (1, 'oude-broker', 1883, 'http://ha.local:8123')"
    )
    old_conn.commit()
    old_conn.close()

    conn = init_db(db_path)
    settings = read_runtime_settings(conn)

    assert settings.mqtt_host == "oude-broker"
    assert settings.mirror_camera_source == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_admin_runtime_settings.py -v`
Expected: FAIL — `TypeError: RuntimeSettings.__init__() got an unexpected
keyword argument 'mirror_camera_source'` (or `AttributeError` on the
assertion)

- [ ] **Step 3: Add the column to `admin/app/db.py`**

Right after the existing `_ensure_column(conn, "app_settings",
"mqtt_topic_prefix", "TEXT NOT NULL DEFAULT ''")` line, add:

```python
    _ensure_column(conn, "app_settings", "mirror_camera_source", "TEXT NOT NULL DEFAULT ''")
```

(`_ensure_column` itself is unchanged — it already generalizes to any
column.)

- [ ] **Step 4: Update `admin/app/runtime_settings.py`**

Replace the whole file:

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
    mqtt_topic_prefix: str = ""
    mirror_camera_source: str = ""


def _env_defaults() -> RuntimeSettings:
    """Zelfde variabelenamen/defaults als config.get_settings() vroeger
    gebruikte voor deze velden -- alleen gelezen zolang er nog geen
    app_settings-rij is (eerste-opstart-seed van een bestaande deploy).
    mirror_camera_source heeft nooit een backend-kant env var gehad, dus
    default gewoon leeg."""
    return RuntimeSettings(
        mqtt_host=os.environ.get("MQTT_HOST", "homeassistant.local"),
        mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        mqtt_user=os.environ.get("MQTT_USER", ""),
        mqtt_pass=os.environ.get("MQTT_PASS", ""),
        ha_url=os.environ.get("HA_URL", "http://homeassistant.local:8123"),
        ha_token=os.environ.get("HA_TOKEN", ""),
        mirror_stream_url="",
        mqtt_topic_prefix=os.environ.get("MQTT_TOPIC_PREFIX", ""),
        mirror_camera_source="",
    )


def read_runtime_settings(conn) -> RuntimeSettings:
    row = conn.execute(
        "SELECT mqtt_host, mqtt_port, mqtt_user, mqtt_pass, ha_url, ha_token, mirror_stream_url, "
        "mqtt_topic_prefix, mirror_camera_source FROM app_settings WHERE id = 1"
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
               (id, mqtt_host, mqtt_port, mqtt_user, mqtt_pass, ha_url, ha_token, mirror_stream_url,
                mqtt_topic_prefix, mirror_camera_source)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               mqtt_host=excluded.mqtt_host, mqtt_port=excluded.mqtt_port,
               mqtt_user=excluded.mqtt_user, mqtt_pass=excluded.mqtt_pass,
               ha_url=excluded.ha_url, ha_token=excluded.ha_token,
               mirror_stream_url=excluded.mirror_stream_url,
               mqtt_topic_prefix=excluded.mqtt_topic_prefix,
               mirror_camera_source=excluded.mirror_camera_source""",
        (
            result.mqtt_host, result.mqtt_port, result.mqtt_user, result.mqtt_pass,
            result.ha_url, result.ha_token, result.mirror_stream_url, result.mqtt_topic_prefix,
            result.mirror_camera_source,
        ),
    )
    conn.commit()
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_runtime_settings.py -v`
Expected: PASS (10 tests — 7 pre-existing + 3 new)

- [ ] **Step 6: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -q`
Expected: Same failures as before this task started (none — the suite was
fully green at the start of this plan) plus no new ones. If anything now
fails outside `tests/test_admin_runtime_settings.py`, stop and investigate
before continuing.

- [ ] **Step 7: Commit**

```bash
git add admin/app/db.py admin/app/runtime_settings.py tests/test_admin_runtime_settings.py
git commit -m "feat: mirror_camera_source-veld in RuntimeSettings/app_settings"
```

---

## Task 2: Backend — `mirror_camera_source` in `/api/settings`

**Files:**
- Modify: `admin/app/routers/settings.py`
- Modify: `tests/test_admin_routes_settings.py`

**Interfaces:**
- Consumes: `RuntimeSettings.mirror_camera_source` (Task 1).
- Produces: `GET`/`PUT /api/settings` krijgen het veld `mirror_camera_source`
  — gebruikt door Task 5 (frontend).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_admin_routes_settings.py`:

```python
def test_get_settings_includes_camera_source(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.get("/api/settings")

    assert response.json()["mirror_camera_source"] == ""


def test_put_settings_persists_camera_source(tmp_path):
    client, app, bridge = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883,
        "mirror_camera_source": "rtsp://user:pass@192.168.1.50:554/stream1",
    })

    assert response.status_code == 200
    assert client.get("/api/settings").json()["mirror_camera_source"] == "rtsp://user:pass@192.168.1.50:554/stream1"


def test_put_settings_accepts_numeric_camera_source(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mirror_camera_source": "1",
    })

    assert response.status_code == 200
    assert client.get("/api/settings").json()["mirror_camera_source"] == "1"


def test_put_settings_accepts_empty_camera_source(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mirror_camera_source": "",
    })

    assert response.status_code == 200


def test_put_settings_rejects_malformed_camera_source(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mirror_camera_source": "not-a-url-or-number",
    })

    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_settings.py -v`
Expected: FAIL — `mirror_camera_source` missing from the `GET` response, no
validation rejects malformed values yet.

- [ ] **Step 3: Update `admin/app/routers/settings.py`**

Replace the whole file:

```python
from fastapi import APIRouter, HTTPException, Request

from admin.app.runtime_settings import read_runtime_settings, write_runtime_settings

router = APIRouter()


def _validate_url(value, field_name):
    if value and not (value.startswith("http://") or value.startswith("https://")):
        raise HTTPException(status_code=400, detail=f"{field_name} moet leeg zijn of met http(s):// beginnen")


def _validate_topic_prefix(value):
    if "#" in value or "+" in value:
        raise HTTPException(status_code=400, detail="mqtt_topic_prefix mag geen # of + bevatten")


def _validate_camera_source(value):
    if not value:
        return
    try:
        int(value)
        return
    except ValueError:
        pass
    if not (value.startswith("rtsp://") or value.startswith("http://") or value.startswith("https://")):
        raise HTTPException(
            status_code=400,
            detail="mirror_camera_source moet leeg zijn, een getal zijn, of met rtsp://, http:// of https:// beginnen",
        )


@router.get("/api/settings")
def get_settings_route(request: Request):
    settings = read_runtime_settings(request.app.state.db)
    return {
        "mqtt_host": settings.mqtt_host,
        "mqtt_port": settings.mqtt_port,
        "mqtt_user": settings.mqtt_user,
        "ha_url": settings.ha_url,
        "mirror_stream_url": settings.mirror_stream_url,
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mirror_camera_source": settings.mirror_camera_source,
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

    mqtt_topic_prefix = str(body.get("mqtt_topic_prefix", "")).strip()
    _validate_topic_prefix(mqtt_topic_prefix)

    mirror_camera_source = str(body.get("mirror_camera_source", "")).strip()
    _validate_camera_source(mirror_camera_source)

    updates = {
        "mqtt_host": mqtt_host,
        "mqtt_port": mqtt_port,
        "mqtt_user": str(body.get("mqtt_user", "")),
        "ha_url": ha_url,
        "mirror_stream_url": mirror_stream_url,
        "mqtt_topic_prefix": mqtt_topic_prefix,
        "mirror_camera_source": mirror_camera_source,
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_settings.py -v`
Expected: PASS (17 tests — 12 pre-existing + 5 new)

- [ ] **Step 5: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -q`
Expected: All green, no new failures.

- [ ] **Step 6: Commit**

```bash
git add admin/app/routers/settings.py tests/test_admin_routes_settings.py
git commit -m "feat: mirror_camera_source instelbaar via /api/settings"
```

---

## Task 3: Backend — `mirror_camera_source` in `/api/node-config`

**Files:**
- Modify: `admin/app/routers/node_config.py`
- Modify: `tests/test_admin_routes_node_config.py`

**Interfaces:**
- Consumes: `RuntimeSettings.mirror_camera_source` (Task 1).
- Produces: `GET /api/node-config` response krijgt het veld
  `mirror_camera_source` — gebruikt door Task 4/6 (`mirror_node`).

- [ ] **Step 1: Update the two existing tests (their exact-equality
  assertions break once the response gains a field) and add one new test**

Replace the whole file `tests/test_admin_routes_node_config.py`:

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
    """Vervangt app.state.bridge door een FakeBridge -- anders roept een PUT
    /api/settings tijdens de test een ECHTE MqttBridge.reconfigure() aan, die
    een reëel achtergrondthread + verbindingspoging start. Zelfde patroon als
    _client() in tests/test_admin_routes_settings.py."""
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    return TestClient(app), app


def test_node_config_works_without_session_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_TOPIC_PREFIX", "seed-prefix")
    client, app = _client(tmp_path)

    response = client.get("/api/node-config")

    assert response.status_code == 200
    assert response.json() == {"mqtt_topic_prefix": "seed-prefix", "mirror_camera_source": ""}


def test_node_config_reflects_saved_prefix(tmp_path):
    client, app = _client(tmp_path)
    client.post("/api/login", json={"password": "testwachtwoord"})
    client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_topic_prefix": "gewijzigd",
    })

    response = client.get("/api/node-config")

    assert response.json() == {"mqtt_topic_prefix": "gewijzigd", "mirror_camera_source": ""}


def test_node_config_includes_camera_source(tmp_path):
    client, app = _client(tmp_path)
    client.post("/api/login", json={"password": "testwachtwoord"})
    client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883,
        "mirror_camera_source": "rtsp://cam.local/stream1",
    })

    response = client.get("/api/node-config")

    assert response.json() == {
        "mqtt_topic_prefix": "",
        "mirror_camera_source": "rtsp://cam.local/stream1",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_node_config.py -v`
Expected: FAIL — the two updated tests fail because the current response
doesn't include `mirror_camera_source`; the new test fails the same way.

- [ ] **Step 3: Update `admin/app/routers/node_config.py`**

Replace the whole file:

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/node-config")
def get_node_config(request: Request):
    """Publiek endpoint (geen sessie nodig) waar mirror-node/scare-node bij
    het opstarten hun configuratie ophalen -- zie shared/topic_prefix.py.
    Geeft bewust alleen niet-gevoelige/expliciet-publiek-gemaakte velden
    terug: de topic-prefix en de mirror-camera-bron (beide besproken en
    geaccepteerd als niet-extra-beveiligd, vertrouwd LAN). Nooit MQTT-host/
    poort/credentials of het HA-token."""
    settings = request.app.state.runtime_settings
    return {
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mirror_camera_source": settings.mirror_camera_source,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_admin_routes_node_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -q`
Expected: All green, no new failures.

- [ ] **Step 6: Commit**

```bash
git add admin/app/routers/node_config.py tests/test_admin_routes_node_config.py
git commit -m "feat: mirror_camera_source mee in publiek /api/node-config"
```

---

## Task 4: `shared/topic_prefix.py` — `fetch_mirror_camera_source`

**Files:**
- Modify: `shared/topic_prefix.py`
- Modify: `tests/test_topic_prefix.py`

**Interfaces:**
- Consumes: niets uit eerdere tasks (herbruikt alleen het bestaande
  `_default_fetch`-patroon in hetzelfde bestand).
- Produces: `fetch_mirror_camera_source(backend_url: str, fallback: str,
  fetch=None, timeout=3) -> str` — gebruikt door Task 6 (`mirror_node`).

- [ ] **Step 1: Write the failing tests**

Update the import line at the top of `tests/test_topic_prefix.py`:

```python
from shared.topic_prefix import fetch_topic_prefix, fetch_mirror_camera_source
```

Add these 6 tests to the same file (mirrors the existing
`fetch_topic_prefix` tests one-for-one):

```python
def test_fetch_mirror_camera_source_returns_backend_value():
    def fake_fetch(url, timeout):
        assert url == "http://backend:8000/api/node-config"
        return b'{"mirror_camera_source": "rtsp://cam.local/stream1"}'

    result = fetch_mirror_camera_source("http://backend:8000", fallback="fallback", fetch=fake_fetch)

    assert result == "rtsp://cam.local/stream1"


def test_fetch_mirror_camera_source_returns_empty_string_correctly():
    def empty_fetch(url, timeout):
        return b'{"mirror_camera_source": ""}'

    result = fetch_mirror_camera_source("http://backend:8000", fallback="fallback", fetch=empty_fetch)

    assert result == ""


def test_fetch_mirror_camera_source_falls_back_on_connection_error():
    def failing_fetch(url, timeout):
        raise OSError("onbereikbaar")

    result = fetch_mirror_camera_source("http://backend:8000", fallback="fallback", fetch=failing_fetch)

    assert result == "fallback"


def test_fetch_mirror_camera_source_falls_back_on_malformed_json():
    def bad_fetch(url, timeout):
        return b"not json"

    result = fetch_mirror_camera_source("http://backend:8000", fallback="fallback", fetch=bad_fetch)

    assert result == "fallback"


def test_fetch_mirror_camera_source_falls_back_when_field_missing():
    def missing_fetch(url, timeout):
        return b"{}"

    result = fetch_mirror_camera_source("http://backend:8000", fallback="fallback", fetch=missing_fetch)

    assert result == "fallback"


def test_fetch_mirror_camera_source_falls_back_when_field_wrong_type():
    def wrong_type_fetch(url, timeout):
        return b'{"mirror_camera_source": 123}'

    result = fetch_mirror_camera_source("http://backend:8000", fallback="fallback", fetch=wrong_type_fetch)

    assert result == "fallback"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_topic_prefix.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_mirror_camera_source'`

- [ ] **Step 3: Add `fetch_mirror_camera_source` to `shared/topic_prefix.py`**

Append this function at the end of the file (leave `_default_fetch` and
`fetch_topic_prefix` exactly as they are):

```python
def fetch_mirror_camera_source(backend_url, fallback, fetch=None, timeout=3):
    """Haalt de actuele mirror-camera-bron op bij de backend
    (`GET {backend_url}/api/node-config`). Lukt dat niet (backend
    onbereikbaar, ongeldig antwoord, verkeerd veldtype), dan `fallback` --
    zelfde fail-safe-patroon als fetch_topic_prefix, bewust een eigen kleine
    functie in plaats van die functie te verbreden (zie de spec)."""
    fetch = fetch or _default_fetch
    try:
        data = fetch(f"{backend_url}/api/node-config", timeout)
        parsed = json.loads(data)
        source = parsed.get("mirror_camera_source")
        if isinstance(source, str):
            return source
        return fallback
    except Exception:
        return fallback
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_topic_prefix.py -v`
Expected: PASS (12 tests — 6 pre-existing + 6 new)

- [ ] **Step 5: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -q`
Expected: All green, no new failures.

- [ ] **Step 6: Commit**

```bash
git add shared/topic_prefix.py tests/test_topic_prefix.py
git commit -m "feat: fetch_mirror_camera_source -- mirror-node haalt de camera-bron op bij de backend, met terugval"
```

---

## Task 5: Frontend — camera-bron-veld op de Instellingen-pagina

**Files:**
- Modify: `admin/frontend/src/types.ts`
- Modify: `admin/frontend/src/pages/SettingsPage.tsx`

**Interfaces:**
- Consumes: `GET`/`PUT /api/settings`'s `mirror_camera_source`-veld (Task 2).
- Produces: geen nieuwe interface voor latere tasks.

- [ ] **Step 1: Update `admin/frontend/src/types.ts`**

In `AppSettings`, add the field (matches the `GET` response from Task 2):

```ts
export interface AppSettings {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  ha_url: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
  mirror_camera_source: string;
  mqtt_pass_set: boolean;
  ha_token_set: boolean;
}
```

In `AppSettingsUpdate`, add the field (matches the `PUT` body from Task 2):

```ts
export interface AppSettingsUpdate {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  mqtt_pass?: string;
  ha_url: string;
  ha_token?: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
  mirror_camera_source: string;
}
```

- [ ] **Step 2: Update `admin/frontend/src/pages/SettingsPage.tsx`**

Add `mirror_camera_source` to the `FormState` interface and `EMPTY_FORM`:

```ts
interface FormState {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  mqtt_pass: string;
  ha_url: string;
  ha_token: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
  mirror_camera_source: string;
}

const EMPTY_FORM: FormState = {
  mqtt_host: "",
  mqtt_port: 1883,
  mqtt_user: "",
  mqtt_pass: "",
  ha_url: "",
  ha_token: "",
  mirror_stream_url: "",
  mqtt_topic_prefix: "",
  mirror_camera_source: "",
};
```

In the `useEffect` that loads settings, include the field when building the
form state from the fetched result:

```tsx
        setForm({
          mqtt_host: result.mqtt_host,
          mqtt_port: result.mqtt_port,
          mqtt_user: result.mqtt_user,
          mqtt_pass: "",
          ha_url: result.ha_url,
          ha_token: "",
          mirror_stream_url: result.mirror_stream_url,
          mqtt_topic_prefix: result.mqtt_topic_prefix,
          mirror_camera_source: result.mirror_camera_source,
        });
```

In `handleSave`, include the field in the `putSettings(...)` call:

```tsx
      await putSettings({
        mqtt_host: form.mqtt_host,
        mqtt_port: form.mqtt_port,
        mqtt_user: form.mqtt_user,
        ...(form.mqtt_pass ? { mqtt_pass: form.mqtt_pass } : {}),
        ha_url: form.ha_url,
        ...(form.ha_token ? { ha_token: form.ha_token } : {}),
        mirror_stream_url: form.mirror_stream_url,
        mqtt_topic_prefix: form.mqtt_topic_prefix,
        mirror_camera_source: form.mirror_camera_source,
      });
```

Find the "Spiegel-node" `<section className="settings-panel">` (the one
containing the "Live-preview-stream-URL" field). Add a new field right
after that field's closing `</label>`, still inside the same
`<div className="settings-grid">`:

```tsx
              <label className="settings-field settings-field--wide">
                <span className="settings-field__label">Camera-bron (optioneel)</span>
                <input
                  className="settings-field__input"
                  type="text"
                  value={form.mirror_camera_source}
                  placeholder="bijv. rtsp://gebruiker:wachtwoord@192.168.1.50:554/stream1"
                  onChange={(e) => update({ mirror_camera_source: e.target.value })}
                />
              </label>
```

Directly below that `<div className="settings-grid">`'s closing tag (still
inside the Spiegel-node `<section>`), add a short explanatory line, same
style as the existing help caption under the MQTT topic-prefix field:

```tsx
            <p className="settings-field__label" style={{ marginTop: "0.75rem" }}>
              Leeg = de lokale camera op de node zelf. Een RTSP/HTTP-URL
              gebruikt die camera in plaats daarvan — elk merk met een
              standaard stream werkt. Nodes halen dit pas op bij hun
              eerstvolgende herstart.
            </p>
```

- [ ] **Step 3: Type-check and build the frontend**

Run: `cd admin/frontend && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/types.ts admin/frontend/src/pages/SettingsPage.tsx
git commit -m "feat: camera-bron-veld op de Instellingen-pagina"
```

---

## Task 6: `mirror_node/main.py` — `_open_camera` + reconnect

**Files:**
- Modify: `mirror_node/main.py`
- Modify: `tests/test_mirror_main.py`

**Interfaces:**
- Consumes: `fetch_mirror_camera_source` (Task 4).
- Produces: `_open_camera(source: str) -> cv2.VideoCapture` — module-level,
  no consumers outside this file.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mirror_main.py`:

```python
def test_open_camera_uses_local_index_when_source_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: calls.append(a) or "cap")

    result = mirror_main._open_camera("")

    assert calls == [(mirror_main.CAMERA_INDEX,)]
    assert result == "cap"


def test_open_camera_uses_local_index_when_source_is_numeric_string(monkeypatch):
    calls = []
    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: calls.append(a) or "cap")

    mirror_main._open_camera("2")

    assert calls == [(2,)]


def test_open_camera_uses_ffmpeg_url_for_network_source(monkeypatch):
    calls = []
    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: calls.append(a) or "cap")

    mirror_main._open_camera("rtsp://cam.local/stream1")

    assert calls == [("rtsp://cam.local/stream1", mirror_main.cv2.CAP_FFMPEG)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_mirror_main.py -v`
Expected: FAIL with `AttributeError: module 'mirror_node.main' has no
attribute '_open_camera'`

- [ ] **Step 3: Update `mirror_node/main.py`**

Change the import line:

```python
from shared.topic_prefix import fetch_topic_prefix
```

to:

```python
from shared.topic_prefix import fetch_topic_prefix, fetch_mirror_camera_source
```

Add a new module-level env var right after `MQTT_TOPIC_PREFIX_ENV`:

```python
MIRROR_CAMERA_SOURCE_ENV = os.environ.get("MIRROR_CAMERA_SOURCE", "")
```

Add a new module-level function, right before `def selfcheck():` (the first
function that uses it — function definition order doesn't affect behavior
here, but this placement keeps it next to its first caller):

```python
def _open_camera(source):
    """Opent de camera-bron: leeg -> lokale index (CAMERA_INDEX), een
    numerieke string -> die index, anders -> een netwerkstream via FFmpeg.
    Camera-merk-agnostisch: elke bron die OpenCV/FFmpeg begrijpt werkt."""
    if not source:
        return cv2.VideoCapture(CAMERA_INDEX)
    try:
        return cv2.VideoCapture(int(source))
    except ValueError:
        return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
```

Update `selfcheck()` — replace:

```python
def selfcheck():
    """Pakt één frame, draait het door het standaard xray-effect en
    laat/bewaart het resultaat. Heeft geen MQTT nodig."""
    cap = cv2.VideoCapture(CAMERA_INDEX)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print(f"selfcheck MISLUKT: geen frame van camera index {CAMERA_INDEX}")
        sys.exit(1)
```

with:

```python
def selfcheck():
    """Pakt één frame, draait het door het standaard xray-effect en
    laat/bewaart het resultaat. Heeft geen MQTT nodig."""
    camera_source = fetch_mirror_camera_source(BACKEND_URL, fallback=MIRROR_CAMERA_SOURCE_ENV)
    cap = _open_camera(camera_source)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print(f"selfcheck MISLUKT: geen frame van camera-bron {camera_source or CAMERA_INDEX}")
        sys.exit(1)
```

(The rest of `selfcheck()` — the xray effect, saving, `imshow` — stays
exactly as it is.)

In `main()`, right after the existing `topics = Topics(prefix=topic_prefix)`
line, add:

```python
    camera_source = fetch_mirror_camera_source(BACKEND_URL, fallback=MIRROR_CAMERA_SOURCE_ENV)
```

Further down in `main()`, replace:

```python
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        logger.error("Kon camera index %s niet openen", CAMERA_INDEX)
        return
```

with:

```python
    cap = _open_camera(camera_source)
    if not cap.isOpened():
        logger.error("Kon camera-bron niet openen: %s", camera_source or CAMERA_INDEX)
        return
```

Replace the `active_until`/logger-start lines and the top of the `try:`
block:

```python
    active_until = 0.0
    logger.info("mirror-node gestart")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                logger.warning("Kon geen frame lezen van camera")
                time.sleep(0.5)
                continue
```

with:

```python
    active_until = 0.0
    consecutive_failures = 0
    MAX_FAILURES_BEFORE_REOPEN = 30  # ~15s bij 0.5s sleep tussen mislukte reads
    logger.info("mirror-node gestart")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                logger.warning("Kon geen frame lezen van camera")
                consecutive_failures += 1
                if consecutive_failures >= MAX_FAILURES_BEFORE_REOPEN:
                    logger.warning("Camera blijft falen, heropen de verbinding")
                    cap.release()
                    cap = _open_camera(camera_source)
                    consecutive_failures = 0
                time.sleep(0.5)
                continue
            consecutive_failures = 0
```

(Everything below that — the `sleeping.is_set()` check onward — is
unchanged; `consecutive_failures = 0` is the new last line before the
existing `if sleeping.is_set():` block.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_mirror_main.py -v`
Expected: PASS (all tests in the file — 9 pre-existing + 3 new)

- [ ] **Step 5: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -q`
Expected: All green, no new failures.

- [ ] **Step 6: Commit**

```bash
git add mirror_node/main.py tests/test_mirror_main.py
git commit -m "feat: mirror-node ondersteunt netwerkcamera (RTSP/HTTP) met reconnect"
```

---

## Task 7: README — camera-bron documenteren

**Files:**
- Modify: `README.md`

**Interfaces:** geen (documentatie).

- [ ] **Step 1: Add `MIRROR_CAMERA_SOURCE` to the "Alleen mirror-node" table**

Find this block:

```
Alleen mirror-node:

| Variabele | Default | Betekenis |
|---|---|---|
| `MIRROR_CAMERA_INDEX` | `0` | OpenCV camera-index |
| `MIRROR_ACTIVE_SECONDS` | `6` | Hoe lang het effect na een trigger aanblijft |
```

Insert a new row right after the `MIRROR_CAMERA_INDEX` row:

```
| `MIRROR_CAMERA_SOURCE` | *(leeg)* | Terugval als de backend bij opstarten onbereikbaar is voor `GET /api/node-config` — normaal gesproken bepaalt de Instellingen-pagina dit centraal. Leeg = gebruik `MIRROR_CAMERA_INDEX`; een RTSP/HTTP-URL gebruikt in plaats daarvan een netwerkcamera (elk merk met een standaard stream). |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: MIRROR_CAMERA_SOURCE en netwerkcamera-ondersteuning documenteren"
```

---

## Task 8: Whole-feature verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend test suite**

Run: `source .venv/bin/activate && pytest tests/ -q`
Expected: All tests PASS.

- [ ] **Step 2: Build the frontend**

Run: `cd admin/frontend && npm run build`
Expected: Succeeds, no TypeScript errors.

- [ ] **Step 3: Manual smoke test — settings round-trip**

Start the backend (`ADMIN_PASSWORD=devpass ADMIN_DB_PATH=/tmp/task8-smoke.db
LOG_DIR=/tmp/task8-logs MQTT_HOST=localhost python -m admin.run` from the
repo root, backend venv at `.venv/`), log in via curl, then:

```bash
curl -s -b /tmp/task8-cookies.txt -X PUT http://localhost:8000/api/settings \
  -H 'Content-Type: application/json' \
  -d '{"mqtt_host":"localhost","mqtt_port":1883,"mirror_camera_source":"rtsp://user:pass@192.168.1.50:554/stream1"}'
curl -s -b /tmp/task8-cookies.txt http://localhost:8000/api/settings | grep mirror_camera_source
curl -s http://localhost:8000/api/node-config
```

Expected: both show the RTSP URL; `/api/node-config` needs no session
cookie. Then confirm validation rejects garbage:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/task8-cookies.txt -X PUT http://localhost:8000/api/settings \
  -H 'Content-Type: application/json' \
  -d '{"mqtt_host":"localhost","mqtt_port":1883,"mirror_camera_source":"garbage"}'
```

Expected: `400`. Clean up: stop the backend, remove `/tmp/task8-smoke.db`,
`/tmp/task8-cookies.txt`, `/tmp/task8-logs`.

- [ ] **Step 4: Verify `_open_camera` is used everywhere the old bare
  `cv2.VideoCapture(CAMERA_INDEX)` call used to be**

Run: `grep -n "cv2.VideoCapture(CAMERA_INDEX)" mirror_node/main.py`
Expected: no output (both call sites — `main()` and `selfcheck()` — now go
through `_open_camera`).

- [ ] **Step 5: Final whole-branch review**

Dispatch a final review pass over every file touched by Tasks 1–7 (same
convention as prior plans in this repo): check that `scare_node/main.py`
received zero changes (it doesn't consume `mirror_camera_source` at all,
confirming the feature stayed scoped to the mirror node), that the
reconnect logic in `mirror_node/main.py`'s main loop actually reassigns
`cap` (not just calls `_open_camera` and discards the result), and that no
secret-handling regression was introduced in `routers/settings.py`'s edits
(the existing `mqtt_pass`/`ha_token` masking must still work exactly as
before).
