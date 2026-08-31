# Mirror-scenegraaf Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vervang de platte, prioriteit-geordende scenes-lijst door een
graaf: scenes worden knopen met eigen, sleepbare uitgaande
verbindingen (outputs), elk met een eigen trigger en doel-scene. De
mirror-node wordt stateful.

**Architecture:** Nieuwe `scene_edges`-tabel (backend) + `is_root`/
`canvas_x`/`canvas_y` op `scenes`; de mirror-node krijgt een
`SceneGraph` (vervangt `SceneEngine`) die de huidige scene onthoudt en
per cyclus alleen diens eigen live outputs checkt. Frontend: een
interactieve node-editor (`@xyflow/react`) vervangt de scene-kaarten-
grid op het Dashboard.

**Tech Stack:** FastAPI + SQLite (backend), React + TypeScript + Vite +
`@xyflow/react` (frontend), Python + OpenCV + paho-mqtt (mirror_node).

**Spec:** `docs/superpowers/specs/2026-08-31-mirror-scene-graph-design.md`

## Global Constraints

- Een edge is pas **live** (telt mee in de mirror-node-evaluatie)
  zodra `to_scene_id` én `trigger_type` allebei gezet zijn. Een lege
  output-stub of een gekoppelde-maar-ongetriggerde lijn wordt genegeerd
  — nooit een crash, nooit onverwacht gedrag tijdens het opbouwen.
- Canvas-positie (`canvas_x`/`canvas_y`) is puur editor-state: nooit
  naar de mirror-node publiceren, en de `/position`-route publiceert
  dus bewust niets naar MQTT.
- Precies één scene is `is_root`; zetten op één scene ontzet 'm overal
  elders (afgedwongen op applicatieniveau, geen DB-constraint).
- Dit project heeft geen DB-foreign-key-afdwinging (geen `PRAGMA
  foreign_keys`, geen enkele bestaande tabel gebruikt `FOREIGN KEY`) —
  edge-opruiming bij het verwijderen van een scene gebeurt daarom
  expliciet in de route (niet via `ON DELETE CASCADE`/`SET NULL`), zie
  Taak 5.
- Eén gecombineerd, retained MQTT-topic (`config/mirror/graph`) voor
  de hele graaf — geen apart topic voor edges. De bestaande
  `on_connect_extra`-republish-hook (vorige feature) wijst hierheen.
- Bestaande deploys migreren automatisch (zie Taak 1) — geen
  handmatige stap.
- Nieuwe frontend-dependency: `@xyflow/react`. Verifieer prop-/
  exportnamen tegen de daadwerkelijk geïnstalleerde versie se
  type-definities als iets in dit plan niet exact blijkt te kloppen —
  normale, verwachte bijstelling bij het gebruik van een nieuwe
  library, geen scope-uitbreiding.

---

## Task 1: Backend DB — `scene_edges`-tabel + graaf-migratie

**Files:**
- Modify: `admin/app/db.py`
- Test: `tests/test_admin_db.py`

**Interfaces:**
- Produces: SQLite-tabel `scene_edges` (kolommen: `id, from_scene_id,
  to_scene_id, trigger_type, trigger_from, trigger_until, priority`);
  nieuwe kolommen op `scenes`: `is_root, canvas_x, canvas_y`.

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_admin_db.py`:

```python
def test_scene_edges_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert "scene_edges" in tables


def test_existing_scenes_migrate_to_star_graph(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(2, 'Scare', 1, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'scare_video', 'motion')"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # tweede run simuleert een herstart na upgrade

    root = conn2.execute("SELECT id FROM scenes WHERE is_root = 1").fetchall()
    assert root == [(1,)]
    edges = conn2.execute(
        "SELECT from_scene_id, to_scene_id, trigger_type FROM scene_edges ORDER BY from_scene_id"
    ).fetchall()
    assert edges == [(1, 2, "motion"), (2, 1, "always")]


def test_graph_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    conn.commit()
    conn.close()
    init_db(path)  # eerste migratie

    conn3 = init_db(path)  # nogmaals -- mag geen extra edges toevoegen

    count = conn3.execute("SELECT COUNT(*) FROM scene_edges").fetchone()[0]
    assert count == 0


def test_graph_migration_does_nothing_without_scenes(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    count = conn.execute("SELECT COUNT(*) FROM scene_edges").fetchone()[0]
    assert count == 0
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -q`
Expected: FAIL — `sqlite3.OperationalError: no such table: scene_edges`

- [ ] **Step 3: Voeg de `scene_edges`-tabel toe in `admin/app/db.py`**

Direct ná het bestaande `CREATE TABLE IF NOT EXISTS scenes (...)`-blok:

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scene_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_scene_id INTEGER NOT NULL,
            to_scene_id INTEGER,
            trigger_type TEXT,
            trigger_from TEXT,
            trigger_until TEXT,
            priority INTEGER NOT NULL DEFAULT 0
        )"""
    )
```

- [ ] **Step 4: Voeg de nieuwe kolommen op `scenes` toe**

Bij de andere `_ensure_column`-aanroepen (na de bestaande
`mirror_config`-kolommen):

```python
    _ensure_column(conn, "scenes", "is_root", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "scenes", "canvas_x", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "scenes", "canvas_y", "REAL NOT NULL DEFAULT 0")
```

- [ ] **Step 5: Voeg de migratiefunctie toe**

Na `_migrate_mirror_config_to_scenes`:

```python
def _migrate_scenes_to_graph(conn):
    """Migreert de oude, platte prioriteit+trigger-scenes naar de
    graaf: de 'always'-scene met de laagste order_index wordt root
    (of, als die er niet is, de scene met de laagste order_index);
    elke andere scene met een niet-lege trigger_type krijgt een edge
    vanaf de root met die trigger; elke scare_video-scene krijgt ook
    een edge terug naar de root ('altijd'). Idempotent: doet niets
    zodra er al edges bestaan, of als er geen scenes zijn."""
    existing_edges = conn.execute("SELECT COUNT(*) FROM scene_edges").fetchone()[0]
    if existing_edges > 0:
        return
    rows = conn.execute(
        "SELECT id, source_mode, trigger_type, trigger_from, trigger_until, order_index "
        "FROM scenes ORDER BY order_index"
    ).fetchall()
    if not rows:
        return
    always_rows = [r for r in rows if r[2] == "always"]
    root_id = always_rows[0][0] if always_rows else rows[0][0]
    conn.execute("UPDATE scenes SET is_root = 0")
    conn.execute("UPDATE scenes SET is_root = 1 WHERE id = ?", (root_id,))
    for scene_id, source_mode, trigger_type, trigger_from, trigger_until, order_index in rows:
        if scene_id == root_id or not trigger_type:
            continue
        conn.execute(
            """INSERT INTO scene_edges
                 (from_scene_id, to_scene_id, trigger_type, trigger_from, trigger_until, priority)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (root_id, scene_id, trigger_type, trigger_from, trigger_until, order_index),
        )
        if source_mode == "scare_video":
            conn.execute(
                """INSERT INTO scene_edges
                     (from_scene_id, to_scene_id, trigger_type, trigger_from, trigger_until, priority)
                   VALUES (?, ?, 'always', NULL, NULL, 0)""",
                (scene_id, root_id),
            )
```

- [ ] **Step 6: Roep de migratie aan vóór de finale `conn.commit()`**

Direct ná de bestaande `_migrate_mirror_config_to_scenes(conn)`-aanroep:

```python
    _migrate_mirror_config_to_scenes(conn)
    _migrate_scenes_to_graph(conn)
    conn.commit()
    return conn
```

- [ ] **Step 7: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -q`
Expected: alle tests PASS

- [ ] **Step 8: Run de volledige backend-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests PASS (deze taak breekt niets bestaands —
`scenes.py`'s routes lezen de nieuwe kolommen pas vanaf Taak 5)

- [ ] **Step 9: Commit**

```bash
git add admin/app/db.py tests/test_admin_db.py
git commit -m "feat: scene_edges-tabel + graaf-migratie vanuit platte scenes"
```

---

## Task 2: mirror_node — `SceneGraph` (vervangt `SceneEngine`)

**Files:**
- Modify: `mirror_node/scenes.py`
- Modify: `tests/test_scene_engine.py`

**Interfaces:**
- Produces: `SceneGraph` met `.set_graph(scenes, edges, root_scene_id)`,
  `.set_preview(scene)`, `.preview_recently_set() -> bool`,
  `.resolve(motion_active: bool, now_hhmm: str) -> (scene: dict | None, transitioned: bool)`.
  Gebruikt door Taak 7. Vervangt `SceneEngine` volledig (verwijderd in
  deze taak).

- [ ] **Step 1: Herschrijf de tests**

Vervang de hele inhoud van `tests/test_scene_engine.py` door:

```python
from mirror_node.scenes import SceneGraph, _time_in_window


def _graph(scenes, edges, root_id, **kwargs):
    g = SceneGraph(**kwargs)
    g.set_graph(scenes, edges, root_id)
    return g


def test_resolves_to_root_with_no_edges():
    g = _graph([{"id": 1, "name": "Basis"}], [], root_id=1)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_transitions_on_matching_motion_edge():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0}
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_no_transition_without_motion():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0}
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_only_current_nodes_own_edges_are_checked():
    """Root heeft een motion-edge naar Scare; Scare heeft er zelf geen
    -- eenmaal bij Scare aangekomen, matcht een volgende beweging niets
    meer (Scare's eigen edge-lijst is leeg)."""
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0}
    ]
    g = _graph(scenes, edges, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")  # naar Scare

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is False


def test_return_edge_brings_state_back_on_next_resolve():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
        {"from_scene_id": 2, "to_scene_id": 1, "trigger_type": "always",
         "trigger_from": None, "trigger_until": None, "priority": 0},
    ]
    g = _graph(scenes, edges, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")  # naar Scare

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")  # altijd-edge terug

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is True


def test_non_live_edges_are_ignored():
    """Een edge zonder to_scene_id (lege output) of zonder trigger_type
    (nog niet ingesteld) telt niet mee."""
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": None, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": None,
         "trigger_from": None, "trigger_until": None, "priority": 1},
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_priority_order_first_matching_edge_wins():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}, {"id": 3, "name": "B"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 3, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 1},
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "A"}


