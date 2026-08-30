# Mirror-scenes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vervang de enkelvoudige mirror-configuratie door meerdere,
prioriteit-geëvalueerde "scenes" (bron + regie + doel + trigger),
programmeerbaar via een wizard-modal op het Dashboard.

**Architecture:** Nieuwe `scenes`-tabel (backend) vervangt de
singleton `mirror_config`; volledige, geordende scene-lijst wordt
live (retained MQTT) naar `mirror_node` gepusht; `mirror_node`
evalueert elke frame welke scene wint (eerste matchende trigger in
prioriteitsvolgorde) en rendert/speelt die af. Frontend: een
4-staps wizard-modal (Input/Animatie/Output/Trigger) op het
Dashboard, die de al bestaande `OverlayCanvas`/`MediaLibrary`-
componenten hergebruikt.

**Tech Stack:** FastAPI + SQLite (backend), React + TypeScript + Vite
(frontend), Python + OpenCV + paho-mqtt (mirror_node), MQTT (contract
tussen backend en node).

**Spec:** `docs/superpowers/specs/2026-08-30-mirror-scenes-design.md`

## Global Constraints

- Precies één scene is op elk moment "actief" — eerste matchende
  trigger in `order_index`-volgorde wint (geen gelijktijdige
  meervoudige output).
- Scare-video-scenes hergebruiken de bestaande
  `mirror_scare_video_config`-pool (willekeurige keuze) ongewijzigd —
  geen los "kies precies deze clip"-veld per scene.
- Scare-video-scenes slaan Animatie/Output over (volledige
  beeld-vervanging, geen compositing) — bestaande, eerder al
  vastgelegde beperking.
- Tijdschema is één simpel van–tot-venster per scene, met
  middernacht-doorloop ondersteund; geen dagen-van-de-week.
- Herordenen via ▲/▼-knoppen, geen drag-and-drop.
- Nieuwe DB-kolommen/tabellen: nieuwe tabellen via
  `CREATE TABLE IF NOT EXISTS`; een kolom op een *bestaande* tabel zou
  via `_ensure_column` moeten (niet van toepassing in dit plan — alle
  wijzigingen hier zijn een geheel nieuwe tabel).
- Bestaande deploys migreren automatisch (één "Basis"-scene uit de
  oude `mirror_config`-rij) — geen handmatige stap.
- `/api/mirror/test` (handmatige trigger-simulatie) blijft ongewijzigd
  bestaan.

---

## Task 1: Backend DB — `scenes`-tabel + migratie

**Files:**
- Modify: `admin/app/db.py`
- Test: `tests/test_admin_db.py`

**Interfaces:**
- Produces: SQLite-tabel `scenes` met kolommen
  `id, name, order_index, enabled, source_mode, effect, params,
  overlay_hash, scale, position, canvas_width, canvas_height,
  source_scale, source_position, trigger_type, trigger_from,
  trigger_until`. Functie `_migrate_mirror_config_to_scenes(conn)`
  (module-privaat in `admin/app/db.py`).

- [ ] **Step 1: Schrijf de falende migratietest**

Voeg toe aan `tests/test_admin_db.py`:

```python
def test_scenes_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert "scenes" in tables


def test_existing_mirror_config_migrates_to_one_scene(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO mirror_config (id, effect, params, overlay_hash, scale, position) "
        "VALUES (1, 'thermal', '{\"intensity\": 0.5}', NULL, 1.5, '[0.2, 0.3]')"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # tweede init_db-run simuleert een herstart na upgrade

    scenes = conn2.execute("SELECT name, trigger_type, effect, scale FROM scenes").fetchall()
    assert scenes == [("Basis", "always", "thermal", 1.5)]


def test_scene_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO mirror_config (id, effect, params, overlay_hash, scale, position) "
        "VALUES (1, 'xray', '{}', NULL, 1.0, '[0.5, 0.5]')"
    )
    conn.commit()
    conn.close()
    init_db(path)  # eerste migratie

    conn3 = init_db(path)  # nogmaals -- mag niet nog een scene toevoegen

    count = conn3.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
    assert count == 1


def test_scene_migration_does_nothing_without_existing_mirror_config(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))  # verse DB, geen mirror_config-rij

    count = conn.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
    assert count == 0
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -q`
Expected: FAIL — `sqlite3.OperationalError: no such table: scenes`

- [ ] **Step 3: Voeg de `scenes`-tabel toe in `admin/app/db.py`**

Direct ná het bestaande `CREATE TABLE IF NOT EXISTS mirror_config (...)`-blok
(vóór `mirror_scare_video_config`):

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scenes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            source_mode TEXT NOT NULL DEFAULT 'camera',
            effect TEXT NOT NULL DEFAULT 'xray',
            params TEXT NOT NULL DEFAULT '{}',
            overlay_hash TEXT,
            scale REAL NOT NULL DEFAULT 1.0,
            position TEXT NOT NULL DEFAULT '[0.5, 0.5]',
            canvas_width INTEGER,
            canvas_height INTEGER,
            source_scale REAL NOT NULL DEFAULT 1.0,
            source_position TEXT NOT NULL DEFAULT '[0.5, 0.5]',
            trigger_type TEXT NOT NULL DEFAULT 'always',
            trigger_from TEXT,
            trigger_until TEXT
        )"""
    )
```

- [ ] **Step 4: Voeg de migratiefunctie toe, ná `_ensure_column`**

```python
def _migrate_mirror_config_to_scenes(conn):
    """Migreert de (oude, enkelvoudige) mirror_config-rij naar één
    'Basis'-scene, zodat een bestaande deploy na de upgrade precies
    hetzelfde beeld blijft tonen. Idempotent: doet niets zodra er al
    minstens één scene bestaat, en niets als er nooit een
    mirror_config-rij was (verse installatie)."""
    existing = conn.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
    if existing > 0:
        return
    row = conn.execute(
        "SELECT effect, params, overlay_hash, scale, position, "
        "canvas_width, canvas_height, source_scale, source_position "
        "FROM mirror_config WHERE id = 1"
    ).fetchone()
    if row is None:
        return
    conn.execute(
        """INSERT INTO scenes
             (name, order_index, enabled, source_mode, effect, params, overlay_hash,
              scale, position, canvas_width, canvas_height, source_scale, source_position,
              trigger_type)
           VALUES ('Basis', 0, 1, 'camera', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'always')""",
        row,
    )
```

- [ ] **Step 5: Roep de migratie aan vóór de finale `conn.commit()` in `init_db`**

`init_db` eindigt momenteel met:

```python
    _ensure_column(conn, "mirror_config", "source_position", "TEXT NOT NULL DEFAULT '[0.5, 0.5]'")
    conn.commit()
    return conn
```

Wordt:

```python
    _ensure_column(conn, "mirror_config", "source_position", "TEXT NOT NULL DEFAULT '[0.5, 0.5]'")
    _migrate_mirror_config_to_scenes(conn)
    conn.commit()
    return conn
```

- [ ] **Step 6: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -q`
Expected: alle tests PASS

- [ ] **Step 7: Commit**

```bash
git add admin/app/db.py tests/test_admin_db.py
git commit -m "feat: scenes-tabel + migratie van bestaande mirror_config"
```

---

## Task 2: mirror_node — `SceneEngine`

**Files:**
- Create: `mirror_node/scenes.py`
- Test: `tests/test_scene_engine.py`

**Interfaces:**
- Consumes: niets (pure, geen afhankelijkheden van andere taken).
- Produces: `SceneEngine` met `.set_scenes(scenes: list[dict])`,
  `.set_preview(scene: dict)`, `.preview_recently_set() -> bool`,
  `.resolve(motion_active: bool, now_hhmm: str) -> dict | None`.
  Functie `_time_in_window(now_hhmm, start, end) -> bool`. Gebruikt
  door Task 6.

- [ ] **Step 1: Schrijf de falende tests**

Maak `tests/test_scene_engine.py`:

```python
from mirror_node.scenes import SceneEngine, _time_in_window


def test_always_scene_wins_without_conditions():
    engine = SceneEngine()
    scene = {"id": 1, "trigger_type": "always"}
    engine.set_scenes([scene])

    assert engine.resolve(motion_active=False, now_hhmm="12:00") == scene


def test_motion_scene_only_wins_when_motion_active():
    engine = SceneEngine()
    scene = {"id": 1, "trigger_type": "motion"}
    engine.set_scenes([scene])

    assert engine.resolve(motion_active=False, now_hhmm="12:00") is None
    assert engine.resolve(motion_active=True, now_hhmm="12:00") == scene


def test_schedule_scene_matches_within_window():
    engine = SceneEngine()
    scene = {"id": 1, "trigger_type": "schedule", "trigger_from": "20:00", "trigger_until": "23:00"}
    engine.set_scenes([scene])

    assert engine.resolve(motion_active=False, now_hhmm="21:00") == scene
    assert engine.resolve(motion_active=False, now_hhmm="19:00") is None


def test_schedule_scene_handles_midnight_wraparound():
    engine = SceneEngine()
    scene = {"id": 1, "trigger_type": "schedule", "trigger_from": "22:00", "trigger_until": "02:00"}
    engine.set_scenes([scene])

    assert engine.resolve(motion_active=False, now_hhmm="23:30") == scene
    assert engine.resolve(motion_active=False, now_hhmm="01:00") == scene
    assert engine.resolve(motion_active=False, now_hhmm="12:00") is None


def test_priority_order_first_match_wins():
    engine = SceneEngine()
    motion_scene = {"id": 1, "trigger_type": "motion"}
    always_scene = {"id": 2, "trigger_type": "always"}
    engine.set_scenes([motion_scene, always_scene])

    result = engine.resolve(motion_active=True, now_hhmm="12:00")

    assert result == motion_scene


def test_disabled_scene_is_skipped():
    engine = SceneEngine()
    disabled = {"id": 1, "trigger_type": "always", "enabled": False}
    enabled = {"id": 2, "trigger_type": "always", "enabled": True}
    engine.set_scenes([disabled, enabled])

    assert engine.resolve(motion_active=False, now_hhmm="12:00") == enabled


def test_no_scene_matches_returns_none():
    engine = SceneEngine()
    engine.set_scenes(
        [{"id": 1, "trigger_type": "schedule", "trigger_from": "20:00", "trigger_until": "21:00"}]
    )

    assert engine.resolve(motion_active=False, now_hhmm="12:00") is None


def test_preview_overrides_normal_resolution():
    clock = {"t": 0.0}
    engine = SceneEngine(preview_timeout=30, clock=lambda: clock["t"])
    engine.set_scenes([{"id": 1, "trigger_type": "always"}])
    preview = {"id": 99, "trigger_type": "always"}
    engine.set_preview(preview)

    assert engine.resolve(motion_active=False, now_hhmm="12:00") == preview


def test_preview_expires_after_timeout():
    clock = {"t": 0.0}
    engine = SceneEngine(preview_timeout=30, clock=lambda: clock["t"])
    normal = {"id": 1, "trigger_type": "always"}
    engine.set_scenes([normal])
    engine.set_preview({"id": 99, "trigger_type": "always"})
    clock["t"] = 31.0

    assert engine.resolve(motion_active=False, now_hhmm="12:00") == normal


def test_time_in_window_normal_range():
    assert _time_in_window("21:00", "20:00", "23:00") is True
    assert _time_in_window("19:00", "20:00", "23:00") is False


def test_time_in_window_midnight_wraparound():
    assert _time_in_window("23:30", "22:00", "02:00") is True
    assert _time_in_window("01:00", "22:00", "02:00") is True
    assert _time_in_window("12:00", "22:00", "02:00") is False


def test_time_in_window_missing_bounds_never_matches():
    assert _time_in_window("12:00", None, None) is False
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_scene_engine.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mirror_node.scenes'`

- [ ] **Step 3: Implementeer `mirror_node/scenes.py`**

```python
import time


class SceneEngine:
    """Houdt de laatst via MQTT ontvangen scene-lijst bij, plus een
    optionele tijdelijke preview-scene (zelfde TTL-mechanisme als de
    vroegere ActiveMirrorConfig, nu op scene-niveau)."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._scenes = []
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_scenes(self, scenes):
        self._scenes = scenes

    def set_preview(self, scene):
        self._preview = scene
        self._preview_set_at = self._clock()

    def preview_recently_set(self):
        if self._preview_set_at is None:
            return False
        return self._clock() - self._preview_set_at <= self._preview_timeout

    def resolve(self, motion_active, now_hhmm):
        """Geeft de winnende scene terug (of None): de preview-scene als
        die recent gezet is, anders de eerste ingeschakelde scene in
        volgorde wiens trigger nu matcht."""
        if self.preview_recently_set():
            return self._preview
        for scene in self._scenes:
            if not scene.get("enabled", True):
                continue
            trigger = scene.get("trigger_type")
            if trigger == "always":
                return scene
            if trigger == "motion" and motion_active:
                return scene
            if trigger == "schedule" and _time_in_window(
                now_hhmm, scene.get("trigger_from"), scene.get("trigger_until")
            ):
                return scene
        return None


