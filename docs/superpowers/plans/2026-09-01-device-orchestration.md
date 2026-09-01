# Device Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every physical device running `mirror_node` gets a small self-updating agent, registers itself with the admin backend, and is assigned to exactly one physical Output over MQTT — replacing the hardcoded single-node/single-output assumption with a real per-device model.

**Architecture:** A new `devices` table + `/api/devices` CRUD + `DevicesPage.tsx` (same shape as Sources/Outputs) let you see registered devices and assign them to an Output. Devices publish a periodic MQTT checkin (`device-info/{uuid}`) the backend upserts into `devices`; the backend publishes back a retained assignment (`device-assignment/{uuid}`) each device subscribes to for its own `output_id`. `mirror_node/main.py`'s hardcoded `NODE_NAME = "mirror"` becomes a locally-persisted `device_uuid`; a new `mirror_node/agent.py` process handles the checkin publish and a periodic + MQTT-nudged `git pull` + service restart. A one-time install script (macOS + Linux) registers both processes with the OS service manager.

**Tech Stack:** FastAPI + SQLite (backend), React + TypeScript (frontend), paho-mqtt (mirror_node + agent), bash (install script), launchd/systemd (process supervision).

**Spec:** docs/superpowers/specs/2026-09-01-device-orchestration-design.md

## Global Constraints