def test_unknown_current_scene_resets_to_root():
    g = _graph([{"id": 1, "name": "Basis"}], [], root_id=1)
    g._current_id = 999  # gesimuleerd: vorige graaf had een scene die nu weg is

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}


def test_no_root_and_no_scenes_returns_none():
    g = SceneGraph()
    g.set_graph([], [], root_scene_id=None)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene is None
    assert transitioned is False


def test_preview_overrides_graph_evaluation():
    clock = {"t": 0.0}
    g = SceneGraph(preview_timeout=30, clock=lambda: clock["t"])
    g.set_graph([{"id": 1, "name": "Basis"}], [], root_scene_id=1)
    preview = {"id": 99, "name": "Preview"}
    g.set_preview(preview)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == preview
    assert transitioned is False


def test_preview_expires_after_timeout():
    clock = {"t": 0.0}
    g = SceneGraph(preview_timeout=30, clock=lambda: clock["t"])
    root = {"id": 1, "name": "Basis"}
    g.set_graph([root], [], root_scene_id=1)
    g.set_preview({"id": 99, "name": "Preview"})
    clock["t"] = 31.0

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == root


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
Expected: FAIL — `ImportError: cannot import name 'SceneGraph' from 'mirror_node.scenes'`

- [ ] **Step 3: Herschrijf `mirror_node/scenes.py`**

Vervang de hele inhoud door:

```python
import time


class SceneGraph:
    """Houdt de laatst via MQTT ontvangen graaf bij (scenes + live
    edges) en de huidige-scene-toestand. Vervangt de vorige stateless
    SceneEngine: welke triggers ertoe doen hangt nu af van waar we nu
    zijn, niet van een globale prioriteitsscan."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._scenes = {}
        self._edges = {}
        self._root_id = None
        self._current_id = None
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_graph(self, scenes, edges, root_scene_id):
        self._scenes = {s["id"]: s for s in scenes}
        by_from = {}
        for e in edges:
            if e.get("to_scene_id") is None or e.get("trigger_type") is None:
                continue  # niet-live: lege stub of ongeconfigureerde trigger
            by_from.setdefault(e["from_scene_id"], []).append(e)
        for lst in by_from.values():
            lst.sort(key=lambda e: e["priority"])
        self._edges = by_from
        self._root_id = root_scene_id
        if self._current_id not in self._scenes:
            self._current_id = root_scene_id

    def set_preview(self, scene):
        self._preview = scene
        self._preview_set_at = self._clock()

    def preview_recently_set(self):
        if self._preview_set_at is None:
            return False
        return self._clock() - self._preview_set_at <= self._preview_timeout

    def resolve(self, motion_active, now_hhmm):
        """Geeft (scene, transitioned) terug. `transitioned` is True als
        dit frame een edge is gevolgd -- de hoofdlus gebruikt dat om
        _handle_trigger() precies bij aankomst aan te roepen, niet elke
        cyclus dat een scare-video-scene toevallig nog 'huidig' is."""
        if self.preview_recently_set():
            return self._preview, False
        if self._current_id not in self._scenes:
            self._current_id = self._root_id
        if self._current_id is None:
            return None, False
        for edge in self._edges.get(self._current_id, []):
            if _edge_matches(edge, motion_active, now_hhmm):
                if edge["to_scene_id"] != self._current_id:
                    self._current_id = edge["to_scene_id"]
                    return self._scenes.get(self._current_id), True
                break
        return self._scenes.get(self._current_id), False


def _edge_matches(edge, motion_active, now_hhmm):
    t = edge["trigger_type"]
    if t == "always":
        return True
    if t == "motion":
        return motion_active
    if t == "schedule":
        return _time_in_window(now_hhmm, edge.get("trigger_from"), edge.get("trigger_until"))
    return False


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
git commit -m "feat: SceneGraph -- stateful graaf-evaluatie (vervangt SceneEngine)"
```

**Let op:** `mirror_node/main.py` importeert nog `SceneEngine` en zal
tot Taak 7 niet importeren — dat is verwacht, Taak 7 (niet deze taak)
werkt `mirror_node/main.py` bij. `tests/test_mirror_main.py` blijft tot
die taak ongewijzigd en zal in de tussentijd falen bij verzameling
(`ImportError`) als je de volledige suite draait — dat is een bekend,
tijdelijk gat dat Taak 7 dichtzet (zelfde patroon als het
Task-3-naar-Task-4/6-gat in de vorige scenes-plan).

---

## Task 3: MQTT-contract — `config/mirror/graph`

**Files:**
- Modify: `shared/mqtt_contract.py`
- Test: `tests/test_mqtt_contract.py`

**Interfaces:**
- Produces: `Topics.config_mirror_graph` (retained). Verwijdert
  `Topics.config_mirror_scenes`.

- [ ] **Step 1: Pas de test aan**

In `tests/test_mqtt_contract.py`, in
`test_topics_without_prefix_match_bare_names`, vervang:

```python
    assert topics.config_mirror_scenes == "config/mirror/scenes"
```

door:

```python
    assert topics.config_mirror_graph == "config/mirror/graph"
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py -q`
Expected: FAIL — `AttributeError: 'Topics' object has no attribute 'config_mirror_graph'`

- [ ] **Step 3: Pas `shared/mqtt_contract.py` aan**

Vervang:

```python
    @property
    def config_mirror_scenes(self) -> str:
        return self._p("config/mirror/scenes")
```

door:

```python
    @property
    def config_mirror_graph(self) -> str:
        return self._p("config/mirror/graph")
```

(`control_mirror_scene_preview` blijft ongewijzigd staan.)

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py -q`
Expected: alle tests PASS

- [ ] **Step 5: Commit**

```bash
git add shared/mqtt_contract.py tests/test_mqtt_contract.py
git commit -m "feat: MQTT-topic config/mirror/graph (vervangt config/mirror/scenes)"
```

---

## Task 4: `MqttBridge` — `publish_mirror_graph`

**Files:**
- Modify: `admin/app/mqtt_bridge.py`
- Test: `tests/test_admin_mqtt_bridge.py`

**Interfaces:**
- Consumes: `Topics.config_mirror_graph` (Taak 3).
- Produces: `MqttBridge.publish_mirror_graph(graph: dict)` (retained).
  Verwijdert `publish_mirror_scenes`. Gebruikt door Taak 5/6.

- [ ] **Step 1: Schrijf de falende test**

In `tests/test_admin_mqtt_bridge.py`, vervang
`test_publish_mirror_scenes_uses_configured_prefix` door:

```python
def test_publish_mirror_graph_uses_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_graph({"scenes": [{"id": 1}], "edges": [], "root_scene_id": 1})

    topic, payload, retain = bridge._client.published[-1]
    assert topic == "test/config/mirror/graph"
    assert json.loads(payload) == {"scenes": [{"id": 1}], "edges": [], "root_scene_id": 1}
    assert retain is True
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_mqtt_bridge.py -q`
Expected: FAIL — `AttributeError: 'MqttBridge' object has no attribute 'publish_mirror_graph'`

- [ ] **Step 3: Pas `admin/app/mqtt_bridge.py` aan**

Vervang de bestaande `publish_mirror_scenes`-methode door:

```python
    def publish_mirror_graph(self, graph):
        self._client.publish(self._topics.config_mirror_graph, json.dumps(graph), retain=True)
```

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_mqtt_bridge.py -q`
Expected: alle tests PASS

- [ ] **Step 5: Commit**

```bash
git add admin/app/mqtt_bridge.py tests/test_admin_mqtt_bridge.py
git commit -m "feat: MqttBridge publiceert de volledige graaf"
```

