# Mirror-graaf: triggers als knoop + outputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triggers worden een eigen, zichtbaar/verplaatsbaar knooptype in
de mirror-scenegraaf (incl. een nieuwe HA-sensor-triggersoort), outputs
worden een eerste-klas entiteit met een eigen camera-bron, en de editor
krijgt hernoemen/kleur en een los, server-side gerenderd voorbeeldpaneel.

**Architecture:** `scene_edges` wordt hernoemd naar `triggers` en
uitgebreid met `kind`/`ha_entity_id`/canvas-positie/naam/kleur; een
nieuwe `outputs`-tabel wordt de bron van waarheid voor de camera-bron
(verhuisd vanaf Instellingen); een nieuwe achtergrondtaak in de backend
pollt Home Assistant en publiceert eenmalige MQTT-pulsen voor
HA-sensor-triggers (zelfde puls-niet-niveau-principe als
bewegingsdetectie); het voorbeeldpaneel laat de backend zelf één
camera-frame ophalen en renderen (mirror_node's eigen effect/overlay-
code hergebruikt, nooit de fysieke installatie aanrakend).

**Tech Stack:** FastAPI + SQLite (backend), React + TypeScript + Vite +
`@xyflow/react` (frontend), Python + OpenCV + paho-mqtt (mirror_node),
Vitest + Testing Library (nieuw, frontend-tests).

**Spec:** `docs/superpowers/specs/2026-08-31-mirror-graph-triggers-outputs-design.md`

## Global Constraints

- Een trigger telt alleen mee in de mirror-node-evaluatie als zowel
  `to_scene_id` als `kind` gezet zijn (zelfde liveness-regel als voorheen
  op `scene_edges`, nu op `triggers`).
- Elke puls naar de mirror-node (beweging, test-trigger, HA-sensor) is
  een EENMALIGE puls voor precies één cameraframe, nooit een aanhoudend
  niveau — de motion-loop-forever-bug uit de vorige feature (Critical 1)
  is de reden hiervoor; hetzelfde patroon geldt onverkort voor
  HA-sensor-triggers.
- Geen DB-foreign-key-afdwinging in dit project (geen `PRAGMA
  foreign_keys` ergens gezet) — opruiming bij verwijderen gebeurt
  expliciet in de route, nooit via `ON DELETE CASCADE`.
- Route-parameters die een integer-ID matchen gebruiken altijd
  `{id:int}` in FastAPI (bekende, herhaalde bugklasse in dit project:
  een bare `{id}` matcht ook niet-numerieke sub-paden en shadowt
  statische sibling-routes zoals `/preview-frame`).
- Nieuwe kolommen op een bestaande tabel gaan altijd via
  `_ensure_column`/`ALTER TABLE`, nooit alleen via `CREATE TABLE IF NOT
  EXISTS` (no-op op een tabel die al bestaat).
- `app_settings.mirror_camera_source` blijft in de DB staan (geen
  destructieve schemawijziging) maar wordt na dit plan door niets meer
  gelezen of getoond — de output is de nieuwe bron van waarheid.
- Docker-builds voor dit project moeten op `lan01` zelf gebeuren (lokale
  Mac-builds werken niet, zie het project se genoteerde lan01-Docker-
  lessen) — niet relevant voor het schrijven van deze taken, wel voor
  wie dit ooit deployt.

---

## Task 1: Klik-op-stap-bug — reproduceren en fixen (frontend-tests geïntroduceerd)

**Files:**
- Modify: `admin/frontend/package.json` (nieuwe devDependencies + vitest-testconfig)
- Modify: `admin/frontend/vite.config.ts`
- Create: `admin/frontend/vitest.setup.ts`
- Modify: `admin/frontend/src/components/SceneGraphCanvas.tsx` (indien de test een echte bug blootlegt)
- Test: `admin/frontend/src/components/SceneGraphCanvas.test.tsx`

**Interfaces:**
- Consumes: bestaande `SceneGraphCanvas`-props (`scenes`, `edges`,
  `onSceneClick(sceneId, step)`, `onGraphChanged`, `onAddScene`).
- Produces: niets nieuws voor latere taken — dit is een geïsoleerde
  bugfix. Wel: dit is de EERSTE keer dat `vitest` (al aanwezig in
  `package.json` maar nooit gebruikt) daadwerkelijk een testbestand
  uitvoert — latere frontend-taken in dit plan mogen dezelfde
  testinfrastructuur hergebruiken.

Dit project heeft `vitest` al als devDependency en een `"test": "vitest
run"`-script, maar nul testbestanden en geen DOM-testomgeving
geconfigureerd. Deze taak maakt dat voor het eerst echt bruikbaar.

- [ ] **Step 1: Installeer de ontbrekende testafhankelijkheden**

```bash
cd admin/frontend && npm install --save-dev jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

- [ ] **Step 2: Voeg een test-omgeving toe aan `vite.config.ts`**

Vervang de hele inhoud door:

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", ws: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
  },
});
```

- [ ] **Step 3: Maak `admin/frontend/vitest.setup.ts`**

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 4: Schrijf de falende test**

Maak `admin/frontend/src/components/SceneGraphCanvas.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SceneGraphCanvas from "./SceneGraphCanvas";
import type { Scene } from "../types";

vi.mock("../api/sceneEdges", () => ({
  createSceneEdge: vi.fn(),
  updateSceneEdge: vi.fn(),
  deleteSceneEdge: vi.fn(),
}));
vi.mock("../api/scenes", () => ({
  updateScene: vi.fn(),
  updateScenePosition: vi.fn(),
}));

const SCENE: Scene = {
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
};

describe("SceneGraphCanvas -- klikken op een stap-chip", () => {
  it("roept onSceneClick met de juiste stap aan bij klikken op de effect-chip", async () => {
    const onSceneClick = vi.fn();
    render(
      <SceneGraphCanvas
        scenes={[SCENE]}
        edges={[]}
        onSceneClick={onSceneClick}
        onGraphChanged={vi.fn()}
        onAddScene={vi.fn()}
      />,
    );

    const chip = await screen.findByText("xray");
    await userEvent.click(chip);

    expect(onSceneClick).toHaveBeenCalledWith(1, "animation");
  });

  it("roept onSceneClick met 'output' aan bij klikken op de Weergave-chip", async () => {
    const onSceneClick = vi.fn();
    render(
      <SceneGraphCanvas
        scenes={[SCENE]}
        edges={[]}
        onSceneClick={onSceneClick}
        onGraphChanged={vi.fn()}
        onAddScene={vi.fn()}
      />,
    );

    const chip = await screen.findByText("Weergave");
    await userEvent.click(chip);

    expect(onSceneClick).toHaveBeenCalledWith(1, "output");
  });
});
```

- [ ] **Step 5: Run de test, observeer het resultaat**

Run: `cd admin/frontend && npx vitest run src/components/SceneGraphCanvas.test.tsx`

Twee mogelijke uitkomsten, allebei geldig — dit is een onderzoekende
stap, geen voorspelde uitkomst:

- **De test FAALT** (bijv. `onSceneClick` wordt niet aangeroepen, of met
  het verkeerde argument, of `@xyflow/react` rendert de node-content
  niet buiten een `<ReactFlowProvider>`): dit is de daadwerkelijke bug.
  Lees de foutmelding zorgvuldig — als `@xyflow/react` klaagt dat het
  buiten een provider gerenderd wordt, is de test zelf onvolledig (zie
  Step 5a hieronder) en geen bewijs van een productiebug. Als de test na
  het toevoegen van een provider nog steeds faalt op de assertion zelf,
  is dat de echte, live bug.
- **De test SLAAGT**: dan werkt het klikgedrag in isolatie prima, en ligt
  het gerapporteerde probleem elders (bijv. een interactie met
  React Flow's eigen pan/drag-detectie die zich alleen manifesteert bij
  een sleep-beweging vlak vóór de klik, of een puur perceptueel/
  ontdekbaarheids-probleem — de chips zijn klein en laag-contrast). Meld
  dit expliciet in je rapport; voeg in dat geval een `nodrag`-klasse
  (React Flow's eigen conventie om te voorkomen dat de node-drag-handler
  klik-events op interactieve kind-elementen opeet) toe aan elke
  `scene-node__chip`/`scene-node__name`/`scene-node__root` als
  verdedigende maatregel, ook al is de test groen — dit is een bekende,
  documenteerde React Flow-valkuil die zonder de klasse soms pas bij
  een sleepbeweging manifesteert, niet bij een geïsoleerde test-klik.

**Step 5a (indien nodig):** als de test faalt met een foutmelding over
een ontbrekende `ReactFlowProvider`/`viewport`, wikkel de render-aanroep
in beide tests in `<ReactFlowProvider>` (importeer die uit
`@xyflow/react`) en run opnieuw voordat je verder diagnosticeert.

- [ ] **Step 6: Fix (indien Step 5 een echte bug blootlegde) of documenteer (indien niet)**

Als er een echte bug was: pas `SceneGraphCanvas.tsx` aan op basis van
wat de foutmelding onthulde, en voeg de `nodrag`-klasse sowieso toe aan
alle klikbare kind-elementen binnen een node (zie Step 5) als
verdedigende maatregel tegen deze bugklasse.

Als de test meteen slaagde: voeg alleen de `nodrag`-klasse toe (Step 5),
commit de nieuwe test + die kleine defensieve wijziging samen, en
vermeld in je rapport expliciet dat de oorspronkelijke melding niet
reproduceerbaar was in isolatie.

- [ ] **Step 7: Run de test opnieuw, verifieer dat 'ie slaagt**

Run: `cd admin/frontend && npx vitest run src/components/SceneGraphCanvas.test.tsx`
Expected: beide tests PASS

- [ ] **Step 8: Run de volledige frontend-toolchain**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build && npx vitest run`
Expected: alles slaagt, geen regressie

- [ ] **Step 9: Commit**

```bash
git add admin/frontend/package.json admin/frontend/package-lock.json \
  admin/frontend/vite.config.ts admin/frontend/vitest.setup.ts \
  admin/frontend/src/components/SceneGraphCanvas.tsx \
  admin/frontend/src/components/SceneGraphCanvas.test.tsx
git commit -m "test: eerste frontend-test + klik-op-stap-chip-fix/verharding"
```

---

## Task 2: Backend DB — `outputs`-tabel + `scenes.output_id`/`scenes.color`

**Files:**
- Modify: `admin/app/db.py`
- Test: `tests/test_admin_db.py`

**Interfaces:**
- Produces: SQLite-tabel `outputs` (`id, name, camera_source`); nieuwe
  kolommen op `scenes`: `output_id INTEGER`, `color TEXT`. Gebruikt door
  Taak 4 (outputs-route) en Taak 5 (scenes-route).

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_admin_db.py`:

```python
def test_outputs_table_created(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "outputs" in tables


def test_default_output_created_from_mirror_camera_source(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO app_settings (id, mqtt_host, mqtt_port, ha_url, mirror_camera_source) "
        "VALUES (1, 'broker', 1883, 'http://ha', 'rtsp://cam.local/stream')"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)

    rows = conn2.execute("SELECT name, camera_source FROM outputs").fetchall()
    assert rows == [("Spiegel", "rtsp://cam.local/stream")]


def test_default_output_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    count = conn.execute("SELECT COUNT(*) FROM outputs").fetchone()[0]
    assert count == 1


def test_existing_scenes_get_output_id_from_migration(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode, is_root) VALUES "
        "(1, 'Basis', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera', 1)"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)

    output_id = conn2.execute("SELECT id FROM outputs LIMIT 1").fetchone()[0]
    scene_output_id = conn2.execute("SELECT output_id FROM scenes WHERE id = 1").fetchone()[0]
    assert scene_output_id == output_id


def test_scenes_color_column_defaults_to_null(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'X', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.commit()

    color = conn.execute("SELECT color FROM scenes WHERE id = 1").fetchone()[0]
    assert color is None
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -q`
Expected: FAIL — `sqlite3.OperationalError: no such table: outputs`

- [ ] **Step 3: Voeg de `outputs`-tabel toe**

