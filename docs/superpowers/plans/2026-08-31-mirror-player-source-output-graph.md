# Player/Source/Trigger/Output Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Scene/Trigger graph into a 4-node-type flow: Scene becomes Player (with playback-mode settings), Source and Output become their own connectable graph node types, and Players gain named, draggable outgoing branches that route to a Trigger or straight to an Output.

**Architecture:** Rename `scenes`→`players` throughout (DB table, backend routes, frontend types/components/pages, MQTT payload). Add two new first-class entities — `sources` (camera stream or static image, many-to-one into players) and `player_branches` (named outgoing ports on a player) — plus an `output_connections` join table wiring a branch straight to a physical `output` (bypassing Trigger). `mirror_node` gains a playback-mode gate (once / repeat once / repeat-while-sensor, the last one deliberately level-based, unlike the pulse-based HA-sensor trigger) before its existing trigger-evaluation loop, and dynamic per-player source resolution (camera reopen on source change, or a cached static image).

**Tech Stack:** FastAPI + SQLite (backend), React + `@xyflow/react` + TypeScript (frontend), OpenCV/paho-mqtt (mirror_node), pytest + Vitest.

**Spec:** docs/superpowers/specs/2026-08-31-mirror-player-source-output-graph-design.md

## Global Constraints

- No DB foreign keys — all cascade cleanup happens in application code (route handlers), never via `PRAGMA foreign_keys` or `REFERENCES`.
- FastAPI route params that take a numeric id use the `{id:int}` typed converter, never a bare `{id}` (except the pre-existing `preview_scene_route`, whose bare `{scene_id}` is a known, out-of-scope pattern — do not "fix" it as a drive-by).
- New columns on existing tables go through `admin/app/db.py`'s `_ensure_column(conn, table, column, ddl)` helper, never a bare `ALTER TABLE ... ADD COLUMN` inline — `_ensure_column` is idempotent-safe (checks column existence first) and every other migration in this file already uses it.
- A table **rename** (as opposed to a new column) is a different hazard than `_ensure_column` handles: every other place in `db.py` that references the old table name by a literal SQL string must either run strictly *before* the rename (same `init_db()` call, in-order) or be updated/guarded so it no longer references the old name on a *later* run once the rename has already happened once. Task 2 below hits this directly — read its migration section carefully before touching `db.py`.
- Trigger firing stays strictly **pulse-based** (rising-edge only, never a sustained "on" level) — this is unchanged from the existing HA-sensor-trigger mechanism and must not regress. The new `repeat_while` playback mode is *intentionally* the opposite (level-based: loops exactly as long as its sensor reports "on") — this is a different mechanism for a different purpose (playback duration, not trigger firing) and both must coexist without one being mistaken for the other.
- `PRAGMA user_version` gates every migration that **renames or restructures** an existing table (never a proxy like "row count == 0", which breaks on a legitimately-empty-but-already-migrated install — see the existing `_migrate_scenes_to_graph` docstring for the incident this rule comes from). Purely additive `_ensure_column` calls need no such gate. The existing gates are v1 (scenes→graph) and v2 (scene_edges→triggers); this plan adds v3 (scenes→players), v4 (player_branches), v5 (triggers branch-columns), v6 (output canvas-position seed), v7 (output_connections seed) — always check `PRAGMA user_version` at the top of a new migration function and bump it at the bottom, exactly once per version.
- Run backend tests with `.venv/bin/python -m pytest tests/ -q` from the repo root (the system `python3` lacks `paho`/`cv2` — always use the repo's `.venv`). Run frontend tests with `cd admin/frontend && npm test`. Run the frontend typecheck with `cd admin/frontend && npx tsc --noEmit`.

---

### Task 1: `sources` table + migration + CRUD route

**Files:**
- Modify: `admin/app/db.py`
- Create: `admin/app/routers/sources.py`
- Modify: `admin/app/main.py` (register `sources_router`)
- Test: `tests/test_admin_db.py` (append)
- Test: `tests/test_admin_routes_sources.py` (new)

**Interfaces:**
- Produces: `sources` table (`id, name, kind, value, canvas_x, canvas_y`); `GET/POST /api/sources`, `GET/PUT/DELETE /api/sources/{source_id:int}`. `kind` is `'camera_stream'` or `'static_image'`; `value` is the camera URL or a media hash/path.
- Consumes: nothing from a later task. `_migrate_sources` reads the existing `outputs` table (already migrated by the time this runs, since `_migrate_outputs` is called earlier in `init_db()`).

- [ ] **Step 1: Write the failing migration tests**

Append to `tests/test_admin_db.py`:

```python
def test_sources_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "sources" in tables


def test_default_source_created_from_output_camera_source(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(
        """CREATE TABLE app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mqtt_host TEXT NOT NULL,
            mqtt_port INTEGER NOT NULL,
            mqtt_user TEXT NOT NULL DEFAULT '',
            mqtt_pass TEXT NOT NULL DEFAULT '',
            ha_url TEXT NOT NULL,
            ha_token TEXT NOT NULL DEFAULT '',
            mirror_stream_url TEXT NOT NULL DEFAULT '',
            mqtt_topic_prefix TEXT NOT NULL DEFAULT '',
            mirror_camera_source TEXT NOT NULL DEFAULT ''
        )"""
    )
    raw.execute(
        "INSERT INTO app_settings (id, mqtt_host, mqtt_port, ha_url, mirror_camera_source) "
        "VALUES (1, 'broker', 1883, 'http://ha', 'rtsp://cam.local/stream')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code -- outputs- en sources-migratie samen

    rows = conn.execute("SELECT name, kind, value FROM sources").fetchall()
    assert rows == [("Spiegel camera", "camera_stream", "rtsp://cam.local/stream")]


def test_source_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    assert count == 1


def test_blanked_source_value_is_not_reverted_on_restart(tmp_path):
    """Zelfde soort regressie als Finding 2 op outputs: een bewust
    leeggemaakte source-waarde mag niet teruggezet worden bij herstart."""
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    source_id = conn.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
    conn.execute("UPDATE sources SET value = '' WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # herstart

    rows = conn2.execute("SELECT value FROM sources").fetchall()
    assert rows == [("",)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k source -v`
Expected: FAIL — no `sources` table exists yet.

- [ ] **Step 3: Add the table and migration to `admin/app/db.py`**

Add the `CREATE TABLE` next to the other table-creation calls in `init_db()`, directly after the existing `outputs` block:

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'camera_stream',
            value TEXT NOT NULL DEFAULT '',
            canvas_x REAL NOT NULL DEFAULT 0,
            canvas_y REAL NOT NULL DEFAULT 0
        )"""
    )
```

Add the call `_migrate_sources(conn)` in `init_db()` directly after the existing `_migrate_outputs(conn)` call (before `_migrate_scene_edges_to_triggers(conn)` — order doesn't matter between these two, but keep it grouped with `_migrate_outputs` since it reads from `outputs`).

Add the function itself, near `_migrate_outputs`:

```python
def _migrate_sources(conn):
    """Zorgt dat er minstens één source bestaat, gevuld vanuit de huidige
    (enige) output's camera_source bij de allereerste run na deze upgrade.
    Idempotent: doet niets zodra er al een source is -- zelfde reden als
    _migrate_outputs hierboven: geen 'value nog leeg? opnieuw vullen'-pad
    op elke run, dat zou een bewust leeggemaakte source terugzetten."""
    existing = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    if existing > 0:
        return
    output_row = conn.execute("SELECT name, camera_source FROM outputs ORDER BY id LIMIT 1").fetchone()
    if output_row is None:
        return
    output_name, camera_source = output_row
    conn.execute(
        "INSERT INTO sources (name, kind, value, canvas_x, canvas_y) VALUES (?, 'camera_stream', ?, ?, ?)",
        (f"{output_name} camera", camera_source, -300.0, 0.0),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k source -v`
Expected: PASS.

- [ ] **Step 5: Write the failing route tests**

Create `tests/test_admin_routes_sources.py`:

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

    def publish_mirror_ha_trigger(self, entity_id):
        self.calls.append(("ha_trigger", entity_id))


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


def test_list_sources_includes_the_migrated_default(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/sources")

    assert response.status_code == 200
    sources = response.json()
    assert len(sources) == 1
    assert sources[0]["kind"] == "camera_stream"


def test_create_source(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/sources", json={
        "name": "Tuinbeeld", "kind": "camera_stream", "value": "rtsp://x", "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Tuinbeeld"
    assert created["kind"] == "camera_stream"


def test_create_source_rejects_empty_name(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/sources", json={
        "name": "  ", "kind": "camera_stream", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 400


def test_create_source_rejects_invalid_kind(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/sources", json={
        "name": "X", "kind": "teleport", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 400


def test_update_source(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/sources", json={
        "name": "A", "kind": "camera_stream", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    }).json()

    response = client.put(f"/api/sources/{created['id']}", json={
        "name": "B", "kind": "static_image", "value": "abc123", "canvas_x": 10.0, "canvas_y": 5.0,
    })

    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "B"
    assert updated["kind"] == "static_image"
    assert updated["canvas_x"] == 10.0


def test_update_source_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/sources/999", json={
        "name": "X", "kind": "camera_stream", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 404


def test_delete_source_without_players(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/sources", json={
        "name": "Tijdelijk", "kind": "camera_stream", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    }).json()

    response = client.delete(f"/api/sources/{created['id']}")

    assert response.status_code == 200
    remaining_ids = [s["id"] for s in client.get("/api/sources").json()]
    assert created["id"] not in remaining_ids


def test_source_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    assert client.get("/api/sources").status_code == 401
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_sources.py -v`
Expected: FAIL — no route registered (404 on every request).

- [ ] **Step 7: Create the router**

Create `admin/app/routers/sources.py`:

```python
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_SOURCE_COLUMNS = "id, name, kind, value, canvas_x, canvas_y"
_VALID_KINDS = {"camera_stream", "static_image"}


def _row_to_source(row):
    return {"id": row[0], "name": row[1], "kind": row[2], "value": row[3], "canvas_x": row[4], "canvas_y": row[5]}


def _list_sources(db):
    rows = db.execute(f"SELECT {_SOURCE_COLUMNS} FROM sources ORDER BY id").fetchall()
    return [_row_to_source(r) for r in rows]


def _validate_source_body(body):
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name mag niet leeg zijn")
    kind = body.get("kind", "camera_stream")
    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind moet één van {sorted(_VALID_KINDS)} zijn")
    return {
        "name": name,
        "kind": kind,
        "value": str(body.get("value", "")),
        "canvas_x": float(body.get("canvas_x", 0.0)),
        "canvas_y": float(body.get("canvas_y", 0.0)),
    }


@router.get("/api/sources")
def list_sources_route(request: Request):
    return _list_sources(request.app.state.db)


@router.get("/api/sources/{source_id:int}")
def get_source_route(source_id: int, request: Request):
    row = request.app.state.db.execute(
        f"SELECT {_SOURCE_COLUMNS} FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Source niet gevonden")
    return _row_to_source(row)


@router.post("/api/sources")
async def create_source_route(request: Request):
    body = await request.json()
    fields = _validate_source_body(body)
    db = request.app.state.db
    cursor = db.execute(
        "INSERT INTO sources (name, kind, value, canvas_x, canvas_y) VALUES (?, ?, ?, ?, ?)",
        (fields["name"], fields["kind"], fields["value"], fields["canvas_x"], fields["canvas_y"]),
    )
    db.commit()
    return get_source_route(cursor.lastrowid, request)


@router.put("/api/sources/{source_id:int}")
async def update_source_route(source_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM sources WHERE id = ?", (source_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Source niet gevonden")
    body = await request.json()
    fields = _validate_source_body(body)
    db.execute(
        "UPDATE sources SET name = ?, kind = ?, value = ?, canvas_x = ?, canvas_y = ? WHERE id = ?",
        (fields["name"], fields["kind"], fields["value"], fields["canvas_x"], fields["canvas_y"], source_id),
    )
    db.commit()
    return get_source_route(source_id, request)


@router.delete("/api/sources/{source_id:int}")
def delete_source_route(source_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM sources WHERE id = ?", (source_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Source niet gevonden")
    db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    db.commit()
    return {"ok": True}
```

Note: this DELETE has no "still in use" guard yet — Task 2 adds one once `players.source_id` exists to check against.

- [ ] **Step 8: Register the router in `admin/app/main.py`**

Add the import near the other router imports:

```python
from admin.app.routers import sources as sources_router
```

Add the registration near `app.include_router(outputs_router.router)`:

```python
    app.include_router(sources_router.router)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_sources.py tests/test_admin_db.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add admin/app/db.py admin/app/routers/sources.py admin/app/main.py tests/test_admin_db.py tests/test_admin_routes_sources.py
git commit -m "feat: sources-tabel + CRUD (camera stream of statische afbeelding)"
```

---

### Task 2: `scenes` → `players` (full rename) + playback-mode columns

**This is the biggest single task in the plan — read it fully before touching `db.py`.** The core hazard: several *existing, unconditional* migration statements literally say `scenes` in their SQL. Once this task renames the table, those statements must not run again against a name that no longer exists on every later restart. The fix is a table-existence guard, detailed in Step 3.

**Files:**
- Modify: `admin/app/db.py`
- Modify: `admin/app/routers/scenes.py` → rename to `admin/app/routers/players.py`
- Modify: `admin/app/routers/sources.py` (add the "still referenced by a player" delete-guard)
- Modify: `admin/app/routers/preview.py` (only the import line — `_resolve_output_id` now lives in `players.py`; the rendering logic itself is rewritten in Task 8)
- Modify: `admin/app/main.py` (router import/registration rename)
- Modify: `admin/app/graph_publish.py` (import path only — `_list_scenes` becomes `_list_players`, imported from `players.py`; payload key rename happens in Task 7)
- Modify: `tests/test_admin_routes_scenes.py` → rename to `tests/test_admin_routes_players.py`
- Modify: `tests/test_admin_routes_sources.py` (append the new guard test)
- Modify: `tests/test_admin_mqtt_bridge.py` (path rename only, line ~212)
- Modify: `tests/test_admin_routes_triggers.py` (path renames only, `/api/scenes`→`/api/players`, `_SCENE_PAYLOAD`→`_PLAYER_PAYLOAD` with new fields — this task only needs the payload's shape to stay parseable; Task 4 will separately update trigger-specific assertions)
- Modify: `tests/test_admin_routes_outputs.py` (path rename only, line ~101)
- Test: `tests/test_admin_db.py` (append)

**Interfaces:**
- Consumes: `sources` table + `/api/sources` from Task 1.
- Produces: `players` table (all prior `scenes` columns, minus `output_id` from the API surface — the DB column stays but is no longer read/written by the route layer — plus `source_id INTEGER`, `playback_mode TEXT NOT NULL DEFAULT 'once'`, `repeat_while_ha_entity_id TEXT`). Routes: `GET/POST /api/players`, `GET/PUT/DELETE /api/players/{player_id:int}`, `PUT /api/players/{player_id:int}/position`, `_resolve_source_id(db, source_id)` helper (mirrors the existing `_resolve_output_id` pattern), `_list_players(db)` (renamed from `_list_scenes`).

- [ ] **Step 1: Write the failing migration tests**

Append to `tests/test_admin_db.py` (uses the existing `_LEGACY_SCENES_DDL` constant already at the top of the file):

```python
def test_players_table_replaces_scenes(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "players" in tables
    assert "scenes" not in tables


def test_existing_scenes_data_survives_rename_to_players(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code -- de rename zelf

    row = conn.execute("SELECT name FROM players WHERE id = 1").fetchone()
    assert row == ("Basis",)


def test_players_get_new_playback_columns_with_sensible_defaults(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO players (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.commit()

    row = conn.execute(
        "SELECT playback_mode, repeat_while_ha_entity_id FROM players WHERE id = 1"
    ).fetchone()
    assert row == ("once", None)


def test_existing_players_get_source_id_from_migration(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)

    default_source_id = conn.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
    player_source_id = conn.execute("SELECT source_id FROM players WHERE id = 1").fetchone()[0]
    assert player_source_id == default_source_id


def test_players_rename_is_idempotent_across_restarts(tmp_path):
    """Regressie voor de kern-hazard van deze taak: init_db() draait
    meerdere keren na de rename en mag niet crashen op 'no such table:
    scenes' (de oude, ongeconditioneerde migraties die dat literal nog
    noemen)."""
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)  # derde run -- als een van de oude scenes-migraties
    # niet correct geguard is, gooit een van deze drie calls al een
    # sqlite3.OperationalError

    count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    assert count == 0  # geen crash, en (verse install) nog geen players
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k player -v`
Expected: FAIL — no `players` table exists yet.

- [ ] **Step 3: Fix the pre-existing unconditional `scenes`-referencing migrations**

This is the hazard described above. In `admin/app/db.py`, three spots currently reference the literal table name `scenes` **unconditionally** (no version gate, no existence check) — they must be guarded so they become no-ops once `scenes` has been renamed away:

**3a.** The five standalone `_ensure_column(conn, "scenes", ...)` calls in `init_db()`. Wrap them in an existence check. Replace:

```python
    _ensure_column(conn, "scenes", "is_root", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "scenes", "canvas_x", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "scenes", "canvas_y", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "scenes", "output_id", "INTEGER")
    _ensure_column(conn, "scenes", "color", "TEXT")
```

with:

```python
    _tables_before_players_rename = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scenes" in _tables_before_players_rename:
        _ensure_column(conn, "scenes", "is_root", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "scenes", "canvas_x", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "scenes", "canvas_y", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "scenes", "output_id", "INTEGER")
        _ensure_column(conn, "scenes", "color", "TEXT")
```

**3b.** `_migrate_mirror_config_to_scenes`'s early-return check reads `SELECT COUNT(*) FROM scenes` directly — add a table-existence guard at the very top of the function, before that line:

```python
def _migrate_mirror_config_to_scenes(conn):
    """..." (docstring unchanged) ..."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scenes" not in tables:
        return  # al hernoemd naar players in een vorige run -- niets te doen
    existing = conn.execute("SELECT COUNT(*) FROM scenes").fetchone()[0]
    if existing > 0:
        return
    # ... rest of function body unchanged ...
```

**3c.** `_migrate_outputs`'s final line runs unconditionally every call: `conn.execute("UPDATE scenes SET output_id = ? WHERE output_id IS NULL", (output_id,))`. Guard it the same way — replace that one line with:

```python
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scenes" in tables:
        conn.execute("UPDATE scenes SET output_id = ? WHERE output_id IS NULL", (output_id,))
```

(`_migrate_scenes_to_graph` and `_migrate_scene_edges_to_triggers` are already safe — both are gated by their own `PRAGMA user_version` checks at the top and return immediately once past version 1/2 respectively, so they never reach their `scenes`-referencing lines on a later run. No change needed to either.)

- [ ] **Step 4: Add the rename migration**

Add the call `_migrate_scenes_to_players(conn)` as the **last** line before `conn.commit()` in `init_db()` (it must run after every other scenes-touching migration in the same call, since they all still expect the table to be named `scenes` while they run):

```python
    _migrate_scenes_to_players(conn)
    conn.commit()
    return conn
```

Add the function itself:

```python
def _migrate_scenes_to_players(conn):
    """Hernoemt scenes naar players en voegt de nieuwe afspeel-kolommen toe
    (source_id, playback_mode, repeat_while_ha_entity_id). Moet de LAATSTE
    scenes-migratie in init_db() zijn -- elke migratie ervóór verwacht de
    tabel nog 'scenes' te heten. Idempotent via PRAGMA user_version (>=3
    betekent 'deze migratie is al gedaan', zelfde patroon als de
    scene_edges->triggers-migratie op versie 2)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 3:
        return
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scenes" in tables:
        conn.execute("ALTER TABLE scenes RENAME TO players")
    else:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS players (
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
                trigger_until TEXT,
                is_root INTEGER NOT NULL DEFAULT 0,
                canvas_x REAL NOT NULL DEFAULT 0,
                canvas_y REAL NOT NULL DEFAULT 0,
                output_id INTEGER,
                color TEXT
            )"""
        )
    _ensure_column(conn, "players", "source_id", "INTEGER")
    _ensure_column(conn, "players", "playback_mode", "TEXT NOT NULL DEFAULT 'once'")
    _ensure_column(conn, "players", "repeat_while_ha_entity_id", "TEXT")
    default_source = conn.execute("SELECT id FROM sources ORDER BY id LIMIT 1").fetchone()
    if default_source is not None:
        conn.execute("UPDATE players SET source_id = ? WHERE source_id IS NULL", (default_source[0],))
    conn.execute("PRAGMA user_version = 3")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k player -v`
Expected: PASS.

- [ ] **Step 6: Rename and update the router**

`git mv admin/app/routers/scenes.py admin/app/routers/players.py`, then edit the new file:

- Rename every SQL string's `scenes` → `players` (table name only — `scene_id` route params become `player_id`, but see below for column-name specifics).
- `_SCENE_COLUMNS`/`_row_to_scene`/`_DEFAULT_SCENE`/`_list_scenes` → `_PLAYER_COLUMNS`/`_row_to_player`/`_DEFAULT_PLAYER`/`_list_players`. Drop `output_id` from `_DEFAULT_PLAYER` and from `_PLAYER_COLUMNS`/`_row_to_player`'s column list entirely (the DB column stays; the API just stops reading/writing it). Add `source_id`, `playback_mode`, `repeat_while_ha_entity_id` to all three, in that column order at the end.
- Rename `_resolve_output_id` → `_resolve_source_id`, changing its target table from `outputs` to `sources`:

```python
def _resolve_source_id(db, source_id):
    """Geeft source_id terug als 'ie gezet is, anders de eerste/enige
    source. 400 als er helemaal geen source bestaat (kan alleen als de
    Taak-1-migratie nooit gedraaid heeft, defensief)."""
    if source_id is not None:
        return source_id
    default_source = db.execute("SELECT id FROM sources ORDER BY id LIMIT 1").fetchone()
    if default_source is None:
        raise HTTPException(status_code=400, detail="Geen source beschikbaar, maak er eerst één aan")
    return default_source[0]