- No DB foreign keys — all cascade/disconnect cleanup happens in application code (route handlers), never `PRAGMA foreign_keys` or `REFERENCES`. Deleting an Output must unlink (`output_id = NULL`) any `devices` row pointing at it, in application code, before the output row is removed.
- FastAPI route params that take a numeric id use the `{id:int}` typed converter, never a bare `{id}`.
- `devices` is a brand-new table with no prior schema to migrate from — its seed/creation logic follows the row-count-gated idempotent pattern already used by `sources`/`outputs` (`admin/app/db.py`'s `_migrate_outputs`/`_migrate_sources`), **not** a `PRAGMA user_version` bump — that mechanism is reserved for renames/restructures of tables that already existed with different shape (the current chain runs through version 7; this plan does not add a version 8).
- Triggers stay strictly pulse-based (rising-edge only, never sustained-on) and `repeat_while` playback stays level-based — this plan does not touch that mechanism at all; do not let device-assignment code (also MQTT-driven) get confused with it.
- No automatic rollback on a bad agent update — a failed `git pull`/restart is retried on the next cycle, nothing more. Do not add rollback logic.
- The GitHub repo has been made public (an already-completed operational step, not part of this plan) — the install script and agent do not need any git credentials.
- Run backend tests with `.venv/bin/python -m pytest tests/ -q` from the repo root (the system `python3` lacks `paho`/`cv2` — always use the repo's `.venv`). Run frontend typecheck with `cd admin/frontend && npx tsc --noEmit` and tests with `npm test`.

---

### Task 1: `devices` table + `/api/devices` CRUD

**Files:**
- Modify: `admin/app/db.py`
- Create: `admin/app/routers/devices.py`
- Modify: `admin/app/main.py` (register `devices_router`)
- Test: `tests/test_admin_db.py` (append)
- Test: `tests/test_admin_routes_devices.py` (new)

**Interfaces:**
- Produces: `devices` table (`id, device_uuid, name, platform, git_sha, last_seen_at, output_id`). `GET /api/devices`, `PUT /api/devices/{device_id:int}` (body `{name, output_id}`, `output_id` may be `null`), `DELETE /api/devices/{device_id:int}`.
- Consumes: nothing from other tasks. This task's `PUT` route does NOT yet publish an MQTT assignment message (that wiring is Task 4, once the bridge method exists) — for now it only writes the DB row. Note this explicitly in the route with a comment so Task 4's diff is a small, obvious addition, not a rewrite.

- [ ] **Step 1: Write the failing migration test**

Add to `tests/test_admin_db.py`:

```python
def test_devices_table_starts_empty(tmp_path):
    conn = init_db(str(tmp_path / "admin.db"))
    assert conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0


def test_devices_table_survives_a_second_init_db_call(tmp_path):
    db_path = str(tmp_path / "admin.db")
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO devices (device_uuid, name, platform) VALUES ('abc-123', 'Oude MacBook', 'darwin')"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(db_path)
    rows = conn2.execute("SELECT device_uuid, name FROM devices").fetchall()
    assert rows == [("abc-123", "Oude MacBook")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k devices -v`
Expected: FAIL with `sqlite3.OperationalError: no such table: devices`

- [ ] **Step 3: Add the `devices` table to `admin/app/db.py`**

Add this `CREATE TABLE` call in `init_db`, right after the existing `output_connections` block (after line 91, before the `mirror_scare_video_config` block):

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_uuid TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT '',
            git_sha TEXT,
            last_seen_at TEXT,
            output_id INTEGER
        )"""
    )
```

No migration function needed — `CREATE TABLE IF NOT EXISTS` is already idempotent for a brand-new table with no prior shape to reconcile (unlike `sources`/`outputs`, there is no legacy data to seed from, so there's no `_migrate_devices` function to write).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k devices -v`
Expected: PASS

- [ ] **Step 5: Write the failing routes test**

Create `tests/test_admin_routes_devices.py`:

```python
from fastapi.testclient import TestClient

from admin.app.config import Settings
from admin.app.main import create_app


def _client(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "admin.db"),
        log_dir=str(tmp_path / "logs"),
        admin_password="testwachtwoord",
        port=8000,
    )
    app = create_app(settings)
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client


def _seed_device(db, device_uuid="abc-123", name="Oude MacBook", platform="darwin"):
    db.execute(
        "INSERT INTO devices (device_uuid, name, platform) VALUES (?, ?, ?)",
        (device_uuid, name, platform),
    )
    db.commit()
    return db.execute("SELECT id FROM devices WHERE device_uuid = ?", (device_uuid,)).fetchone()[0]


def test_list_devices_returns_empty_list_initially(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/devices")
    assert response.status_code == 200
    assert response.json() == []


def test_list_devices_returns_seeded_device(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db)
    response = client.get("/api/devices")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == device_id
    assert body[0]["device_uuid"] == "abc-123"
    assert body[0]["name"] == "Oude MacBook"
    assert body[0]["platform"] == "darwin"
    assert body[0]["output_id"] is None


def test_update_device_renames_and_assigns_output(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db)
    output = client.post("/api/outputs", json={"name": "Spiegel"}).json()

    response = client.put(f"/api/devices/{device_id}", json={"name": "Voordeur-spiegel", "output_id": output["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Voordeur-spiegel"
    assert body["output_id"] == output["id"]


def test_update_device_can_unassign_with_null_output_id(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db)
    output = client.post("/api/outputs", json={"name": "Spiegel"}).json()
    client.put(f"/api/devices/{device_id}", json={"name": "Voordeur-spiegel", "output_id": output["id"]})

    response = client.put(f"/api/devices/{device_id}", json={"name": "Voordeur-spiegel", "output_id": None})

    assert response.status_code == 200
    assert response.json()["output_id"] is None


def test_update_device_returns_404_for_unknown_id(tmp_path):
    client = _client(tmp_path)
    response = client.put("/api/devices/999", json={"name": "X", "output_id": None})
    assert response.status_code == 404


def test_delete_device_removes_it(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db)

    response = client.delete(f"/api/devices/{device_id}")

    assert response.status_code == 200
    assert client.get("/api/devices").json() == []


def test_devices_route_requires_login(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "admin.db"), log_dir=str(tmp_path / "logs"),
        admin_password="testwachtwoord", port=8000,
    )
    app = create_app(settings)
    client = TestClient(app)
    response = client.get("/api/devices")
    assert response.status_code == 401
```

- [ ] **Step 6: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_devices.py -v`
Expected: FAIL with 404 (no such route) on every test

- [ ] **Step 7: Write `admin/app/routers/devices.py`**

```python
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_DEVICE_COLUMNS = "id, device_uuid, name, platform, git_sha, last_seen_at, output_id"


def _row_to_device(row):
    return {
        "id": row[0],
        "device_uuid": row[1],
        "name": row[2],
        "platform": row[3],
        "git_sha": row[4],
        "last_seen_at": row[5],
        "output_id": row[6],
    }


@router.get("/api/devices")
def list_devices_route(request: Request):
    rows = request.app.state.db.execute(f"SELECT {_DEVICE_COLUMNS} FROM devices ORDER BY name").fetchall()
    return [_row_to_device(r) for r in rows]


@router.put("/api/devices/{device_id:int}")
async def update_device_route(device_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM devices WHERE id = ?", (device_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Apparaat niet gevonden")
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name mag niet leeg zijn")
    output_id = body.get("output_id")
    db.execute("UPDATE devices SET name = ?, output_id = ? WHERE id = ?", (name, output_id, device_id))
    db.commit()
    # Publiceert (nog) geen MQTT-toewijzing -- dat gebeurt vanaf Task 4,
    # zodra MqttBridge een publish_device_assignment-methode heeft.
    row = db.execute(f"SELECT {_DEVICE_COLUMNS} FROM devices WHERE id = ?", (device_id,)).fetchone()
    return _row_to_device(row)


@router.delete("/api/devices/{device_id:int}")
def delete_device_route(device_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM devices WHERE id = ?", (device_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Apparaat niet gevonden")
    db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    db.commit()
    return {"ok": True}
```

- [ ] **Step 8: Register the router in `admin/app/main.py`**

Add the import alongside the other router imports (after `from admin.app.routers import sources as sources_router`):

```python
from admin.app.routers import devices as devices_router
```

Add the registration alongside the other `include_router` calls (after `app.include_router(sources_router.router)`):

```python
    app.include_router(devices_router.router)
```

- [ ] **Step 9: Run all tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py tests/test_admin_routes_devices.py -v`
Expected: all PASS

- [ ] **Step 10: Commit**

```bash
git add admin/app/db.py admin/app/routers/devices.py admin/app/main.py tests/test_admin_db.py tests/test_admin_routes_devices.py
git commit -m "feat: devices-tabel + CRUD (naam hernoemen, output koppelen)"
```

---

### Task 2: MQTT-contract — device-topics

**Files:**
- Modify: `shared/mqtt_contract.py`
- Test: `tests/test_mqtt_contract.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `Topics.device_info_wildcard` (property, `"control/mirror/device-info/+"`), `Topics.device_info(device_uuid)` (method), `Topics.device_assignment(device_uuid)` (method, `"control/mirror/device-assignment/{device_uuid}"`), `Topics.device_update_check` (property, `"control/mirror/device-update-check"`). Task 3 (mqtt_bridge) and Task 7 (mirror_node) both use these.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mqtt_contract.py`:

```python
def test_device_info_topic():
    topics = Topics()
    assert topics.device_info("abc-123") == "control/mirror/device-info/abc-123"


def test_device_info_topic_respects_prefix():
    topics = Topics(prefix="halloween")
    assert topics.device_info("abc-123") == "halloween/control/mirror/device-info/abc-123"


def test_device_info_wildcard_topic():
    topics = Topics()
    assert topics.device_info_wildcard == "control/mirror/device-info/+"


def test_device_assignment_topic():
    topics = Topics()
    assert topics.device_assignment("abc-123") == "control/mirror/device-assignment/abc-123"


def test_device_update_check_topic():
    topics = Topics()
    assert topics.device_update_check == "control/mirror/device-update-check"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py -k device -v`
Expected: FAIL with `AttributeError: 'Topics' object has no attribute 'device_info'`

- [ ] **Step 3: Add the properties/methods to `shared/mqtt_contract.py`**

Add these to the `Topics` class, after the existing `control_mirror_ha_sensor_state` property (after line 49):

```python
    @property
    def device_info_wildcard(self) -> str:
        return self._p("control/mirror/device-info/+")

    def device_info(self, device_uuid: str) -> str:
        return self._p(f"control/mirror/device-info/{device_uuid}")

    def device_assignment(self, device_uuid: str) -> str:
        return self._p(f"control/mirror/device-assignment/{device_uuid}")

    @property
    def device_update_check(self) -> str:
        return self._p("control/mirror/device-update-check")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py -k device -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shared/mqtt_contract.py tests/test_mqtt_contract.py
git commit -m "feat: MQTT-topics voor device-checkin en output-toewijzing"
```

---

### Task 3: `MqttBridge` — device-info-ontvangst + toewijzing-publish

**Files:**
- Modify: `admin/app/mqtt_bridge.py`
- Test: `tests/test_admin_mqtt_bridge.py` (append)

**Interfaces:**
- Consumes: `Topics.device_info_wildcard`, `Topics.device_info(uuid)`, `Topics.device_assignment(uuid)` from Task 2.
- Produces: `MqttBridge.__init__` gains an optional `on_device_info=None` constructor parameter — a callable `(device_uuid: str, info: dict) -> None`, invoked from `_on_message` whenever a message arrives on a `device-info/{uuid}` topic (payload parsed as JSON first). Subscribes to `Topics.device_info_wildcard` in `_on_connect`. New method `publish_device_assignment(device_uuid, output_id)` — publishes retained `{"output_id": output_id}` to `Topics.device_assignment(device_uuid)`. Task 4 wires `on_device_info` in `main.py` and calls `publish_device_assignment` from `devices.py`'s `PUT` route.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_admin_mqtt_bridge.py`:

```python
def test_start_subscribes_to_device_info_wildcard(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)
    bridge = MqttBridge(_settings(), tracker=object())
    bridge.start()
    client = FakeMqttClient.instances[-1]
    client.on_connect(client, None, None, 0)
    assert "control/mirror/device-info/+" in client.subscribed


def test_on_message_calls_on_device_info_for_device_info_topic(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)
    received = []
    bridge = MqttBridge(
        _settings(), tracker=object(),
        on_device_info=lambda device_uuid, info: received.append((device_uuid, info)),
    )
    bridge.start()
    client = FakeMqttClient.instances[-1]

    class FakeMsg:
        topic = "control/mirror/device-info/abc-123"
        payload = json.dumps({"name": "Oude MacBook", "platform": "darwin", "git_sha": "deadbeef"}).encode()

    client.on_message(client, None, FakeMsg())

    assert received == [("abc-123", {"name": "Oude MacBook", "platform": "darwin", "git_sha": "deadbeef"})]


def test_on_message_ignores_malformed_device_info_payload(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)
    received = []
    bridge = MqttBridge(
        _settings(), tracker=object(),
        on_device_info=lambda device_uuid, info: received.append((device_uuid, info)),
    )
    bridge.start()
    client = FakeMqttClient.instances[-1]

    class FakeMsg:
        topic = "control/mirror/device-info/abc-123"
        payload = b"not json"

    client.on_message(client, None, FakeMsg())  # mag niet crashen

    assert received == []


def test_publish_device_assignment_is_retained_with_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)
    bridge = MqttBridge(_settings(mqtt_topic_prefix="halloween"), tracker=object())
    bridge.start()
    client = FakeMqttClient.instances[-1]

    bridge.publish_device_assignment("abc-123", 7)

    topic, payload, retain = client.published[-1]
    assert topic == "halloween/control/mirror/device-assignment/abc-123"
    assert json.loads(payload) == {"output_id": 7}
    assert retain is True
```

Check `_settings()`'s signature in this test file first — if it doesn't already accept `mqtt_topic_prefix` as an override, add `mqtt_topic_prefix=""` to its `base` dict (matching the `RuntimeSettings` constructor) so `_settings(mqtt_topic_prefix="halloween")` works; several existing tests in this file already exercise prefixes (e.g. `test_publish_mirror_graph_uses_configured_prefix`), so this may already work — verify by reading the existing helper before assuming.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_mqtt_bridge.py -k device -v`
Expected: FAIL (`on_device_info` unknown kwarg, or subscribe/publish assertions fail)

- [ ] **Step 3: Implement in `admin/app/mqtt_bridge.py`**

Modify `__init__` (line 17) to accept and store the new callback:

```python
    def __init__(self, settings, tracker, ws_hub=None, loop=None, logger=None, on_connect_extra=None, on_device_info=None):
        self._settings = settings
        self._tracker = tracker
        self._ws_hub = ws_hub
        self._loop = loop
        self._logger = logger
        self._on_connect_extra = on_connect_extra
        self._on_device_info = on_device_info
        self._topics = Topics(prefix=settings.mqtt_topic_prefix)
        self._client = self._build_client(settings)
```

Add the new subscription in `_on_connect` (after `client.subscribe(self._topics.scare_triggered_wildcard)`):

```python
        client.subscribe(self._topics.device_info_wildcard)
```

Modify `_on_message` to dispatch device-info messages before the existing tracker/broadcast logic (insert right after `topic = self._topics.strip_prefix(msg.topic)` and before `payload = msg.payload.decode()` — the device-info branch needs its own payload handling since it's JSON, not the plain string the tracker/broadcast path expects):

```python
    def _on_message(self, client, userdata, msg):
        try:
            topic = self._topics.strip_prefix(msg.topic)
            if topic.startswith("control/mirror/device-info/") and self._on_device_info is not None:
                device_uuid = topic[len("control/mirror/device-info/"):]
                try:
                    info = json.loads(msg.payload.decode())
                except json.JSONDecodeError:
                    return
                if isinstance(info, dict):
                    self._on_device_info(device_uuid, info)
                return
            payload = msg.payload.decode()
            self._tracker.handle_message(topic, payload)
            self._broadcast_to_websockets(topic, payload)
        except Exception:
            pass  # nooit de MQTT-netwerkthread laten crashen
```

Add the new publish method (near the other `publish_*` methods, e.g. after `publish_mirror_ha_sensor_state`):

```python
    def publish_device_assignment(self, device_uuid, output_id):
        self._client.publish(
            self._topics.device_assignment(device_uuid), json.dumps({"output_id": output_id}), retain=True
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_mqtt_bridge.py -v`
Expected: all PASS (including pre-existing tests — confirm no regressions)

- [ ] **Step 5: Commit**

```bash
git add admin/app/mqtt_bridge.py tests/test_admin_mqtt_bridge.py
git commit -m "feat: MqttBridge ontvangt device-checkins, publiceert output-toewijzing"
```

---

### Task 4: Wire devices ⇄ MQTT bridge in `main.py`/`devices.py`

**Files:**
- Modify: `admin/app/main.py`
- Modify: `admin/app/routers/devices.py`
- Test: `tests/test_admin_routes_devices.py` (append)

**Interfaces:**
- Consumes: `MqttBridge(on_device_info=...)` and `MqttBridge.publish_device_assignment` from Task 3.
- Produces: a device that checks in over MQTT appears (or updates) in `GET /api/devices`; `PUT /api/devices/{id}` that changes `output_id` publishes the new assignment.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_routes_devices.py`:

```python
def test_update_device_publishes_assignment_when_output_id_changes(tmp_path, monkeypatch):
    import admin.app.mqtt_bridge as mqtt_bridge_module

    class FakeMqttClient:
        def __init__(self, client_id=None):
            self.published = []
            self.subscribed = []

        def username_pw_set(self, *a, **k):
            pass

        def reconnect_delay_set(self, **k):
            pass

        def connect_async(self, *a, **k):
            pass

        def loop_start(self):
            pass

        def loop_stop(self):
            pass

        def subscribe(self, topic):
            self.subscribed.append(topic)

        def publish(self, topic, payload=None, retain=False):
            self.published.append((topic, payload, retain))

    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db)
    output = client.post("/api/outputs", json={"name": "Spiegel"}).json()

    client.put(f"/api/devices/{device_id}", json={"name": "Voordeur-spiegel", "output_id": output["id"]})

    published = client.app.state.bridge._client.published
    assignment_messages = [p for p in published if "device-assignment/abc-123" in p[0]]
    assert len(assignment_messages) == 1
    import json as jsonlib
    assert jsonlib.loads(assignment_messages[0][1]) == {"output_id": output["id"]}


def test_device_info_checkin_creates_a_new_device(tmp_path):
    client = _client(tmp_path)
    client.app.state.bridge._on_device_info("new-device-uuid", {"name": "Pi Achtertuin", "platform": "linux", "git_sha": "abc1234"})

    devices = client.get("/api/devices").json()
    assert len(devices) == 1
    assert devices[0]["device_uuid"] == "new-device-uuid"
    assert devices[0]["name"] == "Pi Achtertuin"
    assert devices[0]["platform"] == "linux"
    assert devices[0]["git_sha"] == "abc1234"


def test_device_info_checkin_does_not_overwrite_a_user_renamed_device(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db, device_uuid="abc-123", name="Voordeur-spiegel")

    client.app.state.bridge._on_device_info("abc-123", {"name": "hostname-gerapporteerd-door-apparaat", "platform": "darwin", "git_sha": "cafe123"})

    devices = client.get("/api/devices").json()
    assert devices[0]["name"] == "Voordeur-spiegel"
    assert devices[0]["platform"] == "darwin"
    assert devices[0]["git_sha"] == "cafe123"
```

Note this test file's `_client` helper (from Task 1) does not use `monkeypatch` for the plain CRUD tests, but the MQTT-publish test above needs the same `FakeMqttClient` monkeypatch pattern as `tests/test_admin_mqtt_bridge.py` uses — apply `monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)` **before** calling `_client(tmp_path)`, since the fake client must be in place before `create_app` constructs the real `MqttBridge`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_devices.py -k "publishes_assignment or checkin" -v`
Expected: FAIL — `publish_device_assignment` never called (real socket connect attempted or no matching message), `_on_device_info` is `None`/not callable

- [ ] **Step 3: Wire the upsert closure and callback in `admin/app/main.py`**

Add this function near `_get_watched_ha_entities_from_db` (same style — a closure factory over the db connection):

```python
def _handle_device_info(conn):
    def handle(device_uuid, info):
        name = info.get("name")
        platform = info.get("platform", "")
        git_sha = info.get("git_sha")
        if not isinstance(name, str) or not name:
            return
        existing = conn.execute("SELECT id FROM devices WHERE device_uuid = ?", (device_uuid,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO devices (device_uuid, name, platform, git_sha, last_seen_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (device_uuid, name, platform, git_sha),
            )
        else:
            # Bewust: 'name' NIET overschrijven -- een gebruiker die het
            # apparaat in de beheerpagina hernoemd heeft, wil niet dat de
            # eerstvolgende checkin dat weer terugzet naar de hostname.
            conn.execute(
                "UPDATE devices SET platform = ?, git_sha = ?, last_seen_at = datetime('now') WHERE device_uuid = ?",
                (platform, git_sha, device_uuid),
            )
        conn.commit()
    return handle
```

Pass it into the `MqttBridge` constructor (modify the existing `app.state.bridge = MqttBridge(...)` call):

```python
    app.state.bridge = MqttBridge(
        app.state.runtime_settings, app.state.tracker, ws_hub=app.state.ws_hub, logger=app.state.logger,
        on_connect_extra=_republish_retained_config,
        on_device_info=_handle_device_info(app.state.db),
    )
```

- [ ] **Step 4: Wire the assignment-publish call in `admin/app/routers/devices.py`**

Replace the comment-only line in `update_device_route` with an actual call. The updated function body:

```python
@router.put("/api/devices/{device_id:int}")
async def update_device_route(device_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id, device_uuid, output_id FROM devices WHERE id = ?", (device_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Apparaat niet gevonden")
    device_uuid, old_output_id = existing[1], existing[2]
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name mag niet leeg zijn")
    output_id = body.get("output_id")
    db.execute("UPDATE devices SET name = ?, output_id = ? WHERE id = ?", (name, output_id, device_id))
    db.commit()
    if output_id != old_output_id:
        request.app.state.bridge.publish_device_assignment(device_uuid, output_id)
    row = db.execute(f"SELECT {_DEVICE_COLUMNS} FROM devices WHERE id = ?", (device_id,)).fetchone()
    return _row_to_device(row)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_devices.py -v`
Expected: all PASS

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS, paste the literal final summary line into your report.

- [ ] **Step 7: Commit**

```bash
git add admin/app/main.py admin/app/routers/devices.py tests/test_admin_routes_devices.py
git commit -m "feat: device-checkin upsert + output-toewijzing-publish gekoppeld"
```

---

### Task 5: `outputs.py` — apparaten ontkoppelen bij output-verwijdering

**Files:**
- Modify: `admin/app/routers/outputs.py`
- Test: `tests/test_admin_routes_outputs.py` (append)

**Interfaces:**
- Consumes: `devices` table from Task 1.
- Produces: `DELETE /api/outputs/{id:int}` no longer leaves a dangling `devices.output_id` pointing at a deleted output.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_admin_routes_outputs.py` (read the file's existing `_client`/fixture helpers first and match their exact shape rather than assuming — this plan cannot see that file's current helper signatures):

```python
def test_delete_output_unassigns_devices_pointing_at_it(tmp_path):
    client = _client(tmp_path)
    output = client.post("/api/outputs", json={"name": "Spiegel"}).json()
    db = client.app.state.db
    db.execute(
        "INSERT INTO devices (device_uuid, name, platform, output_id) VALUES ('abc-123', 'Oude MacBook', 'darwin', ?)",
        (output["id"],),
    )
    db.commit()

    response = client.delete(f"/api/outputs/{output['id']}")

    assert response.status_code == 200
    devices = client.get("/api/devices").json()
    assert devices[0]["output_id"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_outputs.py -k unassigns_devices -v`
Expected: FAIL — device row still has the old `output_id`, or the delete itself 500s if a DB constraint were involved (it won't, since there are no DB foreign keys, but confirm the assertion fails as expected: `output_id` still equals the deleted output's id)

- [ ] **Step 3: Add the unlink step to `delete_output_route`**

Modify `delete_output_route` in `admin/app/routers/outputs.py` — insert the unlink right after the existing `has_connections` guard check and before `db.execute("DELETE FROM outputs ...")`:

```python
@router.delete("/api/outputs/{output_id:int}")
def delete_output_route(output_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM outputs WHERE id = ?", (output_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Output niet gevonden")
    has_connections = db.execute(
        "SELECT 1 FROM output_connections WHERE output_id = ? LIMIT 1", (output_id,)
    ).fetchone()
    if has_connections is not None:
        raise HTTPException(status_code=400, detail="Output heeft nog verbindingen -- ontkoppel die eerst")
    db.execute("UPDATE devices SET output_id = NULL WHERE output_id = ?", (output_id,))
    db.execute("DELETE FROM outputs WHERE id = ?", (output_id,))
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_outputs.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add admin/app/routers/outputs.py tests/test_admin_routes_outputs.py
git commit -m "fix: output-verwijdering ontkoppelt eerst gekoppelde apparaten"
```

---

### Task 6: `graph_publish.py` — `output_id`-veld verwijderen uit de payload

**Files:**
- Modify: `admin/app/graph_publish.py`
- Test: `tests/test_admin_routes_players.py` (update)

**Interfaces:**
- Consumes: nothing new.
- Produces: the published graph payload is `{players, sources, branches, triggers, output_connections, root_player_id}` — no `output_id` key. Task 7 (`mirror_node/main.py`) stops reading `graph.get("output_id")`.

- [ ] **Step 1: Update the existing test expectations**

In `tests/test_admin_routes_players.py`, four spots reference `output_id` in the expected graph shape:
- Three inline expected-dict literals (around lines 67, 115, 144) each have `"output_id": default_output["id"], "players": ...` — remove the `"output_id": default_output["id"], ` prefix from each so the dict starts directly with `"players":`.
- `test_published_graph_has_the_full_new_shape` (around line 305-314) has `assert graph["output_id"] == default_output["id"]` — replace this line with `assert "output_id" not in graph`.

Read the file first to confirm these are still at the same lines (this plan's line numbers are a starting pointer, not a guarantee — grep for `output_id` in this file to find every occurrence before editing, there should be exactly these four).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py -v`
Expected: FAIL — the four updated assertions now expect no `output_id`, but the current `graph_publish.py` still includes it

- [ ] **Step 3: Remove `output_id` from `graph_publish.py`**

Modify `admin/app/graph_publish.py`:

```python
def publish_graph(db, bridge):
    """Publiceert de volledige graaf (players + sources + branches +
    triggers + output_connections + root) naar MQTT -- gedeeld door
    players.py/triggers.py/sources.py/output_connections.py/outputs.py/
    devices.py (delete-route), elke schrijvende route roept dit aan
    (behalve pure positie-updates) zodat opgeslagen en gepubliceerde graaf
    nooit uit elkaar kunnen lopen. Lazy imports om een cirkel met de
    routers te vermijden (die importeren dit bestand). Geen output_id meer
    in de payload -- elk apparaat filtert voortaan op zijn eigen, apart
    over device-assignment/{device_uuid} ontvangen output_id (zie
    mirror_node/main.py's _assigned_output_id)."""
    from admin.app.routers.players import _list_players
    from admin.app.routers.triggers import _list_triggers
    from admin.app.routers.sources import _list_sources
    from admin.app.routers.output_connections import _list_output_connections

    players = _list_players(db)
    sources = _list_sources(db)
    triggers = _list_triggers(db)
    output_connections = _list_output_connections(db)
    branch_rows = db.execute("SELECT id, player_id, name FROM player_branches ORDER BY id").fetchall()
    branches = [{"id": r[0], "player_id": r[1], "name": r[2]} for r in branch_rows]
    root_player_id = next((p["id"] for p in players if p["is_root"]), None)
    bridge.publish_mirror_graph({
        "players": players,
        "sources": sources,
        "branches": branches,
        "triggers": triggers,
        "output_connections": output_connections,
        "root_player_id": root_player_id,
    })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py tests/test_admin_routes_triggers.py -v`
Expected: all PASS

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS — paste the literal final line into your report (this task removes a field several other test files may incidentally assert on; if anything else breaks, fix that test's expectation the same way, don't add the field back)

- [ ] **Step 6: Commit**

```bash
git add admin/app/graph_publish.py tests/test_admin_routes_players.py
git commit -m "feat: output_id verdwijnt uit de gepubliceerde graaf-payload"
```

---

### Task 7: `mirror_node/main.py` — device_uuid i.p.v. hardcoded NODE_NAME, `_assigned_output_id`

**Files:**
- Create: `mirror_node/device_identity.py`
- Modify: `mirror_node/main.py`
- Test: `tests/test_mirror_main.py`

**Interfaces:**
- Produces: `mirror_node/device_identity.py`'s `get_or_create_device_uuid(path=None) -> str` (generates a `uuid4()` and writes it to `path`, or `~/.spookregie/device-id` if `path` is `None`, on first call; reads and returns the existing value on later calls). `mirror_node/main.py`'s module-level `NODE_NAME` is now set from this function instead of the literal `"mirror"`. `mirror_node/main.py`'s `_current_output_id` module variable is renamed `_assigned_output_id`, no longer set from `graph.get("output_id")` (that key no longer exists in the payload per Task 6) — instead set from a new `_apply_device_assignment_message` handler subscribed on `topics.device_assignment(NODE_NAME)`.
- Consumes: `Topics.device_assignment(device_uuid)` from Task 2.

This is the most integration-sensitive task in this plan — read the CURRENT `mirror_node/main.py` in full before touching it. `_current_output_id` is read/written at exactly these points: its declaration (module scope, initialized `None`), `_apply_graph_message` (sets it from `graph.get("output_id")` — this line is deleted, not renamed), and the main loop's output-routing-publish block (`global _last_published_output_player_id` block, reads it in the `if` condition and in the published payload). `NODE_NAME` is read at: `setup_logging(NODE_NAME, ...)`, `topics.log(NODE_NAME)`, `client.publish(topics.status(NODE_NAME), "online", retain=True)`, `client.will_set(topics.status(NODE_NAME), ...)`. Every one of these stays exactly as-is — only the single assignment `NODE_NAME = "mirror"` changes to a function call, since every other use already just reads the module-level name.

- [ ] **Step 1: Write the failing test for `device_identity.py`**

Create `tests/test_mirror_device_identity.py`:

```python
import os

from mirror_node.device_identity import get_or_create_device_uuid


def test_generates_and_persists_a_uuid_on_first_call(tmp_path):
    path = str(tmp_path / "device-id")
    first = get_or_create_device_uuid(path)
    assert len(first) == 36  # uuid4 string length
    assert os.path.exists(path)


def test_returns_the_same_uuid_on_a_second_call(tmp_path):
    path = str(tmp_path / "device-id")
    first = get_or_create_device_uuid(path)
    second = get_or_create_device_uuid(path)
    assert first == second


def test_creates_parent_directories_if_missing(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "device-id")
    uuid_value = get_or_create_device_uuid(path)
    assert os.path.exists(path)
    assert len(uuid_value) == 36
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mirror_device_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mirror_node.device_identity'`

- [ ] **Step 3: Write `mirror_node/device_identity.py`**

```python
import os
import uuid

DEFAULT_PATH = os.path.expanduser("~/.spookregie/device-id")


def get_or_create_device_uuid(path=None):
    """Geeft de lokaal opgeslagen device-uuid terug -- genereert er één en
    schrijft 'm weg als het bestand nog niet bestaat. Gedeeld tussen
    mirror_node/main.py en mirror_node/agent.py zodat beide processen op
    hetzelfde apparaat exact dezelfde identiteit gebruiken."""
    path = path or DEFAULT_PATH
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    device_uuid = str(uuid.uuid4())
    with open(path, "w") as f:
        f.write(device_uuid)
    return device_uuid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mirror_device_identity.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests for `mirror_node/main.py`'s changes**

Read `tests/test_mirror_main.py`'s existing imports and fixture/monkeypatch conventions first (how it imports `mirror_node.main`, how it resets module globals between tests, if at all) and match that style exactly. Add:

```python
def test_apply_graph_message_no_longer_sets_output_id_from_payload(monkeypatch, ...):
    # Adapt the setup to this file's existing conventions for calling
    # _apply_graph_message and inspecting mirror_main module state (see
    # existing tests in this file for the exact pattern -- e.g. how they
    # reset/read module globals like _current_output_connections).
    ...
    payload = json.dumps({
        "players": [], "sources": [], "branches": [], "triggers": [],
        "output_connections": [], "root_player_id": None,
    })
    mirror_main._apply_graph_message(payload, fake_logger)
    assert mirror_main._assigned_output_id is None  # unchanged by a graph message now


def test_apply_device_assignment_message_sets_assigned_output_id(monkeypatch, ...):
    ...
    mirror_main._apply_device_assignment_message(json.dumps({"output_id": 7}), fake_logger)
    assert mirror_main._assigned_output_id == 7


def test_apply_device_assignment_message_handles_null_output_id(monkeypatch, ...):
    ...
    mirror_main._assigned_output_id = 7
    mirror_main._apply_device_assignment_message(json.dumps({"output_id": None}), fake_logger)
    assert mirror_main._assigned_output_id is None
```

Write these three tests following whatever exact fixture/logger-mocking pattern the rest of `tests/test_mirror_main.py` already uses (read several existing tests for `_apply_graph_message` or `_apply_ha_sensor_state_message` in that file first, and copy their setup shape precisely — do not invent a different pattern).

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py -k "assigned_output_id or apply_device_assignment" -v`
Expected: FAIL — `_assigned_output_id`/`_apply_device_assignment_message` don't exist yet

- [ ] **Step 7: Implement the changes in `mirror_node/main.py`**

Add the import (alongside the other `mirror_node`/`shared` imports, near line 34):

```python
from mirror_node.device_identity import get_or_create_device_uuid
```

Replace the hardcoded `NODE_NAME = "mirror"` (line 40) with:

```python
NODE_NAME = get_or_create_device_uuid()
```

Rename `_current_output_id` to `_assigned_output_id` in its declaration (line 82):

```python
_assigned_output_id = None
```

In `_apply_graph_message` (around line 165-186), remove the line that set it from the payload — delete this line entirely:

```python
    _current_output_id = graph.get("output_id")
```

Also remove `_current_output_id` from that function's `global` statement (it no longer touches this variable at all):

```python
def _apply_graph_message(payload, logger):
    global _current_output_connections, _current_branches, _current_sources
```

Add a new handler function, placed near `_apply_ha_sensor_state_message` (they're both small single-value MQTT-payload handlers with the same shape):

```python
def _apply_device_assignment_message(payload, logger):
    global _assigned_output_id
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige device-assignment-JSON ontvangen, genegeerd")
        return
    if not isinstance(data, dict):
        logger.error("Device-assignment is geen object, genegeerd: %r", data)
        return
    _assigned_output_id = data.get("output_id")
```

Wire it into `make_on_message`'s dispatch (add a new `if` branch, placed after the existing `control_mirror_ha_sensor_state` branch — topic matching needs the per-device topic, built once outside the closure since `NODE_NAME` is now a real value at import time, not a literal being compared):

```python
def make_on_message(logger, topics):
    device_assignment_topic = topics.device_assignment(NODE_NAME)

    def on_message(client, userdata, msg):
        try:
            if msg.topic == topics.system_sleep:
                if msg.payload.decode() == SLEEP_PAYLOAD_ON:
                    sleeping.set()
                else:
                    sleeping.clear()
                return
            if msg.topic == topics.config_mirror_graph:
                _apply_graph_message(msg.payload.decode(), logger)
                return
            if msg.topic == device_assignment_topic:
                _apply_device_assignment_message(msg.payload.decode(), logger)
                return
            if msg.topic == topics.control_mirror_scene_preview:
                _apply_scene_preview_message(msg.payload.decode(), logger)
                return
            if msg.topic == topics.control_mirror_test:
                test_trigger_requested.set()
                return
            if msg.topic == topics.config_mirror_scare_video:
                _apply_scare_video_config_message(msg.payload.decode(), logger)
            if msg.topic == topics.control_mirror_ha_trigger:
                _apply_ha_trigger_message(msg.payload.decode(), logger)
                return
            if msg.topic == topics.control_mirror_ha_sensor_state:
                _apply_ha_sensor_state_message(msg.payload.decode(), logger)
                return
        except Exception as exc:
            logger.error("Fout bij verwerken MQTT-bericht op topic %s: %s", msg.topic, exc)
    return on_message
```

Add the subscription in `main()`'s `on_connect` (after `client.subscribe(topics.control_mirror_ha_sensor_state)`):

```python
        client.subscribe(topics.device_assignment(NODE_NAME))
```

Replace every remaining use of `_current_output_id` in the main loop's output-routing-publish block (around lines 679-690) with `_assigned_output_id`:

```python
            global _last_published_output_player_id
            if (
                winning is not None
                and transitioned
                and _assigned_output_id is not None
                and _player_feeds_this_output(winning["id"], _assigned_output_id, _current_branches, _current_output_connections)
                and winning["id"] != _last_published_output_player_id
            ):
                client.publish(
                    topics.mirror_output, json.dumps({"player_id": winning["id"], "output_id": _assigned_output_id})
                )
                _last_published_output_player_id = winning["id"]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py -v`
Expected: all PASS

- [ ] **Step 9: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS — paste the literal final line into your report.

- [ ] **Step 10: Commit**

```bash
git add mirror_node/device_identity.py mirror_node/main.py tests/test_mirror_device_identity.py tests/test_mirror_main.py
git commit -m "feat: mirror_node gebruikt device_uuid i.p.v. hardcoded NODE_NAME, output-toewijzing via MQTT"
```

---

### Task 8: `mirror_node/agent.py` — checkin + zelf-update

**Files:**
- Create: `mirror_node/agent.py`
- Test: `tests/test_mirror_agent.py`

**Interfaces:**
- Consumes: `get_or_create_device_uuid` from Task 7's `mirror_node/device_identity.py`. `Topics.device_info(uuid)`/`Topics.device_update_check` from Task 2.
- Produces: a standalone script, run as its own OS service (wired up in Task 9's install script) — no other task in this plan imports from it directly, but its pure/testable pieces (the git-update-check logic, the checkin-payload builder) are structured as separate functions so they can be unit-tested without a real MQTT connection or a real git repo.

This file is new and self-contained — no existing code to integrate carefully against, but keep its pure logic (deciding whether an update is needed, building the checkin payload) separate from its I/O (actual `subprocess.run` calls, actual MQTT client) so it's testable, matching this codebase's established `_render_action`-style "pure decision function, separate from the loop that calls it" pattern (see `mirror_node/main.py`'s `_render_action`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mirror_agent.py`:

```python
import json

from mirror_node.agent import build_checkin_payload, needs_update


def test_build_checkin_payload_shape():
    payload = build_checkin_payload(name="Oude MacBook", platform="darwin", git_sha="abc1234")
    assert json.loads(payload) == {"name": "Oude MacBook", "platform": "darwin", "git_sha": "abc1234"}


def test_needs_update_true_when_shas_differ():
    assert needs_update(local_sha="abc123", remote_sha="def456") is True


def test_needs_update_false_when_shas_match():
    assert needs_update(local_sha="abc123", remote_sha="abc123") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mirror_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mirror_node.agent'`

- [ ] **Step 3: Write `mirror_node/agent.py`**

```python
import json
import os
import socket
import subprocess
import sys
import time

import paho.mqtt.client as mqtt

from shared.mqtt_contract import Topics
from shared.logging_setup import setup_logging
from mirror_node.device_identity import get_or_create_device_uuid

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "")
REPO_DIR = os.environ.get("SPOOKREGIE_REPO_DIR", os.path.expanduser("~/spookregie"))
LOG_DIR = os.environ.get("LOG_DIR", "./logs")
CHECKIN_INTERVAL_SECONDS = float(os.environ.get("AGENT_CHECKIN_INTERVAL_SECONDS", "300"))
UPDATE_CHECK_INTERVAL_SECONDS = float(os.environ.get("AGENT_UPDATE_CHECK_INTERVAL_SECONDS", "600"))
# Servicemanager-commando om mirror_node te herstarten na een update --
# platformafhankelijk, door het install-script (Task 9) in de omgeving
# gezet zodat dit script zelf niets over macOS/Linux hoeft te weten.
MIRROR_RESTART_COMMAND = os.environ.get("MIRROR_RESTART_COMMAND", "")


def build_checkin_payload(name, platform, git_sha):
    return json.dumps({"name": name, "platform": platform, "git_sha": git_sha})


def needs_update(local_sha, remote_sha):
    return local_sha != remote_sha


def _git(args, cwd):
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _current_git_sha(cwd):
    code, out, _err = _git(["rev-parse", "HEAD"], cwd)
    return out if code == 0 else None


def _restart_mirror_node(logger):
    if not MIRROR_RESTART_COMMAND:
        logger.warning("MIRROR_RESTART_COMMAND niet gezet, kan mirror_node niet herstarten na update")
        return
    try:
        # Geen shell=True: het install-script (Task 9) schrijft dit als een
        # al-opgeloste, simpele opdracht zonder shell-features nodig (bv.
        # launchd's $(id -u) is al door de heredoc geëxpandeerd op
        # installatiemoment) -- .split() + een lijst voorkomt command-
        # injection via een env-var, ook al is de bron hier vertrouwd.
        subprocess.run(MIRROR_RESTART_COMMAND.split(), check=True)
    except subprocess.CalledProcessError as exc:
        # Geen rollback (bewuste keuze, zie spec) -- gewoon loggen en de
        # volgende update-cyclus opnieuw proberen.
        logger.error("Herstarten van mirror_node mislukt: %s", exc)


def check_and_apply_update(repo_dir, logger):
    """Eén update-cyclus: git fetch, vergelijk lokale met remote HEAD van
    main, pull + herstart bij verschil. Geen rollback bij een falende
    herstart -- de volgende cyclus (interval of MQTT-duw) probeert het
    gewoon opnieuw."""
    code, _out, err = _git(["fetch", "origin", "main"], repo_dir)
    if code != 0:
        logger.warning("git fetch mislukt: %s", err)
        return
    local_sha = _current_git_sha(repo_dir)
    code, remote_sha, err = _git(["rev-parse", "origin/main"], repo_dir)
    if code != 0 or not remote_sha:
        logger.warning("kon remote HEAD niet bepalen: %s", err)
        return
    if not needs_update(local_sha, remote_sha):
        return
    logger.info("nieuwe commit gevonden (%s -> %s), pull + herstart", local_sha, remote_sha)
    code, _out, err = _git(["pull", "--ff-only"], repo_dir)
    if code != 0:
        logger.error("git pull mislukt: %s", err)
        return
    _restart_mirror_node(logger)


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    device_uuid = get_or_create_device_uuid()
    topics = Topics(prefix=MQTT_TOPIC_PREFIX)
    logger = setup_logging(f"agent-{device_uuid}", LOG_DIR)

    client = mqtt.Client(client_id=f"agent-{device_uuid}")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    def do_checkin():
        git_sha = _current_git_sha(REPO_DIR) or "onbekend"
        payload = build_checkin_payload(name=socket.gethostname(), platform=sys.platform, git_sha=git_sha)
        client.publish(topics.device_info(device_uuid), payload, retain=True)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            logger.error("MQTT verbinden mislukt (rc=%s)", rc)
            return
        logger.info("agent verbonden met MQTT %s:%s als %s", MQTT_HOST, MQTT_PORT, device_uuid)
        client.subscribe(topics.device_update_check)
        do_checkin()

    def on_message(client, userdata, msg):
        if msg.topic == topics.device_update_check:
            logger.info("directe update-check aangevraagd via MQTT")
            check_and_apply_update(REPO_DIR, logger)

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    last_checkin = 0.0
    last_update_check = 0.0
    try:
        while True:
            now = time.time()
            if now - last_checkin >= CHECKIN_INTERVAL_SECONDS:
                do_checkin()
                last_checkin = now
            if now - last_update_check >= UPDATE_CHECK_INTERVAL_SECONDS:
                check_and_apply_update(REPO_DIR, logger)
                last_update_check = now
            time.sleep(5)
    finally:
        client.loop_stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mirror_agent.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add mirror_node/agent.py tests/test_mirror_agent.py
git commit -m "feat: mirror_node/agent.py -- device-checkin + zelf-update via git pull"
```

---

### Task 9: `deploy/install-agent.sh` — eenmalige installatie per apparaat

**Files:**
- Create: `deploy/install-agent.sh`

**Interfaces:**
- Consumes: nothing from other tasks (a standalone shell script, run manually on a target device — not imported/tested by Python code).
- Produces: on macOS, two LaunchAgents (`nl.spookregie.mirror`, `nl.spookregie.agent`) in `~/Library/LaunchAgents/`; on Linux, two systemd system services (`spookregie-mirror.service`, `spookregie-agent.service`). Both platforms end up with a `~/spookregie` git clone, a Python venv with `mirror_node`'s requirements installed, and a shared env file both services source.

No automated test for this file (a shell script that registers OS services — this codebase's test suite runs Python, not a live macOS/Linux service manager). Verify manually per Step 4 below.

- [ ] **Step 1: Write `deploy/install-agent.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/ekoppen/spookregie.git"
REPO_DIR="$HOME/spookregie"
ENV_FILE="$HOME/.spookregie/env"

echo "== Spookregie device-installatie =="

command -v git >/dev/null 2>&1 || { echo "git niet gevonden -- installeer git eerst."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 niet gevonden -- installeer python3 eerst."; exit 1; }

if [ ! -d "$REPO_DIR/.git" ]; then
  git clone "$REPO_URL" "$REPO_DIR"
else
  echo "Repo bestaat al op $REPO_DIR, sla clone over."
fi

python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/mirror_node/requirements.txt"

mkdir -p "$(dirname "$ENV_FILE")"
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

  cat > "$ENV_FILE" <<EOF
MQTT_HOST=$mqtt_host
MQTT_PORT=$mqtt_port
MQTT_USER=$mqtt_user
MQTT_PASS=$mqtt_pass
MQTT_TOPIC_PREFIX=$mqtt_topic_prefix
BACKEND_URL=$backend_url
SPOOKREGIE_REPO_DIR=$REPO_DIR
EOF
  echo "Configuratie opgeslagen in $ENV_FILE"
else
  echo "Configuratiebestand bestaat al op $ENV_FILE, sla vragen over."
fi

PLATFORM="$(uname)"

if [ "$PLATFORM" = "Darwin" ]; then
  echo "-- macOS: LaunchAgents installeren --"
  AGENTS_DIR="$HOME/Library/LaunchAgents"
  mkdir -p "$AGENTS_DIR"

  cat > "$AGENTS_DIR/nl.spookregie.mirror.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>nl.spookregie.mirror</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO_DIR/.venv/bin/python</string>
    <string>-m</string>
    <string>mirror_node.main</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>SPOOKREGIE_ENV_FILE</key><string>$ENV_FILE</string></dict>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF

  cat > "$AGENTS_DIR/nl.spookregie.agent.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>nl.spookregie.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO_DIR/.venv/bin/python</string>
    <string>-m</string>
    <string>mirror_node.agent</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SPOOKREGIE_ENV_FILE</key><string>$ENV_FILE</string>
    <key>MIRROR_RESTART_COMMAND</key><string>launchctl kickstart -k gui/$(id -u)/nl.spookregie.mirror</string>
  </dict>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF

  launchctl load "$AGENTS_DIR/nl.spookregie.mirror.plist"
  launchctl load "$AGENTS_DIR/nl.spookregie.agent.plist"
  echo "LaunchAgents geladen. Bekijk status met: launchctl list | grep spookregie"

elif [ "$PLATFORM" = "Linux" ]; then
  echo "-- Linux: systemd-services installeren (vereist sudo) --"

  sudo tee /etc/systemd/system/spookregie-mirror.service > /dev/null <<EOF
[Unit]
Description=Spookregie mirror-node
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$REPO_DIR/.venv/bin/python -m mirror_node.main
Restart=always

[Install]
WantedBy=multi-user.target
EOF

  sudo tee /etc/systemd/system/spookregie-agent.service > /dev/null <<EOF
[Unit]
Description=Spookregie device-agent
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
EnvironmentFile=$ENV_FILE
Environment=MIRROR_RESTART_COMMAND=systemctl restart spookregie-mirror
ExecStart=$REPO_DIR/.venv/bin/python -m mirror_node.agent
Restart=always

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable --now spookregie-mirror spookregie-agent
  echo "systemd-services actief. Bekijk status met: systemctl status spookregie-mirror spookregie-agent"

else
  echo "Onbekend platform: $PLATFORM -- alleen macOS (Darwin) en Linux worden ondersteund."
  exit 1
fi

echo "== Installatie klaar. Ga naar de beheerpagina > Apparaten om dit apparaat aan een output te koppelen. =="
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x deploy/install-agent.sh
```

- [ ] **Step 3: Read it back once for obvious shell mistakes**

There is no automated test for this file. Read the written script once yourself, checking: every heredoc's closing `EOF` is unindented and matches its opener, every variable that should NOT be shell-expanded inside the `.plist`/`.service` heredocs (none here — all are meant to expand) is handled correctly, and `set -euo pipefail` at the top means any failed command aborts the script rather than continuing silently.

- [ ] **Step 4: Manual verification note for the report**

This script cannot be run as part of this task's automated verification (it registers real OS services and needs a real macOS or Linux machine with sudo). Note in your report that it was written and read-back-checked but not executed — actual end-to-end verification of the install script happens later, when the user runs it on a real device, outside this plan's automated test loop.

- [ ] **Step 5: Commit**

```bash
git add deploy/install-agent.sh
git commit -m "feat: install-agent.sh -- eenmalige apparaat-installatie (macOS + Linux)"
```

---

### Task 10: Frontend `types.ts` + `api/devices.ts`

**Files:**
- Modify: `admin/frontend/src/types.ts`
- Create: `admin/frontend/src/api/devices.ts`

**Interfaces:**
- Produces: `Device` interface (`id, device_uuid, name, platform, git_sha, last_seen_at, output_id`), matching `admin/app/routers/devices.py`'s `_row_to_device` exactly. `listDevices()`, `updateDevice(id, {name, output_id})`, `deleteDevice(id)` in `api/devices.ts`.
- Consumes: nothing (pure type/API-wrapper task, no runtime dependency on other frontend tasks).

- [ ] **Step 1: Add the `Device` type to `admin/frontend/src/types.ts`**

Add after the `OutputConnection` interface (after line 65):

```typescript
export interface Device {
  id: number;
  device_uuid: string;
  name: string;
  platform: string;
  git_sha: string | null;
  last_seen_at: string | null;
  output_id: number | null;
}
```

- [ ] **Step 2: Write `admin/frontend/src/api/devices.ts`**

```typescript
import { apiFetch } from "./client";
import type { Device } from "../types";

export interface DeviceUpdate {
  name: string;
  output_id: number | null;
}

export function listDevices(): Promise<Device[]> {
  return apiFetch<Device[]>("/api/devices");
}

export function updateDevice(id: number, update: DeviceUpdate): Promise<Device> {
  return apiFetch<Device>(`/api/devices/${id}`, { method: "PUT", body: JSON.stringify(update) });
}

export function deleteDevice(id: number): Promise<void> {
  return apiFetch(`/api/devices/${id}`, { method: "DELETE" });
}
```

- [ ] **Step 3: Run typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: no new errors attributable to `types.ts`/`api/devices.ts` (nothing consumes `Device`/`api/devices.ts` yet, so this should simply compile cleanly)

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/types.ts admin/frontend/src/api/devices.ts
git commit -m "feat: frontend-types + API-laag voor devices"
```

---

### Task 11: `DevicesPage.tsx` — apparaten-beheerpagina

**Files:**
- Create: `admin/frontend/src/pages/DevicesPage.tsx`
- Create: `admin/frontend/src/pages/DevicesPage.css`
- Modify: `admin/frontend/src/App.tsx` (route)
- Modify: `admin/frontend/src/components/Layout.tsx` (nav link)

**Interfaces:**
- Consumes: `Device`, `listDevices`/`updateDevice`/`deleteDevice` from Task 10; `Output`/`listOutputs` (existing, `admin/frontend/src/api/outputs.ts`); `getNodes`/`NodeStatusMap` (existing, `admin/frontend/src/api/nodes.ts`/`admin/frontend/src/types.ts`) for the online/offline badge, keyed by `device.device_uuid` — matches how `DashboardPage.tsx` already keys its own `nodes` state by whatever raw MQTT node-name string it sees.
- Produces: nothing consumed elsewhere in this plan — this is the final, user-facing task.

Read `admin/frontend/src/pages/OutputsPage.tsx` and `admin/frontend/src/pages/OutputsPage.css` in full first — this page follows the exact same shape (inline-editable list, no separate "new row" since devices self-register rather than being created here, delete-with-surfaced-backend-error). Unlike Sources/Outputs, this page has no create-row and no free-text name-on-create — every row already exists because a device checked in.

- [ ] **Step 1: Write `admin/frontend/src/pages/DevicesPage.tsx`**

```typescript
import { useEffect, useState } from "react";
import { listDevices, updateDevice, deleteDevice } from "../api/devices";
import { listOutputs } from "../api/outputs";
import { getNodes } from "../api/nodes";
import { ApiError } from "../api/client";
import type { Device, Output, NodeStatusMap } from "../types";
import "./DevicesPage.css";

interface Draft {
  name: string;
  output_id: number | null;
}

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [nodes, setNodes] = useState<NodeStatusMap>({});
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function refresh() {
    listDevices()
      .then((result) => {
        setDevices(result);
        setDrafts(Object.fromEntries(result.map((d) => [d.id, { name: d.name, output_id: d.output_id }])));
        setError(null);
      })
      .catch(() => setError("Apparaten konden niet worden geladen."));
  }

  useEffect(() => {
    refresh();
    listOutputs().catch(() => setError("Outputs konden niet worden geladen."));
    listOutputs().then(setOutputs).catch(() => setError("Outputs konden niet worden geladen."));
    getNodes().then(setNodes).catch(() => {
      /* online/offline-badge blijft dan gewoon leeg */
    });
  }, []);

  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 3000);
  }

  function updateDraft(id: number, patch: Partial<Draft>) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  async function handleSave(id: number) {
    const draft = drafts[id];
    if (!draft) return;
    setSaving(true);
    try {
      await updateDevice(id, { name: draft.name, output_id: draft.output_id });
      refresh();
      showNotice("Apparaat opgeslagen.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Dit apparaat uit de lijst verwijderen? Het meldt zich vanzelf opnieuw als het weer een checkin stuurt.")) return;
    setSaving(true);
    try {
      await deleteDevice(id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Verwijderen is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="devices-page">
      <header className="devices-header">
        <p className="devices-eyebrow">
          <span className="devices-eyebrow__led" aria-hidden="true" />
          Apparaten
        </p>
        <h1 className="devices-heading">Apparaten</h1>
      </header>

      {error && (
        <p className="devices-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="devices-notice" role="status">
          {notice}
        </p>
      )}

      <section className="devices-panel">
        {devices.length === 0 && <p className="devices-empty">Nog geen apparaten gemeld.</p>}
        {devices.map((device) => {
          const draft = drafts[device.id] ?? { name: device.name, output_id: device.output_id };
          const online = nodes[device.device_uuid]?.status === "online";
          return (
            <div className="devices-row" key={device.id}>
              <span className={`devices-status-badge devices-status-badge--${online ? "online" : "offline"}`}>
                {online ? "Online" : "Offline"}
              </span>
              <input
                className="devices-field__input"
                type="text"
                value={draft.name}
                onChange={(e) => updateDraft(device.id, { name: e.target.value })}
              />
              <span className="devices-field__meta">{device.platform}</span>
              <span className="devices-field__meta">{device.git_sha ? device.git_sha.slice(0, 7) : "—"}</span>
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
              <button type="button" onClick={() => handleSave(device.id)} disabled={saving}>
                Opslaan
              </button>
              <button type="button" onClick={() => handleDelete(device.id)} disabled={saving}>
                Verwijderen
              </button>
            </div>
          );
        })}
      </section>

      <p className="devices-field__label">
        Apparaten melden zichzelf zodra hun agent draait en verbinding heeft
        -- zie deploy/install-agent.sh voor de eenmalige installatie. Koppel
        hier welke fysieke output een apparaat bedient.
      </p>
    </div>
  );
}
```

Note the accidental duplicate `listOutputs()` call in Step 1's `useEffect` — the first `listOutputs().catch(...)` line is dead/redundant with the second `listOutputs().then(setOutputs).catch(...)` line right after it. Remove the first, dead line before running anything; the effect should call `listOutputs()` exactly once.

- [ ] **Step 2: Write `admin/frontend/src/pages/DevicesPage.css`**

Base this directly on `admin/frontend/src/pages/OutputsPage.css` (read it first) — same `.outputs-page`/`.outputs-header`/`.outputs-eyebrow`/`.outputs-eyebrow__led`/`.outputs-heading`/`.outputs-error`/`.outputs-notice`/`.outputs-panel`/`.outputs-field__input`/`.outputs-field__label` rules, renamed to the `devices-` prefix, plus a `.devices-row` grid with one extra column for the status badge and one for the output `<select>`, and two new rules for the badge itself:

```css
.devices-page {
  padding: 1.5rem 2rem;
  color: var(--bone);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

.devices-header {
  margin-bottom: 1.5rem;
}

.devices-eyebrow {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ash);
  margin: 0 0 0.3rem;
}

.devices-eyebrow__led {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ember);
}

.devices-heading {
  margin: 0;
  font-size: 1.5rem;
}

.devices-error {
  color: var(--alarm);
  margin-bottom: 1rem;
}

.devices-notice {
  color: var(--signal);
  margin-bottom: 1rem;
}

.devices-empty {
  color: var(--ash);
  font-size: 0.85rem;
}

.devices-panel {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 10px;
  padding: 1rem;
}

.devices-row {
  display: grid;
  grid-template-columns: auto 1fr auto auto 1fr auto auto;
  gap: 0.6rem;
  align-items: center;
}

.devices-field__input,
.devices-field__select {
  padding: 0.5rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 6px;
  color: var(--bone);
}

.devices-field__meta {
  font-size: 0.8rem;
  color: var(--ash);
  font-family: monospace;
}

.devices-field__label {
  margin-top: 1rem;
  font-size: 0.8rem;
  color: var(--ash);
}

.devices-status-badge {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.2rem 0.5rem;
  border-radius: 999px;
  white-space: nowrap;
}

.devices-status-badge--online {
  background: rgba(46, 204, 113, 0.15);
  color: var(--signal);
}

.devices-status-badge--offline {
  background: rgba(231, 76, 60, 0.15);
  color: var(--alarm);
}
```

- [ ] **Step 3: Wire the route into `admin/frontend/src/App.tsx`**

Add the import (after `import SourcesPage from "./pages/SourcesPage";`):

```typescript
import DevicesPage from "./pages/DevicesPage";
```

Add the route (after `<Route path="/sources" element={<SourcesPage />} />`):

```typescript
          <Route path="/devices" element={<DevicesPage />} />
```

- [ ] **Step 4: Wire the nav link into `admin/frontend/src/components/Layout.tsx`**

Add to the `links` array (after `{ to: "/sources", label: "Sources", end: false },`):

```typescript
  { to: "/devices", label: "Apparaten", end: false },
```

- [ ] **Step 5: Run typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Run the frontend test suite**

Run: `cd admin/frontend && npm test`
Expected: all existing tests still pass (this task adds no new test file — there's no interaction logic complex enough to warrant one beyond what plain CRUD pages in this codebase already get, matching `OutputsPage.tsx`/`SourcesPage.tsx`, neither of which have a dedicated test file either)

- [ ] **Step 7: Commit**

```bash
git add admin/frontend/src/pages/DevicesPage.tsx admin/frontend/src/pages/DevicesPage.css admin/frontend/src/App.tsx admin/frontend/src/components/Layout.tsx
git commit -m "feat: Apparaten-pagina -- lijst, hernoemen, output koppelen, verwijderen"
```

---

## Final Integration Check (part of the last task's own verification, not a separate task)

After Task 11, run the full three-suite check one more time from the repo root:

```bash
.venv/bin/python -m pytest tests/ -q
cd admin/frontend && npx tsc --noEmit && npm test
```

All three must be clean before this plan is considered done.