def _time_in_window(now_hhmm, start, end):
    """"HH:MM"-vergelijking met middernacht-doorloop ondersteund
    (bijv. 22:00-02:00). Ontbrekende grenzen matchen nooit."""
    if not start or not end:
        return False
    if start <= end:
        return start <= now_hhmm < end
    return now_hhmm >= start or now_hhmm < end
```

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_scene_engine.py -q`
Expected: alle tests PASS

- [ ] **Step 5: Commit**

```bash
git add mirror_node/scenes.py tests/test_scene_engine.py
git commit -m "feat: SceneEngine -- prioriteit-evaluatie van scenes"
```

---

## Task 3: MQTT-contract — scene-topics

**Files:**
- Modify: `shared/mqtt_contract.py`
- Test: `tests/test_mqtt_contract.py`

**Interfaces:**
- Produces: `Topics.config_mirror_scenes` (retained, gepubliceerd door
  backend, geabonneerd door mirror_node), `Topics.control_mirror_scene_preview`
  (niet retained). Verwijdert `Topics.config_mirror` en
  `Topics.control_mirror_preview`.

- [ ] **Step 1: Pas de test aan (RED voor de nieuwe properties)**

In `tests/test_mqtt_contract.py`, in `test_topics_without_prefix_match_bare_names`,
vervang:

```python
    assert topics.config_mirror == "config/mirror"
    assert topics.control_mirror_preview == "control/mirror/preview"
```

door:

```python
    assert topics.config_mirror_scenes == "config/mirror/scenes"
    assert topics.control_mirror_scene_preview == "control/mirror/scene-preview"
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py -q`
Expected: FAIL — `AttributeError: 'Topics' object has no attribute 'config_mirror_scenes'`

- [ ] **Step 3: Pas `shared/mqtt_contract.py` aan**

Vervang:

```python
    @property
    def config_mirror(self) -> str:
        return self._p("config/mirror")

    @property
    def control_mirror_preview(self) -> str:
        return self._p("control/mirror/preview")
```

door:

```python
    @property
    def config_mirror_scenes(self) -> str:
        return self._p("config/mirror/scenes")

    @property
    def control_mirror_scene_preview(self) -> str:
        return self._p("control/mirror/scene-preview")
```

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py -q`
Expected: alle tests PASS

- [ ] **Step 5: Commit**

```bash
git add shared/mqtt_contract.py tests/test_mqtt_contract.py
git commit -m "feat: MQTT-topics voor scenes (vervangt config/mirror)"
```

---

## Task 4: `MqttBridge` — scene-publish-methoden

**Files:**
- Modify: `admin/app/mqtt_bridge.py`
- Test: `tests/test_admin_mqtt_bridge.py`

**Interfaces:**
- Consumes: `Topics.config_mirror_scenes`, `Topics.control_mirror_scene_preview` (Task 3).
- Produces: `MqttBridge.publish_mirror_scenes(scenes: list[dict])` (retained),
  `MqttBridge.publish_mirror_scene_preview(scene: dict)` (niet retained).
  Verwijdert `publish_mirror_config`, `publish_mirror_preview`. Gebruikt door Task 5.

- [ ] **Step 1: Schrijf de falende tests**

In `tests/test_admin_mqtt_bridge.py`, vervang
`test_publish_mirror_config_uses_configured_prefix` door:

```python
def test_publish_mirror_scenes_uses_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_scenes([{"id": 1, "name": "Basis"}])

    topic, payload, retain = bridge._client.published[-1]
    assert topic == "test/config/mirror/scenes"
    assert json.loads(payload) == [{"id": 1, "name": "Basis"}]
    assert retain is True