```

- Every route path `/api/scenes...` → `/api/players...`; every `scene_id` param → `player_id`; every `get_scene_route`/`create_scene_route`/etc. function name → `get_player_route`/`create_player_route`/etc.
- In `create_player_route` and `update_player_route`, replace the `fields["output_id"] = _resolve_output_id(db, fields["output_id"])` line with `fields["source_id"] = _resolve_source_id(db, fields["source_id"])`, and update the INSERT/UPDATE column lists and value tuples to match (drop `output_id`, add `source_id, playback_mode, repeat_while_ha_entity_id` — `playback_mode` defaults to `"once"` via `_DEFAULT_PLAYER`, `repeat_while_ha_entity_id` defaults to `None`, neither needs validation at the route layer per the spec).
- `delete_player_route` stays functionally the same for this task (still cleans up `triggers` by the OLD column names `from_scene_id`/`to_scene_id` — Task 4 updates this once those columns are renamed). Just rename `scenes`→`players` in its own DELETE statement.
- `preview_scene_route` at the bottom: leave its route path and `{scene_id}` (bare, untyped — per Global Constraints, this pre-existing pattern is not in scope to fix) exactly as-is; only update its internal reference from `scenes` table if any (it has none — it just publishes to MQTT). No functional change needed here in this task.

- [ ] **Step 7: Rename the test file and update every payload**

`git mv tests/test_admin_routes_scenes.py tests/test_admin_routes_players.py`, then:

- Every `/api/scenes` path → `/api/players`.
- `_SCENE_PAYLOAD` → `_PLAYER_PAYLOAD`; replace its `"output_id": None` key with `"source_id": None, "playback_mode": "once", "repeat_while_ha_entity_id": None`.
- Every reference to `"scene"`/`"Scene"` in test names/comments can stay if renaming would be pure churn — but update `test_create_scene_without_output_id_uses_the_default_output` and `test_create_scene_with_explicit_output_id` (and their bodies) to instead assert on `source_id`/`/api/sources` the same way the existing test asserts on `output_id`/`/api/outputs` — copy the existing test shape, substitute source for output.
- `test_published_graph_includes_output_id`: keep as-is for now (still asserts `graph["output_id"]` — Task 7 rewrites `graph_publish.py`'s payload shape; this specific assertion gets updated there, not here). All other tests in this file should pass once the route/payload renames above are applied 1:1.

- [ ] **Step 8: Mechanical path-only renames in the other three test files**

In `tests/test_admin_mqtt_bridge.py` line ~212: `/api/scenes` → `/api/players`, and its `scene_payload` variable's `output_id` key → `source_id` (value `None` is fine, matches the new default-resolution behavior).

In `tests/test_admin_routes_triggers.py`: every `/api/scenes` → `/api/players`; `_SCENE_PAYLOAD`'s `"output_id": None` → `"source_id": None, "playback_mode": "once", "repeat_while_ha_entity_id": None` (same substitution as Step 7). Do not touch the trigger-specific assertions (`from_scene_id`/`to_scene_id` field names) — Task 4 handles those.

In `tests/test_admin_routes_outputs.py` line ~101: `/api/scenes` → `/api/players`, and that payload's `"output_id": default_output["id"], "color": None` → `"source_id": None, "playback_mode": "once", "repeat_while_ha_entity_id": None, "color": None` (this particular test — `test_delete_output_rejected_when_it_has_a_scene` — currently proves an output can't be deleted while a scene references it; once Task 6 lands, this guard moves to `output_connections`. For *this* task, just keep the test passing by fixing the payload shape; do not change its assertion.).

- [ ] **Step 9: Fix the two files that import from the old module path**

`admin/app/graph_publish.py`: change `from admin.app.routers.scenes import _list_scenes` to `from admin.app.routers.players import _list_players`, and the call site `scenes = _list_scenes(db)` to `players = _list_players(db)` — but leave the rest of the function (variable name `scenes` used in the payload dict, `root_scene_id` key, etc.) untouched for now; Task 7 rewrites this function's payload shape fully. For this task, only fix the import and immediate call so the module doesn't crash — rename the local variable if needed to keep the function internally consistent (`scenes` → `players_list`, then use `players_list` in place of `scenes` for the rest of the function body as it exists today).

`admin/app/routers/preview.py`: change `from admin.app.routers.scenes import _resolve_output_id` to `from admin.app.routers.players import _resolve_source_id`. Do not change anything else in this file yet — it will still call `_resolve_output_id(db, draft.get("output_id"))` internally, which no longer exists. Replace that one call with `_resolve_source_id(db, draft.get("source_id"))` and update the two lines below it that queried `outputs.camera_source` by that id to instead query `sources.value`/`sources.kind` (minimal fix to keep this file important-but-not-fully-rewritten; Task 8 does the real rendering-logic rewrite):

```python
    source_id = _resolve_source_id(db, draft.get("source_id"))
    source_row = db.execute(
        "SELECT value FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if source_row is None:
        raise HTTPException(status_code=400, detail="source_id verwijst naar een onbestaande source")
    camera_source = source_row[0]
```

(This makes `tests/test_admin_routes_preview.py`'s existing `output_id`-keyed payloads fail in this task — that's expected and fine; Task 8 rewrites both the route and its tests together. Do not attempt to fix `test_admin_routes_preview.py` in this task.)

- [ ] **Step 10: Update `admin/app/main.py`**

```python
from admin.app.routers import players as players_router
```
(replacing `from admin.app.routers import scenes as scenes_router`), and
```python
    app.include_router(players_router.router)
```
(replacing the `scenes_router` registration).

- [ ] **Step 11: Add the sources delete-guard**

In `admin/app/routers/sources.py`'s `delete_source_route`, add the same "still referenced" guard `outputs.py` already uses, right after the existing-check:

```python
    has_players = db.execute("SELECT 1 FROM players WHERE source_id = ? LIMIT 1", (source_id,)).fetchone()
    if has_players is not None:
        raise HTTPException(status_code=400, detail="Source heeft nog players -- verplaats of verwijder die eerst")
```

Append to `tests/test_admin_routes_sources.py`:

```python
def test_delete_source_rejected_when_it_has_a_player(tmp_path):
    client, bridge = _client(tmp_path)
    default_source = client.get("/api/sources").json()[0]
    client.post("/api/players", json={
        "name": "X", "enabled": True, "source_mode": "camera", "effect": "xray",
        "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
        "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
        "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0, "color": None,
        "source_id": default_source["id"], "playback_mode": "once", "repeat_while_ha_entity_id": None,
    })

    response = client.delete(f"/api/sources/{default_source['id']}")

    assert response.status_code == 400
```

- [ ] **Step 12: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS across the board. `tests/test_admin_routes_preview.py` failures are expected here (see Step 9) and get fixed in Task 8 — confirm every *other* file passes, and that `test_admin_routes_preview.py`'s failures are exactly the `output_id`-shaped ones, not an import crash.

- [ ] **Step 13: Commit**

```bash
git add admin/app/db.py admin/app/routers/players.py admin/app/routers/sources.py admin/app/routers/preview.py admin/app/graph_publish.py admin/app/main.py tests/test_admin_db.py tests/test_admin_routes_players.py tests/test_admin_routes_sources.py tests/test_admin_mqtt_bridge.py tests/test_admin_routes_triggers.py tests/test_admin_routes_outputs.py
git rm admin/app/routers/scenes.py tests/test_admin_routes_scenes.py
git commit -m "feat: scenes wordt players, met afspeel-instellingen (source_id/playback_mode)"
```

---

### Task 3: `player_branches` — the named, draggable outgoing dots

**Files:**
- Modify: `admin/app/db.py`
- Modify: `admin/app/routers/players.py` (sub-routes + auto-create-on-create + delete cleanup)
- Test: `tests/test_admin_db.py` (append)
- Test: `tests/test_admin_routes_players.py` (append)

**Interfaces:**
- Consumes: `players` table from Task 2.
- Produces: `player_branches` table (`id, player_id, name`). Sub-routes on the players router: `GET /api/players/{player_id:int}/branches`, `POST /api/players/{player_id:int}/branches` (body `{"name": str}`), `PUT /api/branches/{branch_id:int}` (body `{"name": str}`), `DELETE /api/branches/{branch_id:int}`. Every newly-created player automatically gets exactly one branch named `"Uitgang 1"`.

- [ ] **Step 1: Write the failing migration tests**

Append to `tests/test_admin_db.py`:

```python
def test_player_branches_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "player_branches" in tables


def test_existing_players_each_get_one_default_branch(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(2, 'B', 1, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)

    rows = conn.execute("SELECT player_id, name FROM player_branches ORDER BY player_id").fetchall()
    assert rows == [(1, "Uitgang 1"), (2, "Uitgang 1")]


def test_player_branches_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    count = conn.execute("SELECT COUNT(*) FROM player_branches").fetchone()[0]
    assert count == 0  # verse install, geen players -> geen branches
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k branch -v`
Expected: FAIL — no `player_branches` table.

- [ ] **Step 3: Add the table and migration**

Add the `CREATE TABLE` in `init_db()`, grouped with the other new-table blocks:

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS player_branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            name TEXT NOT NULL DEFAULT 'Uitgang 1'
        )"""
    )
```

Add the call `_migrate_player_branches(conn)` in `init_db()` directly after `_migrate_scenes_to_players(conn)` (it depends on `players` already existing under its final name), still before `conn.commit()`.

Add the function:

```python
def _migrate_player_branches(conn):
    """Geeft elke bestaande player die nog geen enkele branch heeft er
    precies één ('Uitgang 1'). Idempotent via PRAGMA user_version (>=4)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 4:
        return
    rows = conn.execute(
        "SELECT p.id FROM players p WHERE NOT EXISTS "
        "(SELECT 1 FROM player_branches b WHERE b.player_id = p.id)"
    ).fetchall()
    for (player_id,) in rows:
        conn.execute("INSERT INTO player_branches (player_id, name) VALUES (?, 'Uitgang 1')", (player_id,))
    conn.execute("PRAGMA user_version = 4")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k branch -v`
Expected: PASS.

- [ ] **Step 5: Write the failing route tests**

Append to `tests/test_admin_routes_players.py`:

```python
def test_new_player_gets_one_default_branch(tmp_path):
    client, bridge = _client(tmp_path)

    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    branches = client.get(f"/api/players/{created['id']}/branches").json()
    assert len(branches) == 1
    assert branches[0]["name"] == "Uitgang 1"


def test_create_branch_on_player(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    response = client.post(f"/api/players/{player['id']}/branches", json={"name": "Extra pad"})

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Extra pad"
    assert created["player_id"] == player["id"]
    branches = client.get(f"/api/players/{player['id']}/branches").json()
    assert len(branches) == 2


def test_create_branch_requires_existing_player(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/players/999/branches", json={"name": "X"})

    assert response.status_code == 404


def test_rename_branch(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]

    response = client.put(f"/api/branches/{branch['id']}", json={"name": "Hernoemd"})

    assert response.status_code == 200
    assert response.json()["name"] == "Hernoemd"


def test_delete_branch(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    extra = client.post(f"/api/players/{player['id']}/branches", json={"name": "Extra"}).json()

    response = client.delete(f"/api/branches/{extra['id']}")

    assert response.status_code == 200
    branches = client.get(f"/api/players/{player['id']}/branches").json()
    assert len(branches) == 1


def test_delete_branch_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/branches/999")

    assert response.status_code == 404


def test_deleting_player_removes_its_branches(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    client.delete(f"/api/players/{player['id']}")

    response = client.get(f"/api/players/{player['id']}/branches")
    assert response.status_code == 404
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py -k branch -v`
Expected: FAIL — no branch routes registered.

- [ ] **Step 7: Add the sub-routes to `admin/app/routers/players.py`**

Add near the top, alongside the other column/default constants:

```python
_BRANCH_COLUMNS = "id, player_id, name"


def _row_to_branch(row):
    return {"id": row[0], "player_id": row[1], "name": row[2]}
```

Add the routes (anywhere after the existing player CRUD routes, before `preview_scene_route`):

```python
@router.get("/api/players/{player_id:int}/branches")
def list_player_branches_route(player_id: int, request: Request):
    db = request.app.state.db
    exists = db.execute("SELECT id FROM players WHERE id = ?", (player_id,)).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, detail="Player niet gevonden")
    rows = db.execute(
        f"SELECT {_BRANCH_COLUMNS} FROM player_branches WHERE player_id = ? ORDER BY id", (player_id,)
    ).fetchall()
    return [_row_to_branch(r) for r in rows]


@router.post("/api/players/{player_id:int}/branches")
async def create_player_branch_route(player_id: int, request: Request):
    db = request.app.state.db
    exists = db.execute("SELECT id FROM players WHERE id = ?", (player_id,)).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, detail="Player niet gevonden")
    body = await request.json()
    name = str(body.get("name", "")).strip() or "Nieuwe aftakking"
    cursor = db.execute("INSERT INTO player_branches (player_id, name) VALUES (?, ?)", (player_id, name))
    db.commit()
    row = db.execute(f"SELECT {_BRANCH_COLUMNS} FROM player_branches WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_branch(row)


@router.put("/api/branches/{branch_id:int}")
async def update_player_branch_route(branch_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM player_branches WHERE id = ?", (branch_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Aftakking niet gevonden")
    body = await request.json()
    name = str(body.get("name", "")).strip() or "Aftakking"
    db.execute("UPDATE player_branches SET name = ? WHERE id = ?", (name, branch_id))
    db.commit()
    row = db.execute(f"SELECT {_BRANCH_COLUMNS} FROM player_branches WHERE id = ?", (branch_id,)).fetchone()
    return _row_to_branch(row)


@router.delete("/api/branches/{branch_id:int}")
def delete_player_branch_route(branch_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM player_branches WHERE id = ?", (branch_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Aftakking niet gevonden")
    return {"ok": True}
```

Note: `delete_player_branch_route` has no "still referenced" guard yet — Task 4 (triggers) and Task 6 (output_connections) each add their own once those tables exist.

- [ ] **Step 8: Auto-create the default branch on player creation**

In `create_player_route`, right after `db.commit()` and before `publish_graph(db, request.app.state.bridge)`, insert:

```python
    db.execute("INSERT INTO player_branches (player_id, name) VALUES (?, 'Uitgang 1')", (cursor.lastrowid,))
    db.commit()
```

- [ ] **Step 9: Clean up branches on player deletion**

In `delete_player_route`, add this line before the existing `triggers`-cleanup lines (order doesn't matter between them, but branches must go before the player row itself, which already happens last):

```python
    db.execute("DELETE FROM player_branches WHERE player_id = ?", (player_id,))
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py tests/test_admin_db.py -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add admin/app/db.py admin/app/routers/players.py tests/test_admin_db.py tests/test_admin_routes_players.py
git commit -m "feat: player_branches -- naambare, sleepbare aftakkingen op een player"
```

---

### Task 4: Triggers originate from a branch, not a player directly

**Files:**
- Modify: `admin/app/db.py`
- Modify: `admin/app/routers/triggers.py`
- Modify: `admin/app/routers/players.py` (`delete_player_route` trigger-cleanup + branch-delete guard)
- Modify: `mirror_node/scenes.py` (field names read from each trigger dict — done here since it's a one-line dict-key change, not runtime-logic; the bigger `mirror_node` rewrite is Tasks 9-10)
- Test: `tests/test_admin_db.py` (append)
- Test: `tests/test_admin_routes_triggers.py` (update field names)
- Test: `tests/test_admin_routes_players.py` (update the two delete-cascade tests)
- Test: `tests/test_scene_engine.py` (update trigger dict keys used in fixtures)

**Interfaces:**
- Consumes: `player_branches` from Task 3, `players` from Task 2.
- Produces: `triggers` table with `from_branch_id` (was `from_scene_id`) and `to_player_id` (was `to_scene_id`). `create_trigger_route` now requires `from_branch_id` (validated against `player_branches`); `update_trigger_route`'s `to_player_id` is validated against `players`.

- [ ] **Step 1: Write the failing migration tests**

Append to `tests/test_admin_db.py`:

```python
def test_triggers_columns_renamed_to_branch_and_player(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(triggers)")}

    assert "from_branch_id" in cols
    assert "to_player_id" in cols
    assert "from_scene_id" not in cols
    assert "to_scene_id" not in cols


def test_existing_trigger_from_scene_id_becomes_that_players_default_branch(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(2, 'B', 1, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code

    default_branch_id = conn.execute(
        "SELECT id FROM player_branches WHERE player_id = 1"
    ).fetchone()[0]
    row = conn.execute("SELECT from_branch_id, to_player_id FROM triggers").fetchone()
    assert row == (default_branch_id, 2)


def test_triggers_branch_rename_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(triggers)")}
    assert "from_branch_id" in cols
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k "branch_and_player or default_branch or branch_rename" -v`
Expected: FAIL — columns still named `from_scene_id`/`to_scene_id`.

- [ ] **Step 3: Add the migration**

Add the call `_migrate_triggers_to_branches(conn)` in `init_db()` directly after `_migrate_player_branches(conn)`, before `conn.commit()`.

Add the function:

```python
def _migrate_triggers_to_branches(conn):
    """Hernoemt triggers.from_scene_id/to_scene_id naar from_branch_id/
    to_player_id, en vult from_branch_id met de (op dit punt in de
    migratieketen gegarandeerd bestaande, precies-één) default-branch van
    de player die de kolom vroeger rechtstreeks aanduidde. Idempotent via
    PRAGMA user_version (>=5)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 5:
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(triggers)")}
    if "from_scene_id" in cols:
        conn.execute("ALTER TABLE triggers RENAME COLUMN from_scene_id TO from_branch_id")
        conn.execute("ALTER TABLE triggers RENAME COLUMN to_scene_id TO to_player_id")
        conn.execute(
            "UPDATE triggers SET from_branch_id = ("
            "  SELECT b.id FROM player_branches b WHERE b.player_id = triggers.from_branch_id LIMIT 1"
            ")"
        )
    conn.execute("PRAGMA user_version = 5")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -v`
Expected: PASS (full file, to also confirm nothing earlier regressed).

- [ ] **Step 5: Update `admin/app/routers/triggers.py`**

- `_TRIGGER_COLUMNS`: `from_scene_id, to_scene_id` → `from_branch_id, to_player_id` (keep the rest of the column list unchanged).
- `_row_to_trigger`: keys `from_scene_id`/`to_scene_id` → `from_branch_id`/`to_player_id`.
- `_DEFAULT_TRIGGER`: key `to_scene_id` → `to_player_id`.
- `_list_triggers`: `ORDER BY from_scene_id, priority` → `ORDER BY from_branch_id, priority`.
- `create_trigger_route`: rename `from_scene_id` → `from_branch_id` throughout; change the existence check from `SELECT id FROM scenes WHERE id = ?` to `SELECT id FROM player_branches WHERE id = ?`, and its error message from `"from_scene_id is verplicht"`/`"from_scene_id verwijst naar een onbestaande scene"` to `"from_branch_id is verplicht"`/`"from_branch_id verwijst naar een onbestaande aftakking"`.
- `update_trigger_route`: rename `to_scene_id` → `to_player_id` throughout; change its existence check from `SELECT id FROM scenes WHERE id = ?` to `SELECT id FROM players WHERE id = ?`, and its error message from `"to_scene_id verwijst naar een onbestaande scene"` to `"to_player_id verwijst naar een onbestaande player"`.
- `delete_trigger_route`: no column references, no change needed.

- [ ] **Step 6: Update `delete_player_route` in `admin/app/routers/players.py`**

Replace the existing trigger-cleanup lines:

```python
    db.execute("DELETE FROM triggers WHERE from_scene_id = ?", (scene_id,))
    db.execute(
        "UPDATE triggers SET to_scene_id = NULL, kind = NULL, "
        "schedule_from = NULL, schedule_until = NULL, ha_entity_id = NULL WHERE to_scene_id = ?",
        (scene_id,),
    )
```

with:

```python
    db.execute(
        "DELETE FROM triggers WHERE from_branch_id IN "
        "(SELECT id FROM player_branches WHERE player_id = ?)",
        (player_id,),
    )
    db.execute(
        "UPDATE triggers SET to_player_id = NULL, kind = NULL, "
        "schedule_from = NULL, schedule_until = NULL, ha_entity_id = NULL WHERE to_player_id = ?",
        (player_id,),
    )
```

(Keep this ordered before the existing `db.execute("DELETE FROM player_branches WHERE player_id = ?", ...)` line from Task 3 — the trigger cleanup above still needs to look up the player's branches via `player_branches` before they're deleted.)

- [ ] **Step 7: Add the branch-delete guard**

In `delete_player_branch_route` (added in Task 3), add a "still referenced" guard before the DELETE, mirroring the outputs/sources pattern:

```python
@router.delete("/api/branches/{branch_id:int}")
def delete_player_branch_route(branch_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM player_branches WHERE id = ?", (branch_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Aftakking niet gevonden")
    has_trigger = db.execute("SELECT 1 FROM triggers WHERE from_branch_id = ? LIMIT 1", (branch_id,)).fetchone()
    if has_trigger is not None:
        raise HTTPException(status_code=400, detail="Aftakking heeft nog een trigger -- verwijder die eerst")
    db.execute("DELETE FROM player_branches WHERE id = ?", (branch_id,))
    db.commit()
    return {"ok": True}
```

(This replaces the whole function body from Task 3, not just an addition — the unconditional `cursor = db.execute("DELETE ...")` pattern is gone, replaced by an explicit existence+guard+delete sequence. Task 6 adds a second guard clause here for `output_connections`.)

Append to `tests/test_admin_routes_players.py`:

```python
def test_delete_branch_rejected_when_it_has_a_trigger(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]
    client.post("/api/triggers", json={"from_branch_id": branch["id"]})

    response = client.delete(f"/api/branches/{branch['id']}")

    assert response.status_code == 400
```

- [ ] **Step 8: Update `tests/test_admin_routes_triggers.py`**

Every `from_scene_id`/`to_scene_id` key in every payload and assertion → `from_branch_id`/`to_player_id`. `_two_scenes(client)` helper: change its `from_scene_id` construction to instead fetch each created player's default branch (`client.get(f"/api/players/{a['id']}/branches").json()[0]["id"]`) — introduce a small `_branch_of(client, player)` helper to keep the test bodies readable:

```python
def _branch_of(client, player):
    return client.get(f"/api/players/{player['id']}/branches").json()[0]["id"]
```

Update every test body that currently does `"from_scene_id": a["id"]` to instead do `"from_branch_id": _branch_of(client, a)`, and every `"to_scene_id": b["id"]` to `"to_player_id": b["id"]`. Update `test_create_trigger_requires_valid_from_scene_id` → rename to `test_create_trigger_requires_valid_from_branch_id`, body unchanged in shape (still posts a nonexistent id, still expects 400). Update `test_update_trigger_rejects_unknown_to_scene_id` similarly (rename to `..._to_player_id`, same shape).

- [ ] **Step 9: Update `mirror_node/scenes.py`'s dict-key reads**

`SceneGraph.set_graph`: `t["from_scene_id"]` → `t["from_branch_id"]`, `t.get("to_scene_id")` → `t.get("to_player_id")`. `_trigger_matches` and the rest of the file don't reference these keys directly — no other change needed here. (This file's bigger playback-mode-gate rewrite is Task 9; this step is purely the mechanical key rename so the existing trigger-matching logic keeps working against the new payload shape once Task 7/10 start sending it.)

Update `tests/test_scene_engine.py`: every trigger fixture dict's `"from_scene_id"`/`"to_scene_id"` key → `"from_branch_id"`/`"to_player_id"`.

- [ ] **Step 10: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, except `tests/test_admin_routes_preview.py` (still pending Task 8 — confirm it's still failing only on the `output_id`-shaped payloads, nothing new).

- [ ] **Step 11: Commit**

```bash
git add admin/app/db.py admin/app/routers/triggers.py admin/app/routers/players.py mirror_node/scenes.py tests/test_admin_db.py tests/test_admin_routes_triggers.py tests/test_admin_routes_players.py tests/test_scene_engine.py
git commit -m "feat: triggers ontspringen aan een branch i.p.v. een player direct"
```

---

### Task 5: Outputs get a canvas position (every output is also its own graph node)

**Files:**
- Modify: `admin/app/db.py`
- Modify: `admin/app/routers/outputs.py`
- Test: `tests/test_admin_db.py` (append)
- Test: `tests/test_admin_routes_outputs.py` (append)

**Interfaces:**
- Consumes: `outputs` table (already exists).
- Produces: `outputs.canvas_x`/`outputs.canvas_y` columns, included in the CRUD contract (`_OUTPUT_COLUMNS`/`_row_to_output`, request bodies).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_db.py`:

```python
def test_outputs_get_canvas_position_columns(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(outputs)")}

    assert "canvas_x" in cols
    assert "canvas_y" in cols


def test_migrated_output_gets_a_visible_canvas_position(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    row = conn.execute("SELECT canvas_x, canvas_y FROM outputs LIMIT 1").fetchone()
    assert row == (300.0, 0.0)


def test_output_canvas_position_seed_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    output_id = conn.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]
    conn.execute("UPDATE outputs SET canvas_x = 999.0 WHERE id = ?", (output_id,))
    conn.commit()
    conn.close()

    conn2 = init_db(path)  # herstart -- mag de handmatig versleepte positie niet resetten

    row = conn2.execute("SELECT canvas_x FROM outputs WHERE id = ?", (output_id,)).fetchone()
    assert row == (999.0,)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k canvas_position -v`
Expected: FAIL — no such columns.

- [ ] **Step 3: Add the columns and one-time position seed**

Add near the other `_ensure_column` calls for `outputs`-adjacent additive columns (anywhere in `init_db()` before `conn.commit()` is fine — these are purely additive, unlike the renames above):

```python
    _ensure_column(conn, "outputs", "canvas_x", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "outputs", "canvas_y", "REAL NOT NULL DEFAULT 0")
```

Add the call `_migrate_output_canvas_position(conn)` directly after those two lines (or anywhere before `conn.commit()` — this one has its own PRAGMA gate so ordering relative to the other migrations doesn't matter, as long as it's after the two `_ensure_column` calls above so the columns exist when it runs).

Add the function:

```python
def _migrate_output_canvas_position(conn):
    """Zet éénmalig een zichtbare canvas-positie op elke output die er nog
    geen heeft (rechts naast waar de players staan) -- zonder dit blijft
    een gemigreerde output op (0, 0) staan, precies bovenop de eerste
    player. PRAGMA-gated (>=6) zodat een handmatig versleepte positie
    nooit teruggezet wordt op een latere restart."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 6:
        return
    conn.execute("UPDATE outputs SET canvas_x = 300.0 WHERE canvas_x = 0 AND canvas_y = 0")
    conn.execute("PRAGMA user_version = 6")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -v`
Expected: PASS (full file).

- [ ] **Step 5: Write the failing route tests**

Append to `tests/test_admin_routes_outputs.py`:

```python
def test_output_canvas_position_round_trips(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/outputs", json={
        "name": "A", "camera_source": "", "canvas_x": 12.5, "canvas_y": -3.0,
    }).json()

    assert created["canvas_x"] == 12.5
    assert created["canvas_y"] == -3.0
    fetched = client.get(f"/api/outputs/{created['id']}").json()
    assert fetched["canvas_x"] == 12.5
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_outputs.py -k canvas_position -v`
Expected: FAIL — `created["canvas_x"]` is a `KeyError`/`None`, route doesn't accept or return it yet.

- [ ] **Step 7: Update `admin/app/routers/outputs.py`**

- `_OUTPUT_COLUMNS`: `"id, name, camera_source"` → `"id, name, camera_source, canvas_x, canvas_y"`.
- `_row_to_output`: add `"canvas_x": row[3], "canvas_y": row[4]`.
- `create_output_route`: read `canvas_x = float(body.get("canvas_x", 0.0))` and `canvas_y = float(body.get("canvas_y", 0.0))`, add them to the INSERT column list and value tuple.
- `update_output_route`: same pattern, add to the UPDATE statement and value tuple.

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_outputs.py tests/test_admin_db.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add admin/app/db.py admin/app/routers/outputs.py tests/test_admin_db.py tests/test_admin_routes_outputs.py
git commit -m "feat: outputs krijgen een canvas-positie -- elke output is nu ook zijn eigen graafknoop"
```

---

### Task 6: `output_connections` — a branch wired straight to a physical output

**Files:**
- Modify: `admin/app/db.py`
- Create: `admin/app/routers/output_connections.py`
- Modify: `admin/app/main.py` (register router)
- Modify: `admin/app/routers/outputs.py` (replace the `players`-based delete-guard with the more accurate `output_connections`-based one)
- Modify: `admin/app/routers/players.py` (`delete_player_route` output_connections-cleanup; `delete_player_branch_route` second guard clause)
- Test: `tests/test_admin_db.py` (append)
- Test: `tests/test_admin_routes_output_connections.py` (new)
- Test: `tests/test_admin_routes_outputs.py` (update the delete-guard test)
- Test: `tests/test_admin_routes_players.py` (append)

**Interfaces:**
- Consumes: `player_branches` (Task 3), `outputs` (existing).
- Produces: `output_connections` table (`id, output_id, from_branch_id`). `POST /api/output-connections` (body `{"output_id": int, "from_branch_id": int}`), `DELETE /api/output-connections/{connection_id:int}`.

- [ ] **Step 1: Write the failing migration tests**

Append to `tests/test_admin_db.py`:

```python
def test_output_connections_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "output_connections" in tables


def test_existing_players_default_branch_gets_wired_to_the_output(tmp_path):
    path = str(tmp_path / "test.db")
    raw = sqlite3.connect(path)
    raw.execute(_LEGACY_SCENES_DDL)
    raw.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, trigger_type) VALUES "
        "(1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 'always')"
    )
    raw.commit()
    raw.close()

    conn = init_db(path)  # eerste keer onder de nieuwe code

    output_id = conn.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]
    branch_id = conn.execute("SELECT id FROM player_branches WHERE player_id = 1").fetchone()[0]
    row = conn.execute("SELECT output_id, from_branch_id FROM output_connections").fetchone()
    assert row == (output_id, branch_id)


def test_output_connections_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    count = conn.execute("SELECT COUNT(*) FROM output_connections").fetchone()[0]
    assert count == 0  # verse install, geen players -> geen connections
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k output_connections -v`
Expected: FAIL — no such table.

- [ ] **Step 3: Add the table and migration**

Add the `CREATE TABLE`, grouped with the other new-table blocks:

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS output_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            output_id INTEGER NOT NULL,
            from_branch_id INTEGER NOT NULL
        )"""
    )
```

Add the call `_migrate_output_connections(conn)` in `init_db()` directly after `_migrate_triggers_to_branches(conn)`, before `conn.commit()`.

Add the function:

```python
def _migrate_output_connections(conn):
    """Koppelt elke bestaande player's default-branch rechtstreeks aan de
    (ene, bestaande) output, zodat alles na de upgrade gewoon op het
    scherm blijft verschijnen zonder dat de gebruiker de graaf opnieuw
    hoeft te bedraden. Idempotent via PRAGMA user_version (>=7)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 7:
        return
    output_row = conn.execute("SELECT id FROM outputs ORDER BY id LIMIT 1").fetchone()
    if output_row is not None:
        output_id = output_row[0]
        branch_rows = conn.execute("SELECT id FROM player_branches").fetchall()
        for (branch_id,) in branch_rows:
            conn.execute(
                "INSERT INTO output_connections (output_id, from_branch_id) VALUES (?, ?)",
                (output_id, branch_id),
            )
    conn.execute("PRAGMA user_version = 7")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -v`
Expected: PASS (full file).

- [ ] **Step 5: Write the failing route tests**

Create `tests/test_admin_routes_output_connections.py`:

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

    def publish_mirror_ha_trigger(self, entity_id):
        self.calls.append(("ha_trigger", entity_id))


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


_PLAYER_PAYLOAD = {
    "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
    "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
    "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0, "color": None,
    "source_id": None, "playback_mode": "once", "repeat_while_ha_entity_id": None,
}


def test_create_output_connection(tmp_path):
    client, bridge = _client(tmp_path)
    output = client.post("/api/outputs", json={"name": "Beamer", "camera_source": "", "canvas_x": 0, "canvas_y": 0}).json()
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]

    response = client.post("/api/output-connections", json={"output_id": output["id"], "from_branch_id": branch["id"]})

    assert response.status_code == 200
    created = response.json()
    assert created["output_id"] == output["id"]
    assert created["from_branch_id"] == branch["id"]


def test_create_output_connection_requires_existing_output(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]

    response = client.post("/api/output-connections", json={"output_id": 999, "from_branch_id": branch["id"]})

    assert response.status_code == 400


def test_create_output_connection_requires_existing_branch(tmp_path):
    client, bridge = _client(tmp_path)
    output = client.post("/api/outputs", json={"name": "Beamer", "camera_source": "", "canvas_x": 0, "canvas_y": 0}).json()

    response = client.post("/api/output-connections", json={"output_id": output["id"], "from_branch_id": 999})

    assert response.status_code == 400


def test_delete_output_connection(tmp_path):
    client, bridge = _client(tmp_path)
    output = client.post("/api/outputs", json={"name": "Beamer", "camera_source": "", "canvas_x": 0, "canvas_y": 0}).json()
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]
    connection = client.post("/api/output-connections", json={"output_id": output["id"], "from_branch_id": branch["id"]}).json()

    response = client.delete(f"/api/output-connections/{connection['id']}")

    assert response.status_code == 200


def test_delete_output_connection_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/output-connections/999")

    assert response.status_code == 404


def test_output_connection_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    assert client.post("/api/output-connections", json={"output_id": 1, "from_branch_id": 1}).status_code == 401
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_output_connections.py -v`
Expected: FAIL — 404 on every request, route not registered.

- [ ] **Step 7: Create the router**

Create `admin/app/routers/output_connections.py`:

```python
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_CONNECTION_COLUMNS = "id, output_id, from_branch_id"


def _row_to_connection(row):
    return {"id": row[0], "output_id": row[1], "from_branch_id": row[2]}


@router.post("/api/output-connections")
async def create_output_connection_route(request: Request):
    body = await request.json()
    output_id = body.get("output_id")
    from_branch_id = body.get("from_branch_id")
    db = request.app.state.db
    if db.execute("SELECT id FROM outputs WHERE id = ?", (output_id,)).fetchone() is None:
        raise HTTPException(status_code=400, detail="output_id verwijst naar een onbestaande output")
    if db.execute("SELECT id FROM player_branches WHERE id = ?", (from_branch_id,)).fetchone() is None:
        raise HTTPException(status_code=400, detail="from_branch_id verwijst naar een onbestaande aftakking")
    cursor = db.execute(
        "INSERT INTO output_connections (output_id, from_branch_id) VALUES (?, ?)",
        (output_id, from_branch_id),
    )
    db.commit()
    row = db.execute(f"SELECT {_CONNECTION_COLUMNS} FROM output_connections WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_connection(row)


@router.delete("/api/output-connections/{connection_id:int}")
def delete_output_connection_route(connection_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM output_connections WHERE id = ?", (connection_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Verbinding niet gevonden")
    return {"ok": True}
```

- [ ] **Step 8: Register the router**

In `admin/app/main.py`, add the import (`from admin.app.routers import output_connections as output_connections_router`) and registration (`app.include_router(output_connections_router.router)`) near the other routers.

- [ ] **Step 9: Replace the outputs delete-guard**

In `admin/app/routers/outputs.py`'s `delete_output_route`, replace:

```python
    has_scenes = db.execute("SELECT 1 FROM players WHERE output_id = ? LIMIT 1", (output_id,)).fetchone()
    if has_scenes is not None:
        raise HTTPException(status_code=400, detail="Output heeft nog scenes -- verplaats of verwijder die eerst")
```

with:

```python
    has_connections = db.execute(
        "SELECT 1 FROM output_connections WHERE output_id = ? LIMIT 1", (output_id,)
    ).fetchone()
    if has_connections is not None:
        raise HTTPException(status_code=400, detail="Output heeft nog verbindingen -- ontkoppel die eerst")
```

Update `tests/test_admin_routes_outputs.py`'s `test_delete_output_rejected_when_it_has_a_scene` (rename to `test_delete_output_rejected_when_it_has_a_connection`): replace its body's player-creation with an actual `output_connections` row via a branch, matching the new guard:

```python
def test_delete_output_rejected_when_it_has_a_connection(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    player = client.post("/api/players", json={
        "name": "X", "enabled": True, "source_mode": "camera", "effect": "xray",
        "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
        "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
        "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0, "color": None,
        "source_id": None, "playback_mode": "once", "repeat_while_ha_entity_id": None,
    }).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]
    client.post("/api/output-connections", json={"output_id": default_output["id"], "from_branch_id": branch["id"]})

    response = client.delete(f"/api/outputs/{default_output['id']}")

    assert response.status_code == 400
```

- [ ] **Step 10: Update `delete_player_route` and `delete_player_branch_route` cleanup**

In `admin/app/routers/players.py`'s `delete_player_route`, add before the existing `player_branches` DELETE line:

```python
    db.execute(
        "DELETE FROM output_connections WHERE from_branch_id IN "
        "(SELECT id FROM player_branches WHERE player_id = ?)",
        (player_id,),
    )
```

In `delete_player_branch_route`, add a second guard clause alongside the existing trigger one:

```python
    has_output_connection = db.execute(
        "SELECT 1 FROM output_connections WHERE from_branch_id = ? LIMIT 1", (branch_id,)
    ).fetchone()
    if has_output_connection is not None:
        raise HTTPException(status_code=400, detail="Aftakking heeft nog een output-verbinding -- verwijder die eerst")
```

Append to `tests/test_admin_routes_players.py`:

```python
def test_delete_branch_rejected_when_it_has_an_output_connection(tmp_path):
    client, bridge = _client(tmp_path)
    output = client.post("/api/outputs", json={"name": "X", "camera_source": "", "canvas_x": 0, "canvas_y": 0}).json()
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]
    client.post("/api/output-connections", json={"output_id": output["id"], "from_branch_id": branch["id"]})

    response = client.delete(f"/api/branches/{branch['id']}")

    assert response.status_code == 400
```

- [ ] **Step 11: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, except `tests/test_admin_routes_preview.py` (still pending Task 8).

- [ ] **Step 12: Commit**

```bash
git add admin/app/db.py admin/app/routers/output_connections.py admin/app/main.py admin/app/routers/outputs.py admin/app/routers/players.py tests/test_admin_db.py tests/test_admin_routes_output_connections.py tests/test_admin_routes_outputs.py tests/test_admin_routes_players.py
git commit -m "feat: output_connections -- een aftakking rechtstreeks naar een fysieke output"
```

---

### Task 7: `graph_publish.py` — new payload shape

**Files:**
- Modify: `admin/app/graph_publish.py`
- Test: `tests/test_admin_routes_players.py` (update `test_published_graph_includes_output_id` and the graph-shape assertions)
- Test: `tests/test_admin_routes_triggers.py` (update `test_every_write_publishes_full_graph_with_triggers_key`)

**Interfaces:**
- Consumes: `_list_players` (Task 2), `sources` (Task 1), `player_branches` (Task 3), `_list_triggers` (existing), `output_connections` (Task 6).
- Produces: `publish_graph(db, bridge)` publishing `{"output_id": ..., "players": [...], "sources": [...], "branches": [...], "triggers": [...], "output_connections": [...], "root_player_id": ...}`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_admin_routes_players.py`, replace `test_published_graph_includes_output_id`:

```python
def test_published_graph_has_the_full_new_shape(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    bridge.calls.clear()

    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    kind, graph = bridge.calls[-1]
    assert kind == "graph"
    assert graph["output_id"] == default_output["id"]
    assert graph["players"] == [created]
    assert graph["root_player_id"] == created["id"]
    assert {s["kind"] for s in graph["sources"]} <= {"camera_stream", "static_image"}
    branch = client.get(f"/api/players/{created['id']}/branches").json()[0]
    assert graph["branches"] == [branch]
    assert isinstance(graph["triggers"], list)
    assert isinstance(graph["output_connections"], list)
```

Also update every OTHER assertion in `tests/test_admin_routes_players.py` that currently checks `bridge.calls` for the shape `{"output_id": ..., "scenes": [...], "triggers": [...], "root_scene_id": ...}` (from Task 2's rename pass) — `test_create_scene_persists_and_publishes` → rename to `test_create_player_persists_and_publishes`, `test_update_scene_persists_and_publishes` → `test_update_player_persists_and_publishes`, `test_delete_scene_removes_and_publishes` → `test_delete_player_removes_and_publishes`. In each, replace the asserted dict shape:

```python
    assert (
        "graph",
        {
            "output_id": default_output["id"], "players": [created], "sources": graph_sources,
            "branches": graph_branches, "triggers": [], "output_connections": graph_output_connections,
            "root_player_id": created["id"],
        },
    ) in bridge.calls
```

— fetch `graph_sources = client.get("/api/sources").json()`, `graph_branches = client.get(f"/api/players/{created['id']}/branches").json()` (empty list `[]` for the delete-test, since the player and its branch are gone by the time you assert), and `graph_output_connections = client.get("/api/output-connections").json()` if such a list-route exists — **it doesn't** (Task 6 only added POST/DELETE, no GET). Add a lightweight `GET /api/output-connections` list route in this task instead of adding test-only DB access (see Step 3 below), and use it here.

In `tests/test_admin_routes_triggers.py`, update `test_every_write_publishes_full_graph_with_triggers_key`:

```python
def test_every_write_publishes_full_graph_with_triggers_key(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    client.put(f"/api/players/{a['id']}", json={**_PLAYER_PAYLOAD, "name": "A", "is_root": True})
    bridge.calls.clear()

    trigger = client.post("/api/triggers", json={
        "from_branch_id": _branch_of(client, a), "to_player_id": b["id"], "kind": "always", "priority": 0,
    }).json()

    kind, graph = bridge.calls[-1]
    assert kind == "graph"
    assert graph["triggers"] == [trigger]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py tests/test_admin_routes_triggers.py -v`
Expected: FAIL — `graph["players"]`/`graph["sources"]`/etc. `KeyError`, payload still has the old shape.

- [ ] **Step 3: Add the missing `GET /api/output-connections` list route**

In `admin/app/routers/output_connections.py`, add above the existing `POST` route:

```python
def _list_output_connections(db):
    rows = db.execute(f"SELECT {_CONNECTION_COLUMNS} FROM output_connections ORDER BY id").fetchall()
    return [_row_to_connection(r) for r in rows]


@router.get("/api/output-connections")
def list_output_connections_route(request: Request):
    return _list_output_connections(request.app.state.db)
```

- [ ] **Step 4: Rewrite `admin/app/graph_publish.py`**

```python
def publish_graph(db, bridge):
    """Publiceert de volledige graaf (players + sources + branches +
    triggers + output_connections + root + output) naar MQTT -- gedeeld
    door players.py/triggers.py/sources.py/output_connections.py, elke
    schrijvende route roept dit aan zodat opgeslagen en gepubliceerde
    graaf nooit uit elkaar kunnen lopen. Lazy imports om een cirkel met de
    routers te vermijden (die importeren dit bestand). output_id is
    voorlopig altijd de eerste/enige output -- zelfde ruling als voorheen,
    een toekomstige multi-output-uitrol geeft dit expliciet mee per
    aanroep."""
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
    output_row = db.execute("SELECT id FROM outputs ORDER BY id LIMIT 1").fetchone()
    output_id = output_row[0] if output_row else None
    bridge.publish_mirror_graph({
        "output_id": output_id,
        "players": players,
        "sources": sources,
        "branches": branches,
        "triggers": triggers,
        "output_connections": output_connections,
        "root_player_id": root_player_id,
    })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py tests/test_admin_routes_triggers.py tests/test_admin_routes_output_connections.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, except `tests/test_admin_routes_preview.py` (Task 8) and possibly `tests/test_admin_mqtt_bridge.py` if it asserts on the graph payload shape — check its output; if it does, apply the same shape update as above.

- [ ] **Step 7: Commit**

```bash
git add admin/app/graph_publish.py admin/app/routers/output_connections.py tests/test_admin_routes_players.py tests/test_admin_routes_triggers.py tests/test_admin_mqtt_bridge.py
git commit -m "feat: graph_publish stuurt de volledige nieuwe graaf-vorm (players/sources/branches/output_connections)"
```

---

### Task 8: `preview.py` — render from a source, not an output

**Files:**
- Modify: `admin/app/routers/preview.py`
- Modify: `admin/frontend/src/components/PreviewPanel.tsx` (URL only — done here since it's a one-line same-commit change; the rest of `PreviewPanel.tsx` is untouched until Task 17)
- Test: `tests/test_admin_routes_preview.py` (rewrite)

**Interfaces:**
- Consumes: `sources` (Task 1), `_resolve_source_id` (Task 2).
- Produces: `POST /api/players/preview-frame` (renamed from `/api/scenes/preview-frame`), rendering from the draft's `source_id` (camera_stream: unchanged `open_camera`/`cap.read()` path; static_image: load the image file once from the media directory, no camera call).

- [ ] **Step 1: Read the current test file to preserve its fixtures**

Read `tests/test_admin_routes_preview.py` in full before editing — it has an existing `_client`/`_DRAFT` fixture shape this task reuses.

- [ ] **Step 2: Rewrite the failing tests**

Replace every `output_id`-keyed payload/assertion in `tests/test_admin_routes_preview.py` with `source_id`, and every `/api/scenes/preview-frame` path with `/api/players/preview-frame`. Where the existing file creates an output and asserts against `default_output["id"]`, change it to fetch/create a source instead (`client.get("/api/sources").json()[0]` for the migrated default). Add one new test for the static-image path:

```python
def test_preview_frame_from_static_image_source(tmp_path, monkeypatch):
    client, bridge = _client(tmp_path)
    image_hash = "deadbeef" * 8  # 64 hex chars -- geldig content-hash-formaat
    media_dir = tmp_path / "media"
    media_dir.mkdir(exist_ok=True)
    (media_dir / image_hash).write_bytes(b"not-a-real-image-but-cv2.imread-is-mocked-below")
    source = client.post("/api/sources", json={
        "name": "Stilstaand", "kind": "static_image", "value": image_hash, "canvas_x": 0, "canvas_y": 0,
    }).json()
    monkeypatch.setattr("admin.app.routers.preview.cv2.imread", lambda *a, **k: "decoded-static-frame")

    response = client.post(
        "/api/players/preview-frame", json={**_DRAFT, "source_id": source["id"]}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
```

(This test's `media_dir` must match the app's actual `settings.media_dir` for the created `Settings` in `_client` — check Step 1's read of the existing fixture to confirm `_client(tmp_path)` already sets `media_dir=str(tmp_path / "media")`; if the existing fixture uses a different subpath, write the file there instead.)

(Exact fixture names/variables depend on what Step 1's read reveals — adapt the payload dict name if it isn't literally `_DRAFT`, and keep every pre-existing test's *intent* — 400 on missing source, 502 on failed camera read, 200 with jpeg content-type on success — while swapping `output_id` for `source_id` throughout.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_preview.py -v`
Expected: FAIL — route still at the old path with the Task-2-patched-but-not-fully-rewritten source logic.

- [ ] **Step 4: Rewrite `admin/app/routers/preview.py`**

```python
import cv2
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from mirror_node.camera import open_camera
from mirror_node.effects import get_effect
from mirror_node.overlay import composite_overlay, place_on_canvas
from admin.app.media import get_media_path
from admin.app.routers.players import _resolve_source_id

router = APIRouter()


def _acquire_frame(source_row, media_dir):
    """Geeft één BGR-frame terug voor de gekozen source: bij
    camera_stream via de bestaande open_camera/cap.read()-weg, bij
    static_image door het beeldbestand rechtstreeks te decoderen (geen
    camera-hardware nodig, geen herhaald schijf-I/O per aanroep -- dit
    endpoint wordt al binnen één request maar één keer aangeroepen, dus
    geen cache nodig zoals mirror_node's `_overlay_cache` wel heeft)."""
    kind, value = source_row
    if kind == "static_image":
        # get_media_path valideert het hash-formaat EN bestaat-op-schijf in
        # één stap -- None dekt beide faalgevallen, geen losse exists-check nodig.
        image_path = get_media_path(media_dir, value)
        if image_path is None:
            raise HTTPException(status_code=502, detail="Kon de statische afbeelding niet vinden")
        frame = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if frame is None:
            raise HTTPException(status_code=502, detail="Kon de statische afbeelding niet decoderen")
        return frame
    cap = open_camera(value)
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise HTTPException(status_code=502, detail="Kon geen frame van de camera-bron ophalen")
    return frame


def _render_preview_frame(draft, db, media_dir):
    """Blocking body van preview_frame_route -- draait in een threadpool
    (via run_in_threadpool) zodat een tragere/haperende camera niet de
    hele event loop, en dus elke andere admin-request, blokkeert."""
    source_id = _resolve_source_id(db, draft.get("source_id"))
    source_row = db.execute("SELECT kind, value FROM sources WHERE id = ?", (source_id,)).fetchone()
    if source_row is None:
        raise HTTPException(status_code=400, detail="source_id verwijst naar een onbestaande source")
    frame = _acquire_frame(source_row, media_dir)

    try:
        effect_fn = get_effect(draft.get("effect", "xray"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Onbekend effect: {draft.get('effect')!r}")
    result = effect_fn(frame, draft.get("params", {}))

    canvas_size = draft.get("canvas_size")
    if canvas_size:
        result = place_on_canvas(
            result, tuple(canvas_size),
            scale=draft.get("source_scale", 1.0),
            position=tuple(draft.get("source_position", [0.5, 0.5])),
        )

    overlay_hash = draft.get("overlay_hash")
    if overlay_hash:
        overlay_path = get_media_path(media_dir, overlay_hash)
        overlay_img = cv2.imread(overlay_path, cv2.IMREAD_UNCHANGED) if overlay_path else None
        if overlay_img is not None and overlay_img.ndim == 3 and overlay_img.shape[2] == 4:
            result = composite_overlay(
                result, overlay_img,
                scale=draft.get("scale", 1.0),
                position=tuple(draft.get("position", [0.5, 0.5])),
            )

    ok, buf = cv2.imencode(".jpg", result)
    if not ok:
        raise HTTPException(status_code=500, detail="Kon voorbeeld niet coderen")
    return buf.tobytes()


@router.post("/api/players/preview-frame")
async def preview_frame_route(request: Request):
    """Rendert één losstaand voorbeeldbeeld voor de concept-player in
    `draft` -- zonder de fysieke spiegel/mirror-node aan te raken. Haalt
    zelf één frame op van de gekozen source (camera-stream of statische
    afbeelding) en past dezelfde effect-/overlay-code toe als de
    mirror-node."""
    draft = await request.json()
    jpeg_bytes = await run_in_threadpool(
        _render_preview_frame, draft, request.app.state.db, request.app.state.settings.media_dir
    )
    return Response(content=jpeg_bytes, media_type="image/jpeg")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_preview.py -v`
Expected: PASS.

- [ ] **Step 6: Update the frontend fetch URL**

In `admin/frontend/src/components/PreviewPanel.tsx`, change the `fetch("/api/scenes/preview-frame", ...)` call to `fetch("/api/players/preview-frame", ...)`, and update the comment above it that names the old path.

- [ ] **Step 7: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS across the board — this was the last file blocking full-suite green.

- [ ] **Step 8: Commit**

```bash
git add admin/app/routers/preview.py admin/frontend/src/components/PreviewPanel.tsx tests/test_admin_routes_preview.py
git commit -m "feat: voorbeeldpaneel rendert vanaf een source (camera-stream of statische afbeelding)"
```

---

### Task 9: `mirror_node/scenes.py` → `players.py` — branch-to-player indirection

**Why this task exists on its own:** after Task 4's mechanical rename, `triggers.from_branch_id` genuinely holds a **branch id** in the real database — but the mirror_node-side graph class still looks up triggers by **player id** directly (a leftover from before branches existed). This task fixes that mismatch by resolving branch→player once, in `set_graph()`, so the per-frame `resolve()` loop stays exactly as simple as it is today.

**Files:**
- Modify: `mirror_node/scenes.py` → rename to `mirror_node/players.py`
- Test: `tests/test_scene_engine.py` → rename to `tests/test_player_engine.py`

**Interfaces:**
- Produces: `PlayerGraph` (renamed from `SceneGraph`), `PlayerGraph.set_graph(players, branches, triggers, root_player_id)` (branches param added), `PlayerGraph.resolve(motion_active, now_hhmm, fired_ha_entities=frozenset())` (signature unchanged).

- [ ] **Step 1: Write the failing tests**

`git mv tests/test_scene_engine.py tests/test_player_engine.py`, then replace its entire contents:

```python
from mirror_node.players import PlayerGraph, _time_in_window


def _graph(players, branches, triggers, root_id, **kwargs):
    g = PlayerGraph(**kwargs)
    g.set_graph(players, branches, triggers, root_id)
    return g


# Branch-ids zijn hier bewust ANDERS dan player-ids (101/102 i.p.v. 1/2) --
# zou de indirectie in set_graph() ontbreken (of stilletjes op id-gelijkenis
# leunen), dan falen deze tests meteen in plaats van toevallig te slagen.
_BASIC_BRANCH = {"id": 101, "player_id": 1, "name": "Uitgang 1"}
_SCARE_BRANCH = {"id": 102, "player_id": 2, "name": "Uitgang 1"}


def test_resolves_to_root_with_no_triggers():
    g = _graph([{"id": 1, "name": "Basis"}], [_BASIC_BRANCH], [], root_id=1)

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_transitions_on_matching_motion_trigger():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_no_transition_without_motion():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_only_current_players_own_triggers_are_checked():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 2, "name": "Scare"}
    assert transitioned is False


def test_return_trigger_brings_state_back_on_next_resolve():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH, _SCARE_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_branch_id": 102, "to_player_id": 1, "kind": "always",
         "schedule_from": None, "schedule_until": None, "priority": 0},
    ]
    g = _graph(players, branches, triggers, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is True


def test_non_live_triggers_are_ignored():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": None, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_branch_id": 101, "to_player_id": 2, "kind": None,
         "schedule_from": None, "schedule_until": None, "priority": 1},
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_priority_order_first_matching_trigger_wins():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}, {"id": 3, "name": "B"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 3, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 1},
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 2, "name": "A"}


def test_unknown_current_player_resets_to_root():
    g = _graph([{"id": 1, "name": "Basis"}], [_BASIC_BRANCH], [], root_id=1)
    g._current_id = 999

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}


def test_no_root_and_no_players_returns_none():
    g = PlayerGraph()
    g.set_graph([], [], [], root_player_id=None)

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player is None
    assert transitioned is False


def test_disabled_player_is_never_resolved_to():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare", "enabled": False}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_trigger_to_unknown_player_is_skipped_not_followed():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 999, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 1},
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 2, "name": "A"}
    assert transitioned is True