Direct ná het `scene_edges`-`CREATE TABLE`-blok in `admin/app/db.py`:

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            camera_source TEXT NOT NULL DEFAULT ''
        )"""
    )
```

- [ ] **Step 4: Voeg de nieuwe scenes-kolommen toe**

Bij de andere `_ensure_column`-aanroepen op `scenes`:

```python
    _ensure_column(conn, "scenes", "output_id", "INTEGER")
    _ensure_column(conn, "scenes", "color", "TEXT")
```

- [ ] **Step 5: Voeg de migratiefunctie toe**

Na `_migrate_scenes_to_graph`:

```python
def _migrate_outputs(conn):
    """Zorgt dat er minstens één output bestaat, gevuld vanuit de huidige
    mirror_camera_source-instelling bij de allereerste run na deze
    upgrade, en koppelt scenes zonder output_id eraan. Idempotent: doet
    niets zodra er al een output is."""
    existing = conn.execute("SELECT COUNT(*) FROM outputs").fetchone()[0]
    if existing > 0:
        return
    row = conn.execute("SELECT mirror_camera_source FROM app_settings WHERE id = 1").fetchone()
    camera_source = row[0] if row else ""
    cursor = conn.execute(
        "INSERT INTO outputs (name, camera_source) VALUES ('Spiegel', ?)", (camera_source,)
    )
    output_id = cursor.lastrowid
    conn.execute("UPDATE scenes SET output_id = ? WHERE output_id IS NULL", (output_id,))
```

- [ ] **Step 6: Roep de migratie aan vóór de finale `conn.commit()`**

Direct ná de bestaande `_migrate_scenes_to_graph(conn)`-aanroep:

```python
    _migrate_scenes_to_graph(conn)
    _migrate_outputs(conn)
    conn.commit()
    return conn
```

- [ ] **Step 7: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -q`
Expected: alle tests PASS

- [ ] **Step 8: Run de volledige backend-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests PASS (deze taak breekt niets bestaands)

- [ ] **Step 9: Commit**

```bash
git add admin/app/db.py tests/test_admin_db.py
git commit -m "feat: outputs-tabel + scenes.output_id/color + migratie"
```

---

## Task 3: Backend DB — `scene_edges` → `triggers` hernoemen + uitbreiden

**Files:**
- Modify: `admin/app/db.py`
- Test: `tests/test_admin_db.py`

**Interfaces:**
- Produces: SQLite-tabel `triggers` (`id, from_scene_id, to_scene_id,
  kind, schedule_from, schedule_until, ha_entity_id, priority, canvas_x,
  canvas_y, name, color`) — vervangt `scene_edges` volledig. Gebruikt
  door Taak 5 (`delete_scene_route`) en Taak 6 (triggers-route).

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_admin_db.py`:

```python
def test_triggers_table_replaces_scene_edges(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert "triggers" in tables
    assert "scene_edges" not in tables


def test_existing_scene_edges_data_survives_rename(tmp_path):
    path = str(tmp_path / "test.db")
    conn = init_db(path)
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (2, 'B', 1, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.execute(
        "INSERT INTO scene_edges (from_scene_id, to_scene_id, trigger_type, priority) "
        "VALUES (1, 2, 'motion', 0)"
    )
    conn.commit()
    conn.close()

    conn2 = init_db(path)

    row = conn2.execute(
        "SELECT from_scene_id, to_scene_id, kind FROM triggers"
    ).fetchone()
    assert row == (1, 2, "motion")


def test_triggers_new_columns_have_sensible_defaults(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO scenes (id, name, order_index, effect, params, overlay_hash, scale, "
        "position, source_mode) VALUES (1, 'A', 0, 'xray', '{}', NULL, 1.0, '[0.5,0.5]', 'camera')"
    )
    conn.execute(
        "INSERT INTO triggers (from_scene_id, priority) VALUES (1, 0)"
    )
    conn.commit()

    row = conn.execute(
        "SELECT ha_entity_id, name, color FROM triggers"
    ).fetchone()
    assert row == (None, None, None)


def test_triggers_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)

    conn = init_db(path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "triggers" in tables
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -q`
Expected: FAIL — `sqlite3.OperationalError: no such table: triggers` (of vergelijkbaar)

- [ ] **Step 3: Verwijder het oude `scene_edges`-`CREATE TABLE`-blok**

Verwijder in `admin/app/db.py` het hele blok:

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

(De `triggers`-tabel wordt voortaan uitsluitend door de migratiefunctie
hieronder aangemaakt — voor zowel een verse installatie als een
bestaande met data.)

- [ ] **Step 4: Voeg de migratiefunctie toe**

Na `_migrate_outputs`:

```python
def _migrate_scene_edges_to_triggers(conn):
    """Hernoemt scene_edges naar triggers (trigger_type->kind,
    trigger_from->schedule_from, trigger_until->schedule_until) en voegt
    de nieuwe trigger-als-knoop-kolommen toe (ha_entity_id, canvas_x/y,
    name, color). Idempotent via PRAGMA user_version (>=2 betekent 'deze
    migratie is al gedaan' -- zelfde patroon als de scenes-naar-graaf-
    migratie op versie 1, één stap verder)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 2:
        return
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "scene_edges" in tables:
        conn.execute("ALTER TABLE scene_edges RENAME TO triggers")
        conn.execute("ALTER TABLE triggers RENAME COLUMN trigger_type TO kind")
        conn.execute("ALTER TABLE triggers RENAME COLUMN trigger_from TO schedule_from")
        conn.execute("ALTER TABLE triggers RENAME COLUMN trigger_until TO schedule_until")
    else:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_scene_id INTEGER NOT NULL,
                to_scene_id INTEGER,
                kind TEXT,
                schedule_from TEXT,
                schedule_until TEXT,
                priority INTEGER NOT NULL DEFAULT 0
            )"""
        )
    _ensure_column(conn, "triggers", "ha_entity_id", "TEXT")
    _ensure_column(conn, "triggers", "canvas_x", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "triggers", "canvas_y", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "triggers", "name", "TEXT")
    _ensure_column(conn, "triggers", "color", "TEXT")
    # Zinvolle startpositie: het midden tussen bron- en (indien gezet)
    # doelscene, anders bron-positie + een vaste offset naar rechtsonder.
    conn.execute(
        """UPDATE triggers SET
             canvas_x = COALESCE((
               SELECT (s1.canvas_x + COALESCE(s2.canvas_x, s1.canvas_x + 150)) / 2
               FROM scenes s1 LEFT JOIN scenes s2 ON s2.id = triggers.to_scene_id
               WHERE s1.id = triggers.from_scene_id
             ), 0),
             canvas_y = COALESCE((
               SELECT (s1.canvas_y + COALESCE(s2.canvas_y, s1.canvas_y)) / 2 + 60
               FROM scenes s1 LEFT JOIN scenes s2 ON s2.id = triggers.to_scene_id
               WHERE s1.id = triggers.from_scene_id
             ), 0)
        """
    )
    conn.execute("PRAGMA user_version = 2")
```

- [ ] **Step 5: Roep de migratie aan vóór de finale `conn.commit()`**

Direct ná de `_migrate_outputs(conn)`-aanroep:

```python
    _migrate_outputs(conn)
    _migrate_scene_edges_to_triggers(conn)
    conn.commit()
    return conn
```

- [ ] **Step 6: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -q`
Expected: alle tests PASS

- [ ] **Step 7: Run de volledige backend-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: FAIL in `tests/test_admin_routes_scene_edges.py` en (delen van)
`tests/test_admin_routes_scenes.py` — die verwijzen nog naar de
verwijderde `scene_edges`-tabel/kolomnamen. Dit is verwacht, tijdelijk
gat: Taak 6 (niet deze taak) hernoemt die routes/tests. Controleer
expliciet dat de falende tests in díe twee bestanden zitten, en dat de
fout `no such table: scene_edges` (of een KeyError op `trigger_type`)
is — geen andere, onverwachte breuk.

- [ ] **Step 8: Commit**

```bash
git add admin/app/db.py tests/test_admin_db.py
git commit -m "feat: scene_edges -> triggers hernoemd + trigger-als-knoop-kolommen"
```

---

## Task 4: Backend — `outputs.py` CRUD-route

**Files:**
- Create: `admin/app/routers/outputs.py`
- Create: `tests/test_admin_routes_outputs.py`
- Modify: `admin/app/main.py`

**Interfaces:**
- Consumes: `outputs`-tabel (Taak 2).
- Produces: `GET/POST /api/outputs`, `GET/PUT/DELETE
  /api/outputs/{id:int}`. Gebruikt door Taak 9 (preview-route leest
  `camera_source` direct via SQL, geen dependency op deze module) en
  door de frontend in Taak 15 (Outputs-pagina).

- [ ] **Step 1: Schrijf de falende tests**

Maak `tests/test_admin_routes_outputs.py`:

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


def test_list_outputs_includes_the_migrated_default(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/outputs")

    assert response.status_code == 200
    outputs = response.json()
    assert len(outputs) == 1
    assert outputs[0]["name"] == "Spiegel"


def test_create_output(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/outputs", json={"name": "Beamer tuin", "camera_source": "rtsp://x"})

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Beamer tuin"
    assert created["camera_source"] == "rtsp://x"


def test_create_output_rejects_empty_name(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/outputs", json={"name": "  ", "camera_source": ""})

    assert response.status_code == 400


def test_update_output(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/outputs", json={"name": "A", "camera_source": ""}).json()

    response = client.put(f"/api/outputs/{created['id']}", json={"name": "B", "camera_source": "rtsp://y"})

    assert response.status_code == 200
    assert response.json()["name"] == "B"


def test_update_output_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/outputs/999", json={"name": "X", "camera_source": ""})

    assert response.status_code == 404


def test_delete_output_without_scenes(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/outputs", json={"name": "Tijdelijk", "camera_source": ""}).json()

    response = client.delete(f"/api/outputs/{created['id']}")

    assert response.status_code == 200
    remaining_ids = [o["id"] for o in client.get("/api/outputs").json()]
    assert created["id"] not in remaining_ids


def test_delete_output_rejected_when_it_has_a_scene(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    client.post("/api/scenes", json={
        "name": "X", "enabled": True, "source_mode": "camera", "effect": "xray",
        "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
        "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
        "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0,
        "output_id": default_output["id"], "color": None,
    })

    response = client.delete(f"/api/outputs/{default_output['id']}")

    assert response.status_code == 400


def test_output_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    assert client.get("/api/outputs").status_code == 401
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_outputs.py -q`
Expected: FAIL — `404 Not Found` (route bestaat nog niet)

- [ ] **Step 3: Implementeer `admin/app/routers/outputs.py`**

```python
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_OUTPUT_COLUMNS = "id, name, camera_source"


def _row_to_output(row):
    return {"id": row[0], "name": row[1], "camera_source": row[2]}


def _list_outputs(db):
    rows = db.execute(f"SELECT {_OUTPUT_COLUMNS} FROM outputs ORDER BY id").fetchall()
    return [_row_to_output(r) for r in rows]


@router.get("/api/outputs")
def list_outputs_route(request: Request):
    return _list_outputs(request.app.state.db)


@router.get("/api/outputs/{output_id:int}")
def get_output_route(output_id: int, request: Request):
    row = request.app.state.db.execute(
        f"SELECT {_OUTPUT_COLUMNS} FROM outputs WHERE id = ?", (output_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Output niet gevonden")
    return _row_to_output(row)


@router.post("/api/outputs")
async def create_output_route(request: Request):
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name mag niet leeg zijn")
    camera_source = str(body.get("camera_source", ""))
    db = request.app.state.db
    cursor = db.execute("INSERT INTO outputs (name, camera_source) VALUES (?, ?)", (name, camera_source))
    db.commit()
    return get_output_route(cursor.lastrowid, request)


@router.put("/api/outputs/{output_id:int}")
async def update_output_route(output_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM outputs WHERE id = ?", (output_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Output niet gevonden")
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name mag niet leeg zijn")
    camera_source = str(body.get("camera_source", ""))
    db.execute("UPDATE outputs SET name = ?, camera_source = ? WHERE id = ?", (name, camera_source, output_id))
    db.commit()
    return get_output_route(output_id, request)


@router.delete("/api/outputs/{output_id:int}")
def delete_output_route(output_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM outputs WHERE id = ?", (output_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Output niet gevonden")
    has_scenes = db.execute("SELECT 1 FROM scenes WHERE output_id = ? LIMIT 1", (output_id,)).fetchone()
    if has_scenes is not None:
        raise HTTPException(status_code=400, detail="Output heeft nog scenes -- verplaats of verwijder die eerst")
    db.execute("DELETE FROM outputs WHERE id = ?", (output_id,))
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Registreer de router in `admin/app/main.py`**

Voeg de import toe bij de andere router-imports:

```python
from admin.app.routers import outputs as outputs_router
```

Voeg de registratie toe (na `app.include_router(scenes_router.router)`):

```python
    app.include_router(outputs_router.router)
```

- [ ] **Step 5: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_outputs.py -q`
Expected: alle tests PASS

- [ ] **Step 6: Commit**

```bash
git add admin/app/routers/outputs.py tests/test_admin_routes_outputs.py admin/app/main.py
git commit -m "feat: /api/outputs CRUD"
```

---

## Task 5: Backend — `scenes.py` + `graph_publish.py`: `output_id`/`color`

**Files:**
- Modify: `admin/app/routers/scenes.py`
- Modify: `admin/app/graph_publish.py`
- Modify: `tests/test_admin_routes_scenes.py`

**Interfaces:**
- Consumes: `outputs`-tabel (Taak 2), `scenes.output_id`/`scenes.color`
  (Taak 2), `triggers`-tabel (Taak 3, voor `delete_scene_route`'s
  opruiming).
- Produces: `Scene`-response met `output_id`/`color`.
  `publish_graph(db, bridge)`'s payload krijgt een `output_id`-veld en
  hernoemt de `edges`-sleutel naar `triggers` (voorbereidend op Taak 6 —
  `_list_triggers` bestaat pas na die taak, zie de tijdelijke-gat-
  opmerking in Step 7 hieronder).

- [ ] **Step 1: Werk de bestaande tests bij**

In `tests/test_admin_routes_scenes.py`, vervang `_SCENE_PAYLOAD`:

```python
_SCENE_PAYLOAD = {
    "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
    "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
    "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0, "output_id": None, "color": None,
}
```

Elke test die `("graph", {"scenes": [...], "edges": [], "root_scene_id": ...})`
verwacht, wordt bijgewerkt naar
`("graph", {"output_id": <int>, "scenes": [...], "triggers": [], "root_scene_id": ...})`.
Voeg toe:

```python
def test_create_scene_without_output_id_uses_the_default_output(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]

    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    assert created["output_id"] == default_output["id"]


def test_create_scene_with_explicit_output_id(tmp_path):
    client, bridge = _client(tmp_path)
    other_output = client.post("/api/outputs", json={"name": "Beamer", "camera_source": ""}).json()

    created = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "output_id": other_output["id"]}).json()

    assert created["output_id"] == other_output["id"]


def test_scene_color_round_trips(tmp_path):
    client, bridge = _client(tmp_path)

    created = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "color": "#ff8800"}).json()

    assert created["color"] == "#ff8800"
    fetched = client.get(f"/api/scenes/{created['id']}").json()
    assert fetched["color"] == "#ff8800"


def test_published_graph_includes_output_id(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    bridge.calls.clear()

    client.post("/api/scenes", json=_SCENE_PAYLOAD)

    kind, graph = bridge.calls[-1]
    assert kind == "graph"
    assert graph["output_id"] == default_output["id"]
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_scenes.py -q`
Expected: meerdere FAIL (velden bestaan nog niet, `publish_graph` gooit
nog `edges` i.p.v. `triggers` en heeft nog geen `output_id`)

- [ ] **Step 3: Werk `admin/app/routers/scenes.py` bij**

Vervang `_SCENE_COLUMNS`:

```python
_SCENE_COLUMNS = (
    "id, name, enabled, source_mode, effect, params, overlay_hash, "
    "scale, position, canvas_width, canvas_height, source_scale, source_position, "
    "is_root, canvas_x, canvas_y, output_id, color"
)
```

Vervang `_DEFAULT_SCENE`:

```python
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
    "output_id": None,
    "color": None,
}
```

Vervang `_row_to_scene`:

```python
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
        "output_id": row[16],
        "color": row[17],
    }
```

Voeg een helper toe (na `_clear_other_roots`):

```python
def _resolve_output_id(db, output_id):
    """Geeft output_id terug als 'ie gezet is, anders de eerste/enige
    output. 400 als er helemaal geen output bestaat (kan alleen als de
    Taak-2-migratie nooit gedraaid heeft, defensief)."""
    if output_id is not None:
        return output_id
    default_output = db.execute("SELECT id FROM outputs ORDER BY id LIMIT 1").fetchone()
    if default_output is None:
        raise HTTPException(status_code=400, detail="Geen output beschikbaar, maak er eerst één aan")
    return default_output[0]
```

In `create_scene_route`, direct na `canvas_width, canvas_height =
_canvas_columns(fields)`, voeg toe:

```python
    fields["output_id"] = _resolve_output_id(db, fields["output_id"])
```

Vervang de `INSERT INTO scenes`-aanroep:

```python
    cursor = db.execute(
        # ponytail: order_index blijft NOT NULL in het schema (legacy
        # migratiekolom) maar wordt door de graaf-app niet meer gebruikt
        # -- vaste 0 om aan de constraint te voldoen zonder db.py aan te
        # raken (buiten scope van deze taak).
        """INSERT INTO scenes
             (name, order_index, enabled, source_mode, effect, params, overlay_hash,
              scale, position, canvas_width, canvas_height, source_scale, source_position,
              is_root, canvas_x, canvas_y, output_id, color)
           VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"],
            fields["effect"], json.dumps(fields["params"]), fields["overlay_hash"],
            fields["scale"], json.dumps(fields["position"]), canvas_width, canvas_height,
            fields["source_scale"], json.dumps(fields["source_position"]),
            int(fields["is_root"]), fields["canvas_x"], fields["canvas_y"],
            fields["output_id"], fields["color"],
        ),
    )
```

In `update_scene_route`, direct na `canvas_width, canvas_height =
_canvas_columns(fields)`, voeg toe:

```python
    fields["output_id"] = _resolve_output_id(db, fields["output_id"])