def test_publish_mirror_scene_preview_is_not_retained(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_scene_preview({"id": 1, "effect": "xray"})

    topic, payload, retain = bridge._client.published[-1]
    assert topic == "test/control/mirror/scene-preview"
    assert json.loads(payload) == {"id": 1, "effect": "xray"}
    assert retain is False
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_mqtt_bridge.py -q`
Expected: FAIL — `AttributeError: 'MqttBridge' object has no attribute 'publish_mirror_scenes'`

- [ ] **Step 3: Pas `admin/app/mqtt_bridge.py` aan**

Zoek de bestaande `publish_mirror_config`/`publish_mirror_preview`-methoden
(als die er nog niet zijn verwijderd, staan ze vlak vóór
`publish_mirror_scare_video_config`) en vervang ze door:

```python
    def publish_mirror_scenes(self, scenes):
        self._client.publish(self._topics.config_mirror_scenes, json.dumps(scenes), retain=True)

    def publish_mirror_scene_preview(self, scene):
        self._client.publish(self._topics.control_mirror_scene_preview, json.dumps(scene))
```

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_mqtt_bridge.py -q`
Expected: alle tests PASS

- [ ] **Step 5: Commit**

```bash
git add admin/app/mqtt_bridge.py tests/test_admin_mqtt_bridge.py
git commit -m "feat: MqttBridge publiceert scenes i.p.v. enkelvoudige mirror-config"
```

---

## Task 5: Backend routes — scenes-CRUD

**Files:**
- Create: `admin/app/routers/scenes.py`
- Create: `tests/test_admin_routes_scenes.py`
- Modify: `admin/app/routers/mirror.py` (strip tot alleen `/api/mirror/test`)
- Modify: `admin/app/main.py` (registreer scenes-router)
- Modify: `tests/test_admin_routes_mirror_scare.py` (verwijder mirror-config-tests)

**Interfaces:**
- Consumes: `scenes`-tabel (Task 1), `MqttBridge.publish_mirror_scenes`/
  `publish_mirror_scene_preview` (Task 4).
- Produces: `GET/POST /api/scenes`, `GET/PUT/DELETE /api/scenes/{id}`,
  `PUT /api/scenes/order`, `POST /api/scenes/{id}/preview`. Gebruikt
  door Task 7 (frontend API-client) en Task 9 (Dashboard).

- [ ] **Step 1: Schrijf de falende route-tests**

Maak `tests/test_admin_routes_scenes.py`:

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

    def publish_mirror_scenes(self, scenes):
        self.calls.append(("scenes", scenes))

    def publish_mirror_scene_preview(self, scene):
        self.calls.append(("scene_preview", scene))

    def publish_mirror_test(self):
        self.calls.append(("mirror_test",))


def _client(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app.state.bridge


_SCENE_PAYLOAD = {
    "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
    "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
    "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
    "trigger_type": "always", "trigger_from": None, "trigger_until": None,
}


def test_create_scene_persists_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/scenes", json=_SCENE_PAYLOAD)

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Basis"
    assert created["order_index"] == 0
    assert ("scenes", [created]) in bridge.calls

    listed = client.get("/api/scenes").json()
    assert listed == [created]


def test_create_scene_assigns_increasing_order_index(tmp_path):
    client, bridge = _client(tmp_path)

    first = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()
    second = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "Tweede"}).json()

    assert first["order_index"] == 0
    assert second["order_index"] == 1


def test_get_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/scenes/999")

    assert response.status_code == 404


def test_update_scene_persists_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    response = client.put(f"/api/scenes/{created['id']}", json={**_SCENE_PAYLOAD, "name": "Bijgewerkt"})

    assert response.status_code == 200
    assert response.json()["name"] == "Bijgewerkt"
    assert client.get(f"/api/scenes/{created['id']}").json()["name"] == "Bijgewerkt"
    assert ("scenes", [response.json()]) in bridge.calls


def test_update_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scenes/999", json=_SCENE_PAYLOAD)

    assert response.status_code == 404


def test_delete_scene_removes_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    response = client.delete(f"/api/scenes/{created['id']}")

    assert response.status_code == 200
    assert client.get("/api/scenes").json() == []
    assert ("scenes", []) in bridge.calls


def test_delete_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/scenes/999")

    assert response.status_code == 404