def test_trigger_from_an_orphaned_branch_id_is_ignored():
    """Regressie: als een trigger een from_branch_id heeft die niet (meer)
    in de meegestuurde branches-lijst voorkomt, mag dat niet crashen --
    de trigger wordt simpelweg genegeerd (verweesde/inconsistente data)."""
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}]
    triggers = [
        {"from_branch_id": 999, "to_player_id": 2, "kind": "always",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, [], triggers, root_id=1)  # geen branches meegestuurd

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_preview_overrides_graph_evaluation():
    clock = {"t": 0.0}
    g = PlayerGraph(preview_timeout=30, clock=lambda: clock["t"])
    g.set_graph([{"id": 1, "name": "Basis"}], [], [], root_player_id=1)
    preview = {"id": 99, "name": "Preview"}
    g.set_preview(preview)

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == preview
    assert transitioned is False


def test_preview_expires_after_timeout():
    clock = {"t": 0.0}
    g = PlayerGraph(preview_timeout=30, clock=lambda: clock["t"])
    root = {"id": 1, "name": "Basis"}
    g.set_graph([root], [], [], root_player_id=1)
    g.set_preview({"id": 99, "name": "Preview"})
    clock["t"] = 31.0

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == root


def test_ha_sensor_trigger_matches_only_its_own_fired_entity():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "ha_sensor",
         "schedule_from": None, "schedule_until": None, "ha_entity_id": "binary_sensor.tuin",
         "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    not_fired = g.resolve(motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset())
    assert not_fired == ({"id": 1, "name": "Basis"}, False)

    other_entity_fired = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.woonkamer"})
    )
    assert other_entity_fired == ({"id": 1, "name": "Basis"}, False)

    player, transitioned = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.tuin"})
    )
    assert player == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_ha_sensor_trigger_without_ha_entity_id_never_matches():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "ha_sensor",
         "schedule_from": None, "schedule_until": None, "ha_entity_id": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.tuin"})
    )

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


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

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_player_engine.py -v`
Expected: FAIL — `mirror_node.players` doesn't exist yet, import error.

- [ ] **Step 3: Rename and rewrite `mirror_node/scenes.py`**

`git mv mirror_node/scenes.py mirror_node/players.py`, then replace its entire contents:

```python
import time