**Let op:** `admin/app/main.py`'s `_republish_retained_config` en
`admin/app/routers/scenes.py`'s `_publish_scenes` roepen tot Taak 5/6
nog de oude `publish_mirror_scenes` aan — dat breekt tijdelijk (zelfde,
al eerder geziene patroon: een interface-wijziging gesplitst over
meerdere taken laat de aanroepende code even achter tot de taak die
'm bijwerkt aan de beurt is). `admin/app/main.py` en
`admin/app/routers/scenes.py` niet aanraken in deze taak.

---

## Task 5: Backend — `graph_publish.py` + `scenes.py` herschrijven

**Files:**
- Create: `admin/app/graph_publish.py`
- Modify: `admin/app/routers/scenes.py`
- Test: `tests/test_admin_routes_scenes.py`

**Interfaces:**
- Consumes: `scene_edges`-tabel (Taak 1), `MqttBridge.publish_mirror_graph`
  (Taak 4).
- Produces: `publish_graph(db, bridge)` in `admin/app/graph_publish.py`
  (gebruikt door Taak 6 en `admin/app/main.py` in die taak).
  `admin/app/routers/scenes.py`: scenes zonder trigger/order-velden,
  met `is_root`/`canvas_x`/`canvas_y`; nieuwe
  `PUT /api/scenes/{id}/position`; `PUT /api/scenes/order` vervalt.

- [ ] **Step 1: Maak `admin/app/graph_publish.py`**

```python
def publish_graph(db, bridge):
    """Publiceert de volledige graaf (scenes + edges + root) naar MQTT
    -- gedeeld door scenes.py en scene_edges.py, elke schrijvende
    route in beide roept dit aan zodat opgeslagen en gepubliceerde
    graaf nooit uit elkaar kunnen lopen. Lazy imports om een cirkel
    met de twee routers te vermijden (die importeren dit bestand)."""
    from admin.app.routers.scenes import _list_scenes
    from admin.app.routers.scene_edges import _list_edges

    scenes = _list_scenes(db)
    edges = _list_edges(db)
    root_scene_id = next((s["id"] for s in scenes if s["is_root"]), None)
    bridge.publish_mirror_graph({"scenes": scenes, "edges": edges, "root_scene_id": root_scene_id})
```

- [ ] **Step 2: Schrijf de falende tests**

In `tests/test_admin_routes_scenes.py`, vervang `_SCENE_PAYLOAD` door:

```python
_SCENE_PAYLOAD = {
    "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
    "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
    "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0,
}
```

Vervang `FakeBridge.publish_mirror_scenes` door:

```python
    def publish_mirror_graph(self, graph):
        self.calls.append(("graph", graph))
```

Vervang elke assertie die `("scenes", [...])` verwacht door
`("graph", {"scenes": [...], "edges": [], "root_scene_id": None})` (er
zijn in deze taak nog geen edges — die komen in Taak 6). Verwijder
`test_create_scene_assigns_increasing_order_index`,
`test_reorder_scenes_updates_order_index` en
`test_reorder_scenes_rejects_non_list_order` (die routes/velden
bestaan niet meer). Verwijder ook `test_canvas_size_round_trips_...`
NIET — die blijft, alleen zonder `order_index` in de payload. Voeg toe:

```python
def test_setting_is_root_unsets_it_elsewhere(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A", "is_root": True}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()

    client.put(f"/api/scenes/{b['id']}", json={**_SCENE_PAYLOAD, "name": "B", "is_root": True})

    scenes = {s["id"]: s["is_root"] for s in client.get("/api/scenes").json()}
    assert scenes[a["id"]] is False
    assert scenes[b["id"]] is True


def test_update_scene_position_does_not_publish_to_mqtt(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()
    bridge.calls.clear()

    response = client.put(f"/api/scenes/{created['id']}/position", json={"canvas_x": 12.5, "canvas_y": -3.0})

    assert response.status_code == 200
    assert bridge.calls == []
    updated = client.get(f"/api/scenes/{created['id']}").json()
    assert updated["canvas_x"] == 12.5
    assert updated["canvas_y"] == -3.0


def test_update_scene_position_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scenes/999/position", json={"canvas_x": 0, "canvas_y": 0})

    assert response.status_code == 404


def test_update_scene_position_rejects_non_numeric(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    response = client.put(f"/api/scenes/{created['id']}/position", json={"canvas_x": "nope", "canvas_y": 0})

    assert response.status_code == 400


def test_deleting_scene_clears_its_own_and_incoming_edges(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()
    # eigen uitgaande edge (a -> b) en een inkomende (b -> a)
    client.post("/api/scene-edges", json={
        "from_scene_id": a["id"], "to_scene_id": b["id"],
        "trigger_type": "motion", "trigger_from": None, "trigger_until": None, "priority": 0,
    })
    client.post("/api/scene-edges", json={
        "from_scene_id": b["id"], "to_scene_id": a["id"],
        "trigger_type": "always", "trigger_from": None, "trigger_until": None, "priority": 0,
    })

    client.delete(f"/api/scenes/{a['id']}")

    remaining = client.get("/api/scene-edges").json()
    assert len(remaining) == 1
    assert remaining[0]["from_scene_id"] == b["id"]
    assert remaining[0]["to_scene_id"] is None  # teruggevallen op een lege output-stub
    assert remaining[0]["trigger_type"] is None
```

(Deze laatste test gebruikt `/api/scene-edges`, dat pas in Taak 6
bestaat — deze test hoort dus logisch bij Taak 6, maar staat hier
genoemd zodat je 'm in Taak 6 toevoegt, niet hier: **laat deze laatste
test (`test_deleting_scene_clears_its_own_and_incoming_edges`) weg uit
deze taak**, voeg 'm toe in Taak 6 in plaats daarvan, waar
`/api/scene-edges` al bestaat.)

- [ ] **Step 3: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_scenes.py -q`
Expected: meerdere FAIL (velden/routes bestaan nog niet in de huidige vorm)

- [ ] **Step 4: Herschrijf `admin/app/routers/scenes.py`**

Vervang de hele inhoud door:

```python
import json
from fastapi import APIRouter, HTTPException, Request
from admin.app.graph_publish import publish_graph

router = APIRouter()

_SCENE_COLUMNS = (
    "id, name, enabled, source_mode, effect, params, overlay_hash, "
    "scale, position, canvas_width, canvas_height, source_scale, source_position, "
    "is_root, canvas_x, canvas_y"
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
    "is_root": False,
    "canvas_x": 0.0,
    "canvas_y": 0.0,
}


def _row_to_scene(row):
    canvas_width, canvas_height = row[9], row[10]
    return {
        "id": row[0],
        "name": row[1],
        "enabled": bool(row[2]),
        "source_mode": row[3],
        "effect": row[4],
        "params": json.loads(row[5]),
        "overlay_hash": row[6],
        "scale": row[7],
        "position": json.loads(row[8]),
        "canvas_size": [canvas_width, canvas_height] if canvas_width and canvas_height else None,
        "source_scale": row[11],
        "source_position": json.loads(row[12]),
        "is_root": bool(row[13]),
        "canvas_x": row[14],
        "canvas_y": row[15],
    }


def _list_scenes(db):
    rows = db.execute(f"SELECT {_SCENE_COLUMNS} FROM scenes ORDER BY id").fetchall()
    return [_row_to_scene(r) for r in rows]


def _fields_from_body(body):
    return {k: body.get(k, v) for k, v in _DEFAULT_SCENE.items()}


def _canvas_columns(fields):
    canvas_size = fields["canvas_size"]
    return tuple(canvas_size) if canvas_size else (None, None)


def _clear_other_roots(db, scene_id):
    db.execute("UPDATE scenes SET is_root = 0 WHERE id != ?", (scene_id,))


@router.get("/api/scenes")
def list_scenes_route(request: Request):
    return _list_scenes(request.app.state.db)


@router.get("/api/scenes/{scene_id:int}")
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
    canvas_width, canvas_height = _canvas_columns(fields)
    cursor = db.execute(
        """INSERT INTO scenes
             (name, enabled, source_mode, effect, params, overlay_hash,
              scale, position, canvas_width, canvas_height, source_scale, source_position,
              is_root, canvas_x, canvas_y)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"],
            fields["effect"], json.dumps(fields["params"]), fields["overlay_hash"],
            fields["scale"], json.dumps(fields["position"]), canvas_width, canvas_height,
            fields["source_scale"], json.dumps(fields["source_position"]),
            int(fields["is_root"]), fields["canvas_x"], fields["canvas_y"],
        ),
    )
    if fields["is_root"]:
        _clear_other_roots(db, cursor.lastrowid)
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return get_scene_route(cursor.lastrowid, request)


@router.put("/api/scenes/{scene_id:int}")
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
             is_root=?, canvas_x=?, canvas_y=? WHERE id=?""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"], fields["effect"],
            json.dumps(fields["params"]), fields["overlay_hash"], fields["scale"],
            json.dumps(fields["position"]), canvas_width, canvas_height, fields["source_scale"],
            json.dumps(fields["source_position"]), int(fields["is_root"]),
            fields["canvas_x"], fields["canvas_y"], scene_id,
        ),
    )
    if fields["is_root"]:
        _clear_other_roots(db, scene_id)
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return get_scene_route(scene_id, request)


@router.put("/api/scenes/{scene_id:int}/position")
async def update_scene_position_route(scene_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    body = await request.json()
    try:
        x, y = float(body.get("canvas_x")), float(body.get("canvas_y"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="canvas_x/canvas_y moeten getallen zijn")
    db.execute("UPDATE scenes SET canvas_x = ?, canvas_y = ? WHERE id = ?", (x, y, scene_id))
    db.commit()
    # Bewust GEEN publish_graph hier -- canvaspositie is een editor-
    # aangelegenheid, de mirror-node heeft er niets aan, en dit endpoint
    # wordt tijdens het slepen vaak aangeroepen.
    return {"ok": True}


@router.delete("/api/scenes/{scene_id:int}")
def delete_scene_route(scene_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM scenes WHERE id = ?", (scene_id,))
    if cursor.rowcount == 0:
        db.commit()
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    # Geen DB-foreign-key-afdwinging in dit project -- expliciet
    # opruimen: eigen uitgaande edges verdwijnen mee, inkomende edges
    # vallen terug op een lege output-stub i.p.v. een edge naar een
    # niet-bestaande scene te laten hangen.
    db.execute("DELETE FROM scene_edges WHERE from_scene_id = ?", (scene_id,))
    db.execute(
        "UPDATE scene_edges SET to_scene_id = NULL, trigger_type = NULL, "
        "trigger_from = NULL, trigger_until = NULL WHERE to_scene_id = ?",
        (scene_id,),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}


@router.post("/api/scenes/{scene_id}/preview")
async def preview_scene_route(scene_id: int, request: Request):
    scene = await request.json()
    request.app.state.bridge.publish_mirror_scene_preview(scene)
    return {"ok": True}
```

- [ ] **Step 5: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_scenes.py -q`
Expected: alle tests PASS (behalve de ene test die je naar Taak 6
verplaatst hebt, zie Step 2's opmerking)

- [ ] **Step 6: Commit**

```bash
git add admin/app/graph_publish.py admin/app/routers/scenes.py tests/test_admin_routes_scenes.py
git commit -m "feat: scenes-route zonder trigger/order-velden, is_root + positie-route"
```

**Let op:** `admin/app/main.py` importeert nog steeds de oude
`publish_mirror_scenes`-aanroep in `_republish_retained_config` en
`admin/app/routers/scene_edges.py` bestaat nog niet — de app start op
dit punt nog niet foutloos op. Dat lost Taak 6 op (registreer die
router en werk `main.py` bij). Niet proberen dit in deze taak al te
fixen.

---

## Task 6: Backend — `scene_edges.py` CRUD + `main.py`-wiring

**Files:**
- Create: `admin/app/routers/scene_edges.py`
- Create: `tests/test_admin_routes_scene_edges.py`
- Modify: `admin/app/main.py`
- Modify: `tests/test_admin_routes_scenes.py` (voeg de in Taak 5
  achtergehouden test toe)

**Interfaces:**
- Consumes: `publish_graph` (Taak 5), `scene_edges`-tabel (Taak 1).
- Produces: `GET/POST /api/scene-edges`, `PUT/DELETE
  /api/scene-edges/{id}`. `admin/app/main.py` registreert de router en
  publiceert de graaf bij opstarten/reconnect via `publish_graph`.

- [ ] **Step 1: Schrijf de falende tests**

Maak `tests/test_admin_routes_scene_edges.py`:

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

    def publish_mirror_graph(self, graph):
        self.calls.append(("graph", graph))

    def publish_mirror_scare_video_config(self, enabled_hashes):
        self.calls.append(("scare_video_config", enabled_hashes))


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
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0,
}


def _two_scenes(client):
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()
    return a, b


def test_create_edge_with_empty_output_stub(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)

    response = client.post("/api/scene-edges", json={"from_scene_id": a["id"]})

    assert response.status_code == 200
    created = response.json()
    assert created["from_scene_id"] == a["id"]
    assert created["to_scene_id"] is None
    assert created["trigger_type"] is None
    assert client.get("/api/scene-edges").json() == [created]


def test_create_edge_requires_valid_from_scene_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/scene-edges", json={"from_scene_id": 999})

    assert response.status_code == 400


def test_update_edge_connects_and_configures_trigger(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    edge = client.post("/api/scene-edges", json={"from_scene_id": a["id"]}).json()

    response = client.put(f"/api/scene-edges/{edge['id']}", json={
        "from_scene_id": a["id"], "to_scene_id": b["id"],
        "trigger_type": "motion", "trigger_from": None, "trigger_until": None, "priority": 0,
    })

    assert response.status_code == 200
    updated = response.json()
    assert updated["to_scene_id"] == b["id"]
    assert updated["trigger_type"] == "motion"


def test_update_edge_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scene-edges/999", json={"from_scene_id": 1})

    assert response.status_code == 404


def test_delete_edge(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    edge = client.post("/api/scene-edges", json={"from_scene_id": a["id"]}).json()

    response = client.delete(f"/api/scene-edges/{edge['id']}")

    assert response.status_code == 200
    assert client.get("/api/scene-edges").json() == []


def test_delete_edge_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/scene-edges/999")

    assert response.status_code == 404


def test_every_write_publishes_full_graph_with_root(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    client.put(f"/api/scenes/{a['id']}", json={**_SCENE_PAYLOAD, "name": "A", "is_root": True})
    bridge.calls.clear()

    edge = client.post("/api/scene-edges", json={
        "from_scene_id": a["id"], "to_scene_id": b["id"],
        "trigger_type": "always", "trigger_from": None, "trigger_until": None, "priority": 0,
    }).json()

    kind, graph = bridge.calls[-1]
    assert kind == "graph"
    assert graph["root_scene_id"] == a["id"]
    assert graph["edges"] == [edge]


def test_scene_edge_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)  # geen login

    assert client.get("/api/scene-edges").status_code == 401
    assert client.post("/api/scene-edges", json={"from_scene_id": 1}).status_code == 401
```

Voeg daarnaast toe aan `tests/test_admin_routes_scenes.py` (de test
die in Taak 5 bewust is achtergehouden):

```python
def test_deleting_scene_clears_its_own_and_incoming_edges(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()
    client.post("/api/scene-edges", json={
        "from_scene_id": a["id"], "to_scene_id": b["id"],
        "trigger_type": "motion", "trigger_from": None, "trigger_until": None, "priority": 0,
    })
    client.post("/api/scene-edges", json={
        "from_scene_id": b["id"], "to_scene_id": a["id"],
        "trigger_type": "always", "trigger_from": None, "trigger_until": None, "priority": 0,
    })

    client.delete(f"/api/scenes/{a['id']}")

    remaining = client.get("/api/scene-edges").json()
    assert len(remaining) == 1
    assert remaining[0]["from_scene_id"] == b["id"]
    assert remaining[0]["to_scene_id"] is None
    assert remaining[0]["trigger_type"] is None
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_scene_edges.py -q`
Expected: FAIL — `404 Not Found` (route bestaat nog niet)

- [ ] **Step 3: Implementeer `admin/app/routers/scene_edges.py`**

```python
from fastapi import APIRouter, HTTPException, Request
from admin.app.graph_publish import publish_graph

router = APIRouter()

_EDGE_COLUMNS = "id, from_scene_id, to_scene_id, trigger_type, trigger_from, trigger_until, priority"

_DEFAULT_EDGE = {
    "to_scene_id": None,
    "trigger_type": None,
    "trigger_from": None,
    "trigger_until": None,
    "priority": 0,
}


def _row_to_edge(row):
    return {
        "id": row[0],
        "from_scene_id": row[1],
        "to_scene_id": row[2],
        "trigger_type": row[3],
        "trigger_from": row[4],
        "trigger_until": row[5],
        "priority": row[6],
    }


def _list_edges(db):
    rows = db.execute(
        f"SELECT {_EDGE_COLUMNS} FROM scene_edges ORDER BY from_scene_id, priority"
    ).fetchall()
    return [_row_to_edge(r) for r in rows]


@router.get("/api/scene-edges")
def list_edges_route(request: Request):
    return _list_edges(request.app.state.db)


@router.post("/api/scene-edges")
async def create_edge_route(request: Request):
    body = await request.json()
    from_scene_id = body.get("from_scene_id")
    db = request.app.state.db
    if not isinstance(from_scene_id, int):
        raise HTTPException(status_code=400, detail="from_scene_id is verplicht")
    exists = db.execute("SELECT id FROM scenes WHERE id = ?", (from_scene_id,)).fetchone()
    if exists is None:
        raise HTTPException(status_code=400, detail="from_scene_id verwijst naar een onbestaande scene")
    fields = {k: body.get(k, v) for k, v in _DEFAULT_EDGE.items()}
    cursor = db.execute(
        """INSERT INTO scene_edges
             (from_scene_id, to_scene_id, trigger_type, trigger_from, trigger_until, priority)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (from_scene_id, fields["to_scene_id"], fields["trigger_type"], fields["trigger_from"],
         fields["trigger_until"], fields["priority"]),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    row = db.execute(f"SELECT {_EDGE_COLUMNS} FROM scene_edges WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_edge(row)


@router.put("/api/scene-edges/{edge_id:int}")
async def update_edge_route(edge_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM scene_edges WHERE id = ?", (edge_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Verbinding niet gevonden")
    body = await request.json()
    fields = {k: body.get(k, v) for k, v in _DEFAULT_EDGE.items()}
    db.execute(
        """UPDATE scene_edges SET to_scene_id=?, trigger_type=?, trigger_from=?,
             trigger_until=?, priority=? WHERE id=?""",
        (fields["to_scene_id"], fields["trigger_type"], fields["trigger_from"],
         fields["trigger_until"], fields["priority"], edge_id),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    row = db.execute(f"SELECT {_EDGE_COLUMNS} FROM scene_edges WHERE id = ?", (edge_id,)).fetchone()
    return _row_to_edge(row)


@router.delete("/api/scene-edges/{edge_id:int}")
def delete_edge_route(edge_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM scene_edges WHERE id = ?", (edge_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Verbinding niet gevonden")
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}
```

- [ ] **Step 4: Werk `admin/app/main.py` bij**

Voeg de import toe bij de andere router-imports:

```python
from admin.app.routers import scene_edges as scene_edges_router
from admin.app.graph_publish import publish_graph
```

Verwijder de nu overbodige `from admin.app.routers.scenes import
_list_scenes`-import (die zit voortaan achter `publish_graph`'s eigen,
lazy import).

Voeg de router-registratie toe (na `scenes_router`):

```python
    app.include_router(scene_edges_router.router)
```

Vervang `_republish_retained_config`:

```python
    def _republish_retained_config():
        # Zonder dit blijft een net herstarte mirror-node (of een broker-
        # reconnect) zwart: config/mirror/graph en config/mirror/scare-video
        # zijn retained topics die alleen bij een CRUD-actie op de
        # beheerpagina gepubliceerd worden, nooit uit zichzelf.
        publish_graph(app.state.db, app.state.bridge)
        app.state.bridge.publish_mirror_scare_video_config(read_enabled_hashes(app.state.db))
```

- [ ] **Step 5: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_scene_edges.py tests/test_admin_routes_scenes.py tests/test_admin_mqtt_bridge.py -q`
Expected: alle tests PASS

- [ ] **Step 6: Run de volledige backend-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alles groen BEHALVE `tests/test_mirror_main.py`, dat blijft
kapot tot Taak 7 (bekend, tijdelijk gat — zie Taak 2's slotopmerking).
Controleer expliciet dat de fout in dat bestand nog steeds exact de
verwachte `ImportError` is, geen nieuwe/andere fout.

- [ ] **Step 7: Commit**

```bash
git add admin/app/routers/scene_edges.py tests/test_admin_routes_scene_edges.py \
  tests/test_admin_routes_scenes.py admin/app/main.py
git commit -m "feat: /api/scene-edges CRUD + graaf-republish-on-connect"
```

---

## Task 7: mirror_node — hoofdlus herbedraden naar `SceneGraph`

**Files:**
- Modify: `mirror_node/main.py`
- Modify: `tests/test_mirror_main.py`

**Interfaces:**
- Consumes: `SceneGraph` (Taak 2), `Topics.config_mirror_graph` (Taak 3).
- Produces: module-level `scene_graph: SceneGraph`; nieuwe pure functie
  `_render_action(winning, transitioned) -> "blank"|"scare_video"|"render"`
  (vervangt `_decide_action`/`_resolve_action`, en dicht het gat dat de
  vorige feature's eind-review vond: de hoofdlus-dispatch-logica had
  toen geen enkele test — deze functie is dat wel, expliciet).

- [ ] **Step 1: Werk `tests/test_mirror_main.py` bij**

Vervang:

```python
    on_message(None, None, _FakeMsg(topics.config_mirror_scenes, b"\xff\xfe"))
```

door:

```python
    on_message(None, None, _FakeMsg(topics.config_mirror_graph, b"\xff\xfe"))
```

Vervang de vier `test_apply_scenes_message_*`-tests en
`test_apply_scene_preview_message_sets_preview_and_syncs_overlay` door:

```python
def test_apply_graph_message_ignores_non_dict_json():
    logger = _FakeLogger()
    mirror_main._apply_graph_message("[1, 2, 3]", logger)
    assert logger.errors


def test_apply_graph_message_ignores_malformed_json():
    logger = _FakeLogger()
    mirror_main._apply_graph_message("{niet-geldig-json", logger)
    assert logger.errors


def test_apply_graph_message_ignores_non_list_scenes_or_edges():
    logger = _FakeLogger()
    mirror_main._apply_graph_message(json.dumps({"scenes": "nope", "edges": [], "root_scene_id": 1}), logger)
    assert logger.errors


def test_apply_graph_message_updates_scene_graph():
    scene = {"id": 1, "trigger_type": None, "overlay_hash": None}
    payload = {"scenes": [scene], "edges": [], "root_scene_id": 1}
    mirror_main._apply_graph_message(json.dumps(payload), _FakeLogger())

    result, transitioned = mirror_main.scene_graph.resolve(False, "12:00")
    assert result == scene
    assert transitioned is False


def test_apply_graph_message_syncs_overlay_for_each_scene(monkeypatch):
    started = []
    monkeypatch.setattr(
        mirror_main.threading, "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    scenes = [
        {"id": 1, "overlay_hash": "a" * 64},
        {"id": 2, "overlay_hash": "b" * 64},
    ]
    payload = {"scenes": scenes, "edges": [], "root_scene_id": 1}

    mirror_main._apply_graph_message(json.dumps(payload), _FakeLogger())

    synced_hashes = [kw["args"][2] for kw in started]
    assert synced_hashes == [["a" * 64], ["b" * 64]]


def test_apply_scene_preview_message_sets_preview_and_syncs_overlay(monkeypatch):
    started = []
    monkeypatch.setattr(
        mirror_main.threading, "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    scene = {"id": 5, "overlay_hash": "a" * 64}
    try:
        mirror_main._apply_scene_preview_message(json.dumps(scene), _FakeLogger())
        result, transitioned = mirror_main.scene_graph.resolve(False, "12:00")
        assert result == scene
        assert started and started[0]["args"][2] == ["a" * 64]
    finally:
        mirror_main.scene_graph._preview = None
        mirror_main.scene_graph._preview_set_at = None
```

Verwijder alle `test_decide_action_*`- en `test_resolve_action_*`-tests
(die functies verdwijnen in deze taak) en vervang ze door:

```python
def test_render_action_no_winner_is_blank():
    assert mirror_main._render_action(None, False) == "blank"
    assert mirror_main._render_action(None, True) == "blank"


def test_render_action_scare_video_on_transition_plays():
    winning = {"source_mode": "scare_video"}
    assert mirror_main._render_action(winning, True) == "scare_video"


def test_render_action_scare_video_without_transition_is_blank():
    """Dit is precies het geval dat de vorige feature met een losse
    dubbele-resolve-hack moest oplappen (zwart na afloop van een clip
    zonder terugpad) -- de state machine zelf voorkomt het nu, en dit
    is de test die dat vastlegt."""
    winning = {"source_mode": "scare_video"}
    assert mirror_main._render_action(winning, False) == "blank"


def test_render_action_camera_scene_renders_regardless_of_transition():
    winning = {"source_mode": "camera"}
    assert mirror_main._render_action(winning, True) == "render"
    assert mirror_main._render_action(winning, False) == "render"
```

Voeg bovenaan het bestand (na `import pytest`) `import json` toe als
dat er nog niet staat (zou er al moeten staan sinds de vorige
scenes-feature).

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py -q`
Expected: FAIL — `AttributeError: module 'mirror_node.main' has no attribute '_apply_graph_message'`

- [ ] **Step 3: Werk de imports en module-state bij**

Vervang:

```python
from mirror_node.scenes import SceneEngine
```

door:

```python
from mirror_node.scenes import SceneGraph
```

Vervang:

```python
scene_engine = SceneEngine()
```

door:

```python
scene_graph = SceneGraph()
```

- [ ] **Step 4: Vervang `_apply_scenes_message` door `_apply_graph_message`**

```python
def _apply_graph_message(payload, logger):
    try:
        graph = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige graaf-JSON ontvangen, genegeerd")
        return
    if not isinstance(graph, dict):
        logger.error("Graaf-config is geen object, genegeerd: %r", graph)
        return
    scenes = graph.get("scenes", [])
    edges = graph.get("edges", [])
    root_scene_id = graph.get("root_scene_id")
    if not isinstance(scenes, list) or not isinstance(edges, list):
        logger.error("Graaf-config heeft geen geldige scenes/edges-lijst, genegeerd: %r", graph)
        return
    scene_graph.set_graph(scenes, edges, root_scene_id)
    for scene in scenes:
        if isinstance(scene, dict):
            _sync_overlay_in_background(scene)
```

- [ ] **Step 5: Werk `_apply_scene_preview_message` bij**

Vervang `scene_engine.set_preview(scene)` door `scene_graph.set_preview(scene)`.

- [ ] **Step 6: Werk `make_on_message` bij**

Vervang:

```python
            if msg.topic == topics.config_mirror_scenes:
                _apply_scenes_message(msg.payload.decode(), logger)
                return
```

door:

```python
            if msg.topic == topics.config_mirror_graph:
                _apply_graph_message(msg.payload.decode(), logger)
                return
```

- [ ] **Step 7: Vervang `_decide_action`/`_resolve_action` door `_render_action`**

Verwijder beide bestaande functies volledig, vervang door:

```python
def _render_action(winning, transitioned):
    """Bepaalt wat de hoofdlus deze cyclus moet doen, gegeven wat
    scene_graph.resolve() teruggaf. Puur -- geen state, geen I/O --
    zodat de driewegs-keuze (scare-video afspelen / camera-effect
    renderen / zwart beeld) los van de camera-lus getest kan worden."""
    if winning is None:
        return "blank"
    if winning.get("source_mode") == "scare_video":
        return "scare_video" if transitioned else "blank"
    return "render"
```

- [ ] **Step 8: Werk de MQTT-subscribe in `main()` bij**

Vervang:

```python
        client.subscribe(topics.config_mirror_scenes)
```

door:

```python
        client.subscribe(topics.config_mirror_graph)
```

- [ ] **Step 9: Herschrijf het trigger/dispatch-gedeelte van de hoofdlus**

Vervang het blok vanaf `fired = False` tot en met de
`streamer.publish_frame(rendered)`/`cv2.imshow`-regels door:

```python
            if trigger.detect(gray) and now > active_until:
                client.publish(topics.mirror_triggered, trigger_payload())
                logger.info("mirror triggered")
                active_until = time.time() + ACTIVE_SECONDS

            if test_trigger_requested.is_set():
                test_trigger_requested.clear()
                logger.info("mirror test-trigger")
                active_until = time.time() + ACTIVE_SECONDS

            winning, transitioned = scene_graph.resolve(now < active_until, now_hhmm)
            action = _render_action(winning, transitioned)

            if action == "scare_video":
                # Bij aankomst op een scare-video-scene: speel 'm nu
                # blokkerend af (bestaand _handle_trigger-pad,
                # ongewijzigd). _play_scare_video streamt zijn eigen
                # frames al, dus hier verder niets meer te renderen.
                cooldown = _handle_trigger(streamer, logger)
                active_until = time.time() + cooldown
                rendered = frame * 0
            elif action == "blank":
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
```

(De regels vóór `if trigger.detect(...)` -- `gray = ...`, `now =
time.time()`, `now_hhmm = time.strftime(...)` -- blijven ongewijzigd
staan; alleen het stuk erna verandert.)

- [ ] **Step 10: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py tests/test_scene_engine.py -q`
Expected: alle tests PASS

- [ ] **Step 11: Run de volledige backend/node-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests PASS — dit is de taak die het laatste, tijdelijke
gat uit Taak 2/5/6 sluit.

- [ ] **Step 12: Commit**

```bash
git add mirror_node/main.py tests/test_mirror_main.py
git commit -m "feat: mirror_node evalueert de scenegraaf i.p.v. de platte lijst"
```

---

## Task 8: Frontend — types + API-clients

**Files:**
- Modify: `admin/frontend/src/types.ts`
- Modify: `admin/frontend/src/api/scenes.ts`
- Create: `admin/frontend/src/api/sceneEdges.ts`

**Interfaces:**
- Produces: bijgewerkt `Scene`-type (geen `order_index`/trigger-velden
  meer, wel `is_root`/`canvas_x`/`canvas_y`), nieuw `SceneEdge`-type;
  `listScenes/getScene/createScene/updateScene/deleteScene/
  updateScenePosition/previewScene` (scenes.ts, `reorderScenes`
  vervalt); `listSceneEdges/createSceneEdge/updateSceneEdge/
  deleteSceneEdge` (sceneEdges.ts, nieuw). Gebruikt door Taak 9-12.

- [ ] **Step 1: Werk `Scene` bij en voeg `SceneEdge` toe in `types.ts`**

Vervang de hele `Scene`-interface door:

```ts
export interface Scene {
  id: number;
  name: string;
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
  is_root: boolean;
  canvas_x: number;
  canvas_y: number;
}

export interface SceneEdge {
  id: number;
  from_scene_id: number;
  to_scene_id: number | null;
  trigger_type: "always" | "motion" | "schedule" | null;
  trigger_from: string | null;
  trigger_until: string | null;
  priority: number;
}
```

- [ ] **Step 2: Herschrijf `admin/frontend/src/api/scenes.ts`**

Vervang de hele inhoud door:

```ts
import { apiFetch } from "./client";
import type { Scene } from "../types";

export type SceneDraft = Omit<Scene, "id">;

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

export function updateScenePosition(id: number, canvas_x: number, canvas_y: number): Promise<void> {
  return apiFetch(`/api/scenes/${id}/position`, {
    method: "PUT",
    body: JSON.stringify({ canvas_x, canvas_y }),
  });
}

export function previewScene(id: number, scene: SceneDraft): Promise<void> {
  return apiFetch(`/api/scenes/${id}/preview`, { method: "POST", body: JSON.stringify(scene) });
}
```

- [ ] **Step 3: Maak `admin/frontend/src/api/sceneEdges.ts`**

```ts
import { apiFetch } from "./client";
import type { SceneEdge } from "../types";

export type SceneEdgeDraft = Omit<SceneEdge, "id">;

export function listSceneEdges(): Promise<SceneEdge[]> {
  return apiFetch<SceneEdge[]>("/api/scene-edges");
}

export function createSceneEdge(
  edge: Partial<SceneEdgeDraft> & { from_scene_id: number },
): Promise<SceneEdge> {
  return apiFetch<SceneEdge>("/api/scene-edges", { method: "POST", body: JSON.stringify(edge) });
}

export function updateSceneEdge(id: number, edge: Partial<SceneEdgeDraft>): Promise<SceneEdge> {
  return apiFetch<SceneEdge>(`/api/scene-edges/${id}`, { method: "PUT", body: JSON.stringify(edge) });
}

export function deleteSceneEdge(id: number): Promise<void> {
  return apiFetch(`/api/scene-edges/${id}`, { method: "DELETE" });
}
```

- [ ] **Step 4: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: fouten in `SceneWizardModal.tsx` en `DashboardPage.tsx`
(verwijzen nog naar verwijderde `trigger_type`/`order_index`-velden en
`reorderScenes`) — dat is verwacht op dit punt, opgelost in Taak 9/12.
Geen fouten vanuit `types.ts`, `api/scenes.ts` of `api/sceneEdges.ts` zelf.

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/types.ts admin/frontend/src/api/scenes.ts admin/frontend/src/api/sceneEdges.ts
git commit -m "feat: Scene/SceneEdge-types + scene-edges-API-client"
```

---

## Task 9: Frontend — `SceneWizardModal`: Trigger-stap eruit, `initialStep`-prop erbij

**Files:**
- Modify: `admin/frontend/src/components/SceneWizardModal.tsx`

**Interfaces:**
- Consumes: bijgewerkte `SceneDraft` (Taak 8, geen trigger-velden meer).
- Produces: `<SceneWizardModal sceneId initialStep? onClose onSaved />`
  — trigger-bewerking verhuist naar `EdgeTriggerPopover` (Taak 10).
  Dit is ook de eerder afgesproken "klikbare elementen"-verbetering:
  een aanroeper kan nu direct op een specifieke stap openen.

- [ ] **Step 1: Werk `EMPTY_DRAFT` bij**

Vervang:

```ts
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
```

door:

```ts
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
  is_root: false,
  canvas_x: 0,
  canvas_y: 0,
};
```

- [ ] **Step 2: Werk `Props`, `Step` en `STEP_LABEL` bij**

Vervang:

```ts
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
```

door:

```ts
interface Props {
  sceneId: number | null;
  initialStep?: Step;
  onClose: () => void;
  onSaved: () => void;
}

type Step = "input" | "animation" | "output";
const STEP_LABEL: Record<Step, string> = {
  input: "Input",
  animation: "Animatie",
  output: "Output",
};
```

- [ ] **Step 3: Werk de component-signature en initiële step-state bij**

Vervang:

```ts
export default function SceneWizardModal({ sceneId, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<SceneDraft>(EMPTY_DRAFT);
  const [step, setStep] = useState<Step>("input");
```

door:

```ts
export default function SceneWizardModal({ sceneId, initialStep, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<SceneDraft>(EMPTY_DRAFT);
  const [step, setStep] = useState<Step>(initialStep ?? "input");
```

- [ ] **Step 4: Werk de `steps`-berekening bij**

Vervang:

```ts
  const steps: Step[] =
    draft.source_mode === "camera" ? ["input", "animation", "output", "trigger"] : ["input", "trigger"];
```

door:

```ts
  const steps: Step[] = draft.source_mode === "camera" ? ["input", "animation", "output"] : ["input"];
```

- [ ] **Step 5: Verwijder de hele Trigger-stap-JSX**

Verwijder het volledige `{step === "trigger" && (...)}`-blok (van
`{step === "trigger" && (` tot en met de bijbehorende sluitende `)}`,
direct vóór `</div>` van `scene-modal__body`).

- [ ] **Step 6: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen fouten meer vanuit `SceneWizardModal.tsx` zelf (fouten
in `DashboardPage.tsx` blijven tot Taak 12)

- [ ] **Step 7: Commit**

```bash
git add admin/frontend/src/components/SceneWizardModal.tsx
git commit -m "refactor: SceneWizardModal -- trigger-stap eruit, initialStep-prop erbij"
```

---

## Task 10: Frontend — `EdgeTriggerPopover`

**Files:**
- Create: `admin/frontend/src/components/EdgeTriggerPopover.tsx`
- Create: `admin/frontend/src/components/EdgeTriggerPopover.css`

**Interfaces:**
- Consumes: `SceneEdge`, `updateSceneEdge`/`deleteSceneEdge` (Taak 8).
- Produces: `<EdgeTriggerPopover edge onClose onSaved />`. Gebruikt
  door Taak 11 (canvas, bij het klikken op een verbinding).

- [ ] **Step 1: Implementeer `EdgeTriggerPopover.tsx`**

```tsx
import { useState } from "react";
import { updateSceneEdge, deleteSceneEdge } from "../api/sceneEdges";
import type { SceneEdge } from "../types";
import "./EdgeTriggerPopover.css";

interface Props {
  edge: SceneEdge;
  onClose: () => void;
  onSaved: () => void;
}

export default function EdgeTriggerPopover({ edge, onClose, onSaved }: Props) {
  const [triggerType, setTriggerType] = useState<NonNullable<SceneEdge["trigger_type"]>>(
    edge.trigger_type ?? "always",
  );
  const [from, setFrom] = useState(edge.trigger_from ?? "");
  const [until, setUntil] = useState(edge.trigger_until ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    try {
      await updateSceneEdge(edge.id, {
        from_scene_id: edge.from_scene_id,
        to_scene_id: edge.to_scene_id,
        trigger_type: triggerType,
        trigger_from: triggerType === "schedule" ? from : null,
        trigger_until: triggerType === "schedule" ? until : null,
        priority: edge.priority,
      });
      onSaved();
      onClose();
    } catch {
      setError("Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    setSaving(true);
    try {
      await deleteSceneEdge(edge.id);
      onSaved();
      onClose();
    } catch {
      setError("Verwijderen is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="edge-popover__backdrop" role="dialog" aria-modal="true">
      <div className="edge-popover">
        <p className="edge-popover__title">Trigger voor deze verbinding</p>
        {error && (
          <p className="edge-popover__error" role="alert">
            {error}
          </p>
        )}
        <div className="edge-popover__options">
          <label className="edge-popover__radio">
            <input
              type="radio"
              name="edge-trigger"
              checked={triggerType === "always"}
              onChange={() => setTriggerType("always")}
            />
            Altijd
          </label>
          <label className="edge-popover__radio">
            <input
              type="radio"
              name="edge-trigger"
              checked={triggerType === "motion"}
              onChange={() => setTriggerType("motion")}
            />
            Beweging
          </label>
          <label className="edge-popover__radio">
            <input
              type="radio"
              name="edge-trigger"
              checked={triggerType === "schedule"}
              onChange={() => setTriggerType("schedule")}
            />
            Tijdschema
          </label>
          {triggerType === "schedule" && (
            <div className="edge-popover__schedule">
              <label>
                <span>Van</span>
                <input type="time" value={from} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label>
                <span>Tot</span>
                <input type="time" value={until} onChange={(e) => setUntil(e.target.value)} />
              </label>
            </div>
          )}
        </div>
        <div className="edge-popover__actions">
          <button type="button" onClick={handleDelete} disabled={saving}>
            Verwijderen
          </button>
          <button type="button" onClick={onClose} disabled={saving}>
            Annuleren
          </button>
          <button type="button" onClick={handleSave} disabled={saving}>
            {saving ? "Bezig…" : "Opslaan"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Maak `EdgeTriggerPopover.css`**

```css
.edge-popover__backdrop {
  position: fixed;
  inset: 0;
  background: rgba(11, 11, 15, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
  padding: 1.5rem;
}

.edge-popover {
  width: 100%;
  max-width: 360px;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
  color: var(--bone);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  padding: 1.25rem;
}

.edge-popover__title {
  margin: 0 0 1rem;
  font-weight: 700;
}

.edge-popover__error {
  color: var(--alarm);
  font-size: 0.85rem;
  margin-bottom: 0.75rem;
}

.edge-popover__options {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.edge-popover__radio {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
}

.edge-popover__schedule {
  display: flex;
  gap: 1rem;
  margin-left: 1.5rem;
}

.edge-popover__schedule label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.8rem;
  color: var(--ash);
}

.edge-popover__schedule input {
  padding: 0.5rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 6px;
  color: var(--bone);
  color-scheme: dark;
}

.edge-popover__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.25rem;
}

.edge-popover__actions button {
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  cursor: pointer;
  background: transparent;
  border: 1px solid var(--panel-edge);
  color: var(--bone);
}

.edge-popover__actions button:last-child {
  background: var(--ember);
  border-color: var(--ember);
  color: var(--void);
}
```

- [ ] **Step 3: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen nieuwe fouten vanuit deze twee nieuwe bestanden.

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/components/EdgeTriggerPopover.tsx admin/frontend/src/components/EdgeTriggerPopover.css
git commit -m "feat: EdgeTriggerPopover -- trigger instellen voor één verbinding"
```

---

## Task 11: Frontend — `@xyflow/react` + `SceneGraphCanvas`

**Files:**
- Modify: `admin/frontend/package.json` (nieuwe dependency)
- Create: `admin/frontend/src/components/SceneGraphCanvas.tsx`
- Create: `admin/frontend/src/components/SceneGraphCanvas.css`

**Interfaces:**
- Consumes: `Scene`, `SceneEdge`, scenes-/sceneEdges-API (Taak 8),
  `EdgeTriggerPopover` (Taak 10).
- Produces: `<SceneGraphCanvas scenes edges onSceneClick={(id, step) =>
  void} onGraphChanged={() => void} onAddScene={() => void} />`.
  Gebruikt door Taak 12.

Dit is het grootste, meest onzekere onderdeel van dit plan (nieuwe
library, geen bestaand precedent in deze codebase). Verifieer
prop-/exportnamen tegen de daadwerkelijk geïnstalleerde
`@xyflow/react`-versie als iets hieronder niet exact matcht — dat is
normale bijstelling bij een nieuwe dependency, geen scope-uitbreiding.

- [ ] **Step 1: Voeg de dependency toe**

```bash
cd admin/frontend && npm install @xyflow/react
```

Verifieer: `admin/frontend/package.json`'s `dependencies` bevat nu
`"@xyflow/react": "^..."` (npm kiest de exacte versie).

- [ ] **Step 2: Implementeer `SceneGraphCanvas.tsx`**

```tsx
import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  createSceneEdge,
  deleteSceneEdge,
  updateSceneEdge,
} from "../api/sceneEdges";
import { updateScene, updateScenePosition } from "../api/scenes";
import EdgeTriggerPopover from "./EdgeTriggerPopover";
import type { Scene, SceneEdge } from "../types";
import "./SceneGraphCanvas.css";

interface Props {
  scenes: Scene[];
  edges: SceneEdge[];
  onSceneClick: (sceneId: number, step: "input" | "animation" | "output") => void;
  onGraphChanged: () => void;
  onAddScene: () => void;
}

type SceneNodeData = {
  scene: Scene;
  outputs: SceneEdge[];
  onSceneClick: Props["onSceneClick"];
  onAddOutput: (fromSceneId: number) => void;
  onMakeRoot: (sceneId: number) => void;
};

function triggerLabel(edge: SceneEdge): string {
  if (edge.trigger_type === "always") return "Altijd";
  if (edge.trigger_type === "motion") return "Beweging";
  if (edge.trigger_type === "schedule") return `${edge.trigger_from ?? "?"}–${edge.trigger_until ?? "?"}`;
  return "Nog niet ingesteld";
}

function SceneNode({ data }: NodeProps & { data: SceneNodeData }) {
  const { scene, outputs, onSceneClick, onAddOutput, onMakeRoot } = data;
  return (
    <div className="scene-node" data-root={scene.is_root}>
      <Handle type="target" position={Position.Left} />
      <div className="scene-node__header">
        <button type="button" className="scene-node__root" onClick={() => onMakeRoot(scene.id)} title="Maak root">
          {scene.is_root ? "★" : "☆"}
        </button>
        <span className="scene-node__name" onClick={() => onSceneClick(scene.id, "input")}>
          {scene.name}
        </span>
      </div>
      <div className="scene-node__chips">
        <span className="scene-node__chip" onClick={() => onSceneClick(scene.id, "input")}>
          {scene.source_mode === "camera" ? "Camera" : "Scare-video"}
        </span>
        {scene.source_mode === "camera" && (
          <>
            <span className="scene-node__chip" onClick={() => onSceneClick(scene.id, "animation")}>
              {scene.effect}
            </span>
            <span className="scene-node__chip" onClick={() => onSceneClick(scene.id, "output")}>
              Weergave
            </span>
          </>
        )}
      </div>
      <div className="scene-node__outputs">
        {outputs.map((edge, i) => (
          <div key={edge.id} className="scene-node__output" style={{ top: `${40 + i * 24}px` }}>
            <span className="scene-node__output-label">
              {edge.to_scene_id === null ? "leeg" : triggerLabel(edge)}
            </span>
            <Handle
              type="source"
              position={Position.Right}
              id={`output-${edge.id}`}
              style={{ top: `${40 + i * 24}px` }}
            />
          </div>
        ))}
      </div>
      <button type="button" className="scene-node__add-output" onClick={() => onAddOutput(scene.id)}>
        + output
      </button>
    </div>
  );
}

const nodeTypes = { scene: SceneNode };

export default function SceneGraphCanvas({ scenes, edges, onSceneClick, onGraphChanged, onAddScene }: Props) {
  const [popoverEdge, setPopoverEdge] = useState<SceneEdge | null>(null);

  const handleAddOutput = useCallback(
    async (fromSceneId: number) => {
      await createSceneEdge({ from_scene_id: fromSceneId });
      onGraphChanged();
    },
    [onGraphChanged],
  );

  const handleMakeRoot = useCallback(
    async (sceneId: number) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, is_root: true });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
  );

  const flowNodes: Node[] = useMemo(
    () =>
      scenes.map((scene) => ({
        id: String(scene.id),
        type: "scene",
        position: { x: scene.canvas_x, y: scene.canvas_y },
        data: {
          scene,
          outputs: edges.filter((e) => e.from_scene_id === scene.id),
          onSceneClick,
          onAddOutput: handleAddOutput,
          onMakeRoot: handleMakeRoot,
        } satisfies SceneNodeData,
      })),
    [scenes, edges, onSceneClick, handleAddOutput, handleMakeRoot],
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      edges
        .filter((e) => e.to_scene_id !== null)
        .map((e) => ({
          id: String(e.id),
          source: String(e.from_scene_id),
          sourceHandle: `output-${e.id}`,
          target: String(e.to_scene_id),
          label: triggerLabel(e),
          markerEnd: { type: MarkerType.ArrowClosed },
          data: { edge: e },
        })),
    [edges],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [rfEdges, , onEdgesChange] = useEdgesState(flowEdges);

  // Houdt de React Flow-state in sync zodra scenes/edges van de server
  // opnieuw binnenkomen (na een CRUD-actie elders) -- useNodesState houdt
  // verder zijn eigen interne sleep-state bij tussen renders.
  useMemo(() => {
    setNodes(flowNodes);
  }, [flowNodes, setNodes]);

  const handleConnect = useCallback(
    async (connection: Connection) => {
      if (!connection.sourceHandle || !connection.target) return;
      const edgeId = parseInt(connection.sourceHandle.replace("output-", ""), 10);
      if (Number.isNaN(edgeId)) return;
      const edge = edges.find((e) => e.id === edgeId);
      if (!edge) return;
      await updateSceneEdge(edgeId, {
        from_scene_id: edge.from_scene_id,
        to_scene_id: parseInt(connection.target, 10),
        trigger_type: edge.trigger_type,
        trigger_from: edge.trigger_from,
        trigger_until: edge.trigger_until,
        priority: edge.priority,
      });
      onGraphChanged();
    },
    [edges, onGraphChanged],
  );

  const handleNodeDragStop = useCallback(
    async (_event: unknown, node: Node) => {
      await updateScenePosition(parseInt(node.id, 10), node.position.x, node.position.y);
    },
    [],
  );

  const handleEdgeClick = useCallback(
    (_event: unknown, edge: Edge) => {
      const real = edges.find((e) => String(e.id) === edge.id);
      if (real) setPopoverEdge(real);
    },
    [edges],
  );

  return (
    <div className="scene-graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
        onNodeDragStop={handleNodeDragStop}
        onEdgeClick={handleEdgeClick}
        fitView
      >
        <Background />
        <Controls />
      </ReactFlow>
      <button type="button" className="scene-graph-canvas__add" onClick={onAddScene}>
        + Nieuwe scene
      </button>
      {popoverEdge && (
        <EdgeTriggerPopover
          edge={popoverEdge}
          onClose={() => setPopoverEdge(null)}
          onSaved={onGraphChanged}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Maak `SceneGraphCanvas.css`**

```css
.scene-graph-canvas {
  position: relative;
  height: 520px;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 10px;
  overflow: hidden;
}

.scene-graph-canvas__add {
  position: absolute;
  bottom: 1rem;
  right: 1rem;
  z-index: 5;
  padding: 0.6rem 1rem;
  border-radius: 6px;
  background: var(--ember);
  border: none;
  color: var(--void);
  font-weight: 700;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  cursor: pointer;
}

.scene-node {
  position: relative;
  min-width: 180px;
  padding: 0.75rem;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 10px;
  color: var(--bone);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

.scene-node[data-root="true"] {
  border-color: var(--signal);
}

.scene-node__header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.5rem;
}

.scene-node__root {
  background: transparent;
  border: none;
  color: var(--signal);
  cursor: pointer;
  font-size: 1rem;
  padding: 0;
}

.scene-node__name {
  font-weight: 700;
  cursor: pointer;
}

.scene-node__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-bottom: 1.5rem;
}

.scene-node__chip {
  padding: 0.2rem 0.5rem;
  font-size: 0.7rem;
  border: 1px solid var(--panel-edge);
  border-radius: 999px;
  color: var(--ash);
  cursor: pointer;
}

.scene-node__outputs {
  position: relative;
  min-height: 24px;
}

.scene-node__output {
  position: absolute;
  right: 0.5rem;
  font-size: 0.65rem;
  color: var(--ash);
  transform: translateY(-50%);
}

.scene-node__add-output {
  margin-top: 0.5rem;
  padding: 0.25rem 0.5rem;
  font-size: 0.7rem;
  background: transparent;
  border: 1px dashed var(--panel-edge);
  border-radius: 6px;
  color: var(--ash);
  cursor: pointer;
}
```

- [ ] **Step 4: Typecheck + build**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build`
Expected: 0 fouten vanuit deze twee nieuwe bestanden. Als
`@xyflow/react`'s daadwerkelijke exports/prop-namen afwijken van wat
hierboven staat, pas aan op basis van de foutmelding/de library's
eigen `.d.ts`-bestanden (`node_modules/@xyflow/react/dist/...`) — dat
is verwachte bijstelling, geen scope-uitbreiding.

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/package.json admin/frontend/package-lock.json \
  admin/frontend/src/components/SceneGraphCanvas.tsx admin/frontend/src/components/SceneGraphCanvas.css
git commit -m "feat: SceneGraphCanvas -- sleepbare node-editor voor de scenegraaf"
```

---

## Task 12: Frontend — Dashboard: canvas i.p.v. kaarten-grid

**Files:**
- Modify: `admin/frontend/src/pages/DashboardPage.tsx`

**Interfaces:**
- Consumes: `SceneGraphCanvas` (Taak 11), `listSceneEdges` (Taak 8),
  bijgewerkte `SceneWizardModal` met `initialStep` (Taak 9).
- Produces: Dashboard toont het canvas i.p.v. de scene-kaarten-grid.
  Node-status/noodstop/tijdvenster-secties blijven ongewijzigd.

- [ ] **Step 1: Werk de imports bij**

Vervang:

```tsx
import { listScenes, deleteScene, reorderScenes, updateScene } from "../api/scenes";
```

door:

```tsx
import { listScenes } from "../api/scenes";
import { listSceneEdges } from "../api/sceneEdges";
```

Voeg toe:

```tsx
import SceneGraphCanvas from "../components/SceneGraphCanvas";
import type { SceneEdge } from "../types";
```

(`SceneWizardModal`-import blijft ongewijzigd staan.)

- [ ] **Step 2: Voeg edges-state toe en breid `refreshScenes` uit**

Vervang:

```tsx
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardSceneId, setWizardSceneId] = useState<number | null>(null);
```

door:

```tsx
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [sceneEdges, setSceneEdges] = useState<SceneEdge[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardSceneId, setWizardSceneId] = useState<number | null>(null);
  const [wizardInitialStep, setWizardInitialStep] = useState<"input" | "animation" | "output">("input");
```

Vervang:

```tsx
  function refreshScenes() {
    listScenes()
      .then(setScenes)
      .catch(() => setError("Scenes konden niet worden geladen."));
  }
```

door:

```tsx
  function refreshScenes() {
    listScenes()
      .then(setScenes)
      .catch(() => setError("Scenes konden niet worden geladen."));
    listSceneEdges()
      .then(setSceneEdges)
      .catch(() => setError("Verbindingen konden niet worden geladen."));
  }
```

- [ ] **Step 3: Verwijder de nu overbodige handlers**

Verwijder `handleDeleteScene`, `handleToggleScene`, `handleMoveScene`
en `triggerSummary` volledig — die functionaliteit zit voortaan in
`SceneGraphCanvas`/`EdgeTriggerPopover` (verwijderen/in-uitschakelen
van een scene kan via de wizard zelf, die dat al ongewijzigd
ondersteunt; in-/uitschakelen kan als losse verbetering later
terugkomen op de node zelf als daar behoefte aan blijkt — voor nu:
scope beperkt tot wat deze taak vraagt).

- [ ] **Step 4: Werk `openWizard` bij en voeg de canvas-callbacks toe**

Vervang:

```tsx
  function openWizard(id: number | null) {
    setWizardSceneId(id);
    setWizardOpen(true);
  }
```

door:

```tsx
  function openWizard(id: number | null, step: "input" | "animation" | "output" = "input") {
    setWizardSceneId(id);
    setWizardInitialStep(step);
    setWizardOpen(true);
  }
```

- [ ] **Step 5: Vervang de Scenes-sectie JSX**

Vervang het hele blok van `<section className="dash-panel">` (met
`<p className="dash-panel__eyebrow">Scenes</p>`) tot en met de
bijbehorende sluitende `</section>` door:

```tsx
      <section className="dash-panel">
        <p className="dash-panel__eyebrow">Scenes</p>
        <SceneGraphCanvas
          scenes={scenes}
          edges={sceneEdges}
          onSceneClick={(id, step) => openWizard(id, step)}
          onGraphChanged={refreshScenes}
          onAddScene={() => openWizard(null)}
        />
      </section>
```

- [ ] **Step 6: Werk de `SceneWizardModal`-aanroep bij**

Vervang:

```tsx
      {wizardOpen && (
        <SceneWizardModal
          sceneId={wizardSceneId}
          onClose={() => setWizardOpen(false)}
          onSaved={refreshScenes}
        />
      )}
```

door:

```tsx
      {wizardOpen && (
        <SceneWizardModal
          sceneId={wizardSceneId}
          initialStep={wizardInitialStep}
          onClose={() => setWizardOpen(false)}
          onSaved={refreshScenes}
        />
      )}
```

- [ ] **Step 7: Typecheck + build**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build`
Expected: 0 fouten, build slaagt.

- [ ] **Step 8: Commit**

```bash
git add admin/frontend/src/pages/DashboardPage.tsx
git commit -m "feat: Dashboard toont de scenegraaf-canvas i.p.v. de kaarten-grid"
```

---

## Task 13: README bijwerken

**Files:**
- Modify: `README.md`

**Interfaces:** geen (documentatie).

- [ ] **Step 1: Werk de MQTT-topic-tabel bij**

Vervang de rij voor `config/mirror/scenes` (toegevoegd door de vorige
scenes-feature) door:

```markdown
| `config/mirror/graph` | backend → mirror | JSON `{scenes, edges, root_scene_id}` (retained) |
```

(`control/mirror/scene-preview` blijft ongewijzigd staan.)

- [ ] **Step 2: Werk de scenes-alinea bij**

Vervang de bestaande alinea over scenes (toegevoegd door de vorige
scenes-feature, direct na de introductie-alinea) door:

```markdown
Het spiegel-effect wordt geprogrammeerd als een **scenegraaf** vanaf
het Dashboard van de beheerpagina: scenes zijn knopen, elk met eigen
uitgaande verbindingen (outputs) naar andere scenes, elk met een eigen
trigger (beweging / tijdschema / altijd). De mirror-node onthoudt
welke scene nu actief is en volgt alleen de outputs van díe scene —
een verbinding sleep je tussen twee scenes, de trigger stel je in door
op de lijn te klikken.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README bijwerken voor de scenegraaf"
```

---

## Self-Review Notes

- **Spec coverage:** `scene_edges`-tabel + graaf-migratie (Taak 1),
  `SceneGraph` (Taak 2), MQTT-topic-hernoeming (Taak 3), `MqttBridge`
  (Taak 4), backend scenes-route zonder trigger/order + positie-route
  (Taak 5), scene-edges-CRUD + republish-hook (Taak 6), mirror_node-
  hoofdlus (Taak 7), frontend-types/API (Taak 8), wizard zonder
  trigger-stap (Taak 9), edge-trigger-popover (Taak 10), node-editor-
  canvas (Taak 11), Dashboard-integratie (Taak 12), documentatie
  (Taak 13) — elk spec-onderdeel heeft een taak. De eerder afgesproken
  "klikbare elementen"-verbetering is meegenomen in Taak 9/11 (de
  chips op elke node openen de wizard op de juiste stap) i.p.v. als
  losse taak.
- **Vorige, expliciet uitgestelde bevinding gedicht:** de vorige
  scenes-plan's eind-review vond dat de hoofdlus-dispatch-logica geen
  enkele test had (uitgesteld, geen testharnas voor de camera-lus).
  Taak 7 introduceert `_render_action` als pure, apart testbare
  functie die precies die beslissing vastlegt — dit plan lost dat gat
  dus mee op i.p.v. het nogmaals uit te stellen.
- **Type consistency:** `Scene`/`SceneEdge`/`SceneDraft`/
  `SceneEdgeDraft` (Taak 8) worden letterlijk hetzelfde gebruikt in
  `SceneWizardModal.tsx` (Taak 9), `EdgeTriggerPopover.tsx` (Taak 10)
  en `SceneGraphCanvas.tsx`/`DashboardPage.tsx` (Taak 11-12);
  backend-veldnamen in `admin/app/routers/scenes.py`/`scene_edges.py`
  (Taak 5-6) matchen 1-op-1 de `_row_to_scene`/`_row_to_edge`-sleutels
  die de frontend-types verwachten; `SceneGraph.resolve`'s
  `(scene, transitioned)`-signatuur uit Taak 2 wordt ongewijzigd
  gebruikt in Taak 7.