def test_reorder_scenes_updates_order_index(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()

    response = client.put("/api/scenes/order", json={"order": [b["id"], a["id"]]})

    assert response.status_code == 200
    names = [s["name"] for s in client.get("/api/scenes").json()]
    assert names == ["B", "A"]


def test_reorder_scenes_rejects_non_list_order(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scenes/order", json={"order": "niet-een-lijst"})

    assert response.status_code == 400


def test_preview_scene_publishes_without_saving(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()
    bridge.calls.clear()

    response = client.post(
        f"/api/scenes/{created['id']}/preview", json={**_SCENE_PAYLOAD, "effect": "contour"}
    )

    assert response.status_code == 200
    assert bridge.calls == [("scene_preview", {**_SCENE_PAYLOAD, "effect": "contour"})]
    # niet opgeslagen:
    assert client.get(f"/api/scenes/{created['id']}").json()["effect"] == "xray"


def test_scene_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)  # geen login

    assert client.get("/api/scenes").status_code == 401
    assert client.post("/api/scenes", json=_SCENE_PAYLOAD).status_code == 401


def test_canvas_size_round_trips_through_width_height_columns(tmp_path):
    client, bridge = _client(tmp_path)

    created = client.post(
        "/api/scenes", json={**_SCENE_PAYLOAD, "canvas_size": [576, 720]}
    ).json()

    assert created["canvas_size"] == [576, 720]
    assert client.get(f"/api/scenes/{created['id']}").json()["canvas_size"] == [576, 720]


def test_post_mirror_test_still_works(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/mirror/test")

    assert response.status_code == 200
    assert ("mirror_test",) in bridge.calls
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_scenes.py -q`
Expected: FAIL — `404 Not Found` op `/api/scenes` (route bestaat nog niet)

- [ ] **Step 3: Implementeer `admin/app/routers/scenes.py`**

```python
import json
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_SCENE_COLUMNS = (
    "id, name, order_index, enabled, source_mode, effect, params, overlay_hash, "
    "scale, position, canvas_width, canvas_height, source_scale, source_position, "
    "trigger_type, trigger_from, trigger_until"
)

_DEFAULT_SCENE = {
    "name": "Nieuwe scene",
    "enabled": True,
    "source_mode": "camera",
    "effect": "xray",
    "params": {},
    "overlay_hash": None,
    "scale": 1.0,
    "position": [0.5, 0.5],
    "canvas_size": None,
    "source_scale": 1.0,
    "source_position": [0.5, 0.5],
    "trigger_type": "always",
    "trigger_from": None,
    "trigger_until": None,
}


def _row_to_scene(row):
    canvas_width, canvas_height = row[10], row[11]
    return {
        "id": row[0],
        "name": row[1],
        "order_index": row[2],
        "enabled": bool(row[3]),
        "source_mode": row[4],
        "effect": row[5],
        "params": json.loads(row[6]),
        "overlay_hash": row[7],
        "scale": row[8],
        "position": json.loads(row[9]),
        "canvas_size": [canvas_width, canvas_height] if canvas_width and canvas_height else None,
        "source_scale": row[12],
        "source_position": json.loads(row[13]),
        "trigger_type": row[14],
        "trigger_from": row[15],
        "trigger_until": row[16],
    }


def _list_scenes(db):
    rows = db.execute(f"SELECT {_SCENE_COLUMNS} FROM scenes ORDER BY order_index").fetchall()
    return [_row_to_scene(r) for r in rows]


def _publish_scenes(request):
    request.app.state.bridge.publish_mirror_scenes(_list_scenes(request.app.state.db))


def _fields_from_body(body):
    return {k: body.get(k, v) for k, v in _DEFAULT_SCENE.items()}


def _canvas_columns(fields):
    canvas_size = fields["canvas_size"]
    return tuple(canvas_size) if canvas_size else (None, None)


@router.get("/api/scenes")
def list_scenes_route(request: Request):
    return _list_scenes(request.app.state.db)


@router.get("/api/scenes/{scene_id}")
def get_scene_route(scene_id: int, request: Request):
    row = request.app.state.db.execute(
        f"SELECT {_SCENE_COLUMNS} FROM scenes WHERE id = ?", (scene_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    return _row_to_scene(row)


@router.post("/api/scenes")
async def create_scene_route(request: Request):
    body = await request.json()
    fields = _fields_from_body(body)
    db = request.app.state.db
    max_order = db.execute("SELECT MAX(order_index) FROM scenes").fetchone()[0]
    order_index = 0 if max_order is None else max_order + 1
    canvas_width, canvas_height = _canvas_columns(fields)
    cursor = db.execute(
        """INSERT INTO scenes
             (name, order_index, enabled, source_mode, effect, params, overlay_hash,
              scale, position, canvas_width, canvas_height, source_scale, source_position,
              trigger_type, trigger_from, trigger_until)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fields["name"], order_index, int(fields["enabled"]), fields["source_mode"],
            fields["effect"], json.dumps(fields["params"]), fields["overlay_hash"],
            fields["scale"], json.dumps(fields["position"]), canvas_width, canvas_height,
            fields["source_scale"], json.dumps(fields["source_position"]),
            fields["trigger_type"], fields["trigger_from"], fields["trigger_until"],
        ),
    )
    db.commit()
    _publish_scenes(request)
    return get_scene_route(cursor.lastrowid, request)


@router.put("/api/scenes/{scene_id}")
async def update_scene_route(scene_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    body = await request.json()
    fields = _fields_from_body(body)
    canvas_width, canvas_height = _canvas_columns(fields)
    db.execute(
        """UPDATE scenes SET name=?, enabled=?, source_mode=?, effect=?, params=?, overlay_hash=?,
             scale=?, position=?, canvas_width=?, canvas_height=?, source_scale=?, source_position=?,
             trigger_type=?, trigger_from=?, trigger_until=? WHERE id=?""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"], fields["effect"],
            json.dumps(fields["params"]), fields["overlay_hash"], fields["scale"],
            json.dumps(fields["position"]), canvas_width, canvas_height, fields["source_scale"],
            json.dumps(fields["source_position"]), fields["trigger_type"], fields["trigger_from"],
            fields["trigger_until"], scene_id,
        ),
    )
    db.commit()
    _publish_scenes(request)
    return get_scene_route(scene_id, request)


@router.delete("/api/scenes/{scene_id}")
def delete_scene_route(scene_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM scenes WHERE id = ?", (scene_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    _publish_scenes(request)
    return {"ok": True}


@router.put("/api/scenes/order")
async def reorder_scenes_route(request: Request):
    body = await request.json()
    order = body.get("order")
    if not isinstance(order, list):
        raise HTTPException(status_code=400, detail="order moet een lijst met scene-id's zijn")
    db = request.app.state.db
    for index, scene_id in enumerate(order):
        db.execute("UPDATE scenes SET order_index = ? WHERE id = ?", (index, scene_id))
    db.commit()
    _publish_scenes(request)
    return {"ok": True}


@router.post("/api/scenes/{scene_id}/preview")
async def preview_scene_route(scene_id: int, request: Request):
    scene = await request.json()
    request.app.state.bridge.publish_mirror_scene_preview(scene)
    return {"ok": True}
```

- [ ] **Step 4: Strip `admin/app/routers/mirror.py` tot alleen `/api/mirror/test`**

Vervang de hele inhoud van `admin/app/routers/mirror.py` door:

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/api/mirror/test")
def post_mirror_test(request: Request):
    request.app.state.bridge.publish_mirror_test()
    return {"ok": True}
```

- [ ] **Step 5: Registreer de scenes-router in `admin/app/main.py`**

Voeg toe bij de andere router-imports:

```python
from admin.app.routers import scenes as scenes_router
```

En bij de `include_router`-calls (na `app.include_router(mirror_router.router)`):

```python
    app.include_router(scenes_router.router)
```

- [ ] **Step 6: Verwijder de mirror-config-tests uit `tests/test_admin_routes_mirror_scare.py`**

Verwijder de volgende functies (en de bijbehorende
`publish_mirror_config`/`publish_mirror_preview`-methoden op de
`FakeBridge` in dat bestand, die niet meer worden aangeroepen):
`test_put_mirror_config_saves_and_publishes`,
`test_post_mirror_preview_publishes_without_saving`,
`test_put_mirror_config_normalizes_partial_payload`,
`test_put_mirror_config_saves_and_publishes_canvas_fields`.
Laat `test_post_mirror_test_publishes_test_trigger` en alle
scare-zone-tests ongewijzigd staan.

- [ ] **Step 7: Run de volledige backend-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests PASS (inclusief de nieuwe scenes-tests en de
opgeschoonde mirror-scare-tests)

- [ ] **Step 8: Commit**

```bash
git add admin/app/routers/scenes.py admin/app/routers/mirror.py admin/app/main.py \
  tests/test_admin_routes_scenes.py tests/test_admin_routes_mirror_scare.py
git commit -m "feat: /api/scenes CRUD, mirror.py strippen tot alleen test-trigger"
```

---

## Task 6: mirror_node — hoofdlus herbedraden naar scenes

**Files:**
- Modify: `mirror_node/main.py`
- Delete: `mirror_node/active_config.py`
- Modify: `tests/test_mirror_main.py`

**Interfaces:**
- Consumes: `SceneEngine` (Task 2), `Topics.config_mirror_scenes`/
  `Topics.control_mirror_scene_preview` (Task 3).
- Produces: module-level `scene_engine: SceneEngine` in
  `mirror_node/main.py`; `_render(frame, scene, logger)` (nu met
  `scene`-parameter i.p.v. het globale `active_config`).

- [ ] **Step 1: Schrijf/pas de falende tests aan**

In `tests/test_mirror_main.py`, voeg bovenaan `import json` toe (na
`import pytest`). Verwijder `test_apply_config_message_ignores_non_dict_json`
en `test_preview_config_also_syncs_overlay`. Pas
`test_on_message_survives_malformed_payload` aan: vervang
`topics.config_mirror` door `topics.config_mirror_scenes`. Voeg toe:

```python
def test_apply_scenes_message_ignores_non_list_json():
    logger = _FakeLogger()
    mirror_main._apply_scenes_message('{"not": "a list"}', logger)
    assert logger.errors


def test_apply_scenes_message_ignores_malformed_json():
    logger = _FakeLogger()
    mirror_main._apply_scenes_message("{niet-geldig-json", logger)
    assert logger.errors


def test_apply_scenes_message_updates_scene_engine():
    scene = {"id": 1, "trigger_type": "always", "overlay_hash": None}
    mirror_main._apply_scenes_message(json.dumps([scene]), _FakeLogger())

    assert mirror_main.scene_engine.resolve(False, "12:00") == scene


def test_apply_scenes_message_syncs_overlay_for_each_scene(monkeypatch):
    started = []
    monkeypatch.setattr(
        mirror_main.threading, "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    scenes = [
        {"id": 1, "trigger_type": "always", "overlay_hash": "a" * 64},
        {"id": 2, "trigger_type": "motion", "overlay_hash": "b" * 64},
    ]

    mirror_main._apply_scenes_message(json.dumps(scenes), _FakeLogger())

    synced_hashes = [kw["args"][2] for kw in started]
    assert synced_hashes == [["a" * 64], ["b" * 64]]


def test_apply_scene_preview_message_sets_preview_and_syncs_overlay(monkeypatch):
    started = []
    monkeypatch.setattr(
        mirror_main.threading, "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    scene = {"id": 5, "trigger_type": "always", "overlay_hash": "a" * 64}
    try:
        mirror_main._apply_scene_preview_message(json.dumps(scene), _FakeLogger())
        assert mirror_main.scene_engine.resolve(False, "12:00") == scene
        assert started and started[0]["args"][2] == ["a" * 64]
    finally:
        mirror_main.scene_engine._preview = None
        mirror_main.scene_engine._preview_set_at = None
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py -q`
Expected: FAIL — `AttributeError: module 'mirror_node.main' has no attribute '_apply_scenes_message'`

- [ ] **Step 3: Werk de imports en module-state in `mirror_node/main.py` bij**

Vervang:

```python
from mirror_node.active_config import ActiveMirrorConfig
```

door:

```python
from mirror_node.scenes import SceneEngine
```

Vervang:

```python
active_config = ActiveMirrorConfig()
```

door:

```python
scene_engine = SceneEngine()
```

- [ ] **Step 4: Vervang `_apply_config_message` door de twee nieuwe functies**

Vervang de hele `_apply_config_message`-functie door:

```python
def _apply_scenes_message(payload, logger):
    try:
        scenes = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige scenes-JSON ontvangen, genegeerd")
        return
    if not isinstance(scenes, list):
        logger.error("Scenes-config is geen lijst, genegeerd: %r", scenes)
        return
    scene_engine.set_scenes(scenes)
    for scene in scenes:
        if isinstance(scene, dict):
            _sync_overlay_in_background(scene)


def _apply_scene_preview_message(payload, logger):
    try:
        scene = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige scene-preview-JSON ontvangen, genegeerd")
        return
    if not isinstance(scene, dict):
        logger.error("Scene-preview is geen object, genegeerd: %r", scene)
        return
    scene_engine.set_preview(scene)
    _sync_overlay_in_background(scene)
```

- [ ] **Step 5: Werk `make_on_message` bij**

Vervang:

```python
            if msg.topic == topics.config_mirror:
                _apply_config_message(msg.payload.decode(), is_preview=False, logger=logger)
                return
            if msg.topic == topics.control_mirror_preview:
                _apply_config_message(msg.payload.decode(), is_preview=True, logger=logger)
                return
```

door:

```python
            if msg.topic == topics.config_mirror_scenes:
                _apply_scenes_message(msg.payload.decode(), logger)
                return
            if msg.topic == topics.control_mirror_scene_preview:
                _apply_scene_preview_message(msg.payload.decode(), logger)
                return
```

- [ ] **Step 6: Werk `_render` bij zodat 'ie een scene-parameter neemt**

Vervang:

```python
def _render(frame, logger):
    config = active_config.get()
    try:
        effect_fn = get_effect(config.get("effect", "xray"))
    except ValueError:
        logger.error("Onbekend effect in actieve config: %s", config.get("effect"))
        return frame

    result = effect_fn(frame, config.get("params", {}))

    canvas_size = config.get("canvas_size")
    if canvas_size:
        result = place_on_canvas(
            result,
            tuple(canvas_size),
            scale=config.get("source_scale", 1.0),
            position=tuple(config.get("source_position", [0.5, 0.5])),
        )

    overlay_hash = config.get("overlay_hash")
    if overlay_hash:
        overlay_img = _load_overlay(overlay_hash, logger)
        if overlay_img is not None and overlay_img.ndim == 3 and overlay_img.shape[2] == 4:
            position = config.get("position", [0.5, 0.5])
            if len(position) != 2:
                logger.warning("Ongeldige position in config, val terug op (0.5, 0.5): %r", position)
                position = (0.5, 0.5)
            result = composite_overlay(
                result,
                overlay_img,
                scale=config.get("scale", 1.0),
                position=tuple(position),
            )
    return result
```

door:

```python
def _render(frame, scene, logger):
    try:
        effect_fn = get_effect(scene.get("effect", "xray"))
    except ValueError:
        logger.error("Onbekend effect in actieve scene: %s", scene.get("effect"))
        return frame

    result = effect_fn(frame, scene.get("params", {}))

    canvas_size = scene.get("canvas_size")
    if canvas_size:
        result = place_on_canvas(
            result,
            tuple(canvas_size),
            scale=scene.get("source_scale", 1.0),
            position=tuple(scene.get("source_position", [0.5, 0.5])),
        )

    overlay_hash = scene.get("overlay_hash")
    if overlay_hash:
        overlay_img = _load_overlay(overlay_hash, logger)
        if overlay_img is not None and overlay_img.ndim == 3 and overlay_img.shape[2] == 4:
            position = scene.get("position", [0.5, 0.5])
            if len(position) != 2:
                logger.warning("Ongeldige position in scene, val terug op (0.5, 0.5): %r", position)
                position = (0.5, 0.5)
            result = composite_overlay(
                result,
                overlay_img,
                scale=scene.get("scale", 1.0),
                position=tuple(position),
            )
    return result
```

- [ ] **Step 7: Werk de MQTT-subscribes in `main()` bij**

Vervang:

```python
        client.subscribe(topics.config_mirror)
        client.subscribe(topics.control_mirror_preview)
```

door:

```python
        client.subscribe(topics.config_mirror_scenes)
        client.subscribe(topics.control_mirror_scene_preview)
```

- [ ] **Step 8: Herschrijf de hoofdlus in `main()`**

Vervang het blok vanaf `active_until = 0.0` tot en met de `while True`-lus
(binnen de bestaande `try`/`finally`) door:

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

            if sleeping.is_set():
                if not MIRROR_HEADLESS:
                    cv2.imshow("mirror", frame * 0)
                    cv2.waitKey(1)
                time.sleep(0.2)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            now = time.time()
            now_hhmm = time.strftime("%H:%M")

            fired = False
            if trigger.detect(gray) and now > active_until:
                client.publish(topics.mirror_triggered, trigger_payload())
                logger.info("mirror triggered")
                active_until = time.time() + ACTIVE_SECONDS
                fired = True

            if test_trigger_requested.is_set():
                test_trigger_requested.clear()
                logger.info("mirror test-trigger")
                active_until = time.time() + ACTIVE_SECONDS
                fired = True

            winning = scene_engine.resolve(now < active_until, now_hhmm)

            # Bij het moment van afgaan zelf: als de winnende scene een
            # scare-video is, speel die nu blokkerend af (bestaand
            # _handle_trigger-pad, ongewijzigd) i.p.v. elke cyclus opnieuw.
            if fired and winning is not None and winning.get("source_mode") == "scare_video":
                cooldown = _handle_trigger(streamer, logger)
                active_until = time.time() + cooldown
                winning = scene_engine.resolve(True, now_hhmm)

            if winning is None:
                rendered = frame * 0
            elif winning.get("source_mode") == "scare_video":
                # net al blokkerend afgespeeld (of nog in het venster van een
                # eerdere trigger zonder nieuwe afgaande trigger deze cyclus)
                # -- niets aanvullends te renderen.
                rendered = frame * 0
            else:
                try:
                    rendered = _render(frame, winning, logger)
                except Exception as exc:
                    logger.error("Fout bij renderen: %s", exc)
                    rendered = frame
            streamer.publish_frame(rendered)
            if not MIRROR_HEADLESS:
                cv2.imshow("mirror", rendered)
                cv2.waitKey(1)
    finally:
        cap.release()
        if not MIRROR_HEADLESS:
            cv2.destroyAllWindows()
        streamer.stop()
        client.loop_stop()
```

- [ ] **Step 9: Verwijder `mirror_node/active_config.py`**

```bash
git rm mirror_node/active_config.py
```

- [ ] **Step 10: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py tests/test_scene_engine.py -q`
Expected: alle tests PASS

- [ ] **Step 11: Run de volledige backend/node-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests PASS

- [ ] **Step 12: Commit**

```bash
git add mirror_node/main.py tests/test_mirror_main.py
git commit -m "feat: mirror_node evalueert scenes i.p.v. één globale config"
```

---

## Task 7: Frontend — `Scene`-type + scenes-API

**Files:**
- Modify: `admin/frontend/src/types.ts`
- Create: `admin/frontend/src/api/scenes.ts`
- Modify: `admin/frontend/src/api/mirror.ts`

**Interfaces:**
- Produces: `Scene`-type, `listScenes`, `getScene`, `createScene`,
  `updateScene`, `deleteScene`, `reorderScenes`, `previewScene`.
  Gebruikt door Task 8 en 9. `testMirror` blijft in `api/mirror.ts`.

- [ ] **Step 1: Vervang `MirrorConfig` door `Scene` in `types.ts`**

Vervang:

```ts
export interface MirrorConfig {
  effect: "xray" | "thermal" | "contour" | "posterize";
  params: Record<string, number>;
  overlay_hash: string | null;
  scale: number;
  position: [number, number];
  canvas_size: [number, number] | null;
  source_scale: number;
  source_position: [number, number];
}
```

door:

```ts
export interface Scene {
  id: number;
  name: string;
  order_index: number;
  enabled: boolean;
  source_mode: "camera" | "scare_video";
  effect: "xray" | "thermal" | "contour" | "posterize";
  params: Record<string, number>;
  overlay_hash: string | null;
  scale: number;
  position: [number, number];
  canvas_size: [number, number] | null;
  source_scale: number;
  source_position: [number, number];
  trigger_type: "always" | "motion" | "schedule";
  trigger_from: string | null;
  trigger_until: string | null;
}
```

- [ ] **Step 2: Maak `admin/frontend/src/api/scenes.ts`**

```ts
import { apiFetch } from "./client";
import type { Scene } from "../types";

export type SceneDraft = Omit<Scene, "id" | "order_index">;

export function listScenes(): Promise<Scene[]> {
  return apiFetch<Scene[]>("/api/scenes");
}

export function getScene(id: number): Promise<Scene> {
  return apiFetch<Scene>(`/api/scenes/${id}`);
}

export function createScene(scene: SceneDraft): Promise<Scene> {
  return apiFetch<Scene>("/api/scenes", { method: "POST", body: JSON.stringify(scene) });
}

export function updateScene(id: number, scene: SceneDraft): Promise<Scene> {
  return apiFetch<Scene>(`/api/scenes/${id}`, { method: "PUT", body: JSON.stringify(scene) });
}

export function deleteScene(id: number): Promise<void> {
  return apiFetch(`/api/scenes/${id}`, { method: "DELETE" });
}

export function reorderScenes(order: number[]): Promise<void> {
  return apiFetch("/api/scenes/order", { method: "PUT", body: JSON.stringify({ order }) });
}

export function previewScene(id: number, scene: SceneDraft): Promise<void> {
  return apiFetch(`/api/scenes/${id}/preview`, { method: "POST", body: JSON.stringify(scene) });
}
```

- [ ] **Step 3: Trim `admin/frontend/src/api/mirror.ts`**

Vervang de hele inhoud door:

```ts
import { apiFetch } from "./client";

export function testMirror(): Promise<void> {
  return apiFetch("/api/mirror/test", { method: "POST" });
}
```

- [ ] **Step 4: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: fouten in `MirrorPage.tsx`/`OverlayCanvas.tsx`-gebruik van
`MirrorConfig` (die pas in Task 8/10 verdwijnen) — dat is verwacht op
dit punt; geen fouten in de nieuwe `scenes.ts`/`mirror.ts` zelf.

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/types.ts admin/frontend/src/api/scenes.ts admin/frontend/src/api/mirror.ts
git commit -m "feat: Scene-type en scenes-API-client"
```

---

## Task 8: Frontend — `SceneWizardModal`

**Files:**
- Create: `admin/frontend/src/components/SceneWizardModal.tsx`
- Create: `admin/frontend/src/components/SceneWizardModal.css`

**Interfaces:**
- Consumes: `Scene`, `getScene`/`createScene`/`updateScene`/`previewScene`
  (Task 7), `OverlayCanvas` (bestaand, ongewijzigd), `MediaLibrary`
  (bestaand, ongewijzigd), `getSettings` (bestaand, `api/settings.ts`).
- Produces: `<SceneWizardModal sceneId={number|null} onClose={() => void} onSaved={() => void} />`.
  Gebruikt door Task 9.

- [ ] **Step 1: Implementeer `SceneWizardModal.tsx`**

```tsx
import { useEffect, useState } from "react";
import { getScene, createScene, updateScene, previewScene, type SceneDraft } from "../api/scenes";
import { getSettings } from "../api/settings";
import MediaLibrary from "./MediaLibrary";
import OverlayCanvas from "./OverlayCanvas";
import type { Scene } from "../types";
import "./SceneWizardModal.css";

const EFFECTS = ["xray", "thermal", "contour", "posterize"] as const;
const FIELD_LABELS: Record<string, string> = {
  intensity: "Intensiteit",
  threshold1: "Drempel 1",
  threshold2: "Drempel 2",
  levels: "Niveaus",
};

function paramFieldsFor(effect: Scene["effect"]): string[] {
  switch (effect) {
    case "xray":
    case "thermal":
      return ["intensity"];
    case "contour":
      return ["threshold1", "threshold2"];
    case "posterize":
      return ["levels"];
  }
}

const EMPTY_DRAFT: SceneDraft = {
  name: "Nieuwe scene",
  enabled: true,
  source_mode: "camera",
  effect: "xray",
  params: {},
  overlay_hash: null,
  scale: 1.0,
  position: [0.5, 0.5],
  canvas_size: null,
  source_scale: 1.0,
  source_position: [0.5, 0.5],
  trigger_type: "always",
  trigger_from: null,
  trigger_until: null,
};

interface Props {
  sceneId: number | null;
  onClose: () => void;
  onSaved: () => void;
}

type Step = "input" | "animation" | "output" | "trigger";
const STEP_LABEL: Record<Step, string> = {
  input: "Input",
  animation: "Animatie",
  output: "Output",
  trigger: "Trigger",
};

export default function SceneWizardModal({ sceneId, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<SceneDraft>(EMPTY_DRAFT);
  const [step, setStep] = useState<Step>("input");
  const [cameraSource, setCameraSource] = useState("");
  const [canvasWidthDraft, setCanvasWidthDraft] = useState("");
  const [canvasHeightDraft, setCanvasHeightDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSettings()
      .then((s) => setCameraSource(s.mirror_camera_source))
      .catch(() => {
        /* voorbeeldbeeld blijft dan "niet beschikbaar" */
      });
    if (sceneId !== null) {
      getScene(sceneId)
        .then((scene) => {
          setDraft(scene);
          setCanvasWidthDraft(scene.canvas_size ? String(scene.canvas_size[0]) : "");
          setCanvasHeightDraft(scene.canvas_size ? String(scene.canvas_size[1]) : "");
        })
        .catch(() => setError("Scene kon niet worden geladen."));
    }
  }, [sceneId]);

  // Live preview tijdens het bewerken -- alleen mogelijk voor een al
  // opgeslagen scene (de preview-route heeft een id nodig). Simpele
  // fire-and-forget bij elke wijziging, geen aparte throttle-timer:
  // elke keypress/sleep-update is al een expliciete, door de gebruiker
  // bedoelde wijziging.
  useEffect(() => {
    if (sceneId === null) return;
    previewScene(sceneId, draft).catch((err) => console.error("Preview mislukt:", err));
  }, [sceneId, draft]);

  function update(patch: Partial<SceneDraft>) {
    setDraft((prev) => ({ ...prev, ...patch }));
  }

  function updateCanvasSize(widthStr: string, heightStr: string) {
    const w = parseInt(widthStr, 10);
    const h = parseInt(heightStr, 10);
    update({ canvas_size: w > 0 && h > 0 ? [w, h] : null });
  }

  async function handleSave() {
    setSaving(true);
    try {
      if (sceneId === null) {
        await createScene(draft);
      } else {
        await updateScene(sceneId, draft);
      }
      onSaved();
      onClose();
    } catch {
      setError("Opslaan is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  const steps: Step[] =
    draft.source_mode === "camera" ? ["input", "animation", "output", "trigger"] : ["input", "trigger"];
  const stepIndex = steps.indexOf(step);

  return (
    <div className="scene-modal__backdrop" role="dialog" aria-modal="true">
      <div className="scene-modal">
        <header className="scene-modal__header">
          <input
            className="scene-modal__name"
            type="text"
            value={draft.name}
            onChange={(e) => update({ name: e.target.value })}
            placeholder="Naam van deze scene"
          />
          <button className="scene-modal__close" type="button" onClick={onClose} aria-label="Sluiten">
            ×
          </button>
        </header>

        <nav className="scene-modal__steps">
          {steps.map((s, i) => (
            <span key={s} className="scene-modal__step" data-active={s === step} data-done={i < stepIndex}>
              {i + 1}. {STEP_LABEL[s]}
            </span>
          ))}
        </nav>

        {error && (
          <p className="scene-modal__error" role="alert">
            {error}
          </p>
        )}

        <div className="scene-modal__body">
          {step === "input" && (
            <div className="scene-modal__field-group">
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="source_mode"
                  checked={draft.source_mode === "camera"}
                  onChange={() => update({ source_mode: "camera" })}
                />
                Live camera-bron
              </label>
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="source_mode"
                  checked={draft.source_mode === "scare_video"}
                  onChange={() => update({ source_mode: "scare_video" })}
                />
                Scare-video (willekeurig uit de ingeschakelde bibliotheek)
              </label>
            </div>
          )}

          {step === "animation" && (
            <>
              <div className="scene-modal__field-group">
                <label className="scene-modal__field">
                  <span>Effect</span>
                  <select
                    value={draft.effect}
                    onChange={(e) => update({ effect: e.target.value as Scene["effect"], params: {} })}
                  >
                    {EFFECTS.map((effect) => (
                      <option key={effect} value={effect}>
                        {effect}
                      </option>
                    ))}
                  </select>
                </label>
                {paramFieldsFor(draft.effect).map((field) => (
                  <label className="scene-modal__field" key={field}>
                    <span>{FIELD_LABELS[field] ?? field}</span>
                    <input
                      type="number"
                      step="0.1"
                      value={draft.params[field] ?? ""}
                      onChange={(e) => {
                        const parsed = parseFloat(e.target.value);
                        if (Number.isNaN(parsed)) return;
                        update({ params: { ...draft.params, [field]: parsed } });
                      }}
                    />
                  </label>
                ))}
              </div>
              <p className="scene-modal__label">Overlay</p>
              <MediaLibrary
                category="mirror_overlay"
                selectionMode="single"
                selected={draft.overlay_hash ? [draft.overlay_hash] : []}
                onSelectionChange={(hashes) => update({ overlay_hash: hashes[0] ?? null })}
              />
            </>
          )}

          {step === "output" && (
            <>
              <div className="scene-modal__field-group">
                <label className="scene-modal__field">
                  <span>Breedte (optioneel)</span>
                  <input
                    type="number"
                    min="1"
                    value={canvasWidthDraft}
                    placeholder="bijv. 576"
                    onChange={(e) => {
                      setCanvasWidthDraft(e.target.value);
                      updateCanvasSize(e.target.value, canvasHeightDraft);
                    }}
                  />
                </label>
                <label className="scene-modal__field">
                  <span>Hoogte (optioneel)</span>
                  <input
                    type="number"
                    min="1"
                    value={canvasHeightDraft}
                    placeholder="bijv. 720"
                    onChange={(e) => {
                      setCanvasHeightDraft(e.target.value);
                      updateCanvasSize(canvasWidthDraft, e.target.value);
                    }}
                  />
                </label>
              </div>
              {cameraSource ? (
                <OverlayCanvas
                  streamUrl={cameraSource}
                  overlayUrl={draft.overlay_hash ? `/api/media/${draft.overlay_hash}` : null}
                  scale={draft.scale}
                  position={draft.position}
                  onPositionChange={(position) => update({ position })}
                  onScaleChange={(scale) => update({ scale })}
                  canvasSize={draft.canvas_size}
                  sourceScale={draft.source_scale}
                  sourcePosition={draft.source_position}
                  onSourcePositionChange={(source_position) => update({ source_position })}
                  onSourceScaleChange={(source_scale) => update({ source_scale })}
                />
              ) : (
                <p className="scene-modal__label">
                  Geen camera-bron ingesteld op de Instellingen-pagina — kan hier niet getoond worden.
                </p>
              )}
            </>
          )}

          {step === "trigger" && (
            <div className="scene-modal__field-group">
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="trigger_type"
                  checked={draft.trigger_type === "always"}
                  onChange={() => update({ trigger_type: "always", trigger_from: null, trigger_until: null })}
                />
                Altijd (basis-scene)
              </label>
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="trigger_type"
                  checked={draft.trigger_type === "motion"}
                  onChange={() => update({ trigger_type: "motion", trigger_from: null, trigger_until: null })}
                />
                Beweging
              </label>
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="trigger_type"
                  checked={draft.trigger_type === "schedule"}
                  onChange={() => update({ trigger_type: "schedule" })}
                />
                Tijdschema
              </label>
              {draft.trigger_type === "schedule" && (
                <div className="scene-modal__field-group">
                  <label className="scene-modal__field">
                    <span>Van</span>
                    <input
                      type="time"
                      value={draft.trigger_from ?? ""}
                      onChange={(e) => update({ trigger_from: e.target.value })}
                    />
                  </label>
                  <label className="scene-modal__field">
                    <span>Tot</span>
                    <input
                      type="time"
                      value={draft.trigger_until ?? ""}
                      onChange={(e) => update({ trigger_until: e.target.value })}
                    />
                  </label>
                </div>
              )}
            </div>
          )}
        </div>

        <footer className="scene-modal__footer">
          <button
            type="button"
            className="scene-modal__nav"
            disabled={stepIndex === 0}
            onClick={() => setStep(steps[stepIndex - 1])}
          >
            Vorige
          </button>
          {stepIndex < steps.length - 1 ? (
            <button type="button" className="scene-modal__nav" onClick={() => setStep(steps[stepIndex + 1])}>
              Volgende
            </button>
          ) : (
            <button type="button" className="scene-modal__save" disabled={saving} onClick={handleSave}>
              {saving ? "Bezig…" : "Opslaan"}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Maak `SceneWizardModal.css`**

```css
.scene-modal__backdrop {
  position: fixed;
  inset: 0;
  background: rgba(11, 11, 15, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
  padding: 1.5rem;
}

.scene-modal {
  width: 100%;
  max-width: 640px;
  max-height: 90vh;
  overflow-y: auto;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
  color: var(--bone);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

.scene-modal__header {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem 1.25rem 0.75rem;
  border-bottom: 1px solid var(--panel-edge);
}

.scene-modal__name {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--bone);
  font-size: 1.1rem;
  font-weight: 700;
  outline: none;
}

.scene-modal__close {
  background: transparent;
  border: none;
  color: var(--ash);
  font-size: 1.5rem;
  line-height: 1;
  cursor: pointer;
}

.scene-modal__steps {
  display: flex;
  gap: 0.5rem;
  padding: 0.9rem 1.25rem;
  flex-wrap: wrap;
}

.scene-modal__step {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ash);
  padding: 0.3rem 0.6rem;
  border: 1px solid var(--panel-edge);
  border-radius: 999px;
}

.scene-modal__step[data-active="true"] {
  color: var(--void);
  background: var(--ember);
  border-color: var(--ember);
}

.scene-modal__step[data-done="true"] {
  color: var(--signal);
  border-color: var(--signal);
}

.scene-modal__error {
  margin: 0 1.25rem;
  color: var(--alarm);
  font-size: 0.85rem;
}

.scene-modal__body {
  padding: 0.5rem 1.25rem 1.25rem;
}

.scene-modal__field-group {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 1rem;
}

.scene-modal__field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.8rem;
  color: var(--ash);
}

.scene-modal__field input,
.scene-modal__field select {
  padding: 0.55rem 0.65rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 6px;
  color: var(--bone);
  color-scheme: dark;
}

.scene-modal__radio {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
  width: 100%;
}

.scene-modal__label {
  font-size: 0.8rem;
  color: var(--ash);
  margin: 0.5rem 0;
}

.scene-modal__footer {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.25rem 1.25rem;
  border-top: 1px solid var(--panel-edge);
}

.scene-modal__nav,
.scene-modal__save {
  padding: 0.65rem 1.3rem;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  cursor: pointer;
}

.scene-modal__nav {
  background: transparent;
  border: 1px solid var(--panel-edge);
  color: var(--bone);
}

.scene-modal__nav:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.scene-modal__save {
  background: var(--ember);
  border: none;
  color: var(--void);
  margin-left: auto;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen nieuwe fouten vanuit `SceneWizardModal.tsx` zelf (de
bestaande `MirrorPage.tsx`-fouten uit Task 7 blijven tot Task 10)

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/components/SceneWizardModal.tsx admin/frontend/src/components/SceneWizardModal.css
git commit -m "feat: SceneWizardModal -- 4-staps scene-editor"
```

---

## Task 9: Frontend — Dashboard: scene-kaarten + mirror-node-besturing

**Files:**
- Modify: `admin/frontend/src/pages/DashboardPage.tsx`
- Modify: `admin/frontend/src/pages/DashboardPage.css`

**Interfaces:**
- Consumes: `Scene`, `listScenes`/`deleteScene`/`reorderScenes`
  (Task 7), `SceneWizardModal` (Task 8), `testMirror` (Task 7),
  bestaande `startMirrorProcess`/`stopMirrorProcess`/`getMirrorProcessStatus`
  (`api/mirrorProcess.ts`, ongewijzigd).

- [ ] **Step 1: Werk de imports bovenaan `DashboardPage.tsx` bij**

Vervang:

```tsx
import { useEffect, useState, useCallback } from "react";
import { getNodes } from "../api/nodes";
import { getSchedule, putSchedule, emergencyStop, wake } from "../api/schedule";
import { useWebSocket } from "../hooks/useWebSocket";
import NodeStatusCard from "../components/NodeStatusCard";
import type { NodeStatusMap, Schedule, WsMessage } from "../types";
import "./DashboardPage.css";
```

door:

```tsx
import { useEffect, useState, useCallback } from "react";
import { getNodes } from "../api/nodes";
import { getSchedule, putSchedule, emergencyStop, wake } from "../api/schedule";
import { listScenes, deleteScene, reorderScenes } from "../api/scenes";
import { testMirror } from "../api/mirror";
import { startMirrorProcess, stopMirrorProcess, getMirrorProcessStatus } from "../api/mirrorProcess";
import { useWebSocket } from "../hooks/useWebSocket";
import NodeStatusCard from "../components/NodeStatusCard";
import SceneWizardModal from "../components/SceneWizardModal";
import type { NodeStatusMap, Schedule, Scene, WsMessage } from "../types";
import "./DashboardPage.css";
```

- [ ] **Step 2: Voeg state en effects toe**

Voeg toe, direct ná de bestaande `useState`-regels (vóór de eerste `useEffect`):

```tsx
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardSceneId, setWizardSceneId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [processBusy, setProcessBusy] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [testing, setTesting] = useState(false);
```

Vervang de bestaande `useEffect(() => { getNodes()... getSchedule()... }, [])`
door (voegt scenes + mirror-node-status toe):

```tsx
  function refreshScenes() {
    listScenes()
      .then(setScenes)
      .catch(() => setError("Scenes konden niet worden geladen."));
  }

  useEffect(() => {
    getNodes()
      .then(setNodes)
      .catch(() => setError("Nodes konden niet worden geladen."));
    getSchedule()
      .then(setSchedule)
      .catch(() => setError("Tijdvenster kon niet worden geladen."));
    refreshScenes();
    getMirrorProcessStatus()
      .then((result) => setRunning(result.running))
      .catch(() => {
        /* status blijft "gestopt" tonen bij een netwerkfout */
      });
  }, []);
```

- [ ] **Step 3: Breid `handleWsMessage` uit met de mirror-node-logregels**

Vervang:

```tsx
  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type !== "status") return;
    const match = msg.topic.match(/^status\/(.+)$/);
    if (!match) return;
    const node = match[1];
    setNodes((prev) => ({ ...prev, [node]: { status: msg.payload as "online" | "offline" } }));
  }, []);
```

door:

```tsx
  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type === "status") {
      const match = msg.topic.match(/^status\/(.+)$/);
      if (match) {
        setNodes((prev) => ({ ...prev, [match[1]]: { status: msg.payload as "online" | "offline" } }));
      }
      return;
    }
    if (msg.type === "log" && msg.topic === "process/mirror-node") {
      setLogLines((prev) => [...prev, msg.payload].slice(-200));
    }
  }, []);
```

- [ ] **Step 4: Voeg de nieuwe handlers toe**

Voeg toe, na de bestaande `handleWake`-functie:

```tsx
  async function handleDeleteScene(id: number) {
    try {
      await deleteScene(id);
      refreshScenes();
    } catch {
      setError("Scene verwijderen is mislukt.");
    }
  }

  function handleMoveScene(id: number, direction: -1 | 1) {
    const index = scenes.findIndex((s) => s.id === id);
    const target = index + direction;
    if (index === -1 || target < 0 || target >= scenes.length) return;
    const reordered = [...scenes];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    setScenes(reordered);
    reorderScenes(reordered.map((s) => s.id)).catch(() => {
      setError("Volgorde wijzigen is mislukt.");
      refreshScenes();
    });
  }

  function openWizard(id: number | null) {
    setWizardSceneId(id);
    setWizardOpen(true);
  }

  function triggerSummary(scene: Scene): string {
    if (scene.trigger_type === "always") return "Altijd";
    if (scene.trigger_type === "motion") return "Beweging";
    return `Tijdschema ${scene.trigger_from ?? "?"}–${scene.trigger_until ?? "?"}`;
  }

  async function handleStartProcess() {
    setProcessBusy(true);
    try {
      const status = await startMirrorProcess();
      setRunning(status.running);
    } catch {
      setError("Mirror-node starten is mislukt.");
    } finally {
      setProcessBusy(false);
    }
  }

  async function handleStopProcess() {
    setProcessBusy(true);
    try {
      const status = await stopMirrorProcess();
      setRunning(status.running);
    } catch {
      setError("Mirror-node stoppen is mislukt.");
    } finally {
      setProcessBusy(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    try {
      await testMirror();
    } catch {
      setError("Testoproep is mislukt.");
    } finally {
      setTesting(false);
    }
  }
```

- [ ] **Step 5: Voeg de JSX-secties toe**

Voeg toe direct na het bestaande `{notice && (...)}`-blok, vóór de
"Nodes op het paneel"-sectie:

```tsx
      <section className="dash-panel">
        <p className="dash-panel__eyebrow">Scenes</p>
        <div className="scene-grid">
          {scenes.map((scene, index) => (
            <div className="scene-card" key={scene.id} data-enabled={scene.enabled}>
              <p className="scene-card__name">{scene.name}</p>
              <p className="scene-card__trigger">{triggerSummary(scene)}</p>
              <div className="scene-card__actions">
                <button type="button" onClick={() => handleMoveScene(scene.id, -1)} disabled={index === 0}>
                  ▲
                </button>
                <button
                  type="button"
                  onClick={() => handleMoveScene(scene.id, 1)}
                  disabled={index === scenes.length - 1}
                >
                  ▼
                </button>
                <button type="button" onClick={() => openWizard(scene.id)}>
                  Bewerken
                </button>
                <button type="button" onClick={() => handleDeleteScene(scene.id)}>
                  Verwijderen
                </button>
              </div>
            </div>
          ))}
          <button type="button" className="scene-card scene-card--add" onClick={() => openWizard(null)}>
            + Nieuwe scene
          </button>
        </div>
      </section>

      <section className="dash-panel">
        <p className="dash-panel__eyebrow">Mirror-node</p>
        <div className="mirror-process-row">
          <span className={`mirror-process-status ${running ? "mirror-process-status--running" : ""}`}>
            {running ? "Draait" : "Gestopt"}
          </span>
          <button type="button" onClick={handleStartProcess} disabled={processBusy || running}>
            {processBusy ? "Bezig…" : "Start"}
          </button>
          <button type="button" onClick={handleStopProcess} disabled={processBusy || !running}>
            {processBusy ? "Bezig…" : "Stop"}
          </button>
          <button type="button" onClick={handleTest} disabled={testing}>
            {testing ? "Bezig…" : "Test"}
          </button>
        </div>
        <pre className="mirror-process-log">
          {logLines.length ? logLines.join("\n") : "Nog geen logregels — start de mirror-node om ze hier te zien."}
        </pre>
      </section>

      {wizardOpen && (
        <SceneWizardModal
          sceneId={wizardSceneId}
          onClose={() => setWizardOpen(false)}
          onSaved={refreshScenes}
        />
      )}
```

- [ ] **Step 6: Voeg CSS toe aan `DashboardPage.css`**

```css
.scene-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}

.scene-card {
  padding: 1rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.scene-card[data-enabled="false"] {
  opacity: 0.5;
}

.scene-card__name {
  font-weight: 700;
  color: var(--bone);
}

.scene-card__trigger {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--signal);
}

.scene-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: auto;
}

.scene-card__actions button {
  padding: 0.35rem 0.6rem;
  font-size: 0.75rem;
  background: transparent;
  border: 1px solid var(--panel-edge);
  border-radius: 6px;
  color: var(--bone);
  cursor: pointer;
}

.scene-card--add {
  align-items: center;
  justify-content: center;
  color: var(--ash);
  cursor: pointer;
  border-style: dashed;
}

.mirror-process-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.mirror-process-row button {
  padding: 0.55rem 1.1rem;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  color: var(--bone);
  cursor: pointer;
}

.mirror-process-row button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mirror-process-status {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ash);
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--panel-edge);
  border-radius: 999px;
}

.mirror-process-status--running {
  color: var(--signal);
  border-color: var(--signal);
}

.mirror-process-log {
  margin-top: 0.75rem;
  max-height: 220px;
  overflow-y: auto;
  padding: 0.75rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.75rem;
  color: var(--ash);
  white-space: pre-wrap;
}
```

- [ ] **Step 7: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen nieuwe fouten vanuit `DashboardPage.tsx` zelf

- [ ] **Step 8: Commit**

```bash
git add admin/frontend/src/pages/DashboardPage.tsx admin/frontend/src/pages/DashboardPage.css
git commit -m "feat: scene-kaarten + mirror-node-besturing op het Dashboard"
```

---

## Task 10: Frontend — MirrorPage verwijderen, navigatie bijwerken

**Files:**
- Delete: `admin/frontend/src/pages/MirrorPage.tsx`
- Delete: `admin/frontend/src/pages/MirrorPage.css`
- Modify: `admin/frontend/src/App.tsx`
- Modify: `admin/frontend/src/components/Layout.tsx`

**Interfaces:**
- Consumes: niets nieuws (opruim-taak).
- Produces: geen `/mirror`-route/link meer.

- [ ] **Step 1: Verwijder de bestanden**

```bash
git rm admin/frontend/src/pages/MirrorPage.tsx admin/frontend/src/pages/MirrorPage.css
```

- [ ] **Step 2: Werk `App.tsx` bij**

Verwijder de regel `import MirrorPage from "./pages/MirrorPage";` en de
regel `<Route path="/mirror" element={<MirrorPage />} />`.

- [ ] **Step 3: Werk `Layout.tsx` bij**

Verwijder uit de `links`-array de regel
`{ to: "/mirror", label: "Mirror", end: false },`.

- [ ] **Step 4: Typecheck + build**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build`
Expected: 0 fouten, build slaagt

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/App.tsx admin/frontend/src/components/Layout.tsx
git commit -m "chore: verwijder de losse Mirror-pagina (vervangen door scenes)"
```

---

## Task 11: README bijwerken

**Files:**
- Modify: `README.md`

**Interfaces:** geen (documentatie).

- [ ] **Step 1: Werk de MQTT-topic-tabel bij**

In de tabel onder "## MQTT-topics", vervang de rijen voor
`config/mirror` en `control/mirror/preview` (als die er als aparte
rijen staan — anders: voeg toe als ze ontbreken) door:

```markdown
| `config/mirror/scenes` | backend → mirror | JSON-array van scene-objecten (retained) |
| `control/mirror/scene-preview` | backend → mirror | JSON scene-object (niet retained, live-editing) |
```

- [ ] **Step 2: Voeg een korte uitleg toe over scenes**

Voeg, direct onder de bestaande inleidende alinea van het README (na
de zin over `mirror-node`/`scare-nodes`), één alinea toe:

```markdown
Het spiegel-effect wordt geprogrammeerd als **scenes** (bron + regie +
doel + trigger) vanaf het Dashboard van de beheerpagina — niet meer
via een losse configuratiepagina. Elke scene heeft een eigen
trigger-voorwaarde (beweging / tijdschema / altijd); de mirror-node
kiest continu, in een vaste prioriteitsvolgorde, welke scene op dat
moment wint.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README bijwerken voor scenes"
```

---

## Self-Review Notes

- **Spec coverage:** scenes-tabel+migratie (Task 1), SceneEngine
  (Task 2), MQTT-contract (Task 3), MqttBridge (Task 4),
  backend-CRUD+`/api/mirror/test` behouden (Task 5), mirror_node-
  hoofdlus (Task 6), frontend-type/API (Task 7), wizard-modal
  (Task 8), Dashboard-integratie (Task 9), opruimen oude pagina
  (Task 10), documentatie (Task 11) — elk spec-onderdeel heeft een
  taak.
- **Type consistency:** `Scene`/`SceneDraft` (Task 7) wordt letterlijk
  hetzelfde gebruikt in `SceneWizardModal.tsx` (Task 8) en
  `DashboardPage.tsx` (Task 9); backend-veldnamen in
  `admin/app/routers/scenes.py` (Task 5) matchen 1-op-1 de
  `_row_to_scene`/`_DEFAULT_SCENE`-sleutels die de frontend-`Scene`-
  interface verwacht; `SceneEngine.resolve`-signatuur uit Task 2
  wordt ongewijzigd aangeroepen in Task 6.