class PlayerGraph:
    """Houdt de laatst via MQTT ontvangen graaf bij (players + live
    triggers) en de huidige-player-toestand. Elke trigger ontspringt aan
    een branch (een naambare aftakking op een player) en wijst naar een
    volgende player (from_branch_id -> to_player_id), met een kind
    (always/motion/schedule/ha_sensor). De branch-naar-player-indirectie
    wordt eenmalig opgelost in set_graph() (branch_id -> player_id), dus
    resolve() zelf blijft simpelweg per-player kijken, zoals voorheen."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._players = {}
        self._triggers = {}
        self._root_id = None
        self._current_id = None
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_graph(self, players, branches, triggers, root_player_id):
        # Disabled players tellen niet mee -- ze mogen nooit als winnaar
        # terugkomen. Een trigger naar zo'n player wordt vanzelf als
        # "target bestaat niet" behandeld door resolve() (zelfde pad als
        # een trigger naar een écht verwijderde player).
        self._players = {p["id"]: p for p in players if p.get("enabled", True)}
        branch_to_player = {b["id"]: b["player_id"] for b in branches}
        by_from = {}
        for t in triggers:
            if t.get("to_player_id") is None or t.get("kind") is None:
                continue  # niet-live: lege stub of ongeconfigureerde trigger
            from_player_id = branch_to_player.get(t.get("from_branch_id"))
            if from_player_id is None:
                continue  # branch niet (meer) meegestuurd -- verweesde trigger, negeren
            by_from.setdefault(from_player_id, []).append(t)
        for lst in by_from.values():
            lst.sort(key=lambda t: t["priority"])
        self._triggers = by_from
        self._root_id = root_player_id
        if self._current_id not in self._players:
            self._current_id = root_player_id

    def set_preview(self, player):
        self._preview = player
        self._preview_set_at = self._clock()

    def preview_recently_set(self):
        if self._preview_set_at is None:
            return False
        return self._clock() - self._preview_set_at <= self._preview_timeout

    def resolve(self, motion_active, now_hhmm, fired_ha_entities=frozenset()):
        """Geeft (player, transitioned) terug. `transitioned` is True als
        dit frame een trigger is gevolgd. `fired_ha_entities` is een
        eenmalige puls-set (net als `motion_active` een puls is, geen
        aanhoudend niveau) van HA-entity-ids die dit frame naar 'on' zijn
        gegaan."""
        if self.preview_recently_set():
            return self._preview, False
        if self._current_id not in self._players:
            self._current_id = self._root_id
        if self._current_id is None:
            return None, False
        for trigger in self._triggers.get(self._current_id, []):
            if trigger["to_player_id"] not in self._players:
                continue  # doel bestaat niet (of staat uit) -- val door naar de volgende trigger
            if _trigger_matches(trigger, motion_active, now_hhmm, fired_ha_entities):
                if trigger["to_player_id"] != self._current_id:
                    self._current_id = trigger["to_player_id"]
                    return self._players.get(self._current_id), True
                break
        return self._players.get(self._current_id), False


def _trigger_matches(trigger, motion_active, now_hhmm, fired_ha_entities):
    kind = trigger["kind"]
    if kind == "always":
        return True
    if kind == "motion":
        return motion_active
    if kind == "schedule":
        return _time_in_window(now_hhmm, trigger.get("schedule_from"), trigger.get("schedule_until"))
    if kind == "ha_sensor":
        return trigger.get("ha_entity_id") in fired_ha_entities
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_player_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mirror_node/players.py tests/test_player_engine.py
git rm mirror_node/scenes.py tests/test_scene_engine.py
git commit -m "feat: PlayerGraph lost branch->player-indirectie eenmalig op in set_graph()"
```

---

### Task 10: `HaTriggerPoller` + `MqttBridge` — level-state publishing for `repeat_while`

**Why:** the existing HA-trigger mechanism only ever tells `mirror_node` about a rising edge (a pulse). `repeat_while` needs the opposite — mirror_node must know an entity's **current** state at any moment, to know when to stop looping a scare-video. This task extends the poller (which already reads every watched entity's state every tick) to also publish that raw state on every tick, on a new, non-retained topic, for entities used by a `repeat_while` player. Reusing the poller (rather than adding a second polling loop) keeps there being exactly one place in the codebase that talks to `ha_client.get_states`.

**Files:**
- Modify: `shared/mqtt_contract.py`
- Modify: `admin/app/mqtt_bridge.py`
- Modify: `admin/app/ha_trigger_poller.py`
- Modify: `admin/app/main.py` (`_get_watched_ha_entities_from_db` — union in `repeat_while_ha_entity_id`)
- Test: `tests/test_mqtt_contract.py` (append)
- Test: `tests/test_ha_trigger_poller.py` (append)

**Interfaces:**
- Produces: `Topics.control_mirror_ha_sensor_state` (`"control/mirror/ha-sensor-state"`), `MqttBridge.publish_mirror_ha_sensor_state(entity_id, state)`, `HaTriggerPoller._tick()` now also calls that for every watched entity on every tick (regardless of transition).

- [ ] **Step 1: Write the failing contract test**

Append to `tests/test_mqtt_contract.py` (read the file first to match its existing style/imports):

```python
def test_control_mirror_ha_sensor_state_topic():
    topics = Topics()
    assert topics.control_mirror_ha_sensor_state == "control/mirror/ha-sensor-state"


def test_control_mirror_ha_sensor_state_topic_respects_prefix():
    topics = Topics(prefix="halloween")
    assert topics.control_mirror_ha_sensor_state == "halloween/control/mirror/ha-sensor-state"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py -k sensor_state -v`
Expected: FAIL — `AttributeError: 'Topics' object has no attribute 'control_mirror_ha_sensor_state'`.

- [ ] **Step 3: Add the topic**

In `shared/mqtt_contract.py`, add next to the existing `control_mirror_ha_trigger` property:

```python
    @property
    def control_mirror_ha_sensor_state(self) -> str:
        return self._p("control/mirror/ha-sensor-state")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Add the bridge method**

In `admin/app/mqtt_bridge.py`, add next to `publish_mirror_ha_trigger`:

```python
    def publish_mirror_ha_sensor_state(self, entity_id, state):
        # Niet-retained, net als publish_mirror_ha_trigger -- de poller
        # publiceert dit elke check_interval opnieuw, dus een gemiste
        # boodschap na een reconnect wordt vanzelf binnen één interval
        # ingehaald; geen retained state nodig die op een gegeven moment
        # stil kan gaan liegen (bv. als de poller crasht).
        self._client.publish(
            self._topics.control_mirror_ha_sensor_state, json.dumps({"entity_id": entity_id, "state": state})
        )
```

- [ ] **Step 6: Write the failing poller test**

Append to `tests/test_ha_trigger_poller.py`:

```python
class _FakeBridgeWithState(_FakeBridge):
    def __init__(self):
        super().__init__()
        self.states = []

    def publish_mirror_ha_sensor_state(self, entity_id, state):
        self.states.append((entity_id, state))


def test_every_tick_publishes_current_state_for_every_watched_entity(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "off"}],
    )
    bridge = _FakeBridgeWithState()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()
    poller._tick()

    assert bridge.states == [("binary_sensor.tuin", "off"), ("binary_sensor.tuin", "off")]


def test_state_publish_happens_even_without_a_rising_edge(monkeypatch):
    """Onderscheid met de puls: state wordt ELKE tick gepubliceerd, ook
    als er niets verandert -- repeat_while moet weten dat de sensor nog
    steeds 'on' is, niet alleen het moment waarop hij dat werd."""
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "on"}],
    )
    bridge = _FakeBridgeWithState()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()
    poller._tick()
    poller._tick()

    assert bridge.fired == ["binary_sensor.tuin"]  # puls: alleen de eerste keer
    assert bridge.states == [("binary_sensor.tuin", "on")] * 3  # state: elke keer


def test_state_not_published_for_entity_absent_from_ha_response(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(poller_module, "get_states", lambda url, token: [])
    bridge = _FakeBridgeWithState()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()

    assert bridge.states == []
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ha_trigger_poller.py -k "every_tick or without_a_rising_edge or absent_from_ha" -v`
Expected: FAIL — `AttributeError` (no `publish_mirror_ha_sensor_state` call made, `bridge.states` stays empty).

- [ ] **Step 8: Publish state on every tick**

In `admin/app/ha_trigger_poller.py`'s `_tick`, add one line right after the existing rising-edge check (inside the `for entity_id in watched:` loop, after the `if entity_id not in by_entity: continue` guard so absent entities are correctly skipped for state too):

```python
                new_state = by_entity[entity_id]
                old_state = self._last_states.get(entity_id)
                if new_state in self._FIRED_STATES and old_state not in self._FIRED_STATES:
                    self._bridge.publish_mirror_ha_trigger(entity_id)
                self._bridge.publish_mirror_ha_sensor_state(entity_id, new_state)
                self._last_states[entity_id] = new_state
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ha_trigger_poller.py -v`
Expected: PASS (full file — confirm the pre-existing tests still pass too, since `_FakeBridge` in those doesn't define `publish_mirror_ha_sensor_state` and would now `AttributeError` if the poller tried to call it on those instances. If any pre-existing test fails this way, add a no-op `publish_mirror_ha_sensor_state` method to the base `_FakeBridge` class instead of only `_FakeBridgeWithState`).

- [ ] **Step 10: Watch `repeat_while` entities too**

In `admin/app/main.py`, update `_get_watched_ha_entities_from_db`:

```python
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
```

- [ ] **Step 11: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add shared/mqtt_contract.py admin/app/mqtt_bridge.py admin/app/ha_trigger_poller.py admin/app/main.py tests/test_mqtt_contract.py tests/test_ha_trigger_poller.py
git commit -m "feat: HA-poller publiceert elke tick de actuele sensor-state (voor repeat_while)"
```

---

### Task 11: `mirror_node/main.py` — playback-mode sequencing, dynamic source, output-routing publish

**This is the second-biggest task in the plan.** It touches the running main loop directly — read the current file fully before editing (you already have it from the plan's research phase; re-read `mirror_node/main.py` now to confirm you're editing the actual current state, not a stale copy).

**Files:**
- Modify: `mirror_node/main.py`
- Modify: `admin/app/routers/node_config.py` (boot-time camera source now resolves via the root player's source, not `outputs.camera_source`)
- Test: `tests/test_mirror_main.py`
- Test: `tests/test_mirror_camera.py` (no change expected — confirm still green)
- Test: `tests/test_admin_routes_node_config.py`

**Interfaces:**
- Consumes: `PlayerGraph` (Task 9), `control_mirror_ha_sensor_state` topic (Task 10), the new graph payload shape (Task 7: `players`/`sources`/`branches`/`triggers`/`output_connections`/`root_player_id`/`output_id`).
- Produces: dynamic per-player source resolution (reopens the camera only when the resolved source actually changes; static images load once and are cached), a scare-video play sequence governed by `playback_mode`, and an output-routing MQTT publish whenever the player actively feeding a given `output_id` changes.

- [ ] **Step 1: Re-read the current file**

Read `mirror_node/main.py` in full before making any change — this plan's earlier research read happened before Tasks 1-10 landed; re-confirm line numbers and exact current wording before editing.

- [ ] **Step 2: Write the failing tests**

Read `tests/test_mirror_main.py` in full first (it already `pytest.importorskip`s `paho`/`cv2`, uses a `_FakeLogger`, and monkeypatches `mirror_main.cv2`/`mirror_main.threading` — match that style). Update/add:

Replace every `mirror_main.scene_graph` reference with `mirror_main.player_graph` (the module-level instance is renamed in Step 3). Replace `_apply_graph_message`'s test payloads' keys: `"scenes"` → `"players"`, add `"branches": []`, `"root_scene_id"` → `"root_player_id"`. E.g. `test_apply_graph_message_updates_scene_graph` becomes:

```python
def test_apply_graph_message_updates_player_graph():
    player = {"id": 1, "trigger_type": None, "overlay_hash": None}
    payload = {"players": [player], "branches": [], "triggers": [], "root_player_id": 1}
    mirror_main._apply_graph_message(json.dumps(payload), _FakeLogger())

    result, transitioned = mirror_main.player_graph.resolve(False, "12:00")
    assert result == player
    assert transitioned is False
```

Apply the same payload-shape substitution to `test_apply_graph_message_ignores_non_list_scenes_or_edges` (→ rename to `..._players_or_triggers`, payload becomes `{"players": "nope", "triggers": [], "root_player_id": 1}`), `test_apply_graph_message_reads_triggers_key` (rename to match, same substitution), and `test_apply_graph_message_syncs_overlay_for_each_scene` (rename to `..._for_each_player`, `"scenes"` key → `"players"`).

Add new tests for the playback-mode sequencing and source resolution:

```python
def test_play_scare_video_sequence_once_plays_exactly_one_clip(monkeypatch):
    mirror_main.synced_scare_videos = {"h1": {"video": "v.mp4", "audio": None}}
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)

    try:
        winning = {"playback_mode": "once"}
        result = mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())
        assert result == mirror_main.ACTIVE_SECONDS
        assert len(play_calls) == 1
    finally:
        mirror_main.synced_scare_videos = {}


def test_play_scare_video_sequence_repeat_once_plays_exactly_two_clips(monkeypatch):
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)

    winning = {"playback_mode": "repeat_once"}
    mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())

    assert len(play_calls) == 2


def test_play_scare_video_sequence_repeat_while_loops_until_sensor_drops(monkeypatch):
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)
    states = iter(["on", "on", "off"])  # 1 verplichte keer + 2x nog 'on' + stop op 'off'
    mirror_main._ha_entity_states["binary_sensor.tuin"] = "on"
    monkeypatch.setattr(mirror_main, "_ha_entity_state", lambda entity_id: next(states, "off"))

    winning = {"playback_mode": "repeat_while", "repeat_while_ha_entity_id": "binary_sensor.tuin"}
    mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())

    assert len(play_calls) == 3  # 1 gegarandeerde keer + 2 herhalingen zolang 'on'


def test_play_scare_video_sequence_repeat_while_without_entity_id_plays_once(monkeypatch):
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)

    winning = {"playback_mode": "repeat_while", "repeat_while_ha_entity_id": None}
    mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())

    assert len(play_calls) == 1


def test_apply_ha_sensor_state_message_updates_state():
    mirror_main._ha_entity_states.clear()
    mirror_main._apply_ha_sensor_state_message(
        json.dumps({"entity_id": "binary_sensor.tuin", "state": "on"}), _FakeLogger()
    )

    assert mirror_main._ha_entity_state("binary_sensor.tuin") == "on"
    mirror_main._ha_entity_states.clear()


def test_apply_ha_sensor_state_message_ignores_malformed_payload():
    logger = _FakeLogger()
    mirror_main._apply_ha_sensor_state_message("{niet-geldig-json", logger)
    assert logger.errors


def test_resolve_frame_source_reuses_open_capture_for_unchanged_source(monkeypatch):
    open_calls = []
    monkeypatch.setattr(mirror_main, "open_camera", lambda value, idx: open_calls.append(value) or "cap-object")
    state = mirror_main._SourceState()

    cap1 = mirror_main._ensure_source(state, {"id": 5, "kind": "camera_stream", "value": "rtsp://a"}, _FakeLogger())
    cap2 = mirror_main._ensure_source(state, {"id": 5, "kind": "camera_stream", "value": "rtsp://a"}, _FakeLogger())

    assert cap1 is cap2
    assert open_calls == ["rtsp://a"]  # maar 1x geopend, niet 2x


def test_resolve_frame_source_reopens_when_source_id_changes(monkeypatch):
    monkeypatch.setattr(mirror_main, "open_camera", lambda value, idx: f"cap-{value}")
    released = []
    state = mirror_main._SourceState()
    state.capture = type("FakeCap", (), {"release": lambda self: released.append(1)})()
    state.source_id = 5

    mirror_main._ensure_source(state, {"id": 6, "kind": "camera_stream", "value": "rtsp://b"}, _FakeLogger())

    assert released == [1]  # oude capture netjes gesloten vóór de nieuwe geopend wordt
    assert state.source_id == 6


def test_resolve_frame_source_caches_static_image(monkeypatch):
    read_calls = []
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    monkeypatch.setattr(mirror_main.cv2, "imread", lambda path, *a: read_calls.append(path) or "decoded-image")
    state = mirror_main._SourceState()

    img1 = mirror_main._ensure_source(state, {"id": 7, "kind": "static_image", "value": "a" * 64}, _FakeLogger())
    img2 = mirror_main._ensure_source(state, {"id": 7, "kind": "static_image", "value": "a" * 64}, _FakeLogger())

    assert img1 == "decoded-image"
    assert img2 == "decoded-image"
    assert len(read_calls) == 1  # niet opnieuw gedecodeerd, id ongewijzigd
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py -v`
Expected: FAIL across most of the new/updated tests — `mirror_main.player_graph`/`_play_scare_video_sequence`/`_apply_ha_sensor_state_message`/`_SourceState`/`_ensure_source`/`_ha_entity_state` don't exist yet.

- [ ] **Step 4: Implement the changes in `mirror_node/main.py`**

**4a. Imports and module-level state.** Change:
```python
from mirror_node.scenes import SceneGraph
```
to:
```python
from mirror_node.players import PlayerGraph
```
Change:
```python
scene_graph = SceneGraph()
```
to:
```python
player_graph = PlayerGraph()
```
Add, near the existing `_fired_ha_entities_lock`/`_fired_ha_entities` pair:
```python
_ha_entity_states_lock = threading.Lock()
_ha_entity_states = {}
```

**4b. `_SourceState` and `_ensure_source`.** Add near `_load_overlay`:
```python
class _SourceState:
    """Houdt bij welke source op dit moment 'open' is voor de camera-lus
    -- capture-object bij camera_stream, gedecodeerd beeld bij
    static_image -- zodat een ongewijzigde source niet elk frame opnieuw
    geopend/gedecodeerd wordt, en een gewijzigde source de oude capture
    netjes sluit voordat de nieuwe geopend wordt."""

    def __init__(self):
        self.source_id = None
        self.kind = None
        self.capture = None
        self.image = None


def _ensure_source(state, source, logger):
    """Geeft het huidige frame-beeld (cv2 capture voor camera_stream, een
    gedecodeerd beeld voor static_image) terug voor `source`, en heropent/
    herdecodeert alleen als de source_id daadwerkelijk gewijzigd is sinds
    de vorige aanroep."""
    if source is None:
        return None
    if state.source_id == source.get("id") and state.kind == source.get("kind"):
        return state.capture if state.kind == "camera_stream" else state.image
    if state.capture is not None:
        state.capture.release()
        state.capture = None
    state.image = None
    state.source_id = source.get("id")
    state.kind = source.get("kind")
    if state.kind == "static_image":
        value = source.get("value", "")
        if not _HASH_RE.match(value):
            logger.error("Ongeldige static_image-hash op source: %s", value)
            return None
        image_path = os.path.join(MEDIA_CACHE_DIR, value)
        if not os.path.exists(image_path):
            return None
        state.image = cv2.imread(image_path, cv2.IMREAD_COLOR)
        return state.image
    state.capture = open_camera(source.get("value", ""), CAMERA_INDEX)
    return state.capture
```

**4c. `_play_scare_video_sequence`.** Add near `_handle_trigger`:
```python
def _play_scare_video_sequence(winning, streamer, logger):
    """Speelt scare-video's af volgens winning['playback_mode']: 'once'
    precies 1x (bestaand gedrag, ongewijzigd), 'repeat_once' precies 2x,
    'repeat_while' minstens 1x en daarna zolang de gekoppelde HA-sensor
    (NIVEAU, geen puls -- ander mechanisme dan de HA-trigger hierboven,
    zie het Global Constraints-punt over puls vs. niveau) 'on'/'detected'
    blijft rapporteren. Geeft ACTIVE_SECONDS terug, zelfde contract als
    het onderliggende _handle_trigger."""
    mode = winning.get("playback_mode", "once")
    if mode == "repeat_while":
        entity_id = winning.get("repeat_while_ha_entity_id")
        result = _handle_trigger(streamer, logger)
        while entity_id and _ha_entity_state(entity_id) in ("on", "detected"):
            result = _handle_trigger(streamer, logger)
        return result
    plays = 2 if mode == "repeat_once" else 1
    result = ACTIVE_SECONDS
    for _ in range(plays):
        result = _handle_trigger(streamer, logger)
    return result
```

**4d. `_apply_ha_sensor_state_message` and `_ha_entity_state`.** Add near `_apply_ha_trigger_message`:
```python
def _apply_ha_sensor_state_message(payload, logger):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige ha-sensor-state-JSON ontvangen, genegeerd")
        return
    entity_id = data.get("entity_id") if isinstance(data, dict) else None
    state = data.get("state") if isinstance(data, dict) else None
    if not isinstance(entity_id, str) or not entity_id or not isinstance(state, str):
        logger.error("ha-sensor-state-bericht zonder geldige entity_id/state, genegeerd: %r", data)
        return
    with _ha_entity_states_lock:
        _ha_entity_states[entity_id] = state


def _ha_entity_state(entity_id):
    with _ha_entity_states_lock:
        return _ha_entity_states.get(entity_id)
```

**4e. `_apply_graph_message`.** Replace the body to read the new payload keys and pass `branches` through:
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
    players = graph.get("players", [])
    branches = graph.get("branches", [])
    triggers = graph.get("triggers", [])
    root_player_id = graph.get("root_player_id")
    if not isinstance(players, list) or not isinstance(triggers, list):
        logger.error("Graaf-config heeft geen geldige players/triggers-lijst, genegeerd: %r", graph)
        return
    player_graph.set_graph(players, branches, triggers, root_player_id)
    for player in players:
        if isinstance(player, dict):
            _sync_overlay_in_background(player)
```

**4f. `make_on_message`.** Add a new topic branch for `control_mirror_ha_sensor_state`, placed anywhere in the chain except before `control_mirror_ha_trigger` is unaffected by ordering (this new branch has its own distinct topic, doesn't share the "must be last" hazard the HA-trigger branch had — that hazard was about topic-string overlap with something else in the chain, which doesn't apply here; still, keep it grouped next to the existing `control_mirror_ha_trigger` branch for readability):

```python
            if msg.topic == topics.control_mirror_ha_trigger:
                _apply_ha_trigger_message(msg.payload.decode(), logger)
                return
            if msg.topic == topics.control_mirror_ha_sensor_state:
                _apply_ha_sensor_state_message(msg.payload.decode(), logger)
                return
```

And subscribe to it in `on_connect`, next to the existing `client.subscribe(topics.control_mirror_ha_trigger)` line:
```python
        client.subscribe(topics.control_mirror_ha_sensor_state)
```

**4g. Output-routing publish.** Add module-level state near `player_graph`:
```python
_last_published_output_player_id = None
```
In `main()`'s loop, right after the `winning, transitioned = player_graph.resolve(...)` line, add the output-routing publish (uses the already-parsed `graph` state cached from the last `_apply_graph_message` call — add a small module-level cache for the current `output_connections`/`branches`/`output_id` needed to resolve "does the active player's branch route to *this node's* output" — see below):

Add these three module-level variables near `player_graph`:
```python
_current_output_id = None
_current_output_connections = []
_current_branches = []
```
Extend `_apply_graph_message` (Step 4e) to also capture these three from the payload, right after the `player_graph.set_graph(...)` call:
```python
    global _current_output_id, _current_output_connections, _current_branches
    _current_output_id = graph.get("output_id")
    _current_output_connections = graph.get("output_connections", [])
    _current_branches = branches
```
Add a small pure helper near `_render_action`:
```python
def _player_feeds_this_output(player_id, output_id, branches, output_connections):
    """True als de gegeven player, via een van zijn branches, een
    output_connections-rij heeft naar output_id."""
    player_branch_ids = {b["id"] for b in branches if b.get("player_id") == player_id}
    return any(
        oc["from_branch_id"] in player_branch_ids and oc["output_id"] == output_id
        for oc in output_connections
    )
```
In `main()`'s loop, right after computing `winning, transitioned`, add:
```python
            global _last_published_output_player_id
            if (
                winning is not None
                and transitioned
                and _current_output_id is not None
                and _player_feeds_this_output(winning["id"], _current_output_id, _current_branches, _current_output_connections)
                and winning["id"] != _last_published_output_player_id
            ):
                client.publish(
                    topics.mirror_triggered, json.dumps({"player_id": winning["id"], "output_id": _current_output_id})
                )
                _last_published_output_player_id = winning["id"]
```
(This reuses the existing `topics.mirror_triggered` topic rather than adding a new one — it already exists precisely for "something changed, tell whoever's listening", and nothing outside this mirror_node process currently parses its payload shape, so widening it here is safe. This is a minimal, good-enough approach for the single-output installation this plan targets; a real multi-output rollout would need a per-output topic, explicitly out of scope per the spec.)

**4h. `_render_action` and the main loop's frame source.** `_render_action` currently reads `winning.get("source_mode")`; that field lives on `players` unchanged (Task 2 didn't touch `source_mode`), so no change needed there. But the main loop's frame acquisition needs to switch from the single startup-time `cap` to `_ensure_source`, resolved against the active player's `source_id`.

Add `_current_sources = []` near the other new module-level caches (`_current_output_id` etc. from Step 4g), and in `_apply_graph_message`, add `_current_sources = graph.get("sources", [])` alongside the other three globals in Step 4g's block (same `global` statement, same assignment block).

Then restructure the top of `main()`'s loop — replace:
```python
    try:
        while True:
            ok, frame = cap.read()
```
with:
```python
    source_state = _SourceState()
    sources_by_id = {}
    try:
        while True:
            sources_by_id = {s["id"]: s for s in _current_sources}
            current_player = player_graph._players.get(player_graph._current_id)
            resolved_source = sources_by_id.get(current_player.get("source_id")) if current_player else None
            acquired = _ensure_source(source_state, resolved_source, logger) if resolved_source else None

            if resolved_source is not None and resolved_source.get("kind") == "static_image":
                if acquired is None:
                    time.sleep(0.5)
                    continue
                frame = acquired.copy()
                ok = True
            elif acquired is not None:
                ok, frame = acquired.read()
            else:
                # Geen (nog) bekende source voor de huidige player -- val
                # terug op de startup-camera zodat het beeld nooit
                # volledig leeg blijft vóór de eerste graaf-config binnen is.
                ok, frame = cap.read()
```
Keep everything below this (the existing `if not ok:` failure-handling block, motion-detection, resolve-call, render dispatch) exactly as it is, with two small adjustments: the existing failure-recovery branch (`consecutive_failures >= MAX_FAILURES_BEFORE_REOPEN: ... cap = open_camera(...)`) should reopen `acquired`/`source_state.capture` instead of the old startup-only `cap` when a dynamic source is active — since this is a pre-existing safety net and the startup `cap` fallback above already covers the "no source resolved yet" case, leave the existing reopen logic targeting `cap` as a defensive fallback for that startup-fallback path specifically, and add a parallel reopen for `source_state.capture` guarded by `source_state.kind == "camera_stream"`. Keep this minimal: wrap the existing reopen block's `cap = open_camera(...)` line with a check, replacing it with:
```python
                if source_state.kind == "camera_stream" and source_state.capture is not None:
                    source_state.capture.release()
                    source_state.capture = open_camera(resolved_source.get("value", ""), CAMERA_INDEX)
                else:
                    cap = open_camera(camera_source, CAMERA_INDEX)
```

- [ ] **Step 5: Update `admin/app/routers/node_config.py`**

Replace its body to resolve the boot-time camera source via the root player's source instead of the output's (now-vestigial) `camera_source` column:

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/node-config")
def get_node_config(request: Request):
    """Publiek endpoint (geen sessie nodig) waar mirror-node/scare-node bij
    het opstarten hun configuratie ophalen -- zie shared/topic_prefix.py.
    Geeft bewust alleen niet-gevoelige/expliciet-publiek-gemaakte velden
    terug: de topic-prefix en een startup-camera-bron (de root player's
    source, of anders de eerste/enige source) -- beide besproken en
    geaccepteerd als niet-extra-beveiligd, vertrouwd LAN. Nooit
    MQTT-host/poort/credentials of het HA-token. Dit is alleen de
    STARTUP-bron, vóórdat de eerste graaf-config binnenkomt -- de
    daadwerkelijk actieve source per player wisselt daarna dynamisch,
    zie mirror_node/main.py's _ensure_source."""
    settings = request.app.state.runtime_settings
    db = request.app.state.db
    root_source = db.execute(
        "SELECT s.value FROM players p JOIN sources s ON s.id = p.source_id "
        "WHERE p.is_root = 1 AND s.kind = 'camera_stream' LIMIT 1"
    ).fetchone()
    if root_source is None:
        root_source = db.execute(
            "SELECT value FROM sources WHERE kind = 'camera_stream' ORDER BY id LIMIT 1"
        ).fetchone()
    return {
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mirror_camera_source": root_source[0] if root_source else "",
    }