```

Vervang de `UPDATE scenes`-aanroep:

```python
    db.execute(
        """UPDATE scenes SET name=?, enabled=?, source_mode=?, effect=?, params=?, overlay_hash=?,
             scale=?, position=?, canvas_width=?, canvas_height=?, source_scale=?, source_position=?,
             is_root=?, canvas_x=?, canvas_y=?, output_id=?, color=? WHERE id=?""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"], fields["effect"],
            json.dumps(fields["params"]), fields["overlay_hash"], fields["scale"],
            json.dumps(fields["position"]), canvas_width, canvas_height, fields["source_scale"],
            json.dumps(fields["source_position"]), int(fields["is_root"]),
            fields["canvas_x"], fields["canvas_y"], fields["output_id"], fields["color"], scene_id,
        ),
    )
```

In `delete_scene_route`, vervang de twee `scene_edges`-statements
(tabel is in Taak 3 hernoemd naar `triggers`):

```python
    db.execute("DELETE FROM triggers WHERE from_scene_id = ?", (scene_id,))
    db.execute(
        "UPDATE triggers SET to_scene_id = NULL, kind = NULL, "
        "schedule_from = NULL, schedule_until = NULL, ha_entity_id = NULL WHERE to_scene_id = ?",
        (scene_id,),
    )
```

- [ ] **Step 4: Werk `admin/app/graph_publish.py` bij**

Vervang de hele inhoud door:

```python
def publish_graph(db, bridge):
    """Publiceert de volledige graaf (scenes + triggers + root + output)
    naar MQTT -- gedeeld door scenes.py en triggers.py, elke schrijvende
    route in beide roept dit aan zodat opgeslagen en gepubliceerde graaf
    nooit uit elkaar kunnen lopen. Lazy imports om een cirkel met de
    routers te vermijden (die importeren dit bestand). output_id is
    voorlopig altijd de eerste/enige output -- een toekomstige
    multi-output-uitrol geeft dit expliciet mee per aanroep."""
    from admin.app.routers.scenes import _list_scenes
    from admin.app.routers.triggers import _list_triggers

    scenes = _list_scenes(db)
    triggers = _list_triggers(db)
    root_scene_id = next((s["id"] for s in scenes if s["is_root"]), None)
    output_row = db.execute("SELECT id FROM outputs ORDER BY id LIMIT 1").fetchone()
    output_id = output_row[0] if output_row else None
    bridge.publish_mirror_graph({
        "output_id": output_id, "scenes": scenes, "triggers": triggers, "root_scene_id": root_scene_id,
    })
```

- [ ] **Step 5: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_scenes.py -q`
Expected: `admin.app.routers.triggers`-importfout — verwacht, die module
bestaat pas na Taak 6. Bevestig dat de fout exact
`ModuleNotFoundError: No module named 'admin.app.routers.triggers'` is
op elke test die een schrijvende route aanroept (die `publish_graph`
triggert), en niets anders. Dit is een bewust, tijdelijk gat — net als
het gat tussen Taak 5 en 6 in de vorige scenegraaf-feature.

- [ ] **Step 6: Commit**

```bash
git add admin/app/routers/scenes.py admin/app/graph_publish.py tests/test_admin_routes_scenes.py
git commit -m "feat: scenes-route + graph_publish krijgen output_id/color/triggers-sleutel"
```

---

## Task 6: Backend — `scene_edges.py` → `triggers.py` (hernoemd + uitgebreid)

**Files:**
- Create: `admin/app/routers/triggers.py`
- Delete: `admin/app/routers/scene_edges.py`
- Create: `tests/test_admin_routes_triggers.py`
- Delete: `tests/test_admin_routes_scene_edges.py`
- Modify: `admin/app/main.py`

**Interfaces:**
- Consumes: `triggers`-tabel (Taak 3), `publish_graph` (Taak 5).
- Produces: `GET/POST /api/triggers`, `PUT/DELETE
  /api/triggers/{id:int}`, `PUT /api/triggers/{id:int}/position` —
  vervangt `/api/scene-edges` volledig. Sluit het tijdelijke gat uit
  Taak 5 (`publish_graph`'s `_list_triggers`-import bestaat nu).

- [ ] **Step 1: Verwijder het oude bestand en zijn test**

```bash
git rm admin/app/routers/scene_edges.py tests/test_admin_routes_scene_edges.py
```

- [ ] **Step 2: Schrijf de falende tests**

Maak `tests/test_admin_routes_triggers.py`:

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


_SCENE_PAYLOAD = {
    "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
    "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
    "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0, "output_id": None, "color": None,
}


def _two_scenes(client):
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()
    return a, b


def test_create_trigger_with_empty_output_stub(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)

    response = client.post("/api/triggers", json={"from_scene_id": a["id"]})

    assert response.status_code == 200
    created = response.json()
    assert created["from_scene_id"] == a["id"]
    assert created["to_scene_id"] is None
    assert created["kind"] is None
    assert created["ha_entity_id"] is None


def test_create_trigger_requires_valid_from_scene_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/triggers", json={"from_scene_id": 999})

    assert response.status_code == 400


def test_update_trigger_connects_and_sets_kind(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_scene_id": a["id"]}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={
        "from_scene_id": a["id"], "to_scene_id": b["id"], "kind": "motion", "priority": 0,
    })

    assert response.status_code == 200
    updated = response.json()
    assert updated["to_scene_id"] == b["id"]
    assert updated["kind"] == "motion"


def test_update_trigger_rejects_invalid_kind(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_scene_id": a["id"]}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={"kind": "nonsense"})

    assert response.status_code == 400


def test_ha_sensor_kind_requires_ha_entity_id(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_scene_id": a["id"]}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={
        "to_scene_id": b["id"], "kind": "ha_sensor",
    })

    assert response.status_code == 400


def test_ha_sensor_kind_with_entity_id_succeeds(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_scene_id": a["id"]}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={
        "to_scene_id": b["id"], "kind": "ha_sensor", "ha_entity_id": "binary_sensor.tuin",
    })

    assert response.status_code == 200
    assert response.json()["ha_entity_id"] == "binary_sensor.tuin"


def test_update_trigger_rejects_unknown_to_scene_id(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_scene_id": a["id"]}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={"to_scene_id": 999, "kind": "always"})

    assert response.status_code == 400


def test_update_trigger_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/triggers/999", json={"from_scene_id": 1})

    assert response.status_code == 404


def test_delete_trigger(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_scene_id": a["id"]}).json()

    response = client.delete(f"/api/triggers/{trigger['id']}")

    assert response.status_code == 200
    assert client.get("/api/triggers").json() == []


def test_delete_trigger_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/triggers/999")

    assert response.status_code == 404


def test_update_trigger_position_does_not_publish_to_mqtt(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_scene_id": a["id"]}).json()
    bridge.calls.clear()

    response = client.put(f"/api/triggers/{trigger['id']}/position", json={"canvas_x": 12.5, "canvas_y": -3.0})

    assert response.status_code == 200
    assert bridge.calls == []
    updated = client.get("/api/triggers").json()[0]
    assert updated["canvas_x"] == 12.5
    assert updated["canvas_y"] == -3.0


def test_update_trigger_position_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/triggers/999/position", json={"canvas_x": 0, "canvas_y": 0})

    assert response.status_code == 404


def test_every_write_publishes_full_graph_with_triggers_key(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    client.put(f"/api/scenes/{a['id']}", json={**_SCENE_PAYLOAD, "name": "A", "is_root": True})
    bridge.calls.clear()

    trigger = client.post("/api/triggers", json={
        "from_scene_id": a["id"], "to_scene_id": b["id"], "kind": "always", "priority": 0,
    }).json()

    kind, graph = bridge.calls[-1]
    assert kind == "graph"
    assert graph["triggers"] == [trigger]


def test_trigger_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    assert client.get("/api/triggers").status_code == 401
    assert client.post("/api/triggers", json={"from_scene_id": 1}).status_code == 401
```

- [ ] **Step 3: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_triggers.py -q`
Expected: FAIL — `404 Not Found` (route bestaat nog niet)

- [ ] **Step 4: Implementeer `admin/app/routers/triggers.py`**

```python
from fastapi import APIRouter, HTTPException, Request
from admin.app.graph_publish import publish_graph

router = APIRouter()

_TRIGGER_COLUMNS = (
    "id, from_scene_id, to_scene_id, kind, schedule_from, schedule_until, "
    "ha_entity_id, priority, canvas_x, canvas_y, name, color"
)

_DEFAULT_TRIGGER = {
    "to_scene_id": None,
    "kind": None,
    "schedule_from": None,
    "schedule_until": None,
    "ha_entity_id": None,
    "priority": 0,
    "canvas_x": 0.0,
    "canvas_y": 0.0,
    "name": None,
    "color": None,
}

_VALID_KINDS = {"always", "motion", "schedule", "ha_sensor"}


def _row_to_trigger(row):
    return {
        "id": row[0],
        "from_scene_id": row[1],
        "to_scene_id": row[2],
        "kind": row[3],
        "schedule_from": row[4],
        "schedule_until": row[5],
        "ha_entity_id": row[6],
        "priority": row[7],
        "canvas_x": row[8],
        "canvas_y": row[9],
        "name": row[10],
        "color": row[11],
    }


def _list_triggers(db):
    rows = db.execute(
        f"SELECT {_TRIGGER_COLUMNS} FROM triggers ORDER BY from_scene_id, priority"
    ).fetchall()
    return [_row_to_trigger(r) for r in rows]


def _validate_kind(fields):
    if fields["kind"] is not None and fields["kind"] not in _VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind moet één van {sorted(_VALID_KINDS)} zijn")
    if fields["kind"] == "ha_sensor" and not fields["ha_entity_id"]:
        raise HTTPException(status_code=400, detail="ha_entity_id is verplicht bij kind='ha_sensor'")


@router.get("/api/triggers")
def list_triggers_route(request: Request):
    return _list_triggers(request.app.state.db)


@router.post("/api/triggers")
async def create_trigger_route(request: Request):
    body = await request.json()
    from_scene_id = body.get("from_scene_id")
    db = request.app.state.db
    if not isinstance(from_scene_id, int):
        raise HTTPException(status_code=400, detail="from_scene_id is verplicht")
    exists = db.execute("SELECT id FROM scenes WHERE id = ?", (from_scene_id,)).fetchone()
    if exists is None:
        raise HTTPException(status_code=400, detail="from_scene_id verwijst naar een onbestaande scene")
    fields = {k: body.get(k, v) for k, v in _DEFAULT_TRIGGER.items()}
    _validate_kind(fields)
    cursor = db.execute(
        """INSERT INTO triggers
             (from_scene_id, to_scene_id, kind, schedule_from, schedule_until, ha_entity_id,
              priority, canvas_x, canvas_y, name, color)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (from_scene_id, fields["to_scene_id"], fields["kind"], fields["schedule_from"],
         fields["schedule_until"], fields["ha_entity_id"], fields["priority"],
         fields["canvas_x"], fields["canvas_y"], fields["name"], fields["color"]),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    row = db.execute(f"SELECT {_TRIGGER_COLUMNS} FROM triggers WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_trigger(row)


@router.put("/api/triggers/{trigger_id:int}")
async def update_trigger_route(trigger_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Trigger niet gevonden")
    body = await request.json()
    fields = {k: body.get(k, v) for k, v in _DEFAULT_TRIGGER.items()}
    _validate_kind(fields)
    if fields["to_scene_id"] is not None:
        target = db.execute("SELECT id FROM scenes WHERE id = ?", (fields["to_scene_id"],)).fetchone()
        if target is None:
            raise HTTPException(status_code=400, detail="to_scene_id verwijst naar een onbestaande scene")
    db.execute(
        """UPDATE triggers SET to_scene_id=?, kind=?, schedule_from=?, schedule_until=?,
             ha_entity_id=?, priority=?, canvas_x=?, canvas_y=?, name=?, color=? WHERE id=?""",
        (fields["to_scene_id"], fields["kind"], fields["schedule_from"], fields["schedule_until"],
         fields["ha_entity_id"], fields["priority"], fields["canvas_x"], fields["canvas_y"],
         fields["name"], fields["color"], trigger_id),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    row = db.execute(f"SELECT {_TRIGGER_COLUMNS} FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
    return _row_to_trigger(row)


@router.put("/api/triggers/{trigger_id:int}/position")
async def update_trigger_position_route(trigger_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Trigger niet gevonden")
    body = await request.json()
    try:
        x, y = float(body.get("canvas_x")), float(body.get("canvas_y"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="canvas_x/canvas_y moeten getallen zijn")
    db.execute("UPDATE triggers SET canvas_x = ?, canvas_y = ? WHERE id = ?", (x, y, trigger_id))
    db.commit()
    # Bewust GEEN publish_graph hier -- canvaspositie is een editor-
    # aangelegenheid, zelfde reden als bij scenes' /position-route.
    return {"ok": True}


@router.delete("/api/triggers/{trigger_id:int}")
def delete_trigger_route(trigger_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Trigger niet gevonden")
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}
```

- [ ] **Step 5: Werk `admin/app/main.py` bij**

Vervang de import:

```python
from admin.app.routers import scene_edges as scene_edges_router
```

door:

```python
from admin.app.routers import triggers as triggers_router
```

Vervang de registratie:

```python
    app.include_router(scene_edges_router.router)
```

door:

```python
    app.include_router(triggers_router.router)
```

- [ ] **Step 6: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_triggers.py tests/test_admin_routes_scenes.py -q`
Expected: alle tests PASS (het Taak-5-gat is nu gesloten)

- [ ] **Step 7: Run de volledige backend-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alles groen BEHALVE `tests/test_mirror_main.py`/
`tests/test_scene_engine.py` (die verwachten Taak 7's nieuwe
veldnamen/parameter, nog niet doorgevoerd) en eventuele resterende
verwijzingen naar de oude `edges`-sleutel elders. Bevestig dat de fouten
uitsluitend in díe twee bestanden zitten.

- [ ] **Step 8: Commit**

```bash
git add admin/app/routers/triggers.py tests/test_admin_routes_triggers.py admin/app/main.py
git commit -m "feat: scene_edges-route -> triggers-route (kind/ha_entity_id/canvas/naam/kleur)"
```

---

## Task 7: mirror_node — `SceneGraph` + hoofdlus: `triggers`-sleutel + HA-pulsen

**Files:**
- Modify: `mirror_node/scenes.py`
- Modify: `mirror_node/main.py`
- Modify: `tests/test_scene_engine.py`
- Modify: `tests/test_mirror_main.py`

**Interfaces:**
- Consumes: nieuwe payload-vorm van `config/mirror/graph` (Taak 6):
  `{"output_id": ..., "scenes": [...], "triggers": [...],
  "root_scene_id": ...}`, waarbij elk trigger-record `kind`/
  `schedule_from`/`schedule_until`/`ha_entity_id` heet i.p.v. de oude
  `trigger_type`/`trigger_from`/`trigger_until`.
- Produces: `SceneGraph.set_graph(scenes, triggers, root_scene_id)`,
  `SceneGraph.resolve(motion_active, now_hhmm, fired_ha_entities=frozenset()) ->
  (scene, transitioned)`. Nieuw MQTT-topic
  `topics.control_mirror_ha_trigger` (Taak 8 definieert de property zelf
  — deze taak gebruikt 'm al, zie het tijdelijke-gat-opmerking in Step 8).

- [ ] **Step 1: Herschrijf `tests/test_scene_engine.py`**

Vervang de hele inhoud door:

```python
from mirror_node.scenes import SceneGraph, _time_in_window


def _graph(scenes, triggers, root_id, **kwargs):
    g = SceneGraph(**kwargs)
    g.set_graph(scenes, triggers, root_id)
    return g


def test_resolves_to_root_with_no_triggers():
    g = _graph([{"id": 1, "name": "Basis"}], [], root_id=1)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_transitions_on_matching_motion_trigger():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_no_transition_without_motion():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_only_current_nodes_own_triggers_are_checked():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is False


def test_return_trigger_brings_state_back_on_next_resolve():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_scene_id": 2, "to_scene_id": 1, "kind": "always",
         "schedule_from": None, "schedule_until": None, "priority": 0},
    ]
    g = _graph(scenes, triggers, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is True


def test_non_live_triggers_are_ignored():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": None, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_scene_id": 1, "to_scene_id": 2, "kind": None,
         "schedule_from": None, "schedule_until": None, "priority": 1},
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_priority_order_first_matching_trigger_wins():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}, {"id": 3, "name": "B"}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": 3, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 1},
        {"from_scene_id": 1, "to_scene_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "A"}


def test_unknown_current_scene_resets_to_root():
    g = _graph([{"id": 1, "name": "Basis"}], [], root_id=1)
    g._current_id = 999

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}


def test_no_root_and_no_scenes_returns_none():
    g = SceneGraph()
    g.set_graph([], [], root_scene_id=None)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene is None
    assert transitioned is False


def test_disabled_scene_is_never_resolved_to():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare", "enabled": False}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_trigger_to_unknown_scene_is_skipped_not_followed():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": 999, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_scene_id": 1, "to_scene_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 1},
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "A"}
    assert transitioned is True


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


def test_ha_sensor_trigger_matches_only_its_own_fired_entity():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": 2, "kind": "ha_sensor",
         "schedule_from": None, "schedule_until": None, "ha_entity_id": "binary_sensor.tuin",
         "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    not_fired = g.resolve(motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset())
    assert not_fired == ({"id": 1, "name": "Basis"}, False)

    other_entity_fired = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.woonkamer"})
    )
    assert other_entity_fired == ({"id": 1, "name": "Basis"}, False)

    scene, transitioned = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.tuin"})
    )
    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_ha_sensor_trigger_without_ha_entity_id_never_matches():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_scene_id": 1, "to_scene_id": 2, "kind": "ha_sensor",
         "schedule_from": None, "schedule_until": None, "ha_entity_id": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.tuin"})
    )

    assert scene == {"id": 1, "name": "Basis"}
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

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_scene_engine.py -q`
Expected: FAIL — `TypeError: SceneGraph.set_graph() ...` / `AttributeError` (oude veldnamen)

- [ ] **Step 3: Herschrijf `mirror_node/scenes.py`**

Vervang de hele inhoud door:

```python
import time


class SceneGraph:
    """Houdt de laatst via MQTT ontvangen graaf bij (scenes + live
    triggers) en de huidige-scene-toestand. Elke trigger is een eigen
    knoop tussen twee scenes (from_scene_id -> to_scene_id), met een
    kind (always/motion/schedule/ha_sensor)."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._scenes = {}
        self._triggers = {}
        self._root_id = None
        self._current_id = None
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_graph(self, scenes, triggers, root_scene_id):
        # Disabled scenes tellen niet mee -- ze mogen nooit als winnaar
        # terugkomen. Een trigger naar zo'n scene wordt vanzelf als
        # "target bestaat niet" behandeld door resolve() (zelfde pad als
        # een trigger naar een écht verwijderde scene).
        self._scenes = {s["id"]: s for s in scenes if s.get("enabled", True)}
        by_from = {}
        for t in triggers:
            if t.get("to_scene_id") is None or t.get("kind") is None:
                continue  # niet-live: lege stub of ongeconfigureerde trigger
            by_from.setdefault(t["from_scene_id"], []).append(t)
        for lst in by_from.values():
            lst.sort(key=lambda t: t["priority"])
        self._triggers = by_from
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

    def resolve(self, motion_active, now_hhmm, fired_ha_entities=frozenset()):
        """Geeft (scene, transitioned) terug. `transitioned` is True als
        dit frame een trigger is gevolgd. `fired_ha_entities` is een
        eenmalige puls-set (net als `motion_active` een puls is, geen
        aanhoudend niveau) van HA-entity-ids die dit frame naar 'on' zijn
        gegaan."""
        if self.preview_recently_set():
            return self._preview, False
        if self._current_id not in self._scenes:
            self._current_id = self._root_id
        if self._current_id is None:
            return None, False
        for trigger in self._triggers.get(self._current_id, []):
            if trigger["to_scene_id"] not in self._scenes:
                continue  # doel bestaat niet (of staat uit) -- val door naar de volgende trigger
            if _trigger_matches(trigger, motion_active, now_hhmm, fired_ha_entities):
                if trigger["to_scene_id"] != self._current_id:
                    self._current_id = trigger["to_scene_id"]
                    return self._scenes.get(self._current_id), True
                break
        return self._scenes.get(self._current_id), False


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

- [ ] **Step 4: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_scene_engine.py -q`
Expected: alle tests PASS

- [ ] **Step 5: Werk `tests/test_mirror_main.py` bij**

Zoek elke plek die `graph.get("edges", [])` (of `"edges":` in een
payload-dict), `_apply_graph_message`, `scene_graph.resolve(...)` of
`_fired_ha_entities` raakt en vervang consistent:

- Elke test-payload `{"scenes": [...], "edges": [...], "root_scene_id": ...}`
  wordt `{"scenes": [...], "triggers": [...], "root_scene_id": ...}`.
- Elke `scene_graph.resolve(x, "12:00")`-aanroep/verwachting die een
  2-argumenten-vorm gebruikt blijft geldig (het derde argument heeft een
  default), maar voeg minstens één test toe die het derde argument
  expliciet meegeeft (zie hieronder).

Voeg toe (past bij de bestaande `test_apply_graph_message_*`-groep):

```python
def test_apply_graph_message_reads_triggers_key():
    scene = {"id": 1, "trigger_type": None, "overlay_hash": None}
    payload = {"scenes": [scene], "triggers": [], "root_scene_id": 1}
    mirror_main._apply_graph_message(json.dumps(payload), _FakeLogger())

    result, transitioned = mirror_main.scene_graph.resolve(False, "12:00")
    assert result == scene
    assert transitioned is False
```

Voeg toe (nieuwe groep, HA-trigger-consumptie):

```python
def test_apply_ha_trigger_message_adds_entity_to_fired_set():
    mirror_main._fired_ha_entities.clear()
    mirror_main._apply_ha_trigger_message(json.dumps({"entity_id": "binary_sensor.tuin"}), _FakeLogger())

    with mirror_main._fired_ha_entities_lock:
        assert "binary_sensor.tuin" in mirror_main._fired_ha_entities
    mirror_main._fired_ha_entities.clear()


def test_apply_ha_trigger_message_ignores_malformed_payload():
    logger = _FakeLogger()
    mirror_main._apply_ha_trigger_message("{niet-geldig-json", logger)
    assert logger.errors


def test_apply_ha_trigger_message_ignores_missing_entity_id():
    logger = _FakeLogger()
    mirror_main._apply_ha_trigger_message(json.dumps({}), logger)
    assert logger.errors
```

- [ ] **Step 6: Werk `mirror_node/main.py` bij — imports en module-state**

Geen wijziging aan de `SceneGraph`-import (naam blijft gelijk). Voeg
toe, bij de andere module-level state (na `scene_graph = SceneGraph()`):

```python
_fired_ha_entities_lock = threading.Lock()
_fired_ha_entities = set()
```

- [ ] **Step 7: Werk `_apply_graph_message` bij**

Vervang:

```python
    scenes = graph.get("scenes", [])
    edges = graph.get("edges", [])
    root_scene_id = graph.get("root_scene_id")
    if not isinstance(scenes, list) or not isinstance(edges, list):
        logger.error("Graaf-config heeft geen geldige scenes/edges-lijst, genegeerd: %r", graph)
        return
    scene_graph.set_graph(scenes, edges, root_scene_id)
```

door:

```python
    scenes = graph.get("scenes", [])
    triggers = graph.get("triggers", [])
    root_scene_id = graph.get("root_scene_id")
    if not isinstance(scenes, list) or not isinstance(triggers, list):
        logger.error("Graaf-config heeft geen geldige scenes/triggers-lijst, genegeerd: %r", graph)
        return
    scene_graph.set_graph(scenes, triggers, root_scene_id)
```

- [ ] **Step 8: Voeg `_apply_ha_trigger_message` toe**

Na `_apply_scene_preview_message`:

```python
def _apply_ha_trigger_message(payload, logger):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige ha-trigger-JSON ontvangen, genegeerd")
        return
    entity_id = data.get("entity_id") if isinstance(data, dict) else None
    if not isinstance(entity_id, str) or not entity_id:
        logger.error("ha-trigger-bericht zonder geldige entity_id, genegeerd: %r", data)
        return
    with _fired_ha_entities_lock:
        _fired_ha_entities.add(entity_id)
```

- [ ] **Step 9: Werk `make_on_message` bij**

Voeg een tak toe **helemaal aan het eind van de `if`-keten, ná de
bestaande `config_mirror_scare_video`-tak** (dus als allerlaatste
controle vóór de `except`):

```python
            if msg.topic == topics.control_mirror_ha_trigger:
                _apply_ha_trigger_message(msg.payload.decode(), logger)
                return
```

**Waarom precies aan het eind, en niet ergens middenin:**
`topics.control_mirror_ha_trigger` bestaat pas na Taak 8 (deze taak
schrijft de consumptiekant, Taak 8 de definitie). `tests/test_mirror_main.py`
gebruikt de ECHTE `mirror_main.Topics()` (geen namaak-object) in zijn
fixtures, dus elke aanroep van `on_message(...)` evalueert deze regel
en gooit tot Taak 8 een `AttributeError` — die wordt afgevangen door de
bestaande `try/except Exception` rond de hele functie (bedoeld als
vangnet tegen precies dit soort fouten). Elke bestaande tak vóór deze
nieuwe regel heeft al een eigen `return` (of is, bij
`config_mirror_scare_video`, de voorlaatste tak zonder eigen `return`)
— zolang de nieuwe regel LAATST staat, wordt de AttributeError pas
gegooid NADAT een eventueel matchende eerdere tak al volledig is
uitgevoerd, en beïnvloedt 'm dus geen enkele bestaande test. Zet 'm
ergens middenin de keten, en elke tak DAARNA zou tot Taak 8 stilletjes
nooit meer bereikt worden (de AttributeError onderbreekt de functie
voordat latere `if`-checks aan de beurt komen) — dat zou bestaande,
groene tests op andere topics stuk maken. Run na deze stap
`.venv/bin/python -m pytest tests/test_mirror_main.py -q` en bevestig
dat alle tests die AL bestonden vóór deze taak nog steeds slagen,
naast de nieuwe.

- [ ] **Step 10: Werk het abonneren in `main()` bij**

Voeg toe, na `client.subscribe(topics.control_mirror_scene_preview)`:

```python
        client.subscribe(topics.control_mirror_ha_trigger)
```

- [ ] **Step 11: Werk het hoofdlus-blok bij — puls consumeren**

Vervang:

```python
            winning, transitioned = scene_graph.resolve(fired, now_hhmm)
```

door:

```python
            with _fired_ha_entities_lock:
                fired_ha_entities = frozenset(_fired_ha_entities)
                _fired_ha_entities.clear()

            winning, transitioned = scene_graph.resolve(fired, now_hhmm, fired_ha_entities)
```

- [ ] **Step 12: Run de mirror_node/scene-tests, verifieer resultaat**

Run: `.venv/bin/python -m pytest tests/test_scene_engine.py tests/test_mirror_main.py -q`
Expected: beide bestanden volledig groen, inclusief alle tests die al
vóór deze taak bestonden — dankzij de plaatsing van de nieuwe
`control_mirror_ha_trigger`-tak helemaal achteraan (Step 9) faalt niets
op het nog-ontbrekende topic-attribuut. Als er tests falen, controleer
eerst of de nieuwe tak echt de laatste in de `if`-keten is.

- [ ] **Step 13: Commit**

```bash
git add mirror_node/scenes.py mirror_node/main.py tests/test_scene_engine.py tests/test_mirror_main.py
git commit -m "feat: mirror_node leest triggers-sleutel + consumeert HA-trigger-pulsen"
```

---

## Task 8: MQTT-contract + `MqttBridge` + `HaTriggerPoller` (HA-vuurmechanisme)

**Files:**
- Modify: `shared/mqtt_contract.py`
- Modify: `admin/app/mqtt_bridge.py`
- Create: `admin/app/ha_trigger_poller.py`
- Modify: `admin/app/main.py`
- Test: `tests/test_mqtt_contract.py`
- Test: `tests/test_admin_mqtt_bridge.py`
- Create: `tests/test_ha_trigger_poller.py`

**Interfaces:**
- Produces: `Topics.control_mirror_ha_trigger` (niet-retained). Sluit
  Taak 7's tijdelijke gat. `MqttBridge.publish_mirror_ha_trigger(entity_id)`.
  `HaTriggerPoller(bridge, get_settings, get_watched_entity_ids,
  check_interval=5, logger=None)` met `.start()`/`.stop()`.

- [ ] **Step 1: Schrijf de falende tests**

In `tests/test_mqtt_contract.py`, voeg toe aan de bestaande topic-test:

```python
    assert topics.control_mirror_ha_trigger == "control/mirror/ha-trigger"
```

In `tests/test_admin_mqtt_bridge.py`, voeg toe:

```python
def test_publish_mirror_ha_trigger_is_not_retained(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)
    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_ha_trigger("binary_sensor.tuin")

    topic, payload, retain = bridge._client.published[-1]
    assert topic == "test/control/mirror/ha-trigger"
    assert json.loads(payload) == {"entity_id": "binary_sensor.tuin"}
    assert retain is False
```

Maak `tests/test_ha_trigger_poller.py`:

```python
from admin.app.ha_trigger_poller import HaTriggerPoller


class _FakeSettings:
    ha_url = "http://ha"
    ha_token = "tok"


class _FakeBridge:
    def __init__(self):
        self.fired = []

    def publish_mirror_ha_trigger(self, entity_id):
        self.fired.append(entity_id)


def test_rising_edge_fires_a_pulse(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "off"}],
    )
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()
    assert bridge.fired == []

    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "on"}],
    )
    poller._tick()
    assert bridge.fired == ["binary_sensor.tuin"]


def test_sustained_on_state_does_not_refire(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "on"}],
    )
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()
    poller._tick()
    poller._tick()

    assert bridge.fired == ["binary_sensor.tuin"]


def test_falling_then_rising_edge_fires_again(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    states = {"state": "off"}
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": states["state"]}],
    )
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    states["state"] = "on"
    poller._tick()
    states["state"] = "off"
    poller._tick()
    states["state"] = "on"
    poller._tick()

    assert bridge.fired == ["binary_sensor.tuin", "binary_sensor.tuin"]


def test_no_watched_entities_skips_the_ha_call(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    called = []
    monkeypatch.setattr(poller_module, "get_states", lambda url, token: called.append(1) or [])
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: [], check_interval=999)

    poller._tick()

    assert called == []
    assert bridge.fired == []


def test_ha_unreachable_does_not_crash_the_tick(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module

    def _raise(url, token):
        raise ConnectionError("HA onbereikbaar")

    monkeypatch.setattr(poller_module, "get_states", _raise)
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()  # mag niet raisen

    assert bridge.fired == []


def test_detected_state_also_counts_as_fired(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.deur", "state": "detected"}],
    )
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.deur"], check_interval=999)

    poller._tick()

    assert bridge.fired == ["binary_sensor.deur"]
```

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py tests/test_admin_mqtt_bridge.py tests/test_ha_trigger_poller.py -q`
Expected: FAIL — ontbrekend attribuut/module

- [ ] **Step 3: Voeg de topic-property toe aan `shared/mqtt_contract.py`**

Na `control_mirror_test`:

```python
    @property
    def control_mirror_ha_trigger(self) -> str:
        return self._p("control/mirror/ha-trigger")
```

- [ ] **Step 4: Voeg de publish-methode toe aan `admin/app/mqtt_bridge.py`**

Na `publish_mirror_test`:

```python
    def publish_mirror_ha_trigger(self, entity_id):
        self._client.publish(self._topics.control_mirror_ha_trigger, json.dumps({"entity_id": entity_id}))
```

- [ ] **Step 5: Implementeer `admin/app/ha_trigger_poller.py`**

```python
import threading

from admin.app.ha_client import get_states


class HaTriggerPoller:
    """Pollt periodiek Home Assistant-entity-states en publiceert een
    eenmalige MQTT-puls zodra een gekoppelde entiteit een STIJGENDE FLANK
    maakt naar 'on'/'detected' (nooit een aanhoudend signaal -- zelfde
    puls-niet-niveau-les als bewegingsdetectie: een blijvend 'aan'-
    signaal zou dezelfde scare-video oneindig laten herhalen)."""

    _FIRED_STATES = {"on", "detected"}

    def __init__(self, bridge, get_settings, get_watched_entity_ids, check_interval=5, logger=None):
        self._bridge = bridge
        self._get_settings = get_settings
        self._get_watched_entity_ids = get_watched_entity_ids
        self._check_interval = check_interval
        self._logger = logger
        self._last_states = {}
        self._stop_event = threading.Event()
        self._thread = None

    def _tick(self):
        """Eén controle. Vangt alles af: HA onbereikbaar of een kapotte
        entity-id mag de achtergrond-thread niet stilletjes doodmaken."""
        try:
            watched = self._get_watched_entity_ids()
            if not watched:
                return
            settings = self._get_settings()
            states = get_states(settings.ha_url, settings.ha_token)
            by_entity = {s.get("entity_id"): s.get("state") for s in states if isinstance(s, dict)}
            for entity_id in watched:
                new_state = by_entity.get(entity_id)
                old_state = self._last_states.get(entity_id)
                if new_state in self._FIRED_STATES and old_state not in self._FIRED_STATES:
                    self._bridge.publish_mirror_ha_trigger(entity_id)
                self._last_states[entity_id] = new_state
        except Exception as exc:
            if self._logger is not None:
                self._logger.error("HA-trigger-polling mislukt: %s", exc)

    def _loop(self):
        while not self._stop_event.is_set():
            self._tick()
            self._stop_event.wait(self._check_interval)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
```

- [ ] **Step 6: Wire de poller in `admin/app/main.py`**

Voeg de import toe:

```python
from admin.app.ha_trigger_poller import HaTriggerPoller
```

Voeg een helper toe (bij `_get_schedule_from_db`):

```python
def _get_watched_ha_entities_from_db(conn):
    def get_watched():
        rows = conn.execute(
            "SELECT DISTINCT ha_entity_id FROM triggers WHERE kind = 'ha_sensor' AND ha_entity_id IS NOT NULL"
        ).fetchall()
        return [r[0] for r in rows]
    return get_watched
```

Voeg de instantie toe (na `app.state.scheduler = Scheduler(...)`):

```python
    app.state.ha_trigger_poller = HaTriggerPoller(
        app.state.bridge, lambda: app.state.runtime_settings,
        _get_watched_ha_entities_from_db(app.state.db), logger=app.state.logger,
    )
```

Voeg `.start()`/`.stop()` toe in de startup/shutdown-handlers:

```python
        app.state.scheduler.start()
        app.state.ha_trigger_poller.start()
```

```python
        app.state.ha_trigger_poller.stop()
        app.state.scheduler.stop()
```

- [ ] **Step 7: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_mqtt_contract.py tests/test_admin_mqtt_bridge.py tests/test_ha_trigger_poller.py tests/test_mirror_main.py -q`
Expected: alle tests PASS (Taak 7's tijdelijke gat is nu ook gesloten)

- [ ] **Step 8: Run de volledige backend-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests PASS. Er zijn geen bekende gaten meer in de
backend/mirror_node-laag.

- [ ] **Step 9: Commit**

```bash
git add shared/mqtt_contract.py admin/app/mqtt_bridge.py admin/app/ha_trigger_poller.py \
  admin/app/main.py tests/test_mqtt_contract.py tests/test_admin_mqtt_bridge.py tests/test_ha_trigger_poller.py
git commit -m "feat: HA-sensor-trigger-vuurmechanisme (poller + MQTT-puls)"
```

---

## Task 9: `mirror_node/camera.py`-extractie + backend voorbeeldpaneel-route

**Files:**
- Create: `mirror_node/camera.py`
- Modify: `mirror_node/main.py`
- Create: `admin/app/routers/preview.py`
- Modify: `admin/app/main.py`
- Test: `tests/test_mirror_camera.py`
- Test: `tests/test_admin_routes_preview.py`

**Interfaces:**
- Consumes: `outputs.camera_source` (Taak 2), `mirror_node.effects.get_effect`
  (bestaand, ongewijzigd), `mirror_node.overlay.composite_overlay`/
  `place_on_canvas` (bestaand, ongewijzigd), `admin.app.media.get_media_path`
  (bestaand, ongewijzigd).
- Produces: `mirror_node.camera.open_camera(source, camera_index=0)`.
  `POST /api/scenes/preview-frame` (body: een `SceneDraft`-achtig
  object met minstens `output_id`/`effect`/`params`/`overlay_hash`/
  `scale`/`position`/`canvas_size`/`source_scale`/`source_position`) →
  `image/jpeg`.

De admin-backend heeft nog nooit rechtstreeks `cv2`/een camera
aangeraakt. `mirror_node`'s eigen effect-/overlay-code
(`mirror_node.effects`, `mirror_node.overlay`) is al camera-onafhankelijk
en dus zonder wijziging importeerbaar vanuit de backend — dit was al zo
sinds de mirror-node-inline-start-feature, die `mirror_node`'s hele
package + dependencies al in hetzelfde Docker-image bakt als de backend.
Alleen `_open_camera` zit vast in `mirror_node/main.py` en wordt hier
naar een eigen, herbruikbaar bestand verplaatst.

- [ ] **Step 1: Schrijf de falende camera.py-test**

Maak `tests/test_mirror_camera.py`:

```python
from unittest.mock import patch, MagicMock
from mirror_node.camera import open_camera


def test_empty_source_opens_local_index():
    with patch("mirror_node.camera.cv2") as mock_cv2:
        mock_cv2.VideoCapture = MagicMock()
        open_camera("", camera_index=2)
        mock_cv2.VideoCapture.assert_called_once_with(2)


def test_numeric_string_source_opens_that_index():
    with patch("mirror_node.camera.cv2") as mock_cv2:
        mock_cv2.VideoCapture = MagicMock()
        open_camera("3", camera_index=0)
        mock_cv2.VideoCapture.assert_called_once_with(3)


def test_url_source_opens_via_ffmpeg():
    with patch("mirror_node.camera.cv2") as mock_cv2:
        mock_cv2.VideoCapture = MagicMock()
        mock_cv2.CAP_FFMPEG = "FFMPEG_SENTINEL"
        open_camera("rtsp://cam.local/stream", camera_index=0)
        mock_cv2.VideoCapture.assert_called_once_with("rtsp://cam.local/stream", "FFMPEG_SENTINEL")
```

- [ ] **Step 2: Run test, verifieer dat 'ie faalt**

Run: `.venv/bin/python -m pytest tests/test_mirror_camera.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mirror_node.camera'`

- [ ] **Step 3: Maak `mirror_node/camera.py`**

```python
import cv2


def open_camera(source, camera_index=0):
    """Opent de camera-bron: leeg -> lokale index (camera_index), een
    numerieke string -> die index, anders -> een netwerkstream via
    FFmpeg. Camera-merk-agnostisch: elke bron die OpenCV/FFmpeg begrijpt
    werkt. Verplaatst uit mirror_node/main.py zodat de admin-backend 'm
    ook kan gebruiken voor het losse voorbeeldpaneel (zonder de fysieke
    spiegel aan te raken)."""
    if not source:
        return cv2.VideoCapture(camera_index)
    try:
        return cv2.VideoCapture(int(source))
    except ValueError:
        return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
```

- [ ] **Step 4: Werk `mirror_node/main.py` bij**

Verwijder de bestaande `_open_camera`-functie volledig:

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

Voeg de import toe (bij de andere `mirror_node`-imports):

```python
from mirror_node.camera import open_camera
```

Vervang de twee aanroepen van `_open_camera(...)` (één in `main()`, één
in `selfcheck()`) door `open_camera(camera_source, CAMERA_INDEX)` en
`open_camera(camera_source, CAMERA_INDEX)` respectievelijk — dezelfde
argumenten, alleen de nieuwe functienaam met `CAMERA_INDEX` nu expliciet
meegegeven in plaats van impliciet via een module-global binnen de
functie zelf. Zoek ook de heropen-aanroep in de hoofdlus
(`cap = _open_camera(camera_source)` na een reeks mislukte reads) en
vervang die op dezelfde manier.

- [ ] **Step 5: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_mirror_camera.py tests/test_mirror_main.py -q`
Expected: alle tests PASS

- [ ] **Step 6: Schrijf de falende preview-route-test**

Maak `tests/test_admin_routes_preview.py`:

```python
from unittest.mock import patch, MagicMock
import numpy as np
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeBridge:
    def start(self): pass
    def stop(self): pass
    def publish_mirror_graph(self, graph): pass
    def publish_mirror_scare_video_config(self, enabled_hashes): pass
    def publish_mirror_ha_trigger(self, entity_id): pass


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
    return client


_DRAFT = {
    "effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0,
    "position": [0.5, 0.5], "canvas_size": None, "source_scale": 1.0,
    "source_position": [0.5, 0.5],
}


def test_preview_frame_returns_jpeg_for_the_default_output(tmp_path):
    client = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, fake_frame)
        mock_open_camera.return_value = mock_cap

        response = client.post("/api/scenes/preview-frame", json={**_DRAFT, "output_id": default_output["id"]})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0
    mock_cap.release.assert_called_once()


def test_preview_frame_rejects_unknown_output_id(tmp_path):
    client = _client(tmp_path)

    response = client.post("/api/scenes/preview-frame", json={**_DRAFT, "output_id": 999})

    assert response.status_code == 400


def test_preview_frame_returns_502_when_camera_read_fails(tmp_path):
    client = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (False, None)
        mock_open_camera.return_value = mock_cap

        response = client.post("/api/scenes/preview-frame", json={**_DRAFT, "output_id": default_output["id"]})

    assert response.status_code == 502


def test_preview_frame_rejects_unknown_effect(tmp_path):
    client = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, fake_frame)
        mock_open_camera.return_value = mock_cap

        response = client.post(
            "/api/scenes/preview-frame",
            json={**_DRAFT, "output_id": default_output["id"], "effect": "onbestaand"},
        )

    assert response.status_code == 400


def test_preview_frame_route_requires_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    response = client.post("/api/scenes/preview-frame", json=_DRAFT)

    assert response.status_code == 401
```

- [ ] **Step 7: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_preview.py -q`
Expected: FAIL — `404 Not Found`

- [ ] **Step 8: Implementeer `admin/app/routers/preview.py`**

```python
import cv2
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from mirror_node.camera import open_camera
from mirror_node.effects import get_effect
from mirror_node.overlay import composite_overlay, place_on_canvas
from admin.app.media import get_media_path

router = APIRouter()


@router.post("/api/scenes/preview-frame")
async def preview_frame_route(request: Request):
    """Rendert één losstaand voorbeeldbeeld voor de concept-scene in
    `draft` -- zonder de fysieke spiegel/mirror-node aan te raken. Haalt
    zelf één camera-frame op van de gekozen output en past dezelfde
    effect-/overlay-code toe als de mirror-node."""
    draft = await request.json()
    db = request.app.state.db
    output_row = db.execute(
        "SELECT camera_source FROM outputs WHERE id = ?", (draft.get("output_id"),)
    ).fetchone()
    if output_row is None:
        raise HTTPException(status_code=400, detail="output_id verwijst naar een onbestaande output")
    camera_source = output_row[0]

    cap = open_camera(camera_source)
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise HTTPException(status_code=502, detail="Kon geen frame van de camera-bron ophalen")

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
        overlay_path = get_media_path(request.app.state.settings.media_dir, overlay_hash)
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
    return Response(content=buf.tobytes(), media_type="image/jpeg")
```

- [ ] **Step 9: Registreer de router in `admin/app/main.py`**

Voeg de import toe:

```python
from admin.app.routers import preview as preview_router
```

Voeg de registratie toe (na `app.include_router(outputs_router.router)`):

```python
    app.include_router(preview_router.router)
```

- [ ] **Step 10: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_preview.py -q`
Expected: alle tests PASS

- [ ] **Step 11: Run de volledige backend-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests PASS. Dit is de laatste backend/mirror_node-taak
in dit plan — geen bekende gaten meer.

- [ ] **Step 12: Commit**

```bash
git add mirror_node/camera.py mirror_node/main.py admin/app/routers/preview.py \
  admin/app/main.py tests/test_mirror_camera.py tests/test_admin_routes_preview.py
git commit -m "feat: losstaand server-side voorbeeldpaneel (POST /api/scenes/preview-frame)"
```

---

## Task 10: Frontend — types.ts + api/triggers.ts + api/outputs.ts

**Files:**
- Modify: `admin/frontend/src/types.ts`
- Modify: `admin/frontend/src/api/scenes.ts` (geen structurele wijziging nodig, alleen ter controle)
- Create: `admin/frontend/src/api/triggers.ts`
- Delete: `admin/frontend/src/api/sceneEdges.ts`
- Create: `admin/frontend/src/api/outputs.ts`

**Interfaces:**
- Consumes: backend-velden uit Taak 5/6 (`Scene.output_id`/`.color`,
  `Trigger.kind`/`.schedule_from`/`.schedule_until`/`.ha_entity_id`/
  `.canvas_x`/`.canvas_y`/`.name`/`.color`), Taak 4's `/api/outputs`.
- Produces: bijgewerkt `Scene`-type, nieuw `Trigger`-type (vervangt
  `SceneEdge`), nieuw `Output`-type.
  `listTriggers/createTrigger/updateTrigger/updateTriggerPosition/deleteTrigger`,
  `listOutputs/getOutput/createOutput/updateOutput/deleteOutput`.
  Gebruikt door Taak 12-18.

- [ ] **Step 1: Werk `Scene` bij en voeg `Trigger`/`Output` toe in `types.ts`**

Vervang de `Scene`-interface:

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
  output_id: number | null;
  color: string | null;
}

export interface Trigger {
  id: number;
  from_scene_id: number;
  to_scene_id: number | null;
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
}
```

Laat de bestaande `SceneEdge`-interface ONGEWIJZIGD staan (nog niet
verwijderen). `SceneGraphCanvas.tsx`/`EdgeTriggerPopover.tsx` gebruiken
'm tot Taak 14 nog volop; verwijderen hier zou dat hele bestand meteen
kapot maken zonder dat er al iets is dat de vervanging klaarzet. Taak 14
verwijdert `SceneEdge` uiteindelijk, op het moment dat de laatste
gebruiker ervan verdwijnt.

- [ ] **Step 2: Verwijder `mirror_camera_source` uit `AppSettings`/`AppSettingsUpdate`**

Vervang:

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

door:

```ts
export interface AppSettings {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  ha_url: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
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
  mqtt_topic_prefix: string;
}
```

- [ ] **Step 3: Maak `admin/frontend/src/api/triggers.ts`**

Laat `admin/frontend/src/api/sceneEdges.ts` ONGEWIJZIGD en onverwijderd
staan — `SceneGraphCanvas.tsx`/`EdgeTriggerPopover.tsx` importeren 'm
nog tot Taak 14/15. Dit nieuwe bestand komt er gewoon naast te staan.

```ts
import { apiFetch } from "./client";
import type { Trigger } from "../types";

export type TriggerDraft = Omit<Trigger, "id">;

export function listTriggers(): Promise<Trigger[]> {
  return apiFetch<Trigger[]>("/api/triggers");
}

export function createTrigger(
  trigger: Partial<TriggerDraft> & { from_scene_id: number },
): Promise<Trigger> {
  return apiFetch<Trigger>("/api/triggers", { method: "POST", body: JSON.stringify(trigger) });
}

export function updateTrigger(id: number, trigger: Partial<TriggerDraft>): Promise<Trigger> {
  return apiFetch<Trigger>(`/api/triggers/${id}`, { method: "PUT", body: JSON.stringify(trigger) });
}

export function updateTriggerPosition(id: number, canvas_x: number, canvas_y: number): Promise<void> {
  return apiFetch(`/api/triggers/${id}/position`, {
    method: "PUT",
    body: JSON.stringify({ canvas_x, canvas_y }),
  });
}

export function deleteTrigger(id: number): Promise<void> {
  return apiFetch(`/api/triggers/${id}`, { method: "DELETE" });
}
```

- [ ] **Step 4: Maak `admin/frontend/src/api/outputs.ts`**

```ts
import { apiFetch } from "./client";
import type { Output } from "../types";

export type OutputDraft = Omit<Output, "id">;

export function listOutputs(): Promise<Output[]> {
  return apiFetch<Output[]>("/api/outputs");
}

export function getOutput(id: number): Promise<Output> {
  return apiFetch<Output>(`/api/outputs/${id}`);
}

export function createOutput(output: OutputDraft): Promise<Output> {
  return apiFetch<Output>("/api/outputs", { method: "POST", body: JSON.stringify(output) });
}

export function updateOutput(id: number, output: OutputDraft): Promise<Output> {
  return apiFetch<Output>(`/api/outputs/${id}`, { method: "PUT", body: JSON.stringify(output) });
}

export function deleteOutput(id: number): Promise<void> {
  return apiFetch(`/api/outputs/${id}`, { method: "DELETE" });
}
```

- [ ] **Step 5: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: fouten in `SceneWizardModal.tsx` en `SettingsPage.tsx`
(gebruiken `AppSettings.mirror_camera_source`, dat in Step 2 hierboven
is verwijderd) — verwacht op dit punt, opgelost in Taak 12. Geen fouten
vanuit `types.ts`, `api/triggers.ts`, `api/outputs.ts`,
`SceneGraphCanvas.tsx`, `EdgeTriggerPopover.tsx` of `DashboardPage.tsx`
(die gebruiken geen van allen `mirror_camera_source`, en de eerste twee
gebruiken nog steeds de nog-aanwezige `SceneEdge`/`api/sceneEdges.ts`
ongewijzigd, dus geen breuk daar).

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/types.ts admin/frontend/src/api/triggers.ts admin/frontend/src/api/outputs.ts
git commit -m "feat: Trigger/Output-types + triggers/outputs-API-clients"
```

---

## Task 11: Backend — camera-bron verhuist van Instellingen naar `outputs`

**Files:**
- Modify: `admin/app/routers/node_config.py`
- Modify: `admin/app/routers/settings.py`
- Modify: `tests/test_admin_routes_node_config.py`
- Modify: `tests/test_admin_routes_settings.py`

**Interfaces:**
- Consumes: `outputs`-tabel (Taak 2).
- Produces: `GET /api/node-config` leest `mirror_camera_source` uit de
  eerste/enige output i.p.v. `app_settings`. `GET/PUT /api/settings`
  accepteert/retourneert `mirror_camera_source` niet meer.

`app_settings.mirror_camera_source` blijft in de DB staan (geen
destructieve schemawijziging, zie Global Constraints) maar wordt door
niets in deze taak nog gelezen of geschreven.

- [ ] **Step 1: Werk de bestaande tests bij**

Vervang in `tests/test_admin_routes_node_config.py` de hele inhoud van
de drie testfuncties:

```python
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
    output = client.get("/api/outputs").json()[0]
    client.put(f"/api/outputs/{output['id']}", json={"name": output["name"], "camera_source": "rtsp://cam.local/stream1"})

    response = client.get("/api/node-config")

    assert response.json() == {
        "mqtt_topic_prefix": "",
        "mirror_camera_source": "rtsp://cam.local/stream1",
    }
```

In `tests/test_admin_routes_settings.py`, verwijder de vijf tests
`test_get_settings_includes_camera_source`,
`test_put_settings_persists_camera_source`,
`test_put_settings_accepts_numeric_camera_source`,
`test_put_settings_accepts_empty_camera_source`,
`test_put_settings_rejects_malformed_camera_source` volledig (regels
174-223 in het huidige bestand) — dat gedrag hoort voortaan bij
`/api/outputs` (al getest in Taak 4).

- [ ] **Step 2: Run tests, verifieer dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_node_config.py tests/test_admin_routes_settings.py -q`
Expected: FAIL op de bijgewerkte node-config-tests (route leest nog uit
`app_settings`)

- [ ] **Step 3: Werk `admin/app/routers/node_config.py` bij**

Vervang de hele inhoud door:

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/node-config")
def get_node_config(request: Request):
    """Publiek endpoint (geen sessie nodig) waar mirror-node/scare-node bij
    het opstarten hun configuratie ophalen -- zie shared/topic_prefix.py.
    Geeft bewust alleen niet-gevoelige/expliciet-publiek-gemaakte velden
    terug: de topic-prefix en de camera-bron van de (voorlopig enige)
    output (beide besproken en geaccepteerd als niet-extra-beveiligd,
    vertrouwd LAN). Nooit MQTT-host/poort/credentials of het HA-token."""
    settings = request.app.state.runtime_settings
    db = request.app.state.db
    output = db.execute("SELECT camera_source FROM outputs ORDER BY id LIMIT 1").fetchone()
    return {
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mirror_camera_source": output[0] if output else "",
    }
```

- [ ] **Step 4: Werk `admin/app/routers/settings.py` bij**

Verwijder de `_validate_camera_source`-functie volledig.

Vervang de `get_settings_route`-response:

```python
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
        "mqtt_pass_set": bool(settings.mqtt_pass),
        "ha_token_set": bool(settings.ha_token),
    }
```

Verwijder in `put_settings_route` de twee regels:

```python
    mirror_camera_source = str(body.get("mirror_camera_source", "")).strip()
    _validate_camera_source(mirror_camera_source)
```

en verwijder `"mirror_camera_source": mirror_camera_source,` uit de
`updates`-dict.

- [ ] **Step 5: Run tests, verifieer dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_node_config.py tests/test_admin_routes_settings.py -q`
Expected: alle tests PASS

- [ ] **Step 6: Run de volledige backend-testsuite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests PASS. Dit sluit de backend-kant van de
camera-bron-verhuizing af; Taak 12 doet de frontend-kant.

- [ ] **Step 7: Commit**

```bash
git add admin/app/routers/node_config.py admin/app/routers/settings.py \
  tests/test_admin_routes_node_config.py tests/test_admin_routes_settings.py
git commit -m "feat: camera-bron voor node-config komt voortaan uit outputs, niet Instellingen"
```

---

## Task 12: Frontend — Instellingen verliest camera-bron, `SceneWizardModal` haalt 'm van de output

**Files:**
- Modify: `admin/frontend/src/pages/SettingsPage.tsx`
- Modify: `admin/frontend/src/components/SceneWizardModal.tsx`

**Interfaces:**
- Consumes: bijgewerkte `AppSettings` (Taak 10), `Output`/`api/outputs`
  (Taak 10), `Scene.output_id` (Taak 10).
- Produces: geen nieuwe interfaces voor latere taken.

- [ ] **Step 1: Werk `SettingsPage.tsx` bij — verwijder camera-bron**

Verwijder `mirror_camera_source` uit `FormState` en `EMPTY_FORM`:

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
};
```

Verwijder `mirror_camera_source: result.mirror_camera_source,` uit de
`setForm(...)`-aanroep in de `useEffect`, en verwijder
`mirror_camera_source: form.mirror_camera_source,` uit de
`putSettings(...)`-aanroep in `handleSave`.

Verwijder het hele `<label className="settings-field settings-field--wide">`-blok
voor "Camera-bron (optioneel)" (inclusief zijn `<input>` en de
toelichtende tekst eronder over "Leeg = de lokale camera..."). Vervang
de toelichtende paragraaf na het "Live-preview-stream-URL"-veld door:

```tsx
            <p className="settings-field__label" style={{ marginTop: "0.75rem" }}>
              De camera-bron stel je per output in op de nieuwe
              Outputs-pagina, niet hier.
            </p>
```

- [ ] **Step 2: Werk `SceneWizardModal.tsx` bij — camera-bron via de output**

Vervang de import-regel:

```ts
import { getSettings } from "../api/settings";
```

door:

```ts
import { getOutput } from "../api/outputs";
```

Vervang de `useEffect` die `cameraSource` zet:

```tsx
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
          setLoaded(true);
        })
        .catch(() => setError("Scene kon niet worden geladen."));
    }
  }, [sceneId]);
