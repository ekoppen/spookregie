# Camera-apparaatrol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apparaten kunnen zich melden met twee onafhankelijke capabilities (`is_mirror`, `is_camera`, niet-exclusief), zodat een losstaand camera-apparaat een MJPEG-stream serveert die zowel mirror-node als het admin-voorbeeldpaneel kunnen bereiken, en in Apparaten met één klik als Source aangemaakt kan worden.

**Architecture:** `devices` krijgt twee boolean-vlaggen + een zelf-gerapporteerde stream-URL, gevuld via het bestaande MQTT-check-in-pad (`mirror_node.agent` → `device-info/{uuid}` → `admin/app/main.py:_handle_device_info`). Een nieuwe, lichtgewicht module `mirror_node/camera_server.py` hergebruikt de al bestaande `open_camera()` (`mirror_node/camera.py`) en `MJPEGStreamer` (`mirror_node/stream.py`) — geen nieuwe streaming-code, geen nieuwe dependency. `deploy/install-agent.sh` krijgt twee ja/nee-vragen die bepalen welke combinatie van services geïnstalleerd wordt. De Apparaten-pagina toont per rij conditioneel een output-picker (is_mirror) en/of een "Maak hiervan een source"-knop (is_camera) die het al bestaande `POST /api/sources` hergebruikt.

**Tech Stack:** Python (FastAPI-backend, mirror_node), SQLite, OpenCV (`cv2`), Python-stdlib `http.server`/`socket`, React/TypeScript-frontend, bash (install-script).

**Spec:** `docs/superpowers/specs/2026-09-01-camera-device-role-design.md`

## Global Constraints

- Backward compatible: bestaande apparaten/installaties zonder de nieuwe env-vars/velden blijven werken als mirror-only (`is_mirror` default/fallback `True`, `is_camera` default/fallback `False`).
- Geen nieuwe dependencies — hergebruik `cv2`, Python-stdlib `http.server`/`socket`, en de bestaande `MJPEGStreamer`/`open_camera()`.
- Geen foreign key tussen `devices` en `sources` — "Maak hiervan een source" is een eenmalige, kopiërende actie, geen blijvende koppeling.
- Geen authenticatie op de camera-MJPEG-stream (zelfde "vertrouwd LAN"-uitgangspunt als MQTT/`/api/node-config` elders in het project).
- Poorten/rollen zijn env-configureerbaar met defaults: `CAMERA_SERVER_PORT` default `8080`, `SPOOKREGIE_IS_MIRROR` default `"1"`, `SPOOKREGIE_IS_CAMERA` default `"0"`.

---

## Task 1: Devices-schema — is_mirror / is_camera / camera_stream_url

**Files:**
- Modify: `admin/app/db.py`
- Test: `tests/test_admin_db.py`