```

Update `tests/test_admin_routes_node_config.py` (read it first) to match: replace its `outputs`-based fixture setup with a `sources`/`players` one, asserting `mirror_camera_source` resolves to the root player's linked source's `value`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py tests/test_mirror_camera.py tests/test_admin_routes_node_config.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS across the board. This is the last backend/mirror_node task — every remaining task is frontend-only.

- [ ] **Step 8: Commit**

```bash
git add mirror_node/main.py admin/app/routers/node_config.py tests/test_mirror_main.py tests/test_admin_routes_node_config.py
git commit -m "feat: mirror-node volgt playback_mode, dynamische source-resolutie, output-routing-publish"
```

---

### Task 12: Frontend `types.ts` — Player/Source/Branch/OutputConnection

**Files:**
- Modify: `admin/frontend/src/types.ts`

**Interfaces:**
- Produces: `Player` (renamed from `Scene`), `Source`, `PlayerBranch`, `OutputConnection` interfaces; `Output` gains `canvas_x`/`canvas_y`; `Trigger`'s `from_scene_id`/`to_scene_id` become `from_branch_id`/`to_player_id`.

This task has no tests of its own (a `.ts` type-only file has nothing to unit-test); its correctness is verified by every later frontend task's `tsc --noEmit` passing.

- [ ] **Step 1: Rewrite the type definitions**

In `admin/frontend/src/types.ts`, replace the `Scene`, `Trigger`, and `Output` interfaces:

```typescript
export interface Player {
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
  color: string | null;
  source_id: number | null;
  playback_mode: "once" | "repeat_once" | "repeat_while";
  repeat_while_ha_entity_id: string | null;
}

export interface PlayerBranch {
  id: number;
  player_id: number;
  name: string;
}

export interface Source {
  id: number;
  name: string;
  kind: "camera_stream" | "static_image";
  value: string;
  canvas_x: number;
  canvas_y: number;
}

export interface Trigger {
  id: number;
  from_branch_id: number;
  to_player_id: number | null;
  kind: "always" | "motion" | "schedule" | "ha_sensor" | null;
  schedule_from: string | null;
  schedule_until: string | null;
  ha_entity_id: string | null;
  priority: number;
  canvas_x: number;
  canvas_y: number;
  name: string | null;
  color: string | null;
}

export interface Output {
  id: number;
  name: string;
  camera_source: string;
  canvas_x: number;
  canvas_y: number;
}