```

door:

```tsx
  useEffect(() => {
    if (sceneId !== null) {
      getScene(sceneId)
        .then((scene) => {
          setDraft(scene);
          setCanvasWidthDraft(scene.canvas_size ? String(scene.canvas_size[0]) : "");
          setCanvasHeightDraft(scene.canvas_size ? String(scene.canvas_size[1]) : "");
          setLoaded(true);
        })
        .catch(() => setError("Scene kon niet worden geladen."));
    }
  }, [sceneId]);

  useEffect(() => {
    if (draft.output_id === null) {
      setCameraSource("");
      return;
    }
    getOutput(draft.output_id)
      .then((output) => setCameraSource(output.camera_source))
      .catch(() => {
        /* voorbeeldbeeld blijft dan "niet beschikbaar" */
      });
  }, [draft.output_id]);
```

Vervang de foutmelding in de `output`-stap:

```tsx
                <p className="scene-modal__label">
                  Geen camera-bron ingesteld op de Instellingen-pagina — kan hier niet getoond worden.
                </p>
```

door:

```tsx
                <p className="scene-modal__label">
                  Geen camera-bron ingesteld op de Outputs-pagina voor deze output — kan hier niet getoond worden.
                </p>
```

- [ ] **Step 3: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen fouten meer vanuit `SettingsPage.tsx` of
`SceneWizardModal.tsx` zelf (fouten in `SceneGraphCanvas.tsx`/
`EdgeTriggerPopover.tsx`/`DashboardPage.tsx` blijven tot latere taken).

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/pages/SettingsPage.tsx admin/frontend/src/components/SceneWizardModal.tsx
git commit -m "feat: camera-bron in de wizard komt van de gekozen output, niet Instellingen"
```