**Interfaces:**
- Produces: kolommen `devices.is_mirror` (INTEGER NOT NULL DEFAULT 1), `devices.is_camera` (INTEGER NOT NULL DEFAULT 0), `devices.camera_stream_url` (TEXT, nullable). Gelezen door Task 2/3.

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_admin_db.py` (aan het eind van het bestand):

```python
def test_devices_get_role_and_camera_stream_url_columns(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(devices)")}

    assert {"is_mirror", "is_camera", "camera_stream_url"} <= cols


def test_existing_device_defaults_to_mirror_only(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO devices (device_uuid, name, platform) VALUES ('abc-123', 'Oude MacBook', 'darwin')"
    )
    conn.commit()

    row = conn.execute(
        "SELECT is_mirror, is_camera, camera_stream_url FROM devices WHERE device_uuid = 'abc-123'"
    ).fetchone()

    assert row == (1, 0, None)
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `python3 -m pytest tests/test_admin_db.py::test_devices_get_role_and_camera_stream_url_columns tests/test_admin_db.py::test_existing_device_defaults_to_mirror_only -v`
Expected: FAIL — `is_mirror`/`is_camera`/`camera_stream_url` bestaan nog niet.

- [ ] **Step 3: Voeg de migratie toe**

In `admin/app/db.py`, in het cluster van bestaande `_ensure_column`-aanroepen (direct na de regel `_ensure_column(conn, "outputs", "canvas_y", "REAL NOT NULL DEFAULT 0")`, rond regel 136):

```python
    _ensure_column(conn, "outputs", "canvas_y", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "devices", "is_mirror", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "devices", "is_camera", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "devices", "camera_stream_url", "TEXT")
```

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `python3 -m pytest tests/test_admin_db.py -v`
Expected: alle tests slagen (inclusief de twee nieuwe en alle bestaande — geen regressie).

- [ ] **Step 5: Commit**

```bash
git add admin/app/db.py tests/test_admin_db.py
git commit -m "feat: devices.is_mirror/is_camera/camera_stream_url kolommen"
```

---

## Task 2: Devices-router geeft de nieuwe velden terug

**Files:**
- Modify: `admin/app/routers/devices.py`
- Test: `tests/test_admin_routes_devices.py`

**Interfaces:**
- Consumes: `devices.is_mirror`/`is_camera`/`camera_stream_url` (Task 1).
- Produces: `GET /api/devices` en `PUT /api/devices/{id}` geven voortaan ook `is_mirror: bool`, `is_camera: bool`, `camera_stream_url: str | None` terug. Gelezen door frontend Task 7/8.

- [ ] **Step 1: Schrijf de falende test**

Voeg toe aan `tests/test_admin_routes_devices.py` (na `test_list_devices_returns_seeded_device`):

```python
def test_list_devices_includes_role_flags_and_camera_stream_url(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    _seed_device(db)

    response = client.get("/api/devices")

    body = response.json()
    assert body[0]["is_mirror"] is True
    assert body[0]["is_camera"] is False
    assert body[0]["camera_stream_url"] is None
```

- [ ] **Step 2: Run test, verifieer dat 'ie faalt**

Run: `python3 -m pytest tests/test_admin_routes_devices.py::test_list_devices_includes_role_flags_and_camera_stream_url -v`
Expected: FAIL met een `KeyError`/`AssertionError` — de velden zitten nog niet in de response.

- [ ] **Step 3: Breid `_DEVICE_COLUMNS`/`_row_to_device` uit**

In `admin/app/routers/devices.py`:

```python
_DEVICE_COLUMNS = (
    "id, device_uuid, name, platform, git_sha, last_seen_at, output_id, "
    "is_mirror, is_camera, camera_stream_url"
)


def _row_to_device(row):
    return {
        "id": row[0],
        "device_uuid": row[1],
        "name": row[2],
        "platform": row[3],
        "git_sha": row[4],
        "last_seen_at": row[5],
        "output_id": row[6],
        "is_mirror": bool(row[7]),
        "is_camera": bool(row[8]),
        "camera_stream_url": row[9],
    }
```

(De rest van het bestand — `list_devices_route`, `update_device_route`, `delete_device_route` — blijft ongewijzigd; `update_device_route` schrijft nooit naar `is_mirror`/`is_camera`/`camera_stream_url`, dus die blijven precies staan zoals de laatste check-in ze zette.)

- [ ] **Step 4: Run test, verifieer dat 'ie slaagt**

Run: `python3 -m pytest tests/test_admin_routes_devices.py -v`
Expected: alle tests slagen.

- [ ] **Step 5: Commit**

```bash
git add admin/app/routers/devices.py tests/test_admin_routes_devices.py
git commit -m "feat: /api/devices geeft is_mirror/is_camera/camera_stream_url terug"
```

---

## Task 3: Check-in persisteert de rol-vlaggen en stream-URL

**Files:**
- Modify: `admin/app/main.py`
- Test: `tests/test_admin_routes_devices.py`

**Interfaces:**
- Consumes: `devices.is_mirror`/`is_camera`/`camera_stream_url` (Task 1); `client.app.state.bridge._on_device_info(device_uuid, info_dict)` (bestaand testpad, roept `_handle_device_info`'s `handle` rechtstreeks aan).
- Produces: een check-in-payload met `is_mirror`/`is_camera`/`camera_stream_url` wordt correct in `devices` geschreven, zowel bij een nieuw apparaat (INSERT) als een bestaand (UPDATE). Ontbrekende velden (oude agents) defaulten naar `is_mirror=True`, `is_camera=False`.

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_admin_routes_devices.py` (na `test_device_info_checkin_creates_a_new_device`):

```python
def test_device_info_checkin_stores_camera_role_and_stream_url(tmp_path):
    client = _client(tmp_path, real_bridge=True)

    client.app.state.bridge._on_device_info(
        "camera-device-uuid",
        {
            "name": "MacBook camera",
            "platform": "darwin",
            "git_sha": "abc1234",
            "is_mirror": False,
            "is_camera": True,
            "camera_stream_url": "http://192.168.1.50:8080/stream",
        },
    )

    devices = client.get("/api/devices").json()
    assert len(devices) == 1
    assert devices[0]["is_mirror"] is False
    assert devices[0]["is_camera"] is True
    assert devices[0]["camera_stream_url"] == "http://192.168.1.50:8080/stream"


def test_device_info_checkin_without_role_fields_defaults_to_mirror_only(tmp_path):
    """Backward compat: een oude agent die nog geen is_mirror/is_camera
    stuurt mag een bestaand of nieuw apparaat niet naar camera-only zetten."""
    client = _client(tmp_path, real_bridge=True)

    client.app.state.bridge._on_device_info(
        "old-agent-uuid", {"name": "Oude node", "platform": "linux", "git_sha": "abc1234"}
    )

    devices = client.get("/api/devices").json()
    assert devices[0]["is_mirror"] is True
    assert devices[0]["is_camera"] is False
    assert devices[0]["camera_stream_url"] is None


def test_device_info_checkin_updates_camera_stream_url_on_existing_device(tmp_path):
    client = _client(tmp_path, real_bridge=True)
    db = client.app.state.db
    _seed_device(db, device_uuid="cam-1", name="MacBook camera")

    client.app.state.bridge._on_device_info(
        "cam-1",
        {
            "name": "hostname-genegeerd",
            "platform": "darwin",
            "git_sha": "def456",
            "is_mirror": False,
            "is_camera": True,
            "camera_stream_url": "http://192.168.1.51:8080/stream",
        },
    )

    devices = client.get("/api/devices").json()
    assert devices[0]["is_camera"] is True
    assert devices[0]["camera_stream_url"] == "http://192.168.1.51:8080/stream"
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `python3 -m pytest tests/test_admin_routes_devices.py::test_device_info_checkin_stores_camera_role_and_stream_url tests/test_admin_routes_devices.py::test_device_info_checkin_without_role_fields_defaults_to_mirror_only tests/test_admin_routes_devices.py::test_device_info_checkin_updates_camera_stream_url_on_existing_device -v`
Expected: FAIL — `_handle_device_info` schrijft de nieuwe velden nog niet weg (INSERT/UPDATE-statements missen de kolommen, dus de assertions op `is_camera`/`camera_stream_url` falen).

- [ ] **Step 3: Breid `_handle_device_info` uit**

In `admin/app/main.py`, vervang de hele `_handle_device_info`-functie:

```python
def _handle_device_info(conn, app):
    def handle(device_uuid, info):
        name = info.get("name")
        platform = info.get("platform", "")
        git_sha = info.get("git_sha")
        is_mirror = int(bool(info.get("is_mirror", True)))
        is_camera = int(bool(info.get("is_camera", False)))
        camera_stream_url = info.get("camera_stream_url")
        if not isinstance(name, str) or not name:
            return
        existing = conn.execute("SELECT id FROM devices WHERE device_uuid = ?", (device_uuid,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO devices (device_uuid, name, platform, git_sha, last_seen_at, "
                "is_mirror, is_camera, camera_stream_url) VALUES (?, ?, ?, ?, datetime('now'), ?, ?, ?)",
                (device_uuid, name, platform, git_sha, is_mirror, is_camera, camera_stream_url),
            )
        else:
            # Bewust: 'name' NIET overschrijven -- een gebruiker die het
            # apparaat in de beheerpagina hernoemd heeft, wil niet dat de
            # eerstvolgende checkin dat weer terugzet naar de hostname.
            conn.execute(
                "UPDATE devices SET platform = ?, git_sha = ?, last_seen_at = datetime('now'), "
                "is_mirror = ?, is_camera = ?, camera_stream_url = ? WHERE device_uuid = ?",
                (platform, git_sha, is_mirror, is_camera, camera_stream_url, device_uuid),
            )
        conn.commit()
        # Nudge het apparaat om meteen een update-check te doen (in plaats
        # van te wachten op AGENT_UPDATE_CHECK_INTERVAL_SECONDS) -- spec-eis
        # ("interval + directe MQTT-duw"), en de enige plek waar we weten
        # dát een apparaat net iets van zich liet horen. app.state.bridge
        # bestaat nog niet op het moment dat deze closure gebouwd wordt (zie
        # create_app hieronder), vandaar de indirectie via `app` i.p.v. de
        # bridge direct door te geven -- zelfde patroon als
        # _republish_retained_config.
        app.state.bridge.publish_device_update_check()
    return handle
```

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `python3 -m pytest tests/test_admin_routes_devices.py -v`
Expected: alle tests slagen (11 stuks — 8 bestaand + 3 nieuw).

- [ ] **Step 5: Commit**

```bash
git add admin/app/main.py tests/test_admin_routes_devices.py
git commit -m "feat: check-in persisteert is_mirror/is_camera/camera_stream_url"
```

---

## Task 4: Agent rapporteert rol + camera-stream-URL

**Files:**
- Modify: `mirror_node/agent.py`
- Test: `tests/test_mirror_agent.py`

**Interfaces:**
- Consumes: niets nieuws (blijft losstaand van backend-code).
- Produces: `build_checkin_payload(name, platform, git_sha, is_mirror=True, is_camera=False, camera_stream_url=None)` — de JSON-payload die naar `device-info/{uuid}` gepubliceerd wordt (gelezen door Task 3's `_handle_device_info` in productie, niet in tests — tests roepen `_on_device_info` rechtstreeks aan). `_detect_local_ip(host)` — nieuwe helper, geeft het lokale LAN-IP terug via een UDP-`connect()`-truc.

- [ ] **Step 1: Schrijf de falende tests**

Vervang in `tests/test_mirror_agent.py` de bestaande `test_build_checkin_payload_shape`-test door:

```python
def test_build_checkin_payload_shape():
    payload = build_checkin_payload(name="Oude MacBook", platform="darwin", git_sha="abc1234")
    assert json.loads(payload) == {
        "name": "Oude MacBook",
        "platform": "darwin",
        "git_sha": "abc1234",
        "is_mirror": True,
        "is_camera": False,
        "camera_stream_url": None,
    }


def test_build_checkin_payload_includes_camera_role():
    payload = build_checkin_payload(
        name="MacBook camera",
        platform="darwin",
        git_sha="abc1234",
        is_mirror=False,
        is_camera=True,
        camera_stream_url="http://192.168.1.50:8080/stream",
    )
    assert json.loads(payload) == {
        "name": "MacBook camera",
        "platform": "darwin",
        "git_sha": "abc1234",
        "is_mirror": False,
        "is_camera": True,
        "camera_stream_url": "http://192.168.1.50:8080/stream",
    }


def test_detect_local_ip_uses_udp_getsockname(monkeypatch):
    class FakeSocket:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def connect(self, addr):
            self.connected_to = addr

        def getsockname(self):
            return ("192.168.178.80", 54321)

    monkeypatch.setattr(agent_module.socket, "socket", FakeSocket)

    assert agent_module._detect_local_ip("10.10.107.10") == "192.168.178.80"
```

(De `import json`/`import mirror_node.agent as agent_module`/`from mirror_node.agent import build_checkin_payload, ...`-imports bovenaan het bestand bestaan al en blijven ongewijzigd.)

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `python3 -m pytest tests/test_mirror_agent.py -v`
Expected: `test_build_checkin_payload_shape` FAIL (payload mist de nieuwe velden), `test_build_checkin_payload_includes_camera_role` FAIL (`TypeError: unexpected keyword argument`), `test_detect_local_ip_uses_udp_getsockname` FAIL (`AttributeError: module has no attribute '_detect_local_ip'`).

- [ ] **Step 3: Implementeer in `mirror_node/agent.py`**

Voeg toe na de bestaande `MIRROR_RESTART_COMMAND`-regel (rond regel 28):

```python
IS_MIRROR = os.environ.get("SPOOKREGIE_IS_MIRROR", "1") == "1"
IS_CAMERA = os.environ.get("SPOOKREGIE_IS_CAMERA", "0") == "1"
CAMERA_SERVER_PORT = int(os.environ.get("CAMERA_SERVER_PORT", "8080"))
```

Vervang `build_checkin_payload`:

```python
def build_checkin_payload(name, platform, git_sha, is_mirror=True, is_camera=False, camera_stream_url=None):
    return json.dumps({
        "name": name,
        "platform": platform,
        "git_sha": git_sha,
        "is_mirror": is_mirror,
        "is_camera": is_camera,
        "camera_stream_url": camera_stream_url,
    })
```

Voeg een nieuwe helper toe (bijvoorbeeld direct na `_current_git_sha`):

```python
def _detect_local_ip(host):
    """Bepaalt het eigen LAN-IP door een UDP-socket te 'verbinden' naar
    `host` -- UDP connect() verstuurt geen pakket (puur een lokale
    routebepaling), dus dit werkt ook als host (tijdelijk) onbereikbaar is.
    Poort is arbitrair (1), wordt nooit gebruikt."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((host, 1))
        return sock.getsockname()[0]
```

Werk `do_checkin()` binnen `main()` bij:

```python
    def do_checkin():
        git_sha = _current_git_sha(REPO_DIR) or "onbekend"
        camera_stream_url = None
        if IS_CAMERA:
            camera_stream_url = f"http://{_detect_local_ip(MQTT_HOST)}:{CAMERA_SERVER_PORT}/stream"
        payload = build_checkin_payload(
            name=socket.gethostname(),
            platform=sys.platform,
            git_sha=git_sha,
            is_mirror=IS_MIRROR,
            is_camera=IS_CAMERA,
            camera_stream_url=camera_stream_url,
        )
        client.publish(topics.device_info(device_uuid), payload, retain=True)
```

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `python3 -m pytest tests/test_mirror_agent.py -v`
Expected: alle tests slagen.

- [ ] **Step 5: Commit**

```bash
git add mirror_node/agent.py tests/test_mirror_agent.py
git commit -m "feat: agent rapporteert is_mirror/is_camera/camera_stream_url"
```

---

## Task 5: `mirror_node/camera_server.py` — lichtgewicht MJPEG-server

**Files:**
- Create: `mirror_node/camera_server.py`
- Test: `tests/test_mirror_camera_server.py`

**Interfaces:**
- Consumes: `open_camera(source, camera_index=0)` uit `mirror_node/camera.py` (bestaand); `MJPEGStreamer(port)` met `.start()`/`.stop()`/`.publish_frame(frame)` uit `mirror_node/stream.py` (bestaand); `setup_logging(name, log_dir)` uit `shared/logging_setup.py` (bestaand).
- Produces: `read_frame_with_reopen(cap, source, consecutive_failures, logger, max_failures=30)` — pure genoeg te testen zonder een echte camera. `main()` — entrypoint voor `python -m mirror_node.camera_server`, gebruikt door Task 6's service-installatie.

- [ ] **Step 1: Schrijf de falende tests**

Maak `tests/test_mirror_camera_server.py`:

```python
import logging
from unittest.mock import MagicMock

from mirror_node.camera_server import read_frame_with_reopen


def test_read_frame_with_reopen_returns_frame_on_success():
    cap = MagicMock()
    cap.read.return_value = (True, "FRAME")
    logger = logging.getLogger("test-camera-server")

    frame, new_cap, failures = read_frame_with_reopen(cap, "0", 0, logger)

    assert frame == "FRAME"
    assert new_cap is cap
    assert failures == 0


def test_read_frame_with_reopen_counts_failures_without_reopening():
    cap = MagicMock()
    cap.read.return_value = (False, None)
    logger = logging.getLogger("test-camera-server")

    frame, new_cap, failures = read_frame_with_reopen(cap, "0", 5, logger, max_failures=30)

    assert frame is None
    assert new_cap is cap
    assert failures == 6
    cap.release.assert_not_called()


def test_read_frame_with_reopen_reopens_after_max_failures(monkeypatch):
    import mirror_node.camera_server as camera_server_module

    cap = MagicMock()
    cap.read.return_value = (False, None)
    reopened_cap = MagicMock()
    monkeypatch.setattr(camera_server_module, "open_camera", lambda source: reopened_cap)
    logger = logging.getLogger("test-camera-server")

    frame, new_cap, failures = read_frame_with_reopen(cap, "0", 29, logger, max_failures=30)

    assert frame is None
    assert new_cap is reopened_cap
    assert failures == 0
    cap.release.assert_called_once()
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `python3 -m pytest tests/test_mirror_camera_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mirror_node.camera_server'`.

- [ ] **Step 3: Implementeer `mirror_node/camera_server.py`**

```python
import os
import time

from mirror_node.camera import open_camera
from mirror_node.stream import MJPEGStreamer
from shared.logging_setup import setup_logging

CAMERA_SOURCE = os.environ.get("CAMERA_SOURCE", "")
CAMERA_SERVER_PORT = int(os.environ.get("CAMERA_SERVER_PORT", "8080"))
LOG_DIR = os.environ.get("LOG_DIR", "./logs")
MAX_FAILURES_BEFORE_REOPEN = 30  # ~2s bij 1/15s sleep tussen mislukte reads


def read_frame_with_reopen(cap, source, consecutive_failures, logger, max_failures=MAX_FAILURES_BEFORE_REOPEN):
    """Eén cyclus: leest een frame van `cap`. Bij een mislukte read wordt de
    faalteller verhoogd; bij `max_failures` op rij wordt de capture heropend
    (nieuwe open_camera(source)) en de teller gereset. Puur genoeg om zonder
    een echte camera te testen -- cap is elk object met .read()/.release().
    Retourneert (frame-of-None, mogelijk-nieuwe cap, nieuwe consecutive_failures)."""
    ok, frame = cap.read()
    if ok:
        return frame, cap, 0
    consecutive_failures += 1
    if consecutive_failures >= max_failures:
        logger.warning("camera levert al %s keer geen frame, capture wordt heropend", consecutive_failures)
        cap.release()
        return None, open_camera(source), 0
    return None, cap, consecutive_failures


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = setup_logging("camera-server", LOG_DIR)
    cap = open_camera(CAMERA_SOURCE)
    streamer = MJPEGStreamer(CAMERA_SERVER_PORT)
    streamer.start()
    logger.info("camera-server gestart op poort %s (bron=%r)", CAMERA_SERVER_PORT, CAMERA_SOURCE)
    consecutive_failures = 0
    try:
        while True:
            frame, cap, consecutive_failures = read_frame_with_reopen(cap, CAMERA_SOURCE, consecutive_failures, logger)
            if frame is not None:
                streamer.publish_frame(frame)
            time.sleep(1 / 15)
    finally:
        streamer.stop()
        cap.release()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `python3 -m pytest tests/test_mirror_camera_server.py -v`
Expected: alle drie de tests slagen.

- [ ] **Step 5: Commit**

```bash
git add mirror_node/camera_server.py tests/test_mirror_camera_server.py
git commit -m "feat: mirror_node/camera_server.py -- lichtgewicht MJPEG-server voor camera-apparaten"
```

---

## Task 6: `deploy/install-agent.sh` — rolvragen + service-wiring

**Files:**
- Modify: `deploy/install-agent.sh`

**Interfaces:**
- Consumes: `mirror_node.camera_server` (Task 5, moet als module aanroepbaar zijn via `.venv/bin/python -m mirror_node.camera_server`).
- Produces: env-bestand met `SPOOKREGIE_IS_MIRROR`, `SPOOKREGIE_IS_CAMERA`, en (bij camera=ja) `CAMERA_SOURCE`; services/LaunchAgents die overeenkomen met de gekozen rol-combinatie.

- [ ] **Step 1: Voeg de rol-vragen toe aan het env-bestand-blok**

In `deploy/install-agent.sh`, vervang het env-vragen-blok (van `if [ ! -f "$ENV_FILE" ]; then` tot en met de `fi` die daarbij hoort, regels 26-68 in de huidige versie) door:

```bash
if [ ! -f "$ENV_FILE" ]; then
  read -rp "MQTT-host: " mqtt_host
  read -rp "MQTT-poort [1883]: " mqtt_port
  mqtt_port="${mqtt_port:-1883}"
  read -rp "MQTT-gebruiker (leeg = geen auth): " mqtt_user
  read -rsp "MQTT-wachtwoord: " mqtt_pass
  echo
  read -rp "MQTT-topic-prefix (leeg = geen): " mqtt_topic_prefix
  read -rp "Beheerpagina-URL [http://localhost:8000]: " backend_url
  backend_url="${backend_url:-http://localhost:8000}"

  read -rp "Draait hier een mirror/beamer? [J/n]: " wants_mirror
  wants_mirror="${wants_mirror:-j}"
  read -rp "Draait hier een camera? [j/N]: " wants_camera
  wants_camera="${wants_camera:-n}"
  if [[ ! "$wants_mirror" =~ ^[jJ] ]] && [[ ! "$wants_camera" =~ ^[jJ] ]]; then
    echo "Kies minstens één rol (mirror of camera) -- geen van beide is niet geldig." >&2
    exit 1
  fi
  is_mirror=0
  [[ "$wants_mirror" =~ ^[jJ] ]] && is_mirror=1
  is_camera=0
  [[ "$wants_camera" =~ ^[jJ] ]] && is_camera=1

  cat > "$ENV_FILE" <<EOF
MQTT_HOST=$mqtt_host
MQTT_PORT=$mqtt_port
MQTT_USER=$mqtt_user
MQTT_PASS=$mqtt_pass
MQTT_TOPIC_PREFIX=$mqtt_topic_prefix
BACKEND_URL=$backend_url
SPOOKREGIE_REPO_DIR=$REPO_DIR
SPOOKREGIE_IS_MIRROR=$is_mirror
SPOOKREGIE_IS_CAMERA=$is_camera
EOF

  # mirror_node opent een echt GUI-venster (cv2, geen -headless build) voor
  # de beamer-output -- dat venster heeft een draaiende desktop-/X-sessie
  # nodig om naartoe te tekenen. Op macOS regelt launchd dit vanzelf (native
  # Cocoa-venster, geen DISPLAY nodig); op Linux draait de service als
  # systemd system-unit, die zonder deze twee variabelen geen idee heeft
  # welke X-sessie te gebruiken (Qt-fout "Could not load ... xcb"). Alleen
  # relevant voor de mirror-rol -- een camera-only apparaat heeft geen GUI.
  if [ "$is_mirror" = "1" ] && [ "$PLATFORM" = "Linux" ]; then
    read -rp "DISPLAY van de desktop-sessie met de beamer eraan [:0]: " display
    display="${display:-:0}"
    read -rp "XAUTHORITY-pad van die sessie [\$HOME/.Xauthority]: " xauthority
    xauthority="${xauthority:-$HOME/.Xauthority}"
    cat >> "$ENV_FILE" <<EOF
DISPLAY=$display
XAUTHORITY=$xauthority
EOF
  fi

  if [ "$is_camera" = "1" ]; then
    read -rp "Camera-apparaat-index (leeg = standaardcamera) []: " camera_source
    cat >> "$ENV_FILE" <<EOF
CAMERA_SOURCE=$camera_source
EOF
  fi

  chmod 600 "$ENV_FILE"
  echo "Configuratie opgeslagen in $ENV_FILE"
else
  echo "Configuratiebestand bestaat al op $ENV_FILE, sla vragen over."
fi
```

Let op: `PLATFORM` wordt al vóór dit blok gezet (regel 22 in de huidige versie, `PLATFORM="$(uname)"` staat al vóór het env-blok sinds de vorige DISPLAY/XAUTHORITY-toevoeging) — geen wijziging nodig aan die volgorde.

- [ ] **Step 2: Lees de env-vlaggen terug bij een bestaand env-bestand**

Meteen na het hele `if [ ! -f "$ENV_FILE" ]; then ... else ... fi`-blok (dus ook van toepassing als het bestand al bestond en de vragen werden overgeslagen), voeg toe:

```bash
# shellcheck disable=SC1090
source <(grep -E '^SPOOKREGIE_IS_(MIRROR|CAMERA)=' "$ENV_FILE")
is_mirror="${SPOOKREGIE_IS_MIRROR:-1}"
is_camera="${SPOOKREGIE_IS_CAMERA:-0}"
```

(`is_mirror`/`is_camera` zijn dan altijd gezet, ongeacht of het bestand net aangemaakt is of al bestond -- de rest van het script (macOS/Linux-branches) gebruikt vanaf hier alleen deze twee variabelen, nooit meer de `wants_mirror`/`wants_camera`-ruwe input.)

- [ ] **Step 3: macOS-branch — camera-LaunchAgent, conditionele mirror-LaunchAgent**

In het `if [ "$PLATFORM" = "Darwin" ]; then`-blok, vervang de twee `launchctl load`-regels aan het eind (huidige regels 139-141) en de twee `cat > .../nl.spookregie.*.plist`-blokken ervoor zodat mirror alleen geïnstalleerd wordt als `is_mirror=1`, en er een nieuw camera-plist bijkomt als `is_camera=1`:

```bash
  if [ "$is_mirror" = "1" ]; then
    cat > "$AGENTS_DIR/nl.spookregie.mirror.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>nl.spookregie.mirror</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LAUNCHER</string>
    <string>mirror_node.main</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
    launchctl load "$AGENTS_DIR/nl.spookregie.mirror.plist"
  fi

  if [ "$is_camera" = "1" ]; then
    cat > "$AGENTS_DIR/nl.spookregie.camera.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>nl.spookregie.camera</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LAUNCHER</string>
    <string>mirror_node.camera_server</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
    launchctl load "$AGENTS_DIR/nl.spookregie.camera.plist"
  fi

  cat > "$AGENTS_DIR/nl.spookregie.agent.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>nl.spookregie.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LAUNCHER</string>
    <string>mirror_node.agent</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MIRROR_RESTART_COMMAND</key><string>launchctl kickstart -k gui/$(id -u)/nl.spookregie.mirror</string>
  </dict>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF

  launchctl load "$AGENTS_DIR/nl.spookregie.agent.plist"
  echo "LaunchAgents geladen. Bekijk status met: launchctl list | grep spookregie"
```

(De `MIRROR_RESTART_COMMAND` in het agent-plist blijft ongewijzigd verwijzen naar `nl.spookregie.mirror` -- bij een camera-only apparaat bestaat die launch-agent dan niet, en faalt `_restart_mirror_node` in `mirror_node/agent.py` stil met een gelogde foutmelding, zoals dat nu al voor elke ontbrekende `MIRROR_RESTART_COMMAND`-target gaat; geen crash.)

- [ ] **Step 4: Linux-branch — camera-service, conditionele mirror-service, libgl1 alleen voor mirror**

In het `elif [ "$PLATFORM" = "Linux" ]; then`-blok:

Maak de `libgl1`-installatie conditioneel op `is_mirror` (alleen mirror-node heeft het GUI-venster nodig):

```bash
  if [ "$is_mirror" = "1" ] && command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y libgl1
  fi
```

Maak de `spookregie-mirror`-service-installatie (unit-bestand + sudoers-drop-in) conditioneel:

```bash
  if [ "$is_mirror" = "1" ]; then
    sudo tee /etc/systemd/system/spookregie-mirror.service > /dev/null <<EOF
[Unit]
Description=Spookregie mirror-node
After=network.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_GROUP
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$REPO_DIR/.venv/bin/python -m mirror_node.main
Restart=always

[Install]
WantedBy=multi-user.target
EOF

    echo "$INSTALL_USER ALL=(root) NOPASSWD: /bin/systemctl restart spookregie-mirror" \
      | sudo tee /etc/sudoers.d/spookregie >/dev/null
    sudo chmod 440 /etc/sudoers.d/spookregie
  fi
```

Voeg een nieuw, conditioneel camera-service-blok toe (na het mirror-blok, vóór het agent-service-blok):

```bash
  if [ "$is_camera" = "1" ]; then
    sudo tee /etc/systemd/system/spookregie-camera.service > /dev/null <<EOF
[Unit]
Description=Spookregie camera-server
After=network.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$INSTALL_GROUP
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$REPO_DIR/.venv/bin/python -m mirror_node.camera_server
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  fi
```

De `spookregie-agent`-service (`Environment="MIRROR_RESTART_COMMAND=sudo -n /bin/systemctl restart spookregie-mirror"`) en de afsluitende `daemon-reload`/`enable --now`-regels blijven ongewijzigd qua inhoud, maar `enable --now` moet nu de juiste combinatie starten:

```bash
  sudo systemctl daemon-reload
  services_to_enable="spookregie-agent"
  [ "$is_mirror" = "1" ] && services_to_enable="$services_to_enable spookregie-mirror"
  [ "$is_camera" = "1" ] && services_to_enable="$services_to_enable spookregie-camera"
  # shellcheck disable=SC2086
  sudo systemctl enable --now $services_to_enable
  echo "systemd-services actief ($services_to_enable). Bekijk status met: systemctl status $services_to_enable"
```

(Vervangt de bestaande `sudo systemctl enable --now spookregie-mirror spookregie-agent`-regel en de `echo`-regel erna.)

- [ ] **Step 5: Syntax- en lint-check**

Run: `bash -n deploy/install-agent.sh`
Expected: geen output (geldige syntax).

Run: `shellcheck deploy/install-agent.sh`
Expected: geen findings (of alleen al bestaande, niet door deze wijziging geïntroduceerde warnings — vergelijk met de staat vóór deze task als twijfel bestaat).

- [ ] **Step 6: Commit**

```bash
git add deploy/install-agent.sh
git commit -m "feat: install-agent.sh vraagt mirror/camera-rol en installeert de juiste services"
```

---

## Task 7: Frontend — `Device`-type en API-client

**Files:**
- Modify: `admin/frontend/src/types.ts`
- Modify: `admin/frontend/src/api/devices.ts`

**Interfaces:**
- Produces: `Device` bevat voortaan `is_mirror: boolean`, `is_camera: boolean`, `camera_stream_url: string | null`. Gelezen door Task 8.

- [ ] **Step 1: Werk `Device` bij in `admin/frontend/src/types.ts`**

Vervang de bestaande `Device`-interface:

```ts
export interface Device {
  id: number;
  device_uuid: string;
  name: string;
  platform: string;
  git_sha: string | null;
  last_seen_at: string | null;
  output_id: number | null;
  is_mirror: boolean;
  is_camera: boolean;
  camera_stream_url: string | null;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen output (er zijn nog geen consumers die de nieuwe velden gebruiken, dus dit kan alleen falen als er ergens al een `Device`-literal zonder deze velden gebouwd wordt -- controleer in dat geval `DevicesPage.tsx`'s `_seed`/testdata, maar die bestaan nog niet vóór Task 8).

`admin/frontend/src/api/devices.ts` blijft ongewijzigd: `listDevices()`/`updateDevice()`/`deleteDevice()` geven/ontvangen gewoon het volledige `Device`-object, en `DeviceUpdate` (`{ name, output_id }`) hoeft niet uitgebreid te worden -- de rol-vlaggen zijn read-only vanuit de UI (gezet door check-in, niet door een PUT).

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/types.ts
git commit -m "feat: Device-type kent is_mirror/is_camera/camera_stream_url"
```

---

## Task 8: Apparaten-UI — conditionele weergave + "Maak hiervan een source"

**Files:**
- Modify: `admin/frontend/src/pages/DevicesPage.tsx`
- Modify: `admin/frontend/src/pages/DevicesPage.css`
- Test: `admin/frontend/src/pages/DevicesPage.test.tsx` (nieuw)

**Interfaces:**
- Consumes: `Device.is_mirror`/`is_camera`/`camera_stream_url` (Task 7); `createSource(source: SourceDraft): Promise<Source>` uit `admin/frontend/src/api/sources.ts` (bestaand, `SourceDraft = Omit<Source, "id">`).
- Produces: niets voor latere tasks -- dit is de laatste task.

- [ ] **Step 1: Schrijf de falende tests**

Maak `admin/frontend/src/pages/DevicesPage.test.tsx`:

```tsx
// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DevicesPage from "./DevicesPage";
import { listDevices } from "../api/devices";
import { listOutputs } from "../api/outputs";
import { getNodes } from "../api/nodes";
import { createSource } from "../api/sources";
import type { Device } from "../types";

vi.mock("../api/devices", () => ({
  listDevices: vi.fn(),
  updateDevice: vi.fn(),
  deleteDevice: vi.fn(),
}));
vi.mock("../api/outputs", () => ({ listOutputs: vi.fn() }));
vi.mock("../api/nodes", () => ({ getNodes: vi.fn() }));
vi.mock("../api/sources", () => ({ createSource: vi.fn() }));

const MIRROR_DEVICE: Device = {
  id: 1,
  device_uuid: "mirror-uuid",
  name: "Hallo1",
  platform: "linux",
  git_sha: "abc1234",
  last_seen_at: "2026-09-01 20:00:00",
  output_id: null,
  is_mirror: true,
  is_camera: false,
  camera_stream_url: null,
};

const CAMERA_DEVICE: Device = {
  id: 2,
  device_uuid: "camera-uuid",
  name: "MacBook camera",
  platform: "darwin",
  git_sha: "def5678",
  last_seen_at: "2026-09-01 20:05:00",
  output_id: null,
  is_mirror: false,
  is_camera: true,
  camera_stream_url: "http://192.168.1.50:8080/stream",
};

beforeEach(() => {
  vi.mocked(listOutputs).mockResolvedValue([]);
  vi.mocked(getNodes).mockResolvedValue({});
});

describe("DevicesPage -- conditionele rol-weergave", () => {
  it("toont de output-picker voor een mirror-apparaat, geen camera-rij", async () => {
    vi.mocked(listDevices).mockResolvedValue([MIRROR_DEVICE]);
    render(<DevicesPage />);

    expect(await screen.findByText("Hallo1")).toBeInTheDocument();
    expect(screen.getByText("Geen output")).toBeInTheDocument();
    expect(screen.queryByText("Maak hiervan een source")).not.toBeInTheDocument();
  });

  it("toont de stream-URL en een 'Maak hiervan een source'-knop voor een camera-apparaat, geen output-picker", async () => {
    vi.mocked(listDevices).mockResolvedValue([CAMERA_DEVICE]);
    render(<DevicesPage />);

    expect(await screen.findByText("MacBook camera")).toBeInTheDocument();
    expect(screen.getByText("http://192.168.1.50:8080/stream")).toBeInTheDocument();
    expect(screen.getByText("Maak hiervan een source")).toBeInTheDocument();
    expect(screen.queryByText("Geen output")).not.toBeInTheDocument();
  });

  it("'Maak hiervan een source' roept createSource aan met de stream-URL", async () => {
    vi.mocked(listDevices).mockResolvedValue([CAMERA_DEVICE]);
    vi.mocked(createSource).mockResolvedValue({
      id: 9,
      name: "MacBook camera camera",
      kind: "camera_stream",
      value: "http://192.168.1.50:8080/stream",
      canvas_x: 0,
      canvas_y: 0,
    });
    render(<DevicesPage />);

    await userEvent.click(await screen.findByText("Maak hiervan een source"));

    await waitFor(() =>
      expect(createSource).toHaveBeenCalledWith({
        name: "MacBook camera camera",
        kind: "camera_stream",
        value: "http://192.168.1.50:8080/stream",
        canvas_x: 0,
        canvas_y: 0,
      }),
    );
  });
});
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `cd admin/frontend && npx vitest run src/pages/DevicesPage.test.tsx`
Expected: FAIL — de output-picker wordt nu altijd getoond (ook voor `CAMERA_DEVICE`), er is geen camera-rij/knop, `createSource` wordt nergens aangeroepen.

- [ ] **Step 3: Werk `DevicesPage.tsx` bij**

Voeg de import toe (bovenaan, bij de overige `api/*`-imports):

```tsx
import { createSource } from "../api/sources";
```

Voeg de handler toe, in de component-body (bijvoorbeeld direct na `handleDelete`):

```tsx
  async function handleCreateSourceFromDevice(device: Device) {
    if (!device.camera_stream_url) return;
    setSaving(true);
    try {
      await createSource({
        name: `${device.name} camera`,
        kind: "camera_stream",
        value: device.camera_stream_url,
        canvas_x: 0,
        canvas_y: 0,
      });
      showNotice("Source aangemaakt.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Aanmaken is mislukt.");
    } finally {
      setSaving(false);
    }
  }
```

Vervang in de `devices.map((device) => { ... })`-render het bestaande `<select className="devices-field__select" ...>...</select>`-blok (de output-picker) door een conditionele variant, en voeg de camera-rij toe na de sluitende `</div>` van `.devices-row` (dus binnen dezelfde `<div key={device.id}>`-wrapper):

```tsx
              {device.is_mirror ? (
                <select
                  className="devices-field__select"
                  value={draft.output_id ?? ""}
                  onChange={(e) => updateDraft(device.id, { output_id: e.target.value ? Number(e.target.value) : null })}
                >
                  <option value="">Geen output</option>
                  {outputs.map((output) => (
                    <option key={output.id} value={output.id}>
                      {output.name}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="devices-field__meta">— (camera-only)</span>
              )}
              <button type="button" onClick={() => handleSave(device.id)} disabled={saving}>
                Opslaan
              </button>
              <button type="button" onClick={() => handleDelete(device.id)} disabled={saving}>
                Verwijderen
              </button>
            </div>
            {device.is_camera && (
              <div className="devices-camera-row">
                <span className="devices-camera-row__url">
                  {device.camera_stream_url ?? "Nog geen stream-URL ontvangen"}
                </span>
                <button
                  type="button"
                  onClick={() => handleCreateSourceFromDevice(device)}
                  disabled={saving || !device.camera_stream_url}
                >
                  Maak hiervan een source
                </button>
              </div>
            )}
```

(Let op: de laatste `</div>` hierboven sluit de bestaande `.devices-row`; daarna volgt — nog steeds binnen de `<div key={device.id}>`-wrapper van de `.map()` — de nieuwe, conditionele `.devices-camera-row`. Zorg dat de buitenste `<div key={device.id}>` uit de bestaande code intact blijft en nu zowel `.devices-row` als, optioneel, `.devices-camera-row` bevat.)

- [ ] **Step 4: Voeg CSS toe aan `DevicesPage.css`**

Voeg toe aan het eind van `admin/frontend/src/pages/DevicesPage.css`:

```css
.devices-camera-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.3rem 0 0.3rem 2.6rem;
  font-size: 0.8rem;
}

.devices-camera-row__url {
  font-family: monospace;
  color: var(--ash);
}
```

- [ ] **Step 5: Run tests, verifieer dat ze slagen**

Run: `cd admin/frontend && npx vitest run src/pages/DevicesPage.test.tsx`
Expected: alle drie de tests slagen.

Run ook de volledige frontend-testsuite en typecheck om regressies uit te sluiten:

Run: `cd admin/frontend && npx vitest run && npx tsc --noEmit`
Expected: alle tests slagen, geen typefouten.

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/pages/DevicesPage.tsx admin/frontend/src/pages/DevicesPage.css admin/frontend/src/pages/DevicesPage.test.tsx
git commit -m "feat: Apparaten toont per rol een output-picker en/of 'Maak hiervan een source'"
```

---

## Na afronding

Geen deploy-stap in dit plan zelf — na alle 8 tasks (backend + frontend) volgt een losse build/deploy-cyclus (`docker compose up -d --build` op lan01, zoals eerder deze sessie) en, voor een nieuw of bestaand camera-apparaat, een `install-agent.sh`-run (nieuw apparaat) of handmatige env-aanvulling + service-herstart (bestaand apparaat, zoals ook bij de DISPLAY/XAUTHORITY-toevoeging eerder gedaan is).