export interface OutputConnection {
  id: number;
  output_id: number;
  from_branch_id: number;
}
```

Every other interface in this file (`ScareConfig`, `MediaItem`, `NodeStatusMap`, `LogEntry`, `Schedule`, `HaState`, `WsMessage`, `AppSettings`, `AppSettingsUpdate`) stays unchanged.

- [ ] **Step 2: Commit**

```bash
git add admin/frontend/src/types.ts
git commit -m "feat: frontend-types voor Player/Source/PlayerBranch/OutputConnection"
```

(This commit will not typecheck cleanly on its own — every file importing the old `Scene` name now fails `tsc`. That's expected and resolved incrementally by Tasks 13-19; do not run `tsc --noEmit` as a gate for this task specifically, only from Task 19 onward.)

---

### Task 13: Frontend API layer — `players.ts`, `sources.ts`, `branches.ts`, `outputConnections.ts`

**Files:**
- Modify: `admin/frontend/src/api/scenes.ts` → rename to `admin/frontend/src/api/players.ts`
- Create: `admin/frontend/src/api/sources.ts`
- Create: `admin/frontend/src/api/branches.ts`
- Create: `admin/frontend/src/api/outputConnections.ts`
- Modify: `admin/frontend/src/api/triggers.ts`
- Modify: `admin/frontend/src/api/outputs.ts`

**Interfaces:**
- Consumes: `types.ts` (Task 12).
- Produces: `listPlayers`/`getPlayer`/`createPlayer`/`updatePlayer`/`deletePlayer`/`updatePlayerPosition`/`previewPlayer` (renamed), `PlayerDraft`; `listSources`/`getSource`/`createSource`/`updateSource`/`deleteSource`, `SourceDraft`; `listPlayerBranches`/`createPlayerBranch`/`updatePlayerBranch`/`deletePlayerBranch`; `listOutputConnections`/`createOutputConnection`/`deleteOutputConnection`; `updateTrigger`'s type now expects `from_branch_id`/`to_player_id`; `OutputDraft` gains `canvas_x`/`canvas_y`.

No tests of its own (this is a pure fetch-wrapper layer, matching the existing untested `api/*.ts` files) — verified by the frontend suite and `tsc --noEmit` once Task 19 wires everything together.

- [ ] **Step 1: Rename and rewrite the players API**

`git mv admin/frontend/src/api/scenes.ts admin/frontend/src/api/players.ts`, then replace its contents:

```typescript
import { apiFetch } from "./client";
import type { Player } from "../types";

export type PlayerDraft = Omit<Player, "id">;

export function listPlayers(): Promise<Player[]> {
  return apiFetch<Player[]>("/api/players");
}

export function getPlayer(id: number): Promise<Player> {
  return apiFetch<Player>(`/api/players/${id}`);
}

export function createPlayer(player: PlayerDraft): Promise<Player> {
  return apiFetch<Player>("/api/players", { method: "POST", body: JSON.stringify(player) });
}

export function updatePlayer(id: number, player: PlayerDraft): Promise<Player> {
  return apiFetch<Player>(`/api/players/${id}`, { method: "PUT", body: JSON.stringify(player) });
}

export function deletePlayer(id: number): Promise<void> {
  return apiFetch(`/api/players/${id}`, { method: "DELETE" });
}

export function updatePlayerPosition(id: number, canvas_x: number, canvas_y: number): Promise<void> {
  return apiFetch(`/api/players/${id}/position`, {
    method: "PUT",
    body: JSON.stringify({ canvas_x, canvas_y }),
  });
}

export function previewPlayer(id: number, player: PlayerDraft): Promise<void> {
  return apiFetch(`/api/players/${id}/preview`, { method: "POST", body: JSON.stringify(player) });
}
```

- [ ] **Step 2: Create the sources API**

Create `admin/frontend/src/api/sources.ts`:

```typescript
import { apiFetch } from "./client";
import type { Source } from "../types";

export type SourceDraft = Omit<Source, "id">;

export function listSources(): Promise<Source[]> {
  return apiFetch<Source[]>("/api/sources");
}

export function getSource(id: number): Promise<Source> {
  return apiFetch<Source>(`/api/sources/${id}`);
}

export function createSource(source: SourceDraft): Promise<Source> {
  return apiFetch<Source>("/api/sources", { method: "POST", body: JSON.stringify(source) });
}

export function updateSource(id: number, source: SourceDraft): Promise<Source> {
  return apiFetch<Source>(`/api/sources/${id}`, { method: "PUT", body: JSON.stringify(source) });
}

export function deleteSource(id: number): Promise<void> {
  return apiFetch(`/api/sources/${id}`, { method: "DELETE" });
}
```

- [ ] **Step 3: Create the branches API**

Create `admin/frontend/src/api/branches.ts`:

```typescript
import { apiFetch } from "./client";
import type { PlayerBranch } from "../types";

export function listPlayerBranches(playerId: number): Promise<PlayerBranch[]> {
  return apiFetch<PlayerBranch[]>(`/api/players/${playerId}/branches`);
}

export function createPlayerBranch(playerId: number, name: string): Promise<PlayerBranch> {
  return apiFetch<PlayerBranch>(`/api/players/${playerId}/branches`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function updatePlayerBranch(id: number, name: string): Promise<PlayerBranch> {
  return apiFetch<PlayerBranch>(`/api/branches/${id}`, { method: "PUT", body: JSON.stringify({ name }) });
}

export function deletePlayerBranch(id: number): Promise<void> {
  return apiFetch(`/api/branches/${id}`, { method: "DELETE" });
}
```

- [ ] **Step 4: Create the output-connections API**

Create `admin/frontend/src/api/outputConnections.ts`:

```typescript
import { apiFetch } from "./client";
import type { OutputConnection } from "../types";

export function listOutputConnections(): Promise<OutputConnection[]> {
  return apiFetch<OutputConnection[]>("/api/output-connections");
}

export function createOutputConnection(output_id: number, from_branch_id: number): Promise<OutputConnection> {
  return apiFetch<OutputConnection>("/api/output-connections", {
    method: "POST",
    body: JSON.stringify({ output_id, from_branch_id }),
  });
}

export function deleteOutputConnection(id: number): Promise<void> {
  return apiFetch(`/api/output-connections/${id}`, { method: "DELETE" });
}
```

- [ ] **Step 5: Update `admin/frontend/src/api/triggers.ts`**

Change `TriggerDraft`'s implied shape (it's `Omit<Trigger, "id">`, so it follows `types.ts` automatically) — no structural change needed in this file since it only references the `Trigger` type generically. Verify by reading the file: `createTrigger`'s signature `Partial<TriggerDraft> & { from_scene_id: number }` must become `Partial<TriggerDraft> & { from_branch_id: number }`:

```typescript
export function createTrigger(
  trigger: Partial<TriggerDraft> & { from_branch_id: number },
): Promise<Trigger> {
  return apiFetch<Trigger>("/api/triggers", { method: "POST", body: JSON.stringify(trigger) });
}
```

- [ ] **Step 6: Update `admin/frontend/src/api/outputs.ts`**

No functional change needed — `OutputDraft = Omit<Output, "id">` already picks up `canvas_x`/`canvas_y` automatically from the `types.ts` change in Task 12. Read the file to confirm no hardcoded field list exists that needs updating (it doesn't, per the version read during this plan's research phase) — if a fresh read shows otherwise, add `canvas_x`/`canvas_y` to whatever request-body construction exists.

- [ ] **Step 7: Commit**

```bash
git add admin/frontend/src/api/players.ts admin/frontend/src/api/sources.ts admin/frontend/src/api/branches.ts admin/frontend/src/api/outputConnections.ts admin/frontend/src/api/triggers.ts admin/frontend/src/api/outputs.ts
git rm admin/frontend/src/api/scenes.ts
git commit -m "feat: frontend API-laag voor players/sources/branches/output-connections"
```

---

### Task 14: `SourcesPage.tsx` — beheerpagina voor sources, symmetrisch met Outputs

**Files:**
- Create: `admin/frontend/src/pages/SourcesPage.tsx`
- Create: `admin/frontend/src/pages/SourcesPage.css`
- Modify: `admin/frontend/src/App.tsx` (route)
- Modify: `admin/frontend/src/components/Layout.tsx` (nav link)

**Interfaces:**
- Consumes: `listSources`/`createSource`/`updateSource`/`deleteSource` (Task 13), `Source` type (Task 12), `ApiError` (existing `api/client.ts`).
- Produces: `/sources` route, nav link "Sources".

- [ ] **Step 1: Create `SourcesPage.css`**

Copy `admin/frontend/src/pages/OutputsPage.css` verbatim into `admin/frontend/src/pages/SourcesPage.css`, renaming every `outputs-` class prefix to `sources-` (e.g. `.outputs-page` → `.sources-page`, `.outputs-row--new` → `.sources-row--new`). The file is short (79 lines) — read it once, then write the renamed version in full; do not partially rename.

- [ ] **Step 2: Create `SourcesPage.tsx`**

```typescript
import { useEffect, useState } from "react";
import { listSources, createSource, updateSource, deleteSource } from "../api/sources";
import { ApiError } from "../api/client";
import type { Source } from "../types";
import "./SourcesPage.css";

interface Draft {
  name: string;
  kind: "camera_stream" | "static_image";
  value: string;
}

export default function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState<Draft["kind"]>("camera_stream");
  const [newValue, setNewValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function refresh() {
    listSources()
      .then((result) => {
        setSources(result);
        setDrafts(Object.fromEntries(result.map((s) => [s.id, { name: s.name, kind: s.kind, value: s.value }])));
        setError(null);
      })
      .catch(() => setError("Sources konden niet worden geladen."));
  }

  useEffect(() => {
    refresh();
  }, []);

  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 3000);
  }

  function updateDraft(id: number, patch: Partial<Draft>) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  async function handleCreate() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      await createSource({
        name: newName.trim(), kind: newKind, value: newValue.trim(), canvas_x: 0, canvas_y: 0,
      });
      setNewName("");
      setNewValue("");
      refresh();
      showNotice("Source aangemaakt.");
    } catch {
      setError("Aanmaken is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSave(id: number) {
    const draft = drafts[id];
    const existing = sources.find((s) => s.id === id);
    if (!draft || !existing) return;
    setSaving(true);
    try {
      await updateSource(id, { ...draft, canvas_x: existing.canvas_x, canvas_y: existing.canvas_y });
      refresh();
      showNotice("Source opgeslagen.");
    } catch {
      setError("Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Deze source verwijderen?")) return;
    setSaving(true);
    try {
      await deleteSource(id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Verwijderen is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="sources-page">
      <header className="sources-header">
        <p className="sources-eyebrow">
          <span className="sources-eyebrow__led" aria-hidden="true" />
          Beeldbronnen
        </p>
        <h1 className="sources-heading">Sources</h1>
      </header>

      {error && (
        <p className="sources-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="sources-notice" role="status">
          {notice}
        </p>
      )}

      <section className="sources-panel">
        {sources.map((source) => {
          const draft = drafts[source.id] ?? { name: source.name, kind: source.kind, value: source.value };
          return (
            <div className="sources-row" key={source.id}>
              <input
                className="sources-field__input"
                type="text"
                value={draft.name}
                onChange={(e) => updateDraft(source.id, { name: e.target.value })}
              />
              <select
                className="sources-field__input"
                value={draft.kind}
                onChange={(e) => updateDraft(source.id, { kind: e.target.value as Draft["kind"] })}
              >
                <option value="camera_stream">Camera-stream</option>
                <option value="static_image">Statische afbeelding</option>
              </select>
              <input
                className="sources-field__input sources-field__input--wide"
                type="text"
                value={draft.value}
                placeholder={draft.kind === "camera_stream" ? "bijv. rtsp://gebruiker:wachtwoord@192.168.1.50:554/stream1" : "media-hash van een geüploade afbeelding"}
                onChange={(e) => updateDraft(source.id, { value: e.target.value })}
              />
              <button type="button" onClick={() => handleSave(source.id)} disabled={saving}>
                Opslaan
              </button>
              <button type="button" onClick={() => handleDelete(source.id)} disabled={saving}>
                Verwijderen
              </button>
            </div>
          );
        })}

        <div className="sources-row sources-row--new">
          <input
            className="sources-field__input"
            type="text"
            placeholder="Naam (bijv. Tuincamera)"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <select
            className="sources-field__input"
            value={newKind}
            onChange={(e) => setNewKind(e.target.value as Draft["kind"])}
          >
            <option value="camera_stream">Camera-stream</option>
            <option value="static_image">Statische afbeelding</option>
          </select>
          <input
            className="sources-field__input sources-field__input--wide"
            type="text"
            placeholder="Camera-URL of media-hash"
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
          />
          <button type="button" onClick={handleCreate} disabled={saving || !newName.trim()}>
            + Source toevoegen
          </button>
        </div>
      </section>

      <p className="sources-field__label">
        Een source is een camera-stream of een statische afbeelding die je in de
        graaf aan een of meerdere players kunt koppelen. Een source met nog
        players eraan gekoppeld kan niet verwijderd worden.
      </p>
    </div>
  );
}
```

- [ ] **Step 3: Register the route and nav link**

In `admin/frontend/src/App.tsx`, add the import `import SourcesPage from "./pages/SourcesPage";` and the route `<Route path="/sources" element={<SourcesPage />} />` next to the existing `/outputs` route.

In `admin/frontend/src/components/Layout.tsx`, add `{ to: "/sources", label: "Sources", end: false }` to the `links` array, next to the existing `/outputs` entry.

- [ ] **Step 4: Manual verification**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: this file typechecks cleanly on its own merits (it doesn't depend on anything not yet updated). Full-project `tsc` still fails overall until Task 19 — that's expected at this point in the plan.

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/pages/SourcesPage.tsx admin/frontend/src/pages/SourcesPage.css admin/frontend/src/App.tsx admin/frontend/src/components/Layout.tsx
git commit -m "feat: Sources-pagina (CRUD voor camera-streams en statische afbeeldingen)"
```

---

### Task 15: `OutputsPage.tsx` — drop `camera_source`, keep canvas position server-managed

**Files:**
- Modify: `admin/frontend/src/pages/OutputsPage.tsx`

**Interfaces:**
- Consumes: `Output` type (Task 12, now carries `canvas_x`/`canvas_y`), `updateOutput`/`createOutput` (unchanged signatures, `OutputDraft` widened automatically).

- [ ] **Step 1: Remove the `camera_source` field from the form**

In `admin/frontend/src/pages/OutputsPage.tsx`:

- `Draft` interface: remove `camera_source: string`.
- `refresh()`: drop `camera_source: o.camera_source` from the `setDrafts` mapping.
- `newCameraSource`/`setNewCameraSource` state: remove entirely.
- `handleCreate`: change the `createOutput` call to `createOutput({ name: newName.trim(), camera_source: "", canvas_x: 0, canvas_y: 0 })` — `camera_source` stays in the API payload shape (the DB column isn't dropped, per the spec) but is no longer user-editable from this page, always sent empty on creation; `canvas_x`/`canvas_y` default to 0 here since the canvas itself is what actually positions a new output (dragging it in `PlayerGraphCanvas`, Task 17) once it appears as a graph node.
- `handleSave`: change the `updateOutput` call to preserve the existing row's `camera_source`/`canvas_x`/`canvas_y` (this page never edits them) by spreading from the found `output` object instead of `draft`: `updateOutput(id, { name: draft.name, camera_source: output.camera_source, canvas_x: output.canvas_x, canvas_y: output.canvas_y })` — `output` here is the same lookup pattern already used one line above for `draft`'s fallback (`outputs.find((o) => o.id === id)`, currently absent; add it: `const existing = outputs.find((o) => o.id === id); if (!draft || !existing) return;`).
- Remove the camera-bron `<input>` row (`className="outputs-field__input outputs-field__input--wide"` with the `rtsp://...` placeholder) from both the per-row rendering and the new-row form.
- Update the bottom `<p className="outputs-field__label">` copy: remove the "Leeg = de lokale camera..." sentence (no longer relevant here — camera source lives on Sources now); keep the rest about nodes/restart/delete-guard, updating "scenes" wording to "players" if present.

- [ ] **Step 2: Commit**

```bash
git add admin/frontend/src/pages/OutputsPage.tsx
git commit -m "feat: Outputs-pagina verliest camera-bron-veld (hoort nu bij Sources)"
```

---

### Task 16: `PlayerGraphCanvas.tsx` — four node types, branch dots, new connection rules

**The biggest frontend task in the plan — a full rewrite of the canvas component.** Read the current `admin/frontend/src/components/SceneGraphCanvas.tsx` and `SceneGraphCanvas.css` in full before starting (you have their content from this plan's research phase, but re-read to be certain nothing shifted). This task keeps the exact rename/color double-click pattern and the click/dblclick disambiguation `clickTimerRef` trick from the existing `SceneNodeComponent`/`TriggerNodeComponent` verbatim — do not redesign that part, only extend it.

**Files:**
- Modify: `admin/frontend/src/components/SceneGraphCanvas.tsx` → rename to `admin/frontend/src/components/PlayerGraphCanvas.tsx`
- Modify: `admin/frontend/src/components/SceneGraphCanvas.css` → rename to `admin/frontend/src/components/PlayerGraphCanvas.css`
- Modify: `admin/frontend/src/components/SceneGraphCanvas.test.tsx` → rename to `admin/frontend/src/components/PlayerGraphCanvas.test.tsx`

**Interfaces:**
- Consumes: `Player`/`Source`/`PlayerBranch`/`Trigger`/`Output`/`OutputConnection` types (Task 12), `players.ts`/`sources.ts`/`branches.ts`/`triggers.ts`/`outputs.ts`/`outputConnections.ts` APIs (Task 13).
- Produces: `PlayerGraphCanvas` component, `Props = { players, sources, branches, triggers, outputs, outputConnections, onPlayerClick, onGraphChanged, onAddPlayer }`.

- [ ] **Step 1: Rewrite the failing test file**

`git mv admin/frontend/src/components/SceneGraphCanvas.test.tsx admin/frontend/src/components/PlayerGraphCanvas.test.tsx`, then replace its contents:

```typescript
// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlayerGraphCanvas from "./PlayerGraphCanvas";
import type { Player } from "../types";

vi.mock("../api/triggers", () => ({
  createTrigger: vi.fn(),
  updateTrigger: vi.fn(),
  deleteTrigger: vi.fn(),
  updateTriggerPosition: vi.fn(),
}));
vi.mock("../api/players", () => ({
  updatePlayer: vi.fn(),
  updatePlayerPosition: vi.fn(),
}));
vi.mock("../api/sources", () => ({ updateSource: vi.fn() }));
vi.mock("../api/outputs", () => ({ updateOutput: vi.fn() }));
vi.mock("../api/branches", () => ({ createPlayerBranch: vi.fn() }));
vi.mock("../api/outputConnections", () => ({ createOutputConnection: vi.fn() }));

const PLAYER: Player = {
  id: 1,
  name: "Basis",
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
  is_root: true,
  canvas_x: 0,
  canvas_y: 0,
  color: null,
  source_id: null,
  playback_mode: "once",
  repeat_while_ha_entity_id: null,
};

describe("PlayerGraphCanvas -- klikken op een stap-chip", () => {
  it("roept onPlayerClick met de juiste stap aan bij klikken op de effect-chip", async () => {
    const onPlayerClick = vi.fn();
    render(
      <PlayerGraphCanvas
        players={[PLAYER]}
        sources={[]}
        branches={[]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={onPlayerClick}
        onGraphChanged={vi.fn()}
        onAddPlayer={vi.fn()}
      />,
    );

    const chip = await screen.findByText("xray");
    await userEvent.click(chip);

    expect(onPlayerClick).toHaveBeenCalledWith(1, "animation");
  });

  it("roept onPlayerClick met 'output' aan bij klikken op de Weergave-chip", async () => {
    const onPlayerClick = vi.fn();
    render(
      <PlayerGraphCanvas
        players={[PLAYER]}
        sources={[]}
        branches={[]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={onPlayerClick}
        onGraphChanged={vi.fn()}
        onAddPlayer={vi.fn()}
      />,
    );

    const chip = await screen.findByText("Weergave");
    await userEvent.click(chip);

    expect(onPlayerClick).toHaveBeenCalledWith(1, "output");
  });
});

describe("PlayerGraphCanvas -- branch-dots", () => {
  it("toont één aftakking-rij per branch van een player", async () => {
    render(
      <PlayerGraphCanvas
        players={[PLAYER]}
        sources={[]}
        branches={[{ id: 101, player_id: 1, name: "Uitgang 1" }, { id: 102, player_id: 1, name: "Extra" }]}
        triggers={[]}
        outputs={[]}
        outputConnections={[]}
        onPlayerClick={vi.fn()}
        onGraphChanged={vi.fn()}
        onAddPlayer={vi.fn()}
      />,
    );

    expect(await screen.findByText("Uitgang 1")).toBeInTheDocument();
    expect(await screen.findByText("Extra")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd admin/frontend && npx vitest run src/components/PlayerGraphCanvas.test.tsx`
Expected: FAIL — `PlayerGraphCanvas` module doesn't exist yet.

- [ ] **Step 3: Rename and rewrite the CSS file**

`git mv admin/frontend/src/components/SceneGraphCanvas.css admin/frontend/src/components/PlayerGraphCanvas.css`. Rename every `.scene-graph-canvas`/`.scene-node`/`.scene-node__*` class to `.player-graph-canvas`/`.player-node`/`.player-node__*` throughout the file (mechanical find-replace — the file's 211 lines of existing rules for layout/root-star/name-input/color-swatch/color-palette/chips/trigger-node all keep their exact same visual design, only the `scene-` prefix changes to `player-`; `.trigger-node` stays unchanged since it was never prefixed with `scene-`). Then append these new rule blocks at the end of the file:

```css
.player-node__branch {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.3rem;
  padding: 0.15rem 0.4rem;
  font-size: 0.7rem;
}

.player-node__branch-name {
  color: var(--ash);
}

.player-node__branch-add {
  border: none;
  background: transparent;
  color: var(--ash);
  cursor: pointer;
  font-size: 0.85rem;
  line-height: 1;
}

.source-node,
.output-node {
  position: relative;
  min-width: 120px;
  padding: 0.5rem 0.7rem;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 8px;
  color: var(--bone);
  font-size: 0.75rem;
}

.source-node__header,
.output-node__header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.source-node__icon,
.output-node__icon {
  font-size: 0.9rem;
}
```

- [ ] **Step 4: Rename and rewrite the component**

`git mv admin/frontend/src/components/SceneGraphCanvas.tsx admin/frontend/src/components/PlayerGraphCanvas.tsx`, then replace its contents in full:

```typescript
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { createTrigger, updateTrigger, updateTriggerPosition } from "../api/triggers";
import { updatePlayer, updatePlayerPosition } from "../api/players";
import { updateSource } from "../api/sources";
import { updateOutput } from "../api/outputs";
import { createPlayerBranch } from "../api/branches";
import { createOutputConnection } from "../api/outputConnections";
import TriggerPopover from "./TriggerPopover";
import type { Player, Source, PlayerBranch, Trigger, Output, OutputConnection } from "../types";
import "./PlayerGraphCanvas.css";

const NODE_COLORS = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c", "#3498db", "#9b59b6", "#95a5a6"];

interface Props {
  players: Player[];
  sources: Source[];
  branches: PlayerBranch[];
  triggers: Trigger[];
  outputs: Output[];
  outputConnections: OutputConnection[];
  onPlayerClick: (playerId: number, step: "input" | "animation" | "output") => void;
  onGraphChanged: () => void;
  onAddPlayer: () => void;
}

type PlayerNodeData = {
  player: Player;
  branches: PlayerBranch[];
  onPlayerClick: Props["onPlayerClick"];
  onAddBranchTrigger: (branchId: number) => void;
  onMakeRoot: (playerId: number) => void;
  onRename: (playerId: number, name: string) => void;
  onSetColor: (playerId: number, color: string) => void;
  [key: string]: unknown;
};

type SourceNodeData = { source: Source; [key: string]: unknown };
type OutputNodeData = { output: Output; [key: string]: unknown };

type TriggerNodeData = {
  trigger: Trigger;
  onTriggerClick: (triggerId: number) => void;
  onRename: (triggerId: number, name: string) => void;
  onSetColor: (triggerId: number, color: string) => void;
  [key: string]: unknown;
};

// @xyflow/react's Node<T> constrains T to Record<string, unknown>; the
// index signatures above satisfy that constraint for our data payloads.
type PlayerNode = Node<PlayerNodeData, "player">;
type SourceNode = Node<SourceNodeData, "source">;
type OutputNode = Node<OutputNodeData, "output">;
type TriggerNode = Node<TriggerNodeData, "trigger">;
type FlowNode = PlayerNode | SourceNode | OutputNode | TriggerNode;

function triggerKindLabel(trigger: Trigger): string {
  if (trigger.kind === "always") return "Altijd";
  if (trigger.kind === "motion") return "Beweging";
  if (trigger.kind === "schedule") return `${trigger.schedule_from ?? "?"}–${trigger.schedule_until ?? "?"}`;
  if (trigger.kind === "ha_sensor") return trigger.ha_entity_id ?? "HA-sensor";
  return "Nog niet ingesteld";
}

function PlayerNodeComponent({ data }: NodeProps<PlayerNode>) {
  const { player, branches, onPlayerClick, onAddBranchTrigger, onMakeRoot, onRename, onSetColor } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(player.name);
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const clickTimerRef = useRef<number | null>(null);

  function commitRename() {
    setEditingName(false);
    const trimmed = nameDraft.trim();
    if (trimmed && trimmed !== player.name) {
      onRename(player.id, trimmed);
    } else {
      setNameDraft(player.name);
    }
  }

  // ponytail: dblclick fires click+click+dblclick per DOM spec; delay the
  // single-click action so dblclick can cancel it before it opens the wizard.
  function handleNameClick() {
    if (clickTimerRef.current !== null) return;
    clickTimerRef.current = window.setTimeout(() => {
      onPlayerClick(player.id, "input");
      clickTimerRef.current = null;
    }, 250);
  }

  function handleNameDoubleClick() {
    if (clickTimerRef.current !== null) {
      window.clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
    setEditingName(true);
  }

  useEffect(() => {
    return () => {
      if (clickTimerRef.current !== null) {
        window.clearTimeout(clickTimerRef.current);
      }
    };
  }, []);

  return (
    <div
      className="player-node"
      data-root={player.is_root}
      style={player.color ? { borderColor: player.color } : undefined}
    >
      <Handle type="target" position={Position.Left} />
      <div className="player-node__header">
        <button
          type="button"
          className="player-node__root nodrag"
          onClick={() => onMakeRoot(player.id)}
          title="Maak root"
        >
          {player.is_root ? "★" : "☆"}
        </button>
        {editingName ? (
          <input
            className="player-node__name-input nodrag"
            autoFocus
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setNameDraft(player.name);
                setEditingName(false);
              }
            }}
          />
        ) : (
          <span
            className="player-node__name nodrag"
            onClick={handleNameClick}
            onDoubleClick={handleNameDoubleClick}
            title="Klik voor instellingen, dubbelklik om te hernoemen"
          >
            {player.name}
          </span>
        )}
        <button
          type="button"
          className="player-node__color-swatch nodrag"
          style={{ backgroundColor: player.color ?? "transparent" }}
          onClick={() => setColorPickerOpen((open) => !open)}
          title="Kleur"
          aria-label="Kleur kiezen"
        />
        {colorPickerOpen && (
          <div className="player-node__color-palette nodrag">
            {NODE_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className="player-node__color-option"
                style={{ backgroundColor: c }}
                onClick={() => {
                  onSetColor(player.id, c);
                  setColorPickerOpen(false);
                }}
                aria-label={`Kies kleur ${c}`}
              />
            ))}
          </div>
        )}
      </div>
      <div className="player-node__chips">
        <span className="player-node__chip nodrag" onClick={() => onPlayerClick(player.id, "input")}>
          {player.source_mode === "camera" ? "Camera" : "Scare-video"}
        </span>
        {player.source_mode === "camera" && (
          <>
            <span className="player-node__chip nodrag" onClick={() => onPlayerClick(player.id, "animation")}>
              {player.effect}
            </span>
            <span className="player-node__chip nodrag" onClick={() => onPlayerClick(player.id, "output")}>
              Weergave
            </span>
          </>
        )}
      </div>
      {branches.map((branch) => (
        <div className="player-node__branch" key={branch.id}>
          <span className="player-node__branch-name nodrag">{branch.name}</span>
          <button
            type="button"
            className="player-node__branch-add nodrag"
            onClick={() => onAddBranchTrigger(branch.id)}
            title="Nieuwe trigger vanaf deze aftakking"
          >
            +
          </button>
          <Handle type="source" position={Position.Right} id={`branch-${branch.id}`} />
        </div>
      ))}
    </div>
  );
}

function SourceNodeComponent({ data }: NodeProps<SourceNode>) {
  const { source } = data;
  return (
    <div className="source-node">
      <div className="source-node__header">
        <span className="source-node__icon">{source.kind === "camera_stream" ? "📷" : "🖼"}</span>
        <span className="source-node__name">{source.name}</span>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function OutputNodeComponent({ data }: NodeProps<OutputNode>) {
  const { output } = data;
  return (
    <div className="output-node">
      <Handle type="target" position={Position.Left} />
      <div className="output-node__header">
        <span className="output-node__icon">🖥</span>
        <span className="output-node__name">{output.name}</span>
      </div>
    </div>
  );
}

function TriggerNodeComponent({ data }: NodeProps<TriggerNode>) {
  const { trigger, onTriggerClick, onRename, onSetColor } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(trigger.name ?? "");
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const clickTimerRef = useRef<number | null>(null);

  function commitRename() {
    setEditingName(false);
    const trimmed = nameDraft.trim();
    if (trimmed !== (trigger.name ?? "")) {
      onRename(trigger.id, trimmed);
    }
  }

  // ponytail: same click/dblclick disambiguation as PlayerNodeComponent --
  // dblclick fires click+click+dblclick per DOM spec, so a plain onClick
  // would also fire (and open the popover) on every double-click-to-rename.
  function handleNameClick() {
    if (clickTimerRef.current !== null) return;
    clickTimerRef.current = window.setTimeout(() => {
      onTriggerClick(trigger.id);
      clickTimerRef.current = null;
    }, 250);
  }

  function handleNameDoubleClick() {
    if (clickTimerRef.current !== null) {
      window.clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }
    setEditingName(true);
  }

  useEffect(() => {
    return () => {
      if (clickTimerRef.current !== null) {
        window.clearTimeout(clickTimerRef.current);
      }
    };
  }, []);

  return (
    <div
      className="trigger-node"
      style={trigger.color ? { borderColor: trigger.color } : undefined}
    >
      <Handle type="target" position={Position.Left} />
      <div className="trigger-node__header">
        {editingName ? (
          <input
            className="trigger-node__name-input nodrag"
            autoFocus
            value={nameDraft}
            placeholder={triggerKindLabel(trigger)}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setNameDraft(trigger.name ?? "");
                setEditingName(false);
              }
            }}
          />
        ) : (
          <span
            className="trigger-node__name nodrag"
            onClick={handleNameClick}
            onDoubleClick={handleNameDoubleClick}
            title="Klik om de trigger in te stellen, dubbelklik om te hernoemen"
          >
            {trigger.name ?? triggerKindLabel(trigger)}
          </span>
        )}
        <button
          type="button"
          className="trigger-node__color-swatch nodrag"
          style={{ backgroundColor: trigger.color ?? "transparent" }}
          onClick={() => setColorPickerOpen((open) => !open)}
          title="Kleur"
          aria-label="Kleur kiezen"
        />
        {colorPickerOpen && (
          <div className="trigger-node__color-palette nodrag">
            {NODE_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className="trigger-node__color-option"
                style={{ backgroundColor: c }}
                onClick={() => {
                  onSetColor(trigger.id, c);
                  setColorPickerOpen(false);
                }}
                aria-label={`Kies kleur ${c}`}
              />
            ))}
          </div>
        )}
      </div>
      {trigger.name && <span className="trigger-node__kind">{triggerKindLabel(trigger)}</span>}
      <Handle type="source" position={Position.Right} id="out" />
    </div>
  );
}

const nodeTypes = {
  player: PlayerNodeComponent,
  source: SourceNodeComponent,
  output: OutputNodeComponent,
  trigger: TriggerNodeComponent,
};

export default function PlayerGraphCanvas({
  players, sources, branches, triggers, outputs, outputConnections, onPlayerClick, onGraphChanged, onAddPlayer,
}: Props) {
  const [popoverTrigger, setPopoverTrigger] = useState<Trigger | null>(null);

  const branchToPlayer = useMemo(
    () => Object.fromEntries(branches.map((b) => [b.id, b.player_id])),
    [branches],
  );

  const handleAddBranchTrigger = useCallback(
    async (branchId: number) => {
      await createTrigger({ from_branch_id: branchId });
      onGraphChanged();
    },
    [onGraphChanged],
  );

  const handleMakeRoot = useCallback(
    async (playerId: number) => {
      const player = players.find((p) => p.id === playerId);
      if (!player) return;
      const { id: _id, ...draft } = player;
      await updatePlayer(playerId, { ...draft, is_root: true });
      onGraphChanged();
    },
    [players, onGraphChanged],
  );

  const handleRenamePlayer = useCallback(
    async (playerId: number, name: string) => {
      const player = players.find((p) => p.id === playerId);
      if (!player) return;
      const { id: _id, ...draft } = player;
      await updatePlayer(playerId, { ...draft, name });
      onGraphChanged();
    },
    [players, onGraphChanged],
  );

  const handleSetPlayerColor = useCallback(
    async (playerId: number, color: string) => {
      const player = players.find((p) => p.id === playerId);
      if (!player) return;
      const { id: _id, ...draft } = player;
      await updatePlayer(playerId, { ...draft, color });
      onGraphChanged();
    },
    [players, onGraphChanged],
  );

  const handleTriggerClick = useCallback(
    (triggerId: number) => {
      const trigger = triggers.find((t) => t.id === triggerId);
      if (trigger) setPopoverTrigger(trigger);
    },
    [triggers],
  );

  const handleRenameTrigger = useCallback(
    async (triggerId: number, name: string) => {
      const trigger = triggers.find((t) => t.id === triggerId);
      if (!trigger) return;
      const { id: _id, ...draft } = trigger;
      await updateTrigger(triggerId, { ...draft, name: name || null });
      onGraphChanged();
    },
    [triggers, onGraphChanged],
  );

  const handleSetTriggerColor = useCallback(
    async (triggerId: number, color: string) => {
      const trigger = triggers.find((t) => t.id === triggerId);
      if (!trigger) return;
      const { id: _id, ...draft } = trigger;
      await updateTrigger(triggerId, { ...draft, color });
      onGraphChanged();
    },
    [triggers, onGraphChanged],
  );

  const flowNodes: FlowNode[] = useMemo(
    () => [
      ...players.map(
        (player): PlayerNode => ({
          id: `player-${player.id}`,
          type: "player",
          position: { x: player.canvas_x, y: player.canvas_y },
          data: {
            player,
            branches: branches.filter((b) => b.player_id === player.id),
            onPlayerClick,
            onAddBranchTrigger: handleAddBranchTrigger,
            onMakeRoot: handleMakeRoot,
            onRename: handleRenamePlayer,
            onSetColor: handleSetPlayerColor,
          },
        }),
      ),
      ...sources.map(
        (source): SourceNode => ({
          id: `source-${source.id}`,
          type: "source",
          position: { x: source.canvas_x, y: source.canvas_y },
          data: { source },
        }),
      ),
      ...outputs.map(
        (output): OutputNode => ({
          id: `output-${output.id}`,
          type: "output",
          position: { x: output.canvas_x, y: output.canvas_y },
          data: { output },
        }),
      ),
      ...triggers.map(
        (trigger): TriggerNode => ({
          id: `trigger-${trigger.id}`,
          type: "trigger",
          position: { x: trigger.canvas_x, y: trigger.canvas_y },
          data: {
            trigger,
            onTriggerClick: handleTriggerClick,
            onRename: handleRenameTrigger,
            onSetColor: handleSetTriggerColor,
          },
        }),
      ),
    ],
    [
      players, sources, outputs, triggers, branches,
      onPlayerClick, handleAddBranchTrigger, handleMakeRoot, handleRenamePlayer, handleSetPlayerColor,
      handleTriggerClick, handleRenameTrigger, handleSetTriggerColor,
    ],
  );

  const flowEdges: Edge[] = useMemo(() => {
    const result: Edge[] = [];
    for (const player of players) {
      if (player.source_id !== null) {
        result.push({
          id: `source-in-${player.id}`,
          source: `source-${player.source_id}`,
          target: `player-${player.id}`,
        });
      }
    }
    for (const trigger of triggers) {
      const fromPlayerId = branchToPlayer[trigger.from_branch_id];
      if (fromPlayerId !== undefined) {
        result.push({
          id: `branch-in-${trigger.id}`,
          source: `player-${fromPlayerId}`,
          sourceHandle: `branch-${trigger.from_branch_id}`,
          target: `trigger-${trigger.id}`,
        });
      }
      if (trigger.to_player_id !== null) {
        result.push({
          id: `out-${trigger.id}`,
          source: `trigger-${trigger.id}`,
          sourceHandle: "out",
          target: `player-${trigger.to_player_id}`,
          markerEnd: { type: MarkerType.ArrowClosed },
        });
      }
    }
    for (const oc of outputConnections) {
      const fromPlayerId = branchToPlayer[oc.from_branch_id];
      if (fromPlayerId !== undefined) {
        result.push({
          id: `oc-${oc.id}`,
          source: `player-${fromPlayerId}`,
          sourceHandle: `branch-${oc.from_branch_id}`,
          target: `output-${oc.output_id}`,
          markerEnd: { type: MarkerType.ArrowClosed },
        });
      }
    }
    return result;
  }, [players, triggers, outputConnections, branchToPlayer]);

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(flowNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(flowEdges);

  // Houdt de React Flow-state in sync zodra players/sources/etc. van de
  // server opnieuw binnenkomen (na een CRUD-actie elders) -- useNodesState/
  // useEdgesState gebruiken hun argument alleen als initiele waarde
  // (zoals useState), en houden verder hun eigen interne sleep-state bij
  // tussen renders.
  useEffect(() => {
    setNodes(flowNodes);
  }, [flowNodes, setNodes]);

  useEffect(() => {
    setRfEdges(flowEdges);
  }, [flowEdges, setRfEdges]);

  const handleConnect = useCallback(
    async (connection: Connection) => {
      if (connection.source?.startsWith("source-") && connection.target?.startsWith("player-")) {
        const sourceId = parseInt(connection.source.replace("source-", ""), 10);
        const playerId = parseInt(connection.target.replace("player-", ""), 10);
        if (Number.isNaN(sourceId) || Number.isNaN(playerId)) return;
        const player = players.find((p) => p.id === playerId);
        if (!player) return;
        const { id: _id, ...draft } = player;
        await updatePlayer(playerId, { ...draft, source_id: sourceId });
        onGraphChanged();
        return;
      }
      if (connection.source?.startsWith("trigger-") && connection.target?.startsWith("player-")) {
        const triggerId = parseInt(connection.source.replace("trigger-", ""), 10);
        const playerId = parseInt(connection.target.replace("player-", ""), 10);
        if (Number.isNaN(triggerId) || Number.isNaN(playerId)) return;
        const trigger = triggers.find((t) => t.id === triggerId);
        if (!trigger) return;
        const { id: _id, ...draft } = trigger;
        await updateTrigger(triggerId, { ...draft, to_player_id: playerId });
        onGraphChanged();
        return;
      }
      if (
        connection.source?.startsWith("player-") &&
        connection.sourceHandle?.startsWith("branch-") &&
        connection.target?.startsWith("output-")
      ) {
        const branchId = parseInt(connection.sourceHandle.replace("branch-", ""), 10);
        const outputId = parseInt(connection.target.replace("output-", ""), 10);
        if (Number.isNaN(branchId) || Number.isNaN(outputId)) return;
        await createOutputConnection(outputId, branchId);
        onGraphChanged();
      }
    },
    [players, triggers, onGraphChanged],
  );

  const handleNodeDragStop = useCallback(
    async (_event: unknown, node: FlowNode) => {
      if (node.id.startsWith("player-")) {
        await updatePlayerPosition(parseInt(node.id.replace("player-", ""), 10), node.position.x, node.position.y);
      } else if (node.id.startsWith("trigger-")) {
        await updateTriggerPosition(parseInt(node.id.replace("trigger-", ""), 10), node.position.x, node.position.y);
      } else if (node.id.startsWith("source-")) {
        const sourceId = parseInt(node.id.replace("source-", ""), 10);
        const source = sources.find((s) => s.id === sourceId);
        if (source) {
          const { id: _id, ...draft } = source;
          await updateSource(sourceId, { ...draft, canvas_x: node.position.x, canvas_y: node.position.y });
        }
      } else if (node.id.startsWith("output-")) {
        const outputId = parseInt(node.id.replace("output-", ""), 10);
        const output = outputs.find((o) => o.id === outputId);
        if (output) {
          const { id: _id, ...draft } = output;
          await updateOutput(outputId, { ...draft, canvas_x: node.position.x, canvas_y: node.position.y });
        }
      }
      // Elke branch hierboven roept onGraphChanged() aan zodra de save
      // klaar is -- zonder dit blijven players/sources/outputs in de
      // parent op de PRE-drag canvas_x/canvas_y staan, en zou de
      // eerstvolgende hernoem/kleur/kind-save de net-gesleepte positie
      // stilletjes weer terugzetten (zelfde les als eerder al gefixt
      // voor players/triggers -- nu structureel voor alle 4 knooptypes).
      onGraphChanged();
    },
    [onGraphChanged, sources, outputs],
  );

  return (
    <div className="player-graph-canvas">
      <ReactFlow
        nodes={nodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={handleConnect}
        onNodeDragStop={handleNodeDragStop}
        fitView
      >
        <Background />
        <Controls />
      </ReactFlow>
      <button type="button" className="player-graph-canvas__add" onClick={onAddPlayer}>
        + Nieuwe player
      </button>
      {popoverTrigger && (
        <TriggerPopover
          trigger={popoverTrigger}
          onClose={() => setPopoverTrigger(null)}
          onSaved={onGraphChanged}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run the frontend test suite**

Run: `cd admin/frontend && npm test`
Expected: PASS for `PlayerGraphCanvas.test.tsx`. Other files (`SceneWizardModal`, `DashboardPage`) still reference the old names and won't compile yet as part of a full `tsc` — that's expected until Tasks 17-18. Vitest itself only type-checks the files it imports for a given test file, so `PlayerGraphCanvas.test.tsx` passing on its own is the correct bar for this task.

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/components/PlayerGraphCanvas.tsx admin/frontend/src/components/PlayerGraphCanvas.css admin/frontend/src/components/PlayerGraphCanvas.test.tsx
git rm admin/frontend/src/components/SceneGraphCanvas.tsx admin/frontend/src/components/SceneGraphCanvas.css admin/frontend/src/components/SceneGraphCanvas.test.tsx
git commit -m "feat: PlayerGraphCanvas -- vier knooptypes (player/source/trigger/output), branch-dots, nieuwe verbindingsregels"
```

---

### Task 17: `PlayerWizardModal.tsx` — Bron/Afspelen tabs + aftakkingen-beheer

**Files:**
- Modify: `admin/frontend/src/components/SceneWizardModal.tsx` → rename to `admin/frontend/src/components/PlayerWizardModal.tsx`
- Modify: `admin/frontend/src/components/SceneWizardModal.css` → rename to `admin/frontend/src/components/PlayerWizardModal.css` (class-prefix rename only, `scene-modal` → `player-modal`, same mechanical pattern as Task 16's CSS rename — no new rules needed beyond a small addition for the branches list, given below)
- Modify: `admin/frontend/src/components/PreviewPanel.tsx` (type import + stale comment wording)

**Interfaces:**
- Consumes: `PlayerDraft`, `listSources`/`getSource` (sources.ts), `listPlayerBranches`/`createPlayerBranch`/`updatePlayerBranch`/`deletePlayerBranch` (branches.ts), `getHaStates` (existing `api/ha.ts`).
- Produces: `PlayerWizardModal` component with steps `input`/`source`/`animation`/`output`/`playback`/`branches` (camera-mode players see `input, source, animation, output, branches`; scare_video-mode players see `input, playback, branches`).

- [ ] **Step 1: Rename and rewrite the CSS file**

`git mv admin/frontend/src/components/SceneWizardModal.css admin/frontend/src/components/PlayerWizardModal.css`. Read it first, then rename every `scene-modal` class prefix to `player-modal` throughout (mechanical, same pattern as Task 16). Append these new rules for the branches tab:

```css
.player-modal__branch-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.player-modal__branch-row input {
  flex: 1;
}
```

- [ ] **Step 2: Rename and rewrite the component**

`git mv admin/frontend/src/components/SceneWizardModal.tsx admin/frontend/src/components/PlayerWizardModal.tsx`, then replace its contents in full:

```typescript
import { useEffect, useState } from "react";
import { getPlayer, createPlayer, updatePlayer, deletePlayer, type PlayerDraft } from "../api/players";
import { listSources, getSource } from "../api/sources";
import { listPlayerBranches, createPlayerBranch, updatePlayerBranch, deletePlayerBranch } from "../api/branches";
import { getHaStates } from "../api/ha";
import MediaLibrary from "./MediaLibrary";
import OverlayCanvas from "./OverlayCanvas";
import PreviewPanel from "./PreviewPanel";
import type { Player, Source, PlayerBranch, HaState } from "../types";
import "./PlayerWizardModal.css";

const EFFECTS = ["xray", "thermal", "contour", "posterize"] as const;
const FIELD_LABELS: Record<string, string> = {
  intensity: "Intensiteit",
  threshold1: "Drempel 1",
  threshold2: "Drempel 2",
  levels: "Niveaus",
};

function paramFieldsFor(effect: Player["effect"]): string[] {
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

const EMPTY_DRAFT: PlayerDraft = {
  name: "Nieuwe player",
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
  color: null,
  source_id: null,
  playback_mode: "once",
  repeat_while_ha_entity_id: null,
};

interface Props {
  playerId: number | null;
  initialStep?: Step;
  onClose: () => void;
  onSaved: () => void;
}

type Step = "input" | "source" | "animation" | "output" | "playback" | "branches";
const STEP_LABEL: Record<Step, string> = {
  input: "Input",
  source: "Bron",
  animation: "Animatie",
  // "Weergave" i.p.v. "Output" -- dit is de canvas-/overlay-plaatsingsstap,
  // niet te verwarren met het nieuwe Output-knooptype in de graaf.
  output: "Weergave",
  playback: "Afspelen",
  branches: "Aftakkingen",
};

export default function PlayerWizardModal({ playerId, initialStep, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<PlayerDraft>(EMPTY_DRAFT);
  const [step, setStep] = useState<Step>(initialStep ?? "input");
  const [cameraSource, setCameraSource] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [canvasWidthDraft, setCanvasWidthDraft] = useState("");
  const [canvasHeightDraft, setCanvasHeightDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [haStates, setHaStates] = useState<HaState[]>([]);
  const [haLoadError, setHaLoadError] = useState(false);
  const [showAllDomains, setShowAllDomains] = useState(false);
  const [branches, setBranches] = useState<PlayerBranch[]>([]);
  const [newBranchName, setNewBranchName] = useState("");

  useEffect(() => {
    if (playerId !== null) {
      getPlayer(playerId)
        .then((player) => {
          setDraft(player);
          setCanvasWidthDraft(player.canvas_size ? String(player.canvas_size[0]) : "");
          setCanvasHeightDraft(player.canvas_size ? String(player.canvas_size[1]) : "");
        })
        .catch(() => setError("Player kon niet worden geladen."));
    }
  }, [playerId]);

  useEffect(() => {
    listSources()
      .then(setSources)
      .catch(() => {
        /* Bron-dropdown blijft dan leeg -- opslaan blijft mogelijk zonder gekozen bron */
      });
  }, []);

  useEffect(() => {
    if (draft.source_id === null) {
      setCameraSource("");
      return;
    }
    getSource(draft.source_id)
      .then((source) => setCameraSource(source.kind === "camera_stream" ? source.value : ""))
      .catch(() => {
        /* voorbeeldbeeld blijft dan "niet beschikbaar" */
      });
  }, [draft.source_id]);

  useEffect(() => {
    if (draft.playback_mode !== "repeat_while") return;
    getHaStates()
      .then(setHaStates)
      .catch(() => setHaLoadError(true));
  }, [draft.playback_mode]);

  function refreshBranches() {
    if (playerId === null) return;
    listPlayerBranches(playerId)
      .then(setBranches)
      .catch(() => setError("Aftakkingen konden niet worden geladen."));
  }

  useEffect(() => {
    if (step === "branches") refreshBranches();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, playerId]);

  const [previewOpen, setPreviewOpen] = useState(false);

  function update(patch: Partial<PlayerDraft>) {
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
      if (playerId === null) {
        await createPlayer(draft);
      } else {
        await updatePlayer(playerId, draft);
      }
      onSaved();
      onClose();
    } catch {
      setError("Opslaan is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (playerId === null) return;
    if (!window.confirm(`Player "${draft.name}" verwijderen? Dit kan niet ongedaan worden gemaakt.`)) return;
    setSaving(true);
    try {
      await deletePlayer(playerId);
      onSaved();
      onClose();
    } catch {
      setError("Verwijderen is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddBranch() {
    if (playerId === null || !newBranchName.trim()) return;
    await createPlayerBranch(playerId, newBranchName.trim());
    setNewBranchName("");
    refreshBranches();
  }

  async function handleRenameBranch(branchId: number, name: string) {
    await updatePlayerBranch(branchId, name);
    refreshBranches();
  }

  async function handleDeleteBranch(branchId: number) {
    try {
      await deletePlayerBranch(branchId);
      refreshBranches();
    } catch {
      setError("Aftakking verwijderen is mislukt -- heeft die nog een trigger of output-verbinding?");
    }
  }

  const steps: Step[] =
    draft.source_mode === "camera" ? ["input", "source", "animation", "output", "branches"] : ["input", "playback", "branches"];
  const stepIndex = steps.indexOf(step);

  return (
    <div className="player-modal__backdrop" role="dialog" aria-modal="true">
      <div className="player-modal">
        <header className="player-modal__header">
          <input
            className="player-modal__name"
            type="text"
            value={draft.name}
            onChange={(e) => update({ name: e.target.value })}
            placeholder="Naam van deze player"
          />
          <button className="player-modal__close" type="button" onClick={onClose} aria-label="Sluiten">
            ×
          </button>
          {draft.source_mode === "camera" && (
            <button
              type="button"
              className="player-modal__preview-toggle"
              onClick={() => setPreviewOpen((open) => !open)}
            >
              {previewOpen ? "Preview verbergen" : "Preview"}
            </button>
          )}
        </header>

        <nav className="player-modal__steps">
          {steps.map((s, i) => (
            <span key={s} className="player-modal__step" data-active={s === step} data-done={i < stepIndex}>
              {i + 1}. {STEP_LABEL[s]}
            </span>
          ))}
        </nav>

        {error && (
          <p className="player-modal__error" role="alert">
            {error}
          </p>
        )}

        <div className="player-modal__body">
          {step === "input" && (
            <div className="player-modal__field-group">
              <label className="player-modal__radio">
                <input
                  type="radio"
                  name="source_mode"
                  checked={draft.source_mode === "camera"}
                  onChange={() => update({ source_mode: "camera" })}
                />
                Live camera-bron
              </label>
              <label className="player-modal__radio">
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

          {step === "source" && (
            <div className="player-modal__field-group">
              <label className="player-modal__field">
                <span>Source</span>
                <select
                  value={draft.source_id ?? ""}
                  onChange={(e) => update({ source_id: e.target.value ? parseInt(e.target.value, 10) : null })}
                >
                  <option value="">— gebruik de eerste/enige source —</option>
                  {sources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.name} ({source.kind === "camera_stream" ? "camera" : "afbeelding"})
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}

          {step === "animation" && (
            <>
              <div className="player-modal__field-group">
                <label className="player-modal__field">
                  <span>Effect</span>
                  <select
                    value={draft.effect}
                    onChange={(e) => update({ effect: e.target.value as Player["effect"], params: {} })}
                  >
                    {EFFECTS.map((effect) => (
                      <option key={effect} value={effect}>
                        {effect}
                      </option>
                    ))}
                  </select>
                </label>
                {paramFieldsFor(draft.effect).map((field) => (
                  <label className="player-modal__field" key={field}>
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
              <p className="player-modal__label">Overlay</p>
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
              <div className="player-modal__field-group">
                <label className="player-modal__field">
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
                <label className="player-modal__field">
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
                <p className="player-modal__label">
                  Geen camera-source gekozen op de Bron-stap (of de gekozen source is een statische
                  afbeelding) — kan hier niet getoond worden.
                </p>
              )}
            </>
          )}

          {step === "playback" && (
            <div className="player-modal__field-group">
              <label className="player-modal__radio">
                <input
                  type="radio"
                  name="playback_mode"
                  checked={draft.playback_mode === "once"}
                  onChange={() => update({ playback_mode: "once" })}
                />
                1x afspelen
              </label>
              <label className="player-modal__radio">
                <input
                  type="radio"
                  name="playback_mode"
                  checked={draft.playback_mode === "repeat_once"}
                  onChange={() => update({ playback_mode: "repeat_once" })}
                />
                Eenmaal herhalen (2x totaal)
              </label>
              <label className="player-modal__radio">
                <input
                  type="radio"
                  name="playback_mode"
                  checked={draft.playback_mode === "repeat_while"}
                  onChange={() => update({ playback_mode: "repeat_while" })}
                />
                Herhalen zolang een sensor actief is
              </label>
              {draft.playback_mode === "repeat_while" && (
                <div className="player-modal__field-group">
                  {haLoadError && <p className="player-modal__error">HA-entiteiten konden niet geladen worden.</p>}
                  <label className="player-modal__field">
                    <span>Sensor</span>
                    <select
                      value={draft.repeat_while_ha_entity_id ?? ""}
                      onChange={(e) => update({ repeat_while_ha_entity_id: e.target.value || null })}
                    >
                      <option value="">— kies een entiteit —</option>
                      {haStates
                        .filter((s) => showAllDomains || s.entity_id.startsWith("binary_sensor."))
                        .map((s) => (
                          <option key={s.entity_id} value={s.entity_id}>
                            {s.entity_id} ({s.state})
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="player-modal__radio">
                    <input
                      type="checkbox"
                      checked={showAllDomains}
                      onChange={(e) => setShowAllDomains(e.target.checked)}
                    />
                    Toon alle entiteiten (niet alleen binary_sensor)
                  </label>
                </div>
              )}
            </div>
          )}

          {step === "branches" && (
            <div className="player-modal__field-group">
              {playerId === null ? (
                <p className="player-modal__label">Sla deze player eerst op om aftakkingen te beheren.</p>
              ) : (
                <>
                  {branches.map((branch) => (
                    <div className="player-modal__branch-row" key={branch.id}>
                      <input
                        type="text"
                        defaultValue={branch.name}
                        onBlur={(e) => {
                          if (e.target.value.trim() && e.target.value !== branch.name) {
                            handleRenameBranch(branch.id, e.target.value.trim());
                          }
                        }}
                      />
                      <button type="button" onClick={() => handleDeleteBranch(branch.id)}>
                        Verwijderen
                      </button>
                    </div>
                  ))}
                  <div className="player-modal__branch-row">
                    <input
                      type="text"
                      placeholder="Naam nieuwe aftakking"
                      value={newBranchName}
                      onChange={(e) => setNewBranchName(e.target.value)}
                    />
                    <button type="button" onClick={handleAddBranch} disabled={!newBranchName.trim()}>
                      + Aftakking
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        <footer className="player-modal__footer">
          {playerId !== null && (
            <button type="button" className="player-modal__delete" disabled={saving} onClick={handleDelete}>
              Verwijderen
            </button>
          )}
          <button
            type="button"
            className="player-modal__nav"
            disabled={stepIndex === 0}
            onClick={() => setStep(steps[stepIndex - 1])}
          >
            Vorige
          </button>
          {stepIndex < steps.length - 1 ? (
            <button type="button" className="player-modal__nav" onClick={() => setStep(steps[stepIndex + 1])}>
              Volgende
            </button>
          ) : (
            <button type="button" className="player-modal__save" disabled={saving} onClick={handleSave}>
              {saving ? "Bezig…" : "Opslaan"}
            </button>
          )}
        </footer>
      </div>
      {previewOpen && draft.source_mode === "camera" && (
        <PreviewPanel draft={draft} onClose={() => setPreviewOpen(false)} />
      )}
    </div>
  );
}
```

Note: the previous file's `loaded`/`setLoaded` dead state (parked as a known Minor since the prior feature) is dropped entirely in this rewrite rather than carried forward — it was unused there too, and this task already touches every line of the file.

- [ ] **Step 3: Update `PreviewPanel.tsx`**

Change `import type { SceneDraft } from "../api/scenes";` to `import type { PlayerDraft } from "../api/players";`, and `Props.draft: SceneDraft` to `Props.draft: PlayerDraft`. Update the comment above the `fetch` call and the `alt` text on line ~83 (`alt="Voorbeeld van de scene"` → `alt="Voorbeeld van de player"`) — both are stale "scene" wording, no functional change.

- [ ] **Step 4: Manual verification**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: this file and its direct dependents typecheck cleanly. The only remaining `tsc` errors project-wide at this point should be in `DashboardPage.tsx` (Task 18).

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/components/PlayerWizardModal.tsx admin/frontend/src/components/PlayerWizardModal.css admin/frontend/src/components/PreviewPanel.tsx
git rm admin/frontend/src/components/SceneWizardModal.tsx admin/frontend/src/components/SceneWizardModal.css
git commit -m "feat: PlayerWizardModal -- Bron/Afspelen-tabs + aftakkingen-beheer"
```

---

### Task 18: `DashboardPage.tsx` wiring + final integration sweep

**Files:**
- Modify: `admin/app/routers/players.py` (add an unscoped `GET /api/branches` list route — the dashboard needs every branch across every player in one call, not one player at a time)
- Modify: `admin/frontend/src/api/branches.ts` (add `listAllBranches`)
- Modify: `admin/frontend/src/pages/DashboardPage.tsx`
- Test: `tests/test_admin_routes_players.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 12-17.
- Produces: `GET /api/branches` (all branches, unscoped), `listAllBranches(): Promise<PlayerBranch[]>`, a fully wired `DashboardPage` rendering `PlayerGraphCanvas` and `PlayerWizardModal`.

This is also the point where the whole project should typecheck and both test suites should pass end-to-end — treat Step 6 below as the real gate for this entire plan, not just this task.

- [ ] **Step 1: Write the failing backend test**

Append to `tests/test_admin_routes_players.py`:

```python
def test_list_all_branches_across_players(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "B"}).json()

    response = client.get("/api/branches")

    assert response.status_code == 200
    player_ids = {branch["player_id"] for branch in response.json()}
    assert player_ids == {a["id"], b["id"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py -k all_branches -v`
Expected: FAIL — 404, no such route.

- [ ] **Step 3: Add the route**

In `admin/app/routers/players.py`, add above `list_player_branches_route`:

```python
@router.get("/api/branches")
def list_all_branches_route(request: Request):
    rows = request.app.state.db.execute(f"SELECT {_BRANCH_COLUMNS} FROM player_branches ORDER BY id").fetchall()
    return [_row_to_branch(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py -v`
Expected: PASS (full file).

- [ ] **Step 5: Add `listAllBranches` to the frontend API layer**

In `admin/frontend/src/api/branches.ts`, add:

```typescript
export function listAllBranches(): Promise<PlayerBranch[]> {
  return apiFetch<PlayerBranch[]>("/api/branches");
}
```

- [ ] **Step 6: Rewrite `admin/frontend/src/pages/DashboardPage.tsx`**

Update the imports:

```typescript
import { listPlayers } from "../api/players";
import { listSources } from "../api/sources";
import { listAllBranches } from "../api/branches";
import { listTriggers } from "../api/triggers";
import { listOutputs } from "../api/outputs";
import { listOutputConnections } from "../api/outputConnections";
import PlayerWizardModal from "../components/PlayerWizardModal";
import PlayerGraphCanvas from "../components/PlayerGraphCanvas";
import type { NodeStatusMap, Schedule, Player, Source, PlayerBranch, Trigger, Output, OutputConnection, WsMessage } from "../types";
```

(Replacing the old `listScenes`/`SceneWizardModal`/`SceneGraphCanvas`/`Scene` imports — `listTriggers`'s import path is unchanged, only what it returns changed shape back in Task 4/7.)

Update the state declarations:

```typescript
  const [players, setPlayers] = useState<Player[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [branches, setBranches] = useState<PlayerBranch[]>([]);
  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [outputConnections, setOutputConnections] = useState<OutputConnection[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardPlayerId, setWizardPlayerId] = useState<number | null>(null);
  const [wizardInitialStep, setWizardInitialStep] = useState<"input" | "animation" | "output">("input");
```

(Replacing `scenes`/`setScenes`, `wizardSceneId`/`setWizardSceneId` — every other state declaration in the file is untouched.)

Replace `refreshScenes`:

```typescript
  function refreshGraph() {
    listPlayers()
      .then(setPlayers)
      .catch(() => setError("Players konden niet worden geladen."));
    listSources()
      .then(setSources)
      .catch(() => setError("Sources konden niet worden geladen."));
    listAllBranches()
      .then(setBranches)
      .catch(() => setError("Aftakkingen konden niet worden geladen."));
    listTriggers()
      .then(setTriggers)
      .catch(() => setError("Triggers konden niet worden geladen."));
    listOutputs()
      .then(setOutputs)
      .catch(() => setError("Outputs konden niet worden geladen."));
    listOutputConnections()
      .then(setOutputConnections)
      .catch(() => setError("Output-verbindingen konden niet worden geladen."));
  }
```

Update the `useEffect` call site: `refreshScenes();` → `refreshGraph();`.

Update `openWizard`:

```typescript
  function openWizard(id: number | null, step: "input" | "animation" | "output" = "input") {
    setWizardPlayerId(id);
    setWizardInitialStep(step);
    setWizardOpen(true);
  }
```

Update the canvas render block:

```typescript
      <section className="dash-panel">
        <p className="dash-panel__eyebrow">Players</p>
        <PlayerGraphCanvas
          players={players}
          sources={sources}
          branches={branches}
          triggers={triggers}
          outputs={outputs}
          outputConnections={outputConnections}
          onPlayerClick={(id, step) => openWizard(id, step)}
          onGraphChanged={refreshGraph}
          onAddPlayer={() => openWizard(null)}
        />
      </section>
```

Update the modal render block:

```typescript
      {wizardOpen && (
        <PlayerWizardModal
          playerId={wizardPlayerId}
          initialStep={wizardInitialStep}
          onClose={() => setWizardOpen(false)}
          onSaved={refreshGraph}
        />
      )}
```

Every other section of the file (nodes grid, mirror-process controls, emergency stop, schedule form, WebSocket handling) is untouched — this task only touches the graph-related imports, state, and the two render blocks above.

- [ ] **Step 7: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, zero failures.

- [ ] **Step 8: Run the full frontend suite**

Run: `cd admin/frontend && npm test`
Expected: PASS, zero failures.

- [ ] **Step 9: Run the full frontend typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: zero errors. This is the real end-to-end confirmation that every rename across the whole plan (backend routes, frontend types, frontend components, frontend pages) is fully consistent.

- [ ] **Step 10: Grep for stragglers**

Run: `grep -rn "SceneGraphCanvas\|SceneWizardModal\|from \"\.\./api/scenes\"\|api/scenes\"\|/api/scenes\b\|from_scene_id\|to_scene_id\|scene_edges" admin/ mirror_node/ tests/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v /dist/`

Expected: no output (or only clearly-intentional historical mentions in comments/docstrings explaining what something used to be called — read each hit and judge). Any real match here is a task in this plan that missed a spot; fix it inline as part of this task rather than leaving it.

- [ ] **Step 11: Commit**

```bash
git add admin/app/routers/players.py admin/frontend/src/api/branches.ts admin/frontend/src/pages/DashboardPage.tsx tests/test_admin_routes_players.py
git commit -m "feat: DashboardPage toont het volledige Player/Source/Trigger/Output-graafmodel"
```

---

## Self-Review Notes (for whoever executes this plan)

- **Spec coverage:** every numbered item in the spec's "Doel" section maps to a task — scene→player rename (Tasks 2, 9, 12-18), source as a node type (Tasks 1, 9-11, 16), trigger-from-branch (Tasks 3-4, 9, 16), output as a node type (Tasks 5-6, 16), branches (Task 3, 16-17), Sources page (Task 14). The migration order in the spec's "Migratie-volgorde" section is followed exactly by Tasks 1-11.
- **The hardest cross-task risk in this plan is Task 2's migration-ordering hazard** (pre-existing unconditional `scenes`-referencing SQL breaking on the second restart after the rename) — verify this specifically and early; every other migration task in this plan follows the established `PRAGMA user_version` gate pattern from the start and doesn't share that risk.
- **The second-hardest risk is Task 11** (mirror_node's main loop restructuring for dynamic source resolution) — it's the one task in this plan that wasn't fully proven out with a working reference implementation before being written down here, only carefully reasoned through. Read it slowly, and don't hesitate to deviate from the exact code shown if the actual current state of `mirror_node/main.py` (re-read fresh, per Task 11 Step 1) makes a different structure clearly cleaner — the behavioral requirements (reopen only on actual source change, static images cached and not re-decoded per frame, playback_mode governs the scare-video replay count/duration, output-routing publishes exactly once per actual hand-off) are what matters, not this exact diff shape.
- **Known follow-up, deliberately out of scope for this plan** (per the spec): actually running multiple physical mirror-node processes simultaneously. Task 11's output-routing publish is written to be correct for the single-output case this plan targets; a future multi-output rollout will need its own topic-per-output design.