---

## Task 13: Frontend — hernoemen (dubbelklik) + kleur op de scene-knoop

**Files:**
- Modify: `admin/frontend/src/components/SceneGraphCanvas.tsx`
- Modify: `admin/frontend/src/components/SceneGraphCanvas.css`

**Interfaces:**
- Consumes: `Scene.color` (Taak 10), `updateScene` (bestaand).
- Produces: `SceneNodeData` krijgt `onRename`/`onSetColor`. Geen nieuwe
  interfaces voor latere taken — Taak 14 (trigger-als-knoop) bouwt
  hierop voort qua patroon (dezelfde hernoem/kleur-aanpak, maar dat is
  een aparte taak met eigen code).

- [ ] **Step 1: Voeg het kleurenpalet en de nieuwe velden toe aan `SceneNodeData`**

Bovenaan `SceneGraphCanvas.tsx`, na de imports:

```ts
const NODE_COLORS = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c", "#3498db", "#9b59b6", "#95a5a6"];
```

Vervang `SceneNodeData` (alleen `onRename`/`onSetColor` toegevoegd; het
bestaande `outputs: SceneEdge[]`-veld en zijn vulling verdwijnen pas in
Taak 14, die de trigger-representatie in dit bestand volledig
herstructureert -- niet aankomen aan `outputs` in deze taak):

```ts
type SceneNodeData = {
  scene: Scene;
  outputs: SceneEdge[];
  onSceneClick: Props["onSceneClick"];
  onAddOutput: (fromSceneId: number) => void;
  onMakeRoot: (sceneId: number) => void;
  onRename: (sceneId: number, name: string) => void;
  onSetColor: (sceneId: number, color: string) => void;
  [key: string]: unknown;
};
```

- [ ] **Step 2: Herschrijf `SceneNodeComponent`'s naam/kleur-gedeelte**

Vervang de hele functie-body tot en met de `scene-node__chips`-`</div>`:

```tsx
function SceneNodeComponent({ data }: NodeProps<SceneNode>) {
  const { scene, outputs, onSceneClick, onAddOutput, onMakeRoot, onRename, onSetColor } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(scene.name);
  const [colorPickerOpen, setColorPickerOpen] = useState(false);

  function commitRename() {
    setEditingName(false);
    const trimmed = nameDraft.trim();
    if (trimmed && trimmed !== scene.name) {
      onRename(scene.id, trimmed);
    } else {
      setNameDraft(scene.name);
    }
  }

  return (
    <div
      className="scene-node"
      data-root={scene.is_root}
      style={scene.color ? { borderColor: scene.color } : undefined}
    >
      <Handle type="target" position={Position.Left} />
      <div className="scene-node__header">
        <button
          type="button"
          className="scene-node__root nodrag"
          onClick={() => onMakeRoot(scene.id)}
          title="Maak root"
        >
          {scene.is_root ? "★" : "☆"}
        </button>
        {editingName ? (
          <input
            className="scene-node__name-input nodrag"
            autoFocus
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setNameDraft(scene.name);
                setEditingName(false);
              }
            }}
          />
        ) : (
          <span
            className="scene-node__name nodrag"
            onClick={() => onSceneClick(scene.id, "input")}
            onDoubleClick={() => setEditingName(true)}
            title="Klik voor instellingen, dubbelklik om te hernoemen"
          >
            {scene.name}
          </span>
        )}
        <button
          type="button"
          className="scene-node__color-swatch nodrag"
          style={{ backgroundColor: scene.color ?? "transparent" }}
          onClick={() => setColorPickerOpen((open) => !open)}
          title="Kleur"
          aria-label="Kleur kiezen"
        />
        {colorPickerOpen && (
          <div className="scene-node__color-palette nodrag">
            {NODE_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className="scene-node__color-option"
                style={{ backgroundColor: c }}
                onClick={() => {
                  onSetColor(scene.id, c);
                  setColorPickerOpen(false);
                }}
                aria-label={`Kies kleur ${c}`}
              />
            ))}
          </div>
        )}
      </div>
      <div className="scene-node__chips">
        <span className="scene-node__chip nodrag" onClick={() => onSceneClick(scene.id, "input")}>
          {scene.source_mode === "camera" ? "Camera" : "Scare-video"}
        </span>
        {scene.source_mode === "camera" && (
          <>
            <span className="scene-node__chip nodrag" onClick={() => onSceneClick(scene.id, "animation")}>
              {scene.effect}
            </span>
            <span className="scene-node__chip nodrag" onClick={() => onSceneClick(scene.id, "output")}>
              Weergave
            </span>
          </>
        )}
      </div>
```

(De rest van de functie -- `scene-node__outputs` en de
`+ output`-knop -- blijft ongewijzigd staan; voeg wel `nodrag` toe aan
de bestaande `+ output`-knop: `className="scene-node__add-output nodrag"`.)

- [ ] **Step 3: Voeg de handlers toe in `SceneGraphCanvas`**

Na `handleMakeRoot`:

```tsx
  const handleRename = useCallback(
    async (sceneId: number, name: string) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, name });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
  );

  const handleSetColor = useCallback(
    async (sceneId: number, color: string) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, color });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
  );
```

Werk de `flowNodes`-`useMemo` bij: voeg `onRename: handleRename,
onSetColor: handleSetColor,` toe aan de `data`-object-literal, en voeg
`handleRename, handleSetColor` toe aan de dependency-array.

- [ ] **Step 4: Voeg CSS toe aan `SceneGraphCanvas.css`**

```css
.scene-node__name-input {
  font-weight: 700;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 4px;
  color: var(--bone);
  padding: 0.1rem 0.3rem;
  font-size: inherit;
  font-family: inherit;
  width: 100%;
}

.scene-node__color-swatch {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid var(--panel-edge);
  cursor: pointer;
  padding: 0;
  margin-left: auto;
  flex-shrink: 0;
}

.scene-node__color-palette {
  position: absolute;
  top: 2.2rem;
  right: 0.5rem;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.3rem;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 8px;
  padding: 0.4rem;
  z-index: 10;
}

.scene-node__color-option {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1px solid var(--panel-edge);
  cursor: pointer;
  padding: 0;
}
```

Vul in `.scene-node__header` (bestaande regel) `position: relative;`
toe als dat er nog niet staat, zodat `.scene-node__color-palette`'s
`position: absolute` t.o.v. de header ankert.

- [ ] **Step 5: Typecheck + build**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build`
Expected: 0 fouten. `SceneEdge` bestaat nog (Taak 10 liet 'm bewust
staan), dus dit bestand blijft in zijn geheel typeveilig na deze taak.

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/components/SceneGraphCanvas.tsx admin/frontend/src/components/SceneGraphCanvas.css
git commit -m "feat: scene-knoop hernoembaar (dubbelklik) + kleur-swatch"
```

---

## Task 14: Frontend — trigger wordt een zichtbare, sleepbare knoop op de canvas

**Files:**
- Modify: `admin/frontend/src/components/SceneGraphCanvas.tsx` (grote herstructurering)
- Modify: `admin/frontend/src/components/SceneGraphCanvas.css`
- Rename: `admin/frontend/src/components/EdgeTriggerPopover.tsx` → `admin/frontend/src/components/TriggerPopover.tsx`
- Rename: `admin/frontend/src/components/EdgeTriggerPopover.css` → `admin/frontend/src/components/TriggerPopover.css`
- Delete: `admin/frontend/src/api/sceneEdges.ts`
- Test: `admin/frontend/src/components/SceneGraphCanvas.test.tsx` (bijgewerkt)

**Interfaces:**
- Consumes: `Trigger`/`api/triggers.ts` (Taak 10), `SceneNodeData`
  incl. `onRename`/`onSetColor` (Taak 13).
- Produces: `SceneGraphCanvas`-props worden `{ scenes, triggers,
  onSceneClick, onGraphChanged, onAddScene }` (was `edges`). Nieuwe
  `TriggerPopover`-props: `{ trigger: Trigger, onClose, onSaved }`
  (basisvorm, zonder HA-sensor-optie -- die voegt Taak 15 toe). Gebruikt
  door Taak 18 (DashboardPage-wiring).

Een trigger wordt voortaan een echte, eigen canvas-knoop: het eerste
stuk van een verbinding (scene → trigger) ontstaat via de bestaande
"+ output"-knop op een scene (die nu `createTrigger` aanroept i.p.v.
`createSceneEdge`); het tweede stuk (trigger → scene) sleep je vanaf de
trigger-knoop's eigen output-handle naar een doel-scene. Klikken op een
trigger-knoop opent het configuratiepaneel (voorheen bereikbaar via een
klik op de verbindingslijn).

- [ ] **Step 1: Werk de bestaande canvas-test bij**

In `admin/frontend/src/components/SceneGraphCanvas.test.tsx`, vervang de
mock-imports bovenaan:

```tsx
vi.mock("../api/triggers", () => ({
  createTrigger: vi.fn(),
  updateTrigger: vi.fn(),
  deleteTrigger: vi.fn(),
  updateTriggerPosition: vi.fn(),
}));
vi.mock("../api/scenes", () => ({
  updateScene: vi.fn(),
  updateScenePosition: vi.fn(),
}));
```

En werk de twee `render(...)`-aanroepen bij: vervang de prop `edges={[]}`
door `triggers={[]}` in beide tests.

- [ ] **Step 2: Run de test, verifieer dat 'ie faalt**

Run: `cd admin/frontend && npx vitest run src/components/SceneGraphCanvas.test.tsx`
Expected: FAIL (compileert niet: `triggers`-prop bestaat nog niet)

- [ ] **Step 3: Hernoem `EdgeTriggerPopover` → `TriggerPopover`**

```bash
git mv admin/frontend/src/components/EdgeTriggerPopover.tsx admin/frontend/src/components/TriggerPopover.tsx
git mv admin/frontend/src/components/EdgeTriggerPopover.css admin/frontend/src/components/TriggerPopover.css
```

Vervang de hele inhoud van `TriggerPopover.tsx` door:

```tsx
import { useState } from "react";
import { updateTrigger, deleteTrigger } from "../api/triggers";
import type { Trigger } from "../types";
import "./TriggerPopover.css";

interface Props {
  trigger: Trigger;
  onClose: () => void;
  onSaved: () => void;
}

export default function TriggerPopover({ trigger, onClose, onSaved }: Props) {
  const [kind, setKind] = useState<NonNullable<Trigger["kind"]>>(trigger.kind ?? "always");
  const [from, setFrom] = useState(trigger.schedule_from ?? "");
  const [until, setUntil] = useState(trigger.schedule_until ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    try {
      await updateTrigger(trigger.id, {
        from_scene_id: trigger.from_scene_id,
        to_scene_id: trigger.to_scene_id,
        kind,
        schedule_from: kind === "schedule" ? from : null,
        schedule_until: kind === "schedule" ? until : null,
        ha_entity_id: trigger.ha_entity_id,
        priority: trigger.priority,
        canvas_x: trigger.canvas_x,
        canvas_y: trigger.canvas_y,
        name: trigger.name,
        color: trigger.color,
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
      await deleteTrigger(trigger.id);
      onSaved();
      onClose();
    } catch {
      setError("Verwijderen is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="trigger-popover__backdrop" role="dialog" aria-modal="true">
      <div className="trigger-popover">
        <p className="trigger-popover__title">Trigger instellen</p>
        {error && (
          <p className="trigger-popover__error" role="alert">
            {error}
          </p>
        )}
        <div className="trigger-popover__options">
          <label className="trigger-popover__radio">
            <input
              type="radio"
              name="trigger-kind"
              checked={kind === "always"}
              onChange={() => setKind("always")}
            />
            Altijd
          </label>
          <label className="trigger-popover__radio">
            <input
              type="radio"
              name="trigger-kind"
              checked={kind === "motion"}
              onChange={() => setKind("motion")}
            />
            Beweging
          </label>
          <label className="trigger-popover__radio">
            <input
              type="radio"
              name="trigger-kind"
              checked={kind === "schedule"}
              onChange={() => setKind("schedule")}
            />
            Tijdschema
          </label>
          {kind === "schedule" && (
            <div className="trigger-popover__schedule">
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
        <div className="trigger-popover__actions">
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

Vervang in `TriggerPopover.css` alle voorkomens van de klasse-prefix
`edge-popover` door `trigger-popover` (zelfde regels, alleen de
selector-namen hernoemd: `.edge-popover__backdrop` →
`.trigger-popover__backdrop`, enzovoort voor elke klasse in het
bestand).

- [ ] **Step 4: Herschrijf `SceneGraphCanvas.tsx` volledig**

Vervang de hele inhoud door:

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
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
import { updateScene, updateScenePosition } from "../api/scenes";
import TriggerPopover from "./TriggerPopover";
import type { Scene, Trigger } from "../types";
import "./SceneGraphCanvas.css";

const NODE_COLORS = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#1abc9c", "#3498db", "#9b59b6", "#95a5a6"];

interface Props {
  scenes: Scene[];
  triggers: Trigger[];
  onSceneClick: (sceneId: number, step: "input" | "animation" | "output") => void;
  onGraphChanged: () => void;
  onAddScene: () => void;
}

type SceneNodeData = {
  scene: Scene;
  onSceneClick: Props["onSceneClick"];
  onAddOutput: (fromSceneId: number) => void;
  onMakeRoot: (sceneId: number) => void;
  onRename: (sceneId: number, name: string) => void;
  onSetColor: (sceneId: number, color: string) => void;
  [key: string]: unknown;
};

type TriggerNodeData = {
  trigger: Trigger;
  onTriggerClick: (triggerId: number) => void;
  onRename: (triggerId: number, name: string) => void;
  onSetColor: (triggerId: number, color: string) => void;
  [key: string]: unknown;
};

// @xyflow/react's Node<T> constrains T to Record<string, unknown>; the
// index signatures above satisfy that constraint for our data payloads.
type SceneNode = Node<SceneNodeData, "scene">;
type TriggerNode = Node<TriggerNodeData, "trigger">;
type FlowNode = SceneNode | TriggerNode;

function triggerKindLabel(trigger: Trigger): string {
  if (trigger.kind === "always") return "Altijd";
  if (trigger.kind === "motion") return "Beweging";
  if (trigger.kind === "schedule") return `${trigger.schedule_from ?? "?"}–${trigger.schedule_until ?? "?"}`;
  if (trigger.kind === "ha_sensor") return trigger.ha_entity_id ?? "HA-sensor";
  return "Nog niet ingesteld";
}

function SceneNodeComponent({ data }: NodeProps<SceneNode>) {
  const { scene, onSceneClick, onAddOutput, onMakeRoot, onRename, onSetColor } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(scene.name);
  const [colorPickerOpen, setColorPickerOpen] = useState(false);

  function commitRename() {
    setEditingName(false);
    const trimmed = nameDraft.trim();
    if (trimmed && trimmed !== scene.name) {
      onRename(scene.id, trimmed);
    } else {
      setNameDraft(scene.name);
    }
  }

  return (
    <div
      className="scene-node"
      data-root={scene.is_root}
      style={scene.color ? { borderColor: scene.color } : undefined}
    >
      <Handle type="target" position={Position.Left} />
      <div className="scene-node__header">
        <button
          type="button"
          className="scene-node__root nodrag"
          onClick={() => onMakeRoot(scene.id)}
          title="Maak root"
        >
          {scene.is_root ? "★" : "☆"}
        </button>
        {editingName ? (
          <input
            className="scene-node__name-input nodrag"
            autoFocus
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setNameDraft(scene.name);
                setEditingName(false);
              }
            }}
          />
        ) : (
          <span
            className="scene-node__name nodrag"
            onClick={() => onSceneClick(scene.id, "input")}
            onDoubleClick={() => setEditingName(true)}
            title="Klik voor instellingen, dubbelklik om te hernoemen"
          >
            {scene.name}
          </span>
        )}
        <button
          type="button"
          className="scene-node__color-swatch nodrag"
          style={{ backgroundColor: scene.color ?? "transparent" }}
          onClick={() => setColorPickerOpen((open) => !open)}
          title="Kleur"
          aria-label="Kleur kiezen"
        />
        {colorPickerOpen && (
          <div className="scene-node__color-palette nodrag">
            {NODE_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className="scene-node__color-option"
                style={{ backgroundColor: c }}
                onClick={() => {
                  onSetColor(scene.id, c);
                  setColorPickerOpen(false);
                }}
                aria-label={`Kies kleur ${c}`}
              />
            ))}
          </div>
        )}
      </div>
      <div className="scene-node__chips">
        <span className="scene-node__chip nodrag" onClick={() => onSceneClick(scene.id, "input")}>
          {scene.source_mode === "camera" ? "Camera" : "Scare-video"}
        </span>
        {scene.source_mode === "camera" && (
          <>
            <span className="scene-node__chip nodrag" onClick={() => onSceneClick(scene.id, "animation")}>
              {scene.effect}
            </span>
            <span className="scene-node__chip nodrag" onClick={() => onSceneClick(scene.id, "output")}>
              Weergave
            </span>
          </>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
      <button type="button" className="scene-node__add-output nodrag" onClick={() => onAddOutput(scene.id)}>
        + output
      </button>
    </div>
  );
}

function TriggerNodeComponent({ data }: NodeProps<TriggerNode>) {
  const { trigger, onTriggerClick, onRename, onSetColor } = data;
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(trigger.name ?? "");
  const [colorPickerOpen, setColorPickerOpen] = useState(false);

  function commitRename() {
    setEditingName(false);
    const trimmed = nameDraft.trim();
    if (trimmed !== (trigger.name ?? "")) {
      onRename(trigger.id, trimmed);
    }
  }

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
            onClick={() => onTriggerClick(trigger.id)}
            onDoubleClick={() => setEditingName(true)}
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

const nodeTypes = { scene: SceneNodeComponent, trigger: TriggerNodeComponent };

export default function SceneGraphCanvas({ scenes, triggers, onSceneClick, onGraphChanged, onAddScene }: Props) {
  const [popoverTrigger, setPopoverTrigger] = useState<Trigger | null>(null);

  const handleAddOutput = useCallback(
    async (fromSceneId: number) => {
      await createTrigger({ from_scene_id: fromSceneId });
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

  const handleRenameScene = useCallback(
    async (sceneId: number, name: string) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, name });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
  );

  const handleSetSceneColor = useCallback(
    async (sceneId: number, color: string) => {
      const scene = scenes.find((s) => s.id === sceneId);
      if (!scene) return;
      const { id: _id, ...draft } = scene;
      await updateScene(sceneId, { ...draft, color });
      onGraphChanged();
    },
    [scenes, onGraphChanged],
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
      ...scenes.map(
        (scene): SceneNode => ({
          id: `scene-${scene.id}`,
          type: "scene",
          position: { x: scene.canvas_x, y: scene.canvas_y },
          data: {
            scene,
            onSceneClick,
            onAddOutput: handleAddOutput,
            onMakeRoot: handleMakeRoot,
            onRename: handleRenameScene,
            onSetColor: handleSetSceneColor,
          },
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
      scenes,
      triggers,
      onSceneClick,
      handleAddOutput,
      handleMakeRoot,
      handleRenameScene,
      handleSetSceneColor,
      handleTriggerClick,
      handleRenameTrigger,
      handleSetTriggerColor,
    ],
  );

  const flowEdges: Edge[] = useMemo(() => {
    const result: Edge[] = [];
    for (const trigger of triggers) {
      result.push({
        id: `in-${trigger.id}`,
        source: `scene-${trigger.from_scene_id}`,
        target: `trigger-${trigger.id}`,
      });
      if (trigger.to_scene_id !== null) {
        result.push({
          id: `out-${trigger.id}`,
          source: `trigger-${trigger.id}`,
          sourceHandle: "out",
          target: `scene-${trigger.to_scene_id}`,
          markerEnd: { type: MarkerType.ArrowClosed },
        });
      }
    }
    return result;
  }, [triggers]);

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(flowNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(flowEdges);

  useEffect(() => {
    setNodes(flowNodes);
  }, [flowNodes, setNodes]);

  useEffect(() => {
    setRfEdges(flowEdges);
  }, [flowEdges, setRfEdges]);

  const handleConnect = useCallback(
    async (connection: Connection) => {
      if (!connection.source?.startsWith("trigger-") || !connection.target?.startsWith("scene-")) return;
      const triggerId = parseInt(connection.source.replace("trigger-", ""), 10);
      const sceneId = parseInt(connection.target.replace("scene-", ""), 10);
      if (Number.isNaN(triggerId) || Number.isNaN(sceneId)) return;
      const trigger = triggers.find((t) => t.id === triggerId);
      if (!trigger) return;
      const { id: _id, ...draft } = trigger;
      await updateTrigger(triggerId, { ...draft, to_scene_id: sceneId });
      onGraphChanged();
    },
    [triggers, onGraphChanged],
  );

  const handleNodeDragStop = useCallback(async (_event: unknown, node: FlowNode) => {
    if (node.id.startsWith("scene-")) {
      await updateScenePosition(parseInt(node.id.replace("scene-", ""), 10), node.position.x, node.position.y);
    } else {
      await updateTriggerPosition(parseInt(node.id.replace("trigger-", ""), 10), node.position.x, node.position.y);
    }
  }, []);

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
        fitView
      >
        <Background />
        <Controls />
      </ReactFlow>
      <button type="button" className="scene-graph-canvas__add" onClick={onAddScene}>
        + Nieuwe scene
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

- [ ] **Step 5: Verwijder `admin/frontend/src/api/sceneEdges.ts`**

```bash
git rm admin/frontend/src/api/sceneEdges.ts
```

- [ ] **Step 6: Voeg CSS toe voor de nieuwe trigger-knoop**

Voeg toe aan `SceneGraphCanvas.css`:

```css
.trigger-node {
  position: relative;
  min-width: 120px;
  padding: 0.5rem;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 8px;
  color: var(--bone);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 0.75rem;
}

.trigger-node__header {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  position: relative;
}

.trigger-node__name {
  cursor: pointer;
  font-weight: 700;
}

.trigger-node__name-input {
  font-weight: 700;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 4px;
  color: var(--bone);
  padding: 0.1rem 0.3rem;
  font-size: inherit;
  font-family: inherit;
  width: 100%;
}

.trigger-node__kind {
  display: block;
  margin-top: 0.2rem;
  color: var(--ash);
}

.trigger-node__color-swatch {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 1px solid var(--panel-edge);
  cursor: pointer;
  padding: 0;
  margin-left: auto;
  flex-shrink: 0;
}

.trigger-node__color-palette {
  position: absolute;
  top: 1.6rem;
  right: 0;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.3rem;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 8px;
  padding: 0.4rem;
  z-index: 10;
}

.trigger-node__color-option {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1px solid var(--panel-edge);
  cursor: pointer;
  padding: 0;
}
```

Verwijder de nu overbodige `.scene-node__outputs`/`.scene-node__output`/
`.scene-node__output-label`-regels uit `SceneGraphCanvas.css` (de
per-trigger handle-rijen binnen een scene-knoop bestaan niet meer —
elke trigger is nu zijn eigen, losse knoop).

- [ ] **Step 7: Run tests, verifieer dat ze slagen**

Run: `cd admin/frontend && npx vitest run src/components/SceneGraphCanvas.test.tsx`
Expected: alle tests PASS

- [ ] **Step 8: Typecheck + build**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build`
Expected: geen fouten meer vanuit `SceneGraphCanvas.tsx` of
`TriggerPopover.tsx`. `DashboardPage.tsx` geeft nu fouten: het
importeert nog `listSceneEdges` uit `../api/sceneEdges`, dat bestand is
zojuist in Step 5 verwijderd (module bestaat niet meer), en het roept
`SceneGraphCanvas` nog aan met de oude `edges`-prop i.p.v. `triggers`.
Beide zijn verwacht — Taak 18 lost ze samen op.

- [ ] **Step 9: Commit**

```bash
git add admin/frontend/src/components/SceneGraphCanvas.tsx admin/frontend/src/components/SceneGraphCanvas.css \
  admin/frontend/src/components/TriggerPopover.tsx admin/frontend/src/components/TriggerPopover.css \
  admin/frontend/src/components/SceneGraphCanvas.test.tsx
git rm admin/frontend/src/components/EdgeTriggerPopover.tsx admin/frontend/src/components/EdgeTriggerPopover.css 2>/dev/null || true
git commit -m "feat: trigger is nu een zichtbare, sleepbare knoop op de canvas"
```

---

## Task 15: Frontend — `TriggerPopover`: HA-sensor-optie + entiteit-dropdown

**Files:**
- Modify: `admin/frontend/src/components/TriggerPopover.tsx`
- Modify: `admin/frontend/src/components/TriggerPopover.css`

**Interfaces:**
- Consumes: `getHaStates()` (bestaand, `admin/frontend/src/api/ha.ts`),
  `HaState` (bestaand type).
- Produces: geen nieuwe interfaces voor latere taken — dit is de
  laatste trigger-gerelateerde frontend-taak.

- [ ] **Step 1: Werk de imports bij**

Voeg toe aan `TriggerPopover.tsx`:

```ts
import { getHaStates } from "../api/ha";
import type { HaState } from "../types";
```

- [ ] **Step 2: Voeg HA-states-state toe**

Na de bestaande `useState`-declaraties:

```ts
  const [haEntityId, setHaEntityId] = useState(trigger.ha_entity_id ?? "");
  const [haStates, setHaStates] = useState<HaState[]>([]);
  const [haLoadError, setHaLoadError] = useState(false);
  const [showAllDomains, setShowAllDomains] = useState(false);

  useEffect(() => {
    if (kind !== "ha_sensor") return;
    getHaStates()
      .then(setHaStates)
      .catch(() => setHaLoadError(true));
  }, [kind]);
```

(Voeg `useEffect` toe aan de bestaande `import { useState } from "react";`-regel: `import { useEffect, useState } from "react";`.)

- [ ] **Step 3: Werk `handleSave` bij**

Vervang `ha_entity_id: trigger.ha_entity_id,` in de `updateTrigger`-aanroep door:

```ts
        ha_entity_id: kind === "ha_sensor" ? haEntityId : null,
```

Voeg vóór de `try`-block in `handleSave` een validatie toe:

```ts
    if (kind === "ha_sensor" && !haEntityId) {
      setError("Kies een HA-entiteit.");
      return;
    }
```

- [ ] **Step 4: Voeg de radio-optie en dropdown toe aan de JSX**

Na het `Tijdschema`-`<label>` (vóór de `{kind === "schedule" && (...)}`-blok):

```tsx
          <label className="trigger-popover__radio">
            <input
              type="radio"
              name="trigger-kind"
              checked={kind === "ha_sensor"}
              onChange={() => setKind("ha_sensor")}
            />
            Home Assistant-sensor
          </label>
          {kind === "ha_sensor" && (
            <div className="trigger-popover__ha">
              {haLoadError && <p className="trigger-popover__error">HA-entiteiten konden niet geladen worden.</p>}
              <label>
                <span>Entiteit</span>
                <select value={haEntityId} onChange={(e) => setHaEntityId(e.target.value)}>
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
              <label className="trigger-popover__checkbox">
                <input
                  type="checkbox"
                  checked={showAllDomains}
                  onChange={(e) => setShowAllDomains(e.target.checked)}
                />
                Toon alle entiteiten (niet alleen binary_sensor)
              </label>
            </div>
          )}
```

- [ ] **Step 5: Voeg CSS toe**

Voeg toe aan `TriggerPopover.css`:

```css
.trigger-popover__ha {
  margin-left: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.trigger-popover__ha select {
  width: 100%;
  padding: 0.4rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 6px;
  color: var(--bone);
}

.trigger-popover__checkbox {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  color: var(--ash);
}
```

- [ ] **Step 6: Typecheck + build**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build`
Expected: geen fouten meer vanuit `TriggerPopover.tsx`. `DashboardPage.tsx`
geeft nog steeds zijn bekende, tot Taak 18 verwachte fout.

- [ ] **Step 7: Commit**

```bash
git add admin/frontend/src/components/TriggerPopover.tsx admin/frontend/src/components/TriggerPopover.css
git commit -m "feat: TriggerPopover -- HA-sensor-optie met entiteit-dropdown"
```

---

## Task 16: Frontend — nieuwe Outputs-pagina + navigatie

**Files:**
- Create: `admin/frontend/src/pages/OutputsPage.tsx`
- Create: `admin/frontend/src/pages/OutputsPage.css`
- Modify: `admin/frontend/src/App.tsx`
- Modify: `admin/frontend/src/components/Layout.tsx`

**Interfaces:**
- Consumes: `listOutputs/createOutput/updateOutput/deleteOutput`
  (Taak 10).
- Produces: route `/outputs`, navigatie-item "Outputs". Geen nieuwe
  interfaces voor latere taken.

- [ ] **Step 1: Maak `admin/frontend/src/pages/OutputsPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { listOutputs, createOutput, updateOutput, deleteOutput } from "../api/outputs";
import type { Output } from "../types";
import "./OutputsPage.css";

interface Draft {
  name: string;
  camera_source: string;
}

export default function OutputsPage() {
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [newName, setNewName] = useState("");
  const [newCameraSource, setNewCameraSource] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function refresh() {
    listOutputs()
      .then((result) => {
        setOutputs(result);
        setDrafts(Object.fromEntries(result.map((o) => [o.id, { name: o.name, camera_source: o.camera_source }])));
        setError(null);
      })
      .catch(() => setError("Outputs konden niet worden geladen."));
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
      await createOutput({ name: newName.trim(), camera_source: newCameraSource.trim() });
      setNewName("");
      setNewCameraSource("");
      refresh();
      showNotice("Output aangemaakt.");
    } catch {
      setError("Aanmaken is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSave(id: number) {
    const draft = drafts[id];
    if (!draft) return;
    setSaving(true);
    try {
      await updateOutput(id, draft);
      refresh();
      showNotice("Output opgeslagen.");
    } catch {
      setError("Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Deze output verwijderen?")) return;
    setSaving(true);
    try {
      await deleteOutput(id);
      refresh();
    } catch {
      setError("Verwijderen is mislukt — heeft deze output nog scenes?");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="outputs-page">
      <header className="outputs-header">
        <p className="outputs-eyebrow">
          <span className="outputs-eyebrow__led" aria-hidden="true" />
          Fysieke uitgangen
        </p>
        <h1 className="outputs-heading">Outputs</h1>
      </header>

      {error && (
        <p className="outputs-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="outputs-notice" role="status">
          {notice}
        </p>
      )}

      <section className="outputs-panel">
        {outputs.map((output) => {
          const draft = drafts[output.id] ?? { name: output.name, camera_source: output.camera_source };
          return (
            <div className="outputs-row" key={output.id}>
              <input
                className="outputs-field__input"
                type="text"
                value={draft.name}
                onChange={(e) => updateDraft(output.id, { name: e.target.value })}
              />
              <input
                className="outputs-field__input outputs-field__input--wide"
                type="text"
                value={draft.camera_source}
                placeholder="bijv. rtsp://gebruiker:wachtwoord@192.168.1.50:554/stream1"
                onChange={(e) => updateDraft(output.id, { camera_source: e.target.value })}
              />
              <button type="button" onClick={() => handleSave(output.id)} disabled={saving}>
                Opslaan
              </button>
              <button type="button" onClick={() => handleDelete(output.id)} disabled={saving}>
                Verwijderen
              </button>
            </div>
          );
        })}

        <div className="outputs-row outputs-row--new">
          <input
            className="outputs-field__input"
            type="text"
            placeholder="Naam (bijv. Beamer tuin)"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <input
            className="outputs-field__input outputs-field__input--wide"
            type="text"
            placeholder="Camera-bron (optioneel)"
            value={newCameraSource}
            onChange={(e) => setNewCameraSource(e.target.value)}
          />
          <button type="button" onClick={handleCreate} disabled={saving || !newName.trim()}>
            + Output toevoegen
          </button>
        </div>
      </section>

      <p className="outputs-field__label">
        Leeg = de lokale camera op de node zelf. Een RTSP/HTTP-URL gebruikt die
        camera in plaats daarvan — elk merk met een standaard stream werkt.
        Nodes halen dit pas op bij hun eerstvolgende herstart. Een output met
        nog scenes eraan gekoppeld kan niet verwijderd worden.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Maak `admin/frontend/src/pages/OutputsPage.css`**

```css
.outputs-page {
  padding: 1.5rem 2rem;
  color: var(--bone);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

.outputs-header {
  margin-bottom: 1.5rem;
}

.outputs-eyebrow {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ash);
  margin: 0 0 0.3rem;
}

.outputs-eyebrow__led {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ember);
}

.outputs-heading {
  margin: 0;
  font-size: 1.5rem;
}

.outputs-error {
  color: var(--alarm);
  margin-bottom: 1rem;
}

.outputs-notice {
  color: var(--signal);
  margin-bottom: 1rem;
}

.outputs-panel {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 10px;
  padding: 1rem;
}

.outputs-row {
  display: grid;
  grid-template-columns: 1fr 2fr auto auto;
  gap: 0.6rem;
  align-items: center;
}

.outputs-row--new {
  grid-template-columns: 1fr 2fr auto;
  border-top: 1px dashed var(--panel-edge);
  padding-top: 0.75rem;
}

.outputs-field__input {
  padding: 0.5rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 6px;
  color: var(--bone);
}

.outputs-field__label {
  margin-top: 1rem;
  font-size: 0.8rem;
  color: var(--ash);
}
```

- [ ] **Step 3: Registreer de route in `App.tsx`**

Voeg de import toe:

```ts
import OutputsPage from "./pages/OutputsPage";
```

Voeg de route toe (na `/settings`):

```tsx
          <Route path="/outputs" element={<OutputsPage />} />
```

- [ ] **Step 4: Voeg het navigatie-item toe in `Layout.tsx`**

Voeg toe aan de `links`-array (vóór `/settings`):

```ts
  { to: "/outputs", label: "Outputs", end: false },
```

- [ ] **Step 5: Typecheck + build**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build`
Expected: geen fouten vanuit deze nieuwe/gewijzigde bestanden.
`DashboardPage.tsx` geeft nog steeds zijn bekende, tot Taak 18
verwachte fout.

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/pages/OutputsPage.tsx admin/frontend/src/pages/OutputsPage.css \
  admin/frontend/src/App.tsx admin/frontend/src/components/Layout.tsx
git commit -m "feat: Outputs-pagina (CRUD voor fysieke uitgangen)"
```

---

## Task 17: Frontend — los, server-side gerenderd voorbeeldpaneel

**Files:**
- Create: `admin/frontend/src/components/PreviewPanel.tsx`
- Create: `admin/frontend/src/components/PreviewPanel.css`
- Modify: `admin/frontend/src/components/SceneWizardModal.tsx`

**Interfaces:**
- Consumes: `POST /api/scenes/preview-frame` (Taak 9), bestaande
  `SceneDraft`-type.
- Produces: `<PreviewPanel draft={SceneDraft} onClose={() => void} />`.
  Vervangt de bestaande automatische live-push-naar-hardware-preview
  volledig — die raakte de fysieke spiegel bij elke wijziging aan, wat
  expliciet niet meer gewenst is.

- [ ] **Step 1: Maak `admin/frontend/src/components/PreviewPanel.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import type { SceneDraft } from "../api/scenes";
import "./PreviewPanel.css";

interface Props {
  draft: SceneDraft;
  onClose: () => void;
}

export default function PreviewPanel({ draft, onClose }: Props) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const lastFetchedAtRef = useRef(0);
  const throttleTimerRef = useRef<number | null>(null);

  // Leading-edge throttle (max. 1x per 150ms), zelfde patroon als de
  // vroegere live-hardware-preview -- alleen doelt dit nu op de eigen
  // /api/scenes/preview-frame-route i.p.v. de fysieke spiegel.
  useEffect(() => {
    const THROTTLE_MS = 150;

    async function fetchPreview() {
      lastFetchedAtRef.current = Date.now();
      setLoading(true);
      try {
        const response = await fetch("/api/scenes/preview-frame", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
        if (!response.ok) {
          setError("Voorbeeld kon niet worden opgehaald.");
          return;
        }
        const blob = await response.blob();
        setImageUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return URL.createObjectURL(blob);
        });
        setError(null);
      } catch {
        setError("Voorbeeld kon niet worden opgehaald.");
      } finally {
        setLoading(false);
      }
    }

    const elapsed = Date.now() - lastFetchedAtRef.current;
    if (elapsed >= THROTTLE_MS) {
      fetchPreview();
    } else {
      if (throttleTimerRef.current) window.clearTimeout(throttleTimerRef.current);
      throttleTimerRef.current = window.setTimeout(fetchPreview, THROTTLE_MS - elapsed);
    }

    return () => {
      if (throttleTimerRef.current) window.clearTimeout(throttleTimerRef.current);
    };
  }, [draft]);

  useEffect(() => {
    return () => {
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    };
  }, [imageUrl]);

  return (
    <div className="preview-panel">
      <div className="preview-panel__header">
        <p className="preview-panel__title">Voorbeeld</p>
        <button type="button" className="preview-panel__close" onClick={onClose} aria-label="Sluiten">
          ×
        </button>
      </div>
      {error && (
        <p className="preview-panel__error" role="alert">
          {error}
        </p>
      )}
      {imageUrl ? (
        <img className="preview-panel__image" src={imageUrl} alt="Voorbeeld van de scene" />
      ) : (
        <p className="preview-panel__loading">{loading ? "Bezig…" : "Nog geen voorbeeld."}</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Maak `admin/frontend/src/components/PreviewPanel.css`**

```css
.preview-panel {
  position: fixed;
  top: 1.5rem;
  right: 1.5rem;
  width: 320px;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 10px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
  color: var(--bone);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  padding: 0.75rem;
  z-index: 70;
}

.preview-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.preview-panel__title {
  margin: 0;
  font-weight: 700;
  font-size: 0.85rem;
}

.preview-panel__close {
  background: transparent;
  border: none;
  color: var(--bone);
  font-size: 1.2rem;
  cursor: pointer;
  line-height: 1;
}

.preview-panel__error {
  color: var(--alarm);
  font-size: 0.75rem;
}

.preview-panel__image {
  width: 100%;
  border-radius: 6px;
  display: block;
}

.preview-panel__loading {
  color: var(--ash);
  font-size: 0.8rem;
  text-align: center;
  padding: 2rem 0;
}
```

- [ ] **Step 3: Werk `SceneWizardModal.tsx` bij — verwijder de automatische hardware-push, voeg het paneel toe**

Vervang de import-regel:

```ts
import { getScene, createScene, updateScene, deleteScene, previewScene, type SceneDraft } from "../api/scenes";
```

door:

```ts
import { getScene, createScene, updateScene, deleteScene, type SceneDraft } from "../api/scenes";
```

Voeg toe:

```ts
import PreviewPanel from "./PreviewPanel";
```

Verwijder de hele bestaande live-preview-`useEffect`-block (inclusief
de bijbehorende `lastPreviewSentAtRef`/`previewThrottleTimerRef` en hun
commentaarblok):

```tsx
  // Live preview tijdens het bewerken -- alleen mogelijk voor een al
  // opgeslagen scene (de preview-route heeft een id nodig), en alleen voor
  // een camera-scene: een scare_video-scene heeft niets previewbaars (de
  // Animatie/Output-stappen worden er ook al voor overgeslagen), en zou de
  // SceneEngine op de mirror-node juist volledig zwart laten renderen
  // (fired=False, volledige 30s-TTL) zolang de wizard openstaat.
  // Leading-edge throttle (max. 1x per 150ms), niet debounce -- debounce
  // stuurt tijdens een sleep pas iets zodra de operator stopt met bewegen,
  // waardoor de live preview de sleep niet in (bijna-)realtime volgt.
  // Zelfde patroon als de inmiddels verwijderde MirrorPage.tsx gebruikte.
  const lastPreviewSentAtRef = useRef(0);
  const previewThrottleTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (sceneId === null || !loaded || draft.source_mode !== "camera") return;
    const THROTTLE_MS = 150;

    function send() {
      lastPreviewSentAtRef.current = Date.now();
      previewScene(sceneId!, draft).catch((err) => console.error("Preview mislukt:", err));
    }

    const elapsed = Date.now() - lastPreviewSentAtRef.current;
    if (elapsed >= THROTTLE_MS) {
      send();
    } else {
      if (previewThrottleTimerRef.current) window.clearTimeout(previewThrottleTimerRef.current);
      previewThrottleTimerRef.current = window.setTimeout(send, THROTTLE_MS - elapsed);
    }

    return () => {
      if (previewThrottleTimerRef.current) window.clearTimeout(previewThrottleTimerRef.current);
    };
  }, [sceneId, draft, loaded]);
```

Voeg in plaats daarvan alleen wat state toe (op dezelfde plek):

```ts
  const [previewOpen, setPreviewOpen] = useState(false);
```

(Als `useRef` daarmee nergens anders meer in dit bestand gebruikt
wordt, verwijder 'm ook uit de `import { useEffect, useRef, useState }
from "react";`-regel — controleer eerst of er nog een andere
`useRef`-aanroep in het bestand staat.)

Voeg een "Preview"-knop toe in `scene-modal__header`, ná de bestaande
`scene-modal__close`-knop:

```tsx
          {draft.source_mode === "camera" && (
            <button
              type="button"
              className="scene-modal__preview-toggle"
              onClick={() => setPreviewOpen((open) => !open)}
            >
              {previewOpen ? "Preview verbergen" : "Preview"}
            </button>
          )}
```

Voeg het paneel toe direct vóór de sluitende `</div>` van
`scene-modal__backdrop` (dus als sibling van `.scene-modal`, niet
erbinnen):

```tsx
      {previewOpen && draft.source_mode === "camera" && (
        <PreviewPanel draft={draft} onClose={() => setPreviewOpen(false)} />
      )}
```

- [ ] **Step 4: Voeg een kleine stijl toe voor de preview-knop**

Voeg toe aan `SceneWizardModal.css`:

```css
.scene-modal__preview-toggle {
  background: transparent;
  border: 1px solid var(--panel-edge);
  color: var(--bone);
  border-radius: 6px;
  padding: 0.3rem 0.6rem;
  font-size: 0.75rem;
  cursor: pointer;
  margin-right: 0.5rem;
}
```

- [ ] **Step 5: Typecheck + build**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build`
Expected: geen fouten meer vanuit `SceneWizardModal.tsx` of de nieuwe
bestanden. `DashboardPage.tsx` geeft nog steeds zijn bekende, tot
Taak 18 verwachte fout.

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/components/PreviewPanel.tsx admin/frontend/src/components/PreviewPanel.css \
  admin/frontend/src/components/SceneWizardModal.tsx admin/frontend/src/components/SceneWizardModal.css
git commit -m "feat: los, server-side gerenderd voorbeeldpaneel (vervangt live-hardware-push)"
```

---

## Task 18: Frontend — `DashboardPage`-wiring + opruiming `SceneEdge`-type

**Files:**
- Modify: `admin/frontend/src/pages/DashboardPage.tsx`
- Modify: `admin/frontend/src/types.ts`

**Interfaces:**
- Consumes: `listTriggers` (Taak 10), bijgewerkte `SceneGraphCanvas`-
  props (Taak 14).
- Produces: geen — dit is de laatste taak in het hele plan. Sluit elk
  bekend, tijdelijk gat dat de voorgaande taken bewust open lieten.

- [ ] **Step 1: Werk de imports bij**

Vervang:

```ts
import { listSceneEdges } from "../api/sceneEdges";
```

door:

```ts
import { listTriggers } from "../api/triggers";
```

Vervang:

```ts
import type { NodeStatusMap, Schedule, Scene, SceneEdge, WsMessage } from "../types";
```

door:

```ts
import type { NodeStatusMap, Schedule, Scene, Trigger, WsMessage } from "../types";
```

- [ ] **Step 2: Werk de state en `refreshScenes` bij**

Vervang:

```ts
  const [sceneEdges, setSceneEdges] = useState<SceneEdge[]>([]);
```

door:

```ts
  const [triggers, setTriggers] = useState<Trigger[]>([]);
```

Vervang in `refreshScenes`:

```ts
    listSceneEdges()
      .then(setSceneEdges)
      .catch(() => setError("Verbindingen konden niet worden geladen."));
```

door:

```ts
    listTriggers()
      .then(setTriggers)
      .catch(() => setError("Triggers konden niet worden geladen."));
```

- [ ] **Step 3: Werk de `SceneGraphCanvas`-aanroep bij**

Vervang:

```tsx
        <SceneGraphCanvas
          scenes={scenes}
          edges={sceneEdges}
          onSceneClick={(id, step) => openWizard(id, step)}
          onGraphChanged={refreshScenes}
          onAddScene={() => openWizard(null)}
        />
```

door:

```tsx
        <SceneGraphCanvas
          scenes={scenes}
          triggers={triggers}
          onSceneClick={(id, step) => openWizard(id, step)}
          onGraphChanged={refreshScenes}
          onAddScene={() => openWizard(null)}
        />
```

- [ ] **Step 4: Verwijder de nu ongebruikte `SceneEdge`-interface uit `types.ts`**

`DashboardPage.tsx` was de laatste plek in de hele frontend die
`SceneEdge` nog gebruikte (Taak 14 verving alle andere gebruikers al
door `Trigger`). Verwijder de hele `SceneEdge`-interface uit
`admin/frontend/src/types.ts`:

```ts
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

- [ ] **Step 5: Typecheck + build**

Run: `cd admin/frontend && npx tsc --noEmit && npx vite build`
Expected: 0 fouten — geen bekende gaten meer in de hele frontend.

- [ ] **Step 6: Run de frontend-tests**

Run: `cd admin/frontend && npx vitest run`
Expected: alle tests PASS (de Taak-1-tests en de Taak-14-canvas-tests).

- [ ] **Step 7: Run de volledige backend-testsuite (regressie-check)**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests PASS — deze taak raakt alleen frontend-bestanden,
maar een volledige regressiecheck aan het eind van het plan hoort erbij.

- [ ] **Step 8: Commit**

```bash
git add admin/frontend/src/pages/DashboardPage.tsx admin/frontend/src/types.ts
git commit -m "feat: Dashboard toont triggers i.p.v. scene-edges, SceneEdge-type opgeruimd"
```

---

## Self-Review Notes

- **Spec coverage:** Trigger-als-knoop + HA-sensor-type (Taken 3, 6, 7,
  8, 14, 15), Outputs als eerste-klas entiteit (Taken 2, 4, 5, 11, 16),
  hernoemen + kleur op scenes én triggers (Taken 13, 14), los
  server-side voorbeeldpaneel (Taken 9, 17), klik-op-stap-bug (Taak 1,
  onderzoekend van aard per het ontbreken van een live-reproductie in
  deze sessie) — elk onderdeel van de spec heeft een taak. De
  migratie-volgorde uit de spec (outputs → scenes.output_id → triggers-
  hernoeming) is exact gevolgd in Taken 2-3.
- **Bekende, tijdelijke gaten en waar ze sluiten:** Taak 5 introduceert
  een gat in `publish_graph` (`admin.app.routers.triggers` bestaat nog
  niet) — gesloten door Taak 6. Taak 7 introduceert een gat op
  `topics.control_mirror_ha_trigger` — gesloten door Taak 8. Taak 10
  laat `SceneEdge`/`api/sceneEdges.ts` bewust ongemoeid staan (nog in
  gebruik door `SceneGraphCanvas.tsx`/`EdgeTriggerPopover.tsx`/
  `DashboardPage.tsx`) — Taak 14 vervangt de eerste twee gebruikers en
  verwijdert `api/sceneEdges.ts`; Taak 18 vervangt de laatste gebruiker
  (`DashboardPage.tsx`) en verwijdert tot slot het `SceneEdge`-type
  zelf. Elk tussenliggend gat is expliciet benoemd in de betreffende
  taak, inclusief wélke foutmelding verwacht wordt, zodat een
  implementer een onverwachte breuk kan onderscheiden van een bekende.
- **Type consistency:** `Trigger.kind`/`.schedule_from`/
  `.schedule_until`/`.ha_entity_id`/`.canvas_x`/`.canvas_y`/`.name`/
  `.color` (Taak 10) worden letterlijk zo gebruikt in
  `SceneGraphCanvas.tsx`/`TriggerPopover.tsx` (Taak 14-15) en matchen
  1-op-1 de backend `_row_to_trigger`-sleutels (Taak 6).
  `SceneGraph.resolve(motion_active, now_hhmm, fired_ha_entities=frozenset())`
  (Taak 7) wordt ongewijzigd zo aangeroepen in `mirror_node/main.py`'s
  hoofdlus (Taak 7, zelfde taak). `Output.camera_source` (Taak 10)
  matcht de backend `_row_to_output`-sleutel (Taak 4) en wordt zo
  gebruikt in `SceneWizardModal.tsx`/`OutputsPage.tsx` (Taak 12, 16).
