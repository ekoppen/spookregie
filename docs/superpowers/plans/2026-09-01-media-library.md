# Algemene medialibrary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eén algemeen media-systeem (`kind`: image/audio/video) in plaats van drie hardgecodeerde categorieën, plus twee nieuwe Source-kinds (`video_loop`, `audio`) zodat video en audio ook als eigen source in de flow-graaf bruikbaar zijn.

**Architecture:** De bestaande `media`-tabel krijgt haar `category`-kolom hernoemd naar `kind` (image/audio/video), met dezelfde magic-byte-validatie op de nieuwe waarden. `sources.kind` krijgt twee nieuwe waarden (`video_loop`, `audio`); een Player krijgt een nieuw, onafhankelijk `audio_source_id`-veld naast het bestaande `source_id` (video). `mirror_node` speelt `video_loop` af door `_ensure_source` te laten loopen, en beheert een los, continu loopend audioproces via een nieuwe `_AudioState`-tracker. Op de frontend wordt `MediaLibrary` van categorie- naar kind-gebaseerd omgebouwd en overal (incl. de drie bestaande embed-plekken) hergebruikt; een nieuwe `/media`-pagina, een picker in `SourcesPage`, en canvas-ondersteuning voor het slepen van een audio-source-edge naar een player sluiten het geheel af.

**Tech Stack:** FastAPI/SQLite (backend), React/TypeScript/@xyflow/react (frontend), OpenCV + ffmpeg/aplay (mirror_node), pytest (backend tests), vitest/RTL (frontend tests).

**Spec:** `docs/superpowers/specs/2026-09-01-media-library-design.md`

## Global Constraints

- Geen nieuwe bestandsformaten boven PNG (image), WAV (audio), MP4 (video).
- Geen nieuw node/edge-type in de canvas-graaf voor audio — audio hangt aan de Player via `audio_source_id`, niet aan een los knooppunt (het canvas-deel gebruikt wel een tweede *Handle* op het bestaande Player-knooppunt om een audio-Source aan te sluiten — dat is geen nieuw node-type).
- Geen gelijktijdige meerdere audio-sources per player — precies één, zelfde exclusiviteit als video.
- Geen waveform-preview, video-thumbnails, of trim/edit-tools.
- Het bestaande one-shot scare-audio/scare-video trigger-mechanisme moet blijven werken zoals nu — alleen de onderliggende kolomnaam verandert (`category` → `kind`), geen ander gedrag.
- Geen publieke/externe base-url-instelling — `BACKEND_URL` blijft het enige basis-url-mechanisme.
- Elke DB-migratie moet idempotent/guarded zijn (dit codebase heeft eerder productie-incidenten gehad met ongeguarde migraties) — volg het bestaande `PRAGMA user_version`-patroon in `admin/app/db.py` voor de rename, en `_ensure_column` voor nieuwe kolommen.
- Geen DB-foreign-keys — app-level cleanup, zelfde conventie als de rest van deze codebase (zie `devices.output_id`).
- FastAPI route-parameters getypeerd als `{id:int}`.
- Nederlandse gebruikersteksten en Nederlandse code-comments, zelfde toon als de rest van de codebase.
- Backend-tests via `.venv/bin/python -m pytest tests/ -q` (of `pytest tests/ -q` als de venv al actief is) vanaf de repo-root. Frontend-typecheck via `cd admin/frontend && npx tsc --noEmit`, frontend-tests via `npm test` (vanuit `admin/frontend`).
- Elke schrijvende route die de graaf raakt roept `publish_graph(db, request.app.state.bridge)` aan (bestaande conventie, zie `admin/app/graph_publish.py`).

**Ontwerp-correctie t.o.v. de spec (vastgelegd hier, geldt voor Taak 10):** de spec suggereerde een `MediaLibrary`-popover op het Player-canvasknooppunt om `audio_source_id` te kiezen. Dat klopt niet: `MediaLibrary` kiest een media-*hash*, maar `audio_source_id` wijst naar een *Source*-rij (die op zijn beurt een hash bevat via `value`). Het bestaande canvas-patroon voor `source_id` (video) is al een sleep-verbinding van een Source-knooppunt naar een Player-knooppunt (`handleConnect`) — Taak 10 volgt exact datzelfde patroon voor `audio_source_id`, geen popover. `SourcesPage`'s gebruik van `MediaLibrary` (Taak 9) is wél correct zoals in de spec: daar kies je een hash om in `Source.value` te zetten, dat is de juiste laag.

---

### Taak 1: DB-migratie — `media.category` → `kind`, `players.audio_source_id`

**Files:**
- Modify: `admin/app/db.py`
- Test: `tests/test_admin_db.py`

**Interfaces:**
- Produces: `media`-tabel heeft voortaan een `kind`-kolom (niet meer `category`) met waarden `image`/`audio`/`video`. `players`-tabel heeft een nieuwe, nullable `audio_source_id INTEGER`-kolom.

- [ ] **Step 1: Schrijf de falende migratie-tests**

Voeg toe aan `tests/test_admin_db.py` (onderaan, na de bestaande device-tests):

```python
def test_media_category_column_renamed_to_kind(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(media)")}

    assert "kind" in cols
    assert "category" not in cols


def test_existing_media_categories_are_remapped_to_kinds(tmp_path):
    db_path = str(tmp_path / "test.db")
    # Zet een pre-upgrade media-rij neer met de oude schema-naam, zoals een
    # echte bestaande deployment 'm zou hebben vóór deze migratie ooit draait.
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE media (
            hash TEXT PRIMARY KEY, filename TEXT NOT NULL,
            category TEXT NOT NULL, uploaded_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "INSERT INTO media VALUES (?, ?, ?, ?)", ("a" * 64, "spook.png", "mirror_overlay", "1.0")
    )
    conn.execute(
        "INSERT INTO media VALUES (?, ?, ?, ?)", ("b" * 64, "gil.wav", "scare_audio", "2.0")
    )
    conn.execute(
        "INSERT INTO media VALUES (?, ?, ?, ?)", ("c" * 64, "zombie.mp4", "mirror_scare_video", "3.0")
    )
    conn.commit()
    conn.close()

    conn = init_db(db_path)

    rows = {r[0]: r[1] for r in conn.execute("SELECT hash, kind FROM media")}
    assert rows["a" * 64] == "image"
    assert rows["b" * 64] == "audio"
    assert rows["c" * 64] == "video"


def test_media_kind_migration_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO media (hash, filename, kind, uploaded_at) VALUES (?, ?, ?, ?)",
        ("d" * 64, "geluid.wav", "audio", "1.0"),
    )
    conn.commit()
    conn.close()

    conn = init_db(db_path)  # tweede run mag niet crashen op een niet-bestaande 'category'-kolom

    row = conn.execute("SELECT kind FROM media WHERE hash = ?", ("d" * 64,)).fetchone()
    assert row[0] == "audio"  # ongewijzigd, niet per ongeluk opnieuw geremapt


def test_players_get_audio_source_id_column(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    cols = {row[1] for row in conn.execute("PRAGMA table_info(players)")}

    assert "audio_source_id" in cols


def test_existing_player_audio_source_id_defaults_to_null(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    row = conn.execute("SELECT audio_source_id FROM players LIMIT 1").fetchone()

    assert row[0] is None
```

`tests/test_admin_db.py` importeert `sqlite3` al niet standaard bovenaan (check het bestaande bestand) — voeg `import sqlite3` toe aan de top-imports als die er nog niet staat (nodig voor de pre-upgrade-simulatie in de tweede test hierboven, zelfde patroon als `_LEGACY_SCENES_DDL` gebruikt).

- [ ] **Step 2: Run de tests, bevestig dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -k "media_kind or media_category or audio_source_id" -v`
Expected: FAIL — `kind`-kolom bestaat nog niet, `audio_source_id` bestaat nog niet.

- [ ] **Step 3: Implementeer de migratie**

In `admin/app/db.py`, wijzig de `CREATE TABLE IF NOT EXISTS media` (regel ~16-22) — laat `category` gewoon staan in de CREATE (voor een verse installatie is dit dood gewicht totdat de migratie hem hernoemt, maar dat is exact hetzelfde patroon als de bestaande `scenes`→`players`-rename hierboven in dit bestand, dus consistent):

Voeg een nieuwe migratiefunctie toe, ná `_migrate_output_connections` (die eindigt op regel 471) en vóór de sluitende newline:

```python
def _migrate_media_kind(conn):
    """Hernoemt media.category naar media.kind en zet de drie oude
    categoriewaarden om naar de nieuwe kind-waarden (image/audio/video).
    Idempotent via PRAGMA user_version (>=8), zelfde patroon als de
    scene_edges->triggers-hernoeming op versie 2."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 8:
        return
    conn.execute("ALTER TABLE media RENAME COLUMN category TO kind")
    conn.execute(
        """UPDATE media SET kind = CASE kind
             WHEN 'mirror_overlay' THEN 'image'
             WHEN 'scare_audio' THEN 'audio'
             WHEN 'mirror_scare_video' THEN 'video'
             ELSE kind
           END"""
    )
    conn.execute("PRAGMA user_version = 8")
```

In `init_db`, roep hem aan direct na `_migrate_output_connections(conn)` (regel 153), vóór `conn.commit()`:

```python
    _migrate_output_connections(conn)
    _migrate_media_kind(conn)
    conn.commit()
```

Voor `players.audio_source_id`: in `_migrate_scenes_to_players` (regel ~361-406), voeg een vierde `_ensure_column`-regel toe direct na de bestaande drie (regel 400-402):

```python
    _ensure_column(conn, "players", "source_id", "INTEGER")
    _ensure_column(conn, "players", "playback_mode", "TEXT NOT NULL DEFAULT 'once'")
    _ensure_column(conn, "players", "repeat_while_ha_entity_id", "TEXT")
    _ensure_column(conn, "players", "audio_source_id", "INTEGER")
```

- [ ] **Step 4: Run de tests, bevestig dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_db.py -v`
Expected: alle tests slagen, inclusief de bestaande (niet alleen de nieuwe).

- [ ] **Step 5: Commit**

```bash
git add admin/app/db.py tests/test_admin_db.py
git commit -m "feat: migratie media.category->kind en players.audio_source_id"
```

---

### Taak 2: Backend `media.py`/`routers/media.py` — `category` → `kind`

**Files:**
- Modify: `admin/app/media.py`
- Modify: `admin/app/routers/media.py`
- Test: `tests/test_admin_media.py`
- Test: `tests/test_admin_routes_media.py`

**Interfaces:**
- Consumes: Taak 1's `media.kind`-kolom.
- Produces: `validate_upload(data, kind)`, `save_media(conn, media_dir, data, filename, kind)`, `list_media(conn, kind=None)`, `extract_audio_if_video(media_dir, hash_, kind)` — allemaal met `kind` i.p.v. `category` als parameternaam en waarden `image`/`audio`/`video`. Route `GET/POST /api/media` gebruikt voortaan de query-/form-parameter `kind`.

- [ ] **Step 1: Herschrijf de falende tests**

In `tests/test_admin_media.py`, vervang overal `category="..."` → `kind="..."` en de oude waarden door de nieuwe. Concreet, vervang de volledige inhoud van het bestand met dezelfde tests als nu, maar met deze substituties (mechanische 1-op-1-mapping, geen gedragswijziging):
- `"mirror_overlay"` → `"image"`
- `"scare_audio"` → `"audio"`
- `"mirror_scare_video"` → `"video"`
- elk `category=` keyword-argument → `kind=`
- `overlays[0]["category"]` (regel 71) → `overlays[0]["kind"]`
- `list_media(conn, category="mirror_overlay")` → `list_media(conn, kind="image")`

Zelfde mechanische substitutie in `tests/test_admin_routes_media.py`: elke `"category": "..."` in een `data={...}`-dict wordt `"kind": "..."` met de nieuwe waarde, elke `params={"category": "..."}` wordt `params={"kind": "..."}`, en de `_upload`-helperfunctie's parameternaam `category` wordt `kind`.

- [ ] **Step 2: Run de tests, bevestig dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_media.py tests/test_admin_routes_media.py -v`
Expected: FAIL — `validate_upload()` krijgt nog een onbekende `kind`-waarde te verwerken tegen de oude categorienamen, dus de PNG/WAV/MP4-checks matchen niet meer.

- [ ] **Step 3: Implementeer de rename in `admin/app/media.py`**

Vervang de hele inhoud van `validate_upload`:

```python
def validate_upload(data, kind):
    """Geeft een foutmelding terug, of None als de upload in orde is.
    Alleen de magic bytes worden gecheckt — genoeg om een verkeerd bestand
    bij upload te weigeren in plaats van een node er later op te laten
    stuklopen (zie spec)."""
    if len(data) > MAX_UPLOAD_SIZE:
        return f"bestand is groter dan {MAX_UPLOAD_SIZE // (1024 * 1024)} MB"
    if kind == "image" and not data.startswith(b"\x89PNG"):
        return "afbeelding moet een PNG-bestand zijn"
    if kind == "audio" and not (data[:4] == b"RIFF" and data[8:12] == b"WAVE"):
        return "audio moet een WAV-bestand zijn"
    if kind == "video" and data[4:8] != b"ftyp":
        return "video moet een MP4-bestand zijn"
    return None


def save_media(conn, media_dir, data, filename, kind):
    os.makedirs(media_dir, exist_ok=True)
    hash_ = content_hash(data)
    with open(os.path.join(media_dir, hash_), "wb") as f:
        f.write(data)
    conn.execute(
        "INSERT OR REPLACE INTO media (hash, filename, kind, uploaded_at) VALUES (?, ?, ?, ?)",
        (hash_, filename, kind, str(time.time())),
    )
    conn.commit()
    return hash_
```

`extract_audio_if_video`: vervang de parameternaam en de check:

```python
def extract_audio_if_video(media_dir, hash_, kind):
    """Extraheert het geluidsspoor van een geüploade video naar
    <hash>.audio via ffmpeg. Best-effort: geen geluidsspoor, een
    ontbrekende ffmpeg-binary, of een mislukte extractie levert gewoon
    geen bestand op -- de video-upload zelf mag hier nooit op stuklopen."""
    if kind != "video":
        return
    ...  # rest ongewijzigd
```

`list_media`: vervang parameternaam en SQL-kolomnaam:

```python
def list_media(conn, kind=None):
    if kind is not None:
        rows = conn.execute(
            "SELECT hash, filename, kind, uploaded_at FROM media WHERE kind = ? ORDER BY uploaded_at DESC",
            (kind,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT hash, filename, kind, uploaded_at FROM media ORDER BY uploaded_at DESC"
        ).fetchall()
    return [
        {"hash": r[0], "filename": r[1], "kind": r[2], "uploaded_at": r[3]}
        for r in rows
    ]
```

- [ ] **Step 4: Implementeer de rename in `admin/app/routers/media.py`**

```python
@router.post("/api/media")
async def upload_media(request: Request, file: UploadFile, kind: str = Form(...)):
    data = await file.read()
    error = validate_upload(data, kind)
    if error is not None:
        raise HTTPException(status_code=400, detail=error)
    h = save_media(request.app.state.db, request.app.state.settings.media_dir, data, file.filename, kind)
    extract_audio_if_video(request.app.state.settings.media_dir, h, kind)
    return {"hash": h, "filename": file.filename, "kind": kind}


@router.get("/api/media")
def list_media_route(request: Request, kind: str | None = None):
    return list_media(request.app.state.db, kind=kind)
```

De rest van `routers/media.py` (download/delete-routes) blijft ongewijzigd — die gebruiken geen `category`/`kind`.

- [ ] **Step 5: Run de tests, bevestig dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_media.py tests/test_admin_routes_media.py -v`
Expected: PASS.

- [ ] **Step 6: Volledige backend-suite draaien (regressiecheck)**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests slagen — met name `test_admin_media.py`'s `delete_media`-tests die `mirror_config.overlay_hash` schoonvegen blijven werken (die kolom heet nog steeds `overlay_hash`, ongewijzigd door deze taak).

- [ ] **Step 7: Commit**

```bash
git add admin/app/media.py admin/app/routers/media.py tests/test_admin_media.py tests/test_admin_routes_media.py
git commit -m "feat: media-opslag van category naar algemeen kind-veld (image/audio/video)"
```

---

### Taak 3: Backend `sources.py` — nieuwe kinds `video_loop`/`audio`

**Files:**
- Modify: `admin/app/routers/sources.py`
- Test: `tests/test_admin_routes_sources.py`

**Interfaces:**
- Produces: `sources.kind` accepteert voortaan ook `video_loop` en `audio` naast de bestaande `camera_stream`/`static_image`. Geen andere routegedrag-wijziging — een Source is op zichzelf altijd geldig voor elk van de vier kinds; welke kind in welk Player-veld mag wordt in Taak 4 afgedwongen.

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_admin_routes_sources.py`:

```python
def test_create_source_accepts_video_loop_kind(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/sources", json={
        "name": "Achtergrondloop", "kind": "video_loop", "value": "a" * 64, "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 200
    assert response.json()["kind"] == "video_loop"


def test_create_source_accepts_audio_kind(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/sources", json={
        "name": "Achtergrondgeluid", "kind": "audio", "value": "b" * 64, "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 200
    assert response.json()["kind"] == "audio"
```

- [ ] **Step 2: Run de tests, bevestig dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_sources.py -v`
Expected: FAIL met 400 (`kind moet één van ['camera_stream', 'static_image'] zijn`).

- [ ] **Step 3: Implementeer**

In `admin/app/routers/sources.py`, regel 8:

```python
_VALID_KINDS = {"camera_stream", "static_image", "video_loop", "audio"}
```

- [ ] **Step 4: Run de tests, bevestig dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add admin/app/routers/sources.py tests/test_admin_routes_sources.py
git commit -m "feat: sources accepteren nu ook video_loop en audio kinds"
```

---

### Taak 4: Backend `players.py` — `audio_source_id`, kind-validatie, cleanup-on-delete

**Files:**
- Modify: `admin/app/routers/players.py`
- Modify: `admin/app/routers/sources.py`
- Test: `tests/test_admin_routes_players.py`
- Test: `tests/test_admin_routes_sources.py`

**Interfaces:**
- Consumes: `sources.kind` uit Taak 3 (`camera_stream`/`static_image`/`video_loop`/`audio`), `players.audio_source_id`-kolom uit Taak 1.
- Produces: `Player`-payload krijgt `audio_source_id`. `POST/PUT /api/players` valideert dat `source_id` een video-kind-Source is en `audio_source_id` (indien gezet) een audio-kind-Source. `DELETE /api/sources/{id}` zet `audio_source_id` op `NULL` bij elke player die naar de verwijderde source verwees (i.p.v. te blokkeren, zoals nu al gebeurt voor `source_id`).

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_admin_routes_players.py` (bovenaan staat al een `_PLAYER_PAYLOAD`-achtige constante rond regel 45 met `"source_id": None, ...` — check de exacte naam in het bestand en gebruik die als basis):

```python
def test_create_player_with_audio_source_id(tmp_path):
    client, bridge = _client(tmp_path)
    default_source = client.get("/api/sources").json()[0]
    audio_source = client.post("/api/sources", json={
        "name": "Kraken", "kind": "audio", "value": "a" * 64, "canvas_x": 0.0, "canvas_y": 0.0,
    }).json()

    created = client.post("/api/players", json={
        **_PLAYER_PAYLOAD, "source_id": default_source["id"], "audio_source_id": audio_source["id"],
    }).json()

    assert created["audio_source_id"] == audio_source["id"]


def test_create_player_rejects_audio_source_id_of_wrong_kind(tmp_path):
    client, bridge = _client(tmp_path)
    default_source = client.get("/api/sources").json()[0]  # camera_stream, geen audio

    response = client.post("/api/players", json={
        **_PLAYER_PAYLOAD, "source_id": default_source["id"], "audio_source_id": default_source["id"],
    })

    assert response.status_code == 400


def test_create_player_rejects_source_id_of_audio_kind(tmp_path):
    client, bridge = _client(tmp_path)
    audio_source = client.post("/api/sources", json={
        "name": "Kraken", "kind": "audio", "value": "a" * 64, "canvas_x": 0.0, "canvas_y": 0.0,
    }).json()

    response = client.post("/api/players", json={**_PLAYER_PAYLOAD, "source_id": audio_source["id"]})

    assert response.status_code == 400


def test_create_player_without_audio_source_id_defaults_to_null(tmp_path):
    client, bridge = _client(tmp_path)
    default_source = client.get("/api/sources").json()[0]

    created = client.post("/api/players", json={**_PLAYER_PAYLOAD, "source_id": default_source["id"]}).json()

    assert created["audio_source_id"] is None
```

(Gebruik de exacte naam van de bestaande payload-constante zoals die in het bestand staat — check regel ~20-45 vóórdat je deze tests toevoegt; als de constante `_PLAYER_PAYLOAD` niet zo heet, gebruik de werkelijke naam consistent met de rest van het bestand.)

Voeg toe aan `tests/test_admin_routes_sources.py`:

```python
def test_delete_source_nulls_out_audio_source_id_on_players(tmp_path):
    client, bridge = _client(tmp_path)
    default_source = client.get("/api/sources").json()[0]
    audio_source = client.post("/api/sources", json={
        "name": "Kraken", "kind": "audio", "value": "a" * 64, "canvas_x": 0.0, "canvas_y": 0.0,
    }).json()
    player = client.post("/api/players", json={
        "name": "X", "enabled": True, "source_mode": "camera", "effect": "xray",
        "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
        "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
        "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0, "color": None,
        "source_id": default_source["id"], "audio_source_id": audio_source["id"],
        "playback_mode": "once", "repeat_while_ha_entity_id": None,
    }).json()

    response = client.delete(f"/api/sources/{audio_source['id']}")

    assert response.status_code == 200
    updated_player = client.get(f"/api/players/{player['id']}").json()
    assert updated_player["audio_source_id"] is None
```

- [ ] **Step 2: Run de tests, bevestig dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py tests/test_admin_routes_sources.py -v`
Expected: FAIL — `audio_source_id` bestaat nog niet in de payload/kolommen, geen kind-validatie.

- [ ] **Step 3: Implementeer in `admin/app/routers/players.py`**

`_PLAYER_COLUMNS` (regel 14-18): voeg `audio_source_id` toe aan het eind:

```python
_PLAYER_COLUMNS = (
    "id, name, enabled, source_mode, effect, params, overlay_hash, "
    "scale, position, canvas_width, canvas_height, source_scale, source_position, "
    "is_root, canvas_x, canvas_y, color, source_id, playback_mode, repeat_while_ha_entity_id, "
    "audio_source_id"
)
```

`_DEFAULT_PLAYER` (regel 20-39): voeg toe vóór de sluitende `}`:

```python
    "audio_source_id": None,
```

`_row_to_player` (regel 42-64): voeg toe na `row[19]` (het laatste bestaande veld):

```python
        "repeat_while_ha_entity_id": row[19],
        "audio_source_id": row[20],
```

Voeg een nieuwe validatiefunctie toe, direct na `_resolve_source_id` (regel 85-94):

```python
def _validate_source_kind(db, source_id, allowed_kinds, field_label):
    """400 als source_id niet bestaat, of niet één van de toegestane kinds
    heeft voor dit veld -- source_id (video) en audio_source_id (audio)
    delen dezelfde sources-tabel maar mogen elkaars kinds niet gebruiken."""
    row = db.execute("SELECT kind FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail=f"{field_label} verwijst naar een onbestaande source")
    if row[0] not in allowed_kinds:
        raise HTTPException(
            status_code=400,
            detail=f"{field_label} moet een source van kind {sorted(allowed_kinds)} zijn, niet {row[0]!r}",
        )
```

In `create_player_route` (regel 112-151) en `update_player_route` (regel 154-182), direct na de bestaande `fields["source_id"] = _resolve_source_id(db, fields["source_id"])`-regel, voeg toe:

```python
    fields["source_id"] = _resolve_source_id(db, fields["source_id"])
    _validate_source_kind(db, fields["source_id"], {"camera_stream", "static_image", "video_loop"}, "source_id")
    if fields["audio_source_id"] is not None:
        _validate_source_kind(db, fields["audio_source_id"], {"audio"}, "audio_source_id")
```

De INSERT-statement in `create_player_route` (regel 130-134): voeg `audio_source_id` toe aan kolomlijst en `VALUES`:

```python
        """INSERT INTO players
             (name, order_index, enabled, source_mode, effect, params, overlay_hash,
              scale, position, canvas_width, canvas_height, source_scale, source_position,
              is_root, canvas_x, canvas_y, color, source_id, playback_mode, repeat_while_ha_entity_id,
              audio_source_id)
           VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"],
            fields["effect"], json.dumps(fields["params"]), fields["overlay_hash"],
            fields["scale"], json.dumps(fields["position"]), canvas_width, canvas_height,
            fields["source_scale"], json.dumps(fields["source_position"]),
            int(fields["is_root"]), fields["canvas_x"], fields["canvas_y"],
            fields["color"], fields["source_id"], fields["playback_mode"],
            fields["repeat_while_ha_entity_id"], fields["audio_source_id"],
        ),
```

De UPDATE-statement in `update_player_route` (regel 164-177):

```python
    db.execute(
        """UPDATE players SET name=?, enabled=?, source_mode=?, effect=?, params=?, overlay_hash=?,
             scale=?, position=?, canvas_width=?, canvas_height=?, source_scale=?, source_position=?,
             is_root=?, canvas_x=?, canvas_y=?, color=?, source_id=?, playback_mode=?,
             repeat_while_ha_entity_id=?, audio_source_id=? WHERE id=?""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"], fields["effect"],
            json.dumps(fields["params"]), fields["overlay_hash"], fields["scale"],
            json.dumps(fields["position"]), canvas_width, canvas_height, fields["source_scale"],
            json.dumps(fields["source_position"]), int(fields["is_root"]),
            fields["canvas_x"], fields["canvas_y"], fields["color"], fields["source_id"],
            fields["playback_mode"], fields["repeat_while_ha_entity_id"], fields["audio_source_id"],
            player_id,
        ),
    )
```

- [ ] **Step 4: Implementeer cleanup in `admin/app/routers/sources.py`**

`delete_source_route` (regel 82-94):

```python
@router.delete("/api/sources/{source_id:int}")
def delete_source_route(source_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM sources WHERE id = ?", (source_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Source niet gevonden")
    has_players = db.execute("SELECT 1 FROM players WHERE source_id = ? LIMIT 1", (source_id,)).fetchone()
    if has_players is not None:
        raise HTTPException(status_code=400, detail="Source heeft nog players -- verplaats of verwijder die eerst")
    db.execute("UPDATE players SET audio_source_id = NULL WHERE audio_source_id = ?", (source_id,))
    db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}
```

- [ ] **Step 5: Run de tests, bevestig dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_admin_routes_players.py tests/test_admin_routes_sources.py -v`
Expected: PASS.

- [ ] **Step 6: Volledige backend-suite draaien**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests slagen. Let specifiek op `test_published_graph_has_the_full_new_shape` (in `test_admin_routes_players.py`, rond regel 305) — die controleert de exacte vorm van de gepubliceerde graaf-payload en moet nu ook `audio_source_id` per player bevatten; werk die test bij als hij een expliciete key-lijst assert (voeg `"audio_source_id"` toe aan de verwachte set/lijst).

- [ ] **Step 7: Commit**

```bash
git add admin/app/routers/players.py admin/app/routers/sources.py tests/test_admin_routes_players.py tests/test_admin_routes_sources.py
git commit -m "feat: players.audio_source_id met kind-validatie en cleanup-on-delete"
```

---

### Taak 5: `mirror_node` — `video_loop`-afspelen in `_ensure_source`

**Files:**
- Modify: `mirror_node/main.py`
- Test: `tests/test_mirror_main.py`

**Interfaces:**
- Consumes: `sources.kind == "video_loop"` uit Taak 3, media-cache-bestanden gesynct via `sync_media` (bestaand mechanisme).
- Produces: `_ensure_source` opent/heropent een `video_loop`-source net als `camera_stream`/`static_image`; de hoofdlus in `main()` laat een `video_loop`-capture bij het bereiken van het laatste frame teruggaan naar frame 0 in plaats van te stoppen.

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_mirror_main.py` (na de bestaande `_ensure_source`-tests rond regel 600):

```python
def test_ensure_source_opens_video_loop_via_videocapture(monkeypatch):
    opened = []

    class FakeCapture:
        def isOpened(self):
            return True

    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        mirror_main.cv2, "VideoCapture",
        lambda path, backend: opened.append(path) or FakeCapture(),
    )
    state = mirror_main._SourceState()

    result = mirror_main._ensure_source(
        state, {"id": 9, "kind": "video_loop", "value": "c" * 64}, _FakeLogger(),
    )

    assert isinstance(result, FakeCapture)
    assert opened == [mirror_main.os.path.join(mirror_main.MEDIA_CACHE_DIR, "c" * 64)]
    assert state.kind == "video_loop"


def test_ensure_source_video_loop_returns_none_when_not_yet_synced(monkeypatch):
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: False)
    state = mirror_main._SourceState()

    result = mirror_main._ensure_source(
        state, {"id": 9, "kind": "video_loop", "value": "c" * 64}, _FakeLogger(),
    )

    assert result is None
    assert state.source_id is None  # niet gecached als "al opgelost" -- zelfde als static_image


def test_ensure_source_video_loop_rejects_malformed_hash():
    state = mirror_main._SourceState()

    result = mirror_main._ensure_source(
        state, {"id": 9, "kind": "video_loop", "value": "niet-een-hash"}, _FakeLogger(),
    )

    assert result is None


def test_ensure_source_video_loop_reuses_open_capture_for_unchanged_source(monkeypatch):
    opened = []

    class FakeCapture:
        def isOpened(self):
            return True

    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        mirror_main.cv2, "VideoCapture",
        lambda path, backend: opened.append(path) or FakeCapture(),
    )
    state = mirror_main._SourceState()

    r1 = mirror_main._ensure_source(state, {"id": 9, "kind": "video_loop", "value": "c" * 64}, _FakeLogger())
    r2 = mirror_main._ensure_source(state, {"id": 9, "kind": "video_loop", "value": "c" * 64}, _FakeLogger())

    assert r1 is r2
    assert len(opened) == 1  # niet opnieuw geopend
```

Ook: voeg een `_sync_sources_in_background`-test toe die bevestigt dat `video_loop`- en `audio`-kinds nu ook meegenomen worden (zoek de bestaande test voor `_sync_sources_in_background` in het bestand en volg dezelfde structuur, met `sync_media` gemonkeypatcht):

```python
def test_sync_sources_in_background_includes_video_loop_and_audio(monkeypatch):
    synced = []
    monkeypatch.setattr(
        mirror_main.threading, "Thread",
        lambda target, args, daemon: type(
            "T", (), {"start": lambda self: synced.append(args[2])},
        )(),
    )

    mirror_main._sync_sources_in_background([
        {"kind": "camera_stream", "value": "rtsp://x"},
        {"kind": "static_image", "value": "a" * 64},
        {"kind": "video_loop", "value": "b" * 64},
        {"kind": "audio", "value": "c" * 64},
    ])

    assert synced == [["a" * 64, "b" * 64, "c" * 64]]
```

- [ ] **Step 2: Run de tests, bevestig dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py -k "video_loop" -v`
Expected: FAIL — `_ensure_source` kent alleen `static_image` als niet-camera_stream-tak, `_sync_sources_in_background` filtert alleen op `static_image`.

- [ ] **Step 3: Implementeer in `mirror_node/main.py`**

`_sync_sources_in_background` (regel 115-135):

```python
def _sync_sources_in_background(sources):
    """Haalt static_image-/video_loop-/audio-sourcebestanden op de
    achtergrond op -- zelfde patroon/reden als _sync_overlay_in_background:
    sync_media kan ~10s blokkeren en mag de MQTT-callbackthread niet
    ophouden. sync_media zelf slaat een hash over die al lokaal in
    MEDIA_CACHE_DIR staat. camera_stream-sources hebben geen media om te
    syncen."""
    hashes = [
        source.get("value")
        for source in sources
        if isinstance(source, dict)
        and source.get("kind") in ("static_image", "video_loop", "audio")
        and isinstance(source.get("value"), str)
        and source.get("value")
    ]
    if not hashes:
        return
    threading.Thread(
        target=sync_media,
        args=(BACKEND_URL, MEDIA_CACHE_DIR, hashes),
        daemon=True,
    ).start()
```

`_ensure_source` (regel 338-378): voeg een `video_loop`-tak toe vóór de finale `camera_stream`-fallback, en werk de return-conditie voor de "ongewijzigd"-check bij (regel 351: `state.capture if state.kind == "camera_stream" else state.image` klopt niet meer voor `video_loop`, die hoort ook bij `state.capture`):

```python
def _ensure_source(state, source, logger):
    """Geeft het huidige frame-beeld terug voor `source`: cv2 capture voor
    camera_stream/video_loop, een gedecodeerd beeld voor static_image. Heropent/
    herdecodeert alleen als id, kind ÉN value ongewijzigd zijn sinds de vorige
    aanroep -- een bewerkte stream-URL of een nieuwe hash op dezelfde source
    moet wel opnieuw opgepakt worden."""
    if source is None:
        return None
    if (
        state.source_id == source.get("id")
        and state.kind == source.get("kind")
        and state.value == source.get("value")
    ):
        return state.image if state.kind == "static_image" else state.capture
    if state.capture is not None:
        state.capture.release()
        state.capture = None
    state.image = None
    kind = source.get("kind")
    value = source.get("value", "")
    if kind == "static_image":
        if not _HASH_RE.match(value):
            logger.error("Ongeldige static_image-hash op source: %s", value)
            return None
        image_path = os.path.join(MEDIA_CACHE_DIR, value)
        if not os.path.exists(image_path):
            return None
        image = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if image is None:
            logger.error("static_image kon niet gedecodeerd worden: %s", value)
            return None
        state.source_id, state.kind, state.value = source.get("id"), kind, value
        state.image = image
        return state.image
    if kind == "video_loop":
        if not _HASH_RE.match(value):
            logger.error("Ongeldige video_loop-hash op source: %s", value)
            return None
        video_path = os.path.join(MEDIA_CACHE_DIR, value)
        if not os.path.exists(video_path):
            # Nog niet gesynct -- state NIET bijwerken, zelfde retry-gedrag
            # als static_image hierboven.
            return None
        capture = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            logger.error("video_loop kon niet geopend worden: %s", value)
            return None
        state.source_id, state.kind, state.value = source.get("id"), kind, value
        state.capture = capture
        return state.capture
    state.source_id, state.kind, state.value = source.get("id"), kind, value
    state.capture = open_camera(value, CAMERA_INDEX)
    return state.capture
```

In de hoofdlus in `main()` (regel 636-638), breid de `elif acquired is not None:`-tak uit met een loop-back voor `video_loop`:

```python
            elif acquired is not None:
                ok, frame = acquired.read()
                if not ok and resolved_source is not None and resolved_source.get("kind") == "video_loop":
                    # Einde van de lus bereikt -- spring terug naar het begin
                    # en lees opnieuw, zodat een video_loop-source oneindig
                    # blijft doorlopen i.p.v. na één keer afspelen stil te
                    # vallen (zelfde contract als camera_stream: altijd een
                    # geldig frame als de bron open is).
                    acquired.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = acquired.read()
```

Ook regel 631 (`if resolved_source is not None and resolved_source.get("kind") == "static_image":`) blijft ongewijzigd — `video_loop` valt terecht in de `elif acquired is not None:`-tak hierboven, niet in de `static_image`-tak.

- [ ] **Step 4: Run de tests, bevestig dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py -v`
Expected: alle tests slagen, inclusief de bestaande `_ensure_source`-tests (regressiecheck op de gewijzigde return-conditie).

- [ ] **Step 5: Commit**

```bash
git add mirror_node/main.py tests/test_mirror_main.py
git commit -m "feat: mirror_node speelt video_loop-sources af (loopend, via _ensure_source)"
```

---

### Taak 6: `mirror_node` — `_AudioState`-tracker voor onafhankelijk loopende audio

**Files:**
- Modify: `mirror_node/main.py`
- Test: `tests/test_mirror_main.py`

**Interfaces:**
- Consumes: `players.audio_source_id` (via `_current_sources`/de gepubliceerde graaf, Taak 4), `sources.kind == "audio"`.
- Produces: `_AudioState`-class, `_stop_audio(state, logger)`, `_start_audio_loop(value, logger)`, `_ensure_audio(state, player, sources_by_id, logger)` — gewijzigd/gestart/gestopt subprocess dat het gekoppelde audiobestand van de actieve player continu loopt, onafhankelijk van het video-spoor.

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_mirror_main.py`:

```python
class _FakeProcess:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True


def test_ensure_audio_starts_loop_for_players_audio_source(monkeypatch):
    started = []
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        mirror_main.subprocess, "Popen",
        lambda cmd, **kw: started.append(cmd) or _FakeProcess(),
    )
    state = mirror_main._AudioState()
    sources_by_id = {5: {"id": 5, "kind": "audio", "value": "a" * 64}}

    mirror_main._ensure_audio(state, {"id": 1, "audio_source_id": 5}, sources_by_id, _FakeLogger())

    assert len(started) == 1
    assert "a" * 64 in started[0][started[0].index("-i") + 1]
    assert state.value == "a" * 64


def test_ensure_audio_does_nothing_when_unchanged(monkeypatch):
    started = []
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    monkeypatch.setattr(mirror_main.subprocess, "Popen", lambda cmd, **kw: started.append(1) or _FakeProcess())
    state = mirror_main._AudioState()
    sources_by_id = {5: {"id": 5, "kind": "audio", "value": "a" * 64}}

    mirror_main._ensure_audio(state, {"id": 1, "audio_source_id": 5}, sources_by_id, _FakeLogger())
    mirror_main._ensure_audio(state, {"id": 1, "audio_source_id": 5}, sources_by_id, _FakeLogger())

    assert len(started) == 1  # niet opnieuw gestart, ongewijzigd


def test_ensure_audio_stops_when_player_has_no_audio_source(monkeypatch):
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    monkeypatch.setattr(mirror_main.subprocess, "Popen", lambda cmd, **kw: _FakeProcess())
    state = mirror_main._AudioState()
    sources_by_id = {5: {"id": 5, "kind": "audio", "value": "a" * 64}}
    mirror_main._ensure_audio(state, {"id": 1, "audio_source_id": 5}, sources_by_id, _FakeLogger())
    running_process = state.process

    mirror_main._ensure_audio(state, {"id": 1, "audio_source_id": None}, sources_by_id, _FakeLogger())

    assert running_process.terminated is True
    assert state.process is None
    assert state.value is None


def test_ensure_audio_switches_process_when_player_changes(monkeypatch):
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    monkeypatch.setattr(mirror_main.subprocess, "Popen", lambda cmd, **kw: _FakeProcess())
    state = mirror_main._AudioState()
    sources_by_id = {
        5: {"id": 5, "kind": "audio", "value": "a" * 64},
        6: {"id": 6, "kind": "audio", "value": "b" * 64},
    }
    mirror_main._ensure_audio(state, {"id": 1, "audio_source_id": 5}, sources_by_id, _FakeLogger())
    first_process = state.process

    mirror_main._ensure_audio(state, {"id": 2, "audio_source_id": 6}, sources_by_id, _FakeLogger())

    assert first_process.terminated is True
    assert state.value == "b" * 64


def test_ensure_audio_failure_to_start_is_not_cached_as_resolved(monkeypatch):
    # Zelfde 'niet-gecached-als-opgelost'-contract als static_image/video_loop:
    # een falende start (bv. ontbrekend bestand) mag niet permanent stil blijven
    # zodra het bestand alsnog beschikbaar komt.
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: False)
    state = mirror_main._AudioState()
    sources_by_id = {5: {"id": 5, "kind": "audio", "value": "a" * 64}}

    mirror_main._ensure_audio(state, {"id": 1, "audio_source_id": 5}, sources_by_id, _FakeLogger())
    assert state.value is None

    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    monkeypatch.setattr(mirror_main.subprocess, "Popen", lambda cmd, **kw: _FakeProcess())
    mirror_main._ensure_audio(state, {"id": 1, "audio_source_id": 5}, sources_by_id, _FakeLogger())

    assert state.value == "a" * 64
```

- [ ] **Step 2: Run de tests, bevestig dat ze falen**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py -k "ensure_audio" -v`
Expected: FAIL — `_AudioState`/`_ensure_audio` bestaan nog niet (`AttributeError`).

- [ ] **Step 3: Implementeer in `mirror_node/main.py`**

Voeg toe direct na de `_SourceState`-class en vóór `_ensure_source` (rond regel 322):

```python
class _AudioState:
    """Houdt bij welk audiobestand op dit moment loopt voor de actieve
    player -- zelfde vorm als _SourceState, maar voor het onafhankelijke
    audio-spoor (players.audio_source_id) i.p.v. het video-spoor
    (players.source_id). Precies één lopend subprocess tegelijk: een
    gewijzigde (of verdwenen) audio_source_id stopt het oude en start
    eventueel een nieuw loopend afspeelproces."""

    def __init__(self):
        self.player_id = None
        self.value = None
        self.process = None


def _stop_audio(state, logger):
    if state.process is not None:
        try:
            state.process.terminate()
        except Exception as exc:
            logger.warning("Kon audio-proces niet stoppen: %s", exc)
        state.process = None


def _start_audio_loop(value, logger):
    """Start een blijvend loopend afspeelproces voor het audiobestand bij
    `value` (media-hash). ffmpeg -stream_loop -1 herhaalt het bestand
    zelf oneindig en schrijft rechtstreeks naar het ALSA default-device --
    geen los aplay-proces nodig zoals bij de one-shot scare-audio.
    Best-effort: een ontbrekend ffmpeg-bestand of kapot audiobestand mag
    de video-pipeline nooit blokkeren, dus alleen loggen en None
    teruggeven bij falen."""
    audio_path = os.path.join(MEDIA_CACHE_DIR, value)
    try:
        return subprocess.Popen(
            ["ffmpeg", "-y", "-stream_loop", "-1", "-i", audio_path, "-f", "alsa", "default"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.warning("Kon audio-loop niet starten: %s", exc)
        return None


def _ensure_audio(state, player, sources_by_id, logger):
    """Zorgt dat het juiste audiobestand loopt voor de gegeven `player`
    (of niets, als de player geen audio_source_id heeft), en doet niets
    als de resolutie ongewijzigd is sinds de vorige aanroep -- zelfde
    ongewijzigd-dan-niets-doen-contract als _ensure_source."""
    player_id = player.get("id") if player else None
    audio_source_id = player.get("audio_source_id") if player else None
    audio_source = sources_by_id.get(audio_source_id) if audio_source_id is not None else None
    value = audio_source.get("value") if audio_source else None

    if state.player_id == player_id and state.value == value:
        return
    _stop_audio(state, logger)
    state.player_id = player_id
    state.value = None
    if value and _HASH_RE.match(value) and os.path.exists(os.path.join(MEDIA_CACHE_DIR, value)):
        process = _start_audio_loop(value, logger)
        if process is not None:
            state.process = process
            state.value = value
```

In `main()`, instantieer `audio_state` naast `source_state` (regel 623):

```python
    source_state = _SourceState()
    audio_state = _AudioState()
```

In de hoofdlus, direct na de bestaande `resolved_source = ...`-regel (regel 628), roep `_ensure_audio` aan:

```python
            sources_by_id = {s["id"]: s for s in _current_sources}
            current_player = player_graph._players.get(player_graph._current_id)
            resolved_source = sources_by_id.get(current_player.get("source_id")) if current_player else None
            _ensure_audio(audio_state, current_player, sources_by_id, logger)
            acquired = _ensure_source(source_state, resolved_source, logger) if resolved_source else None
```

In de `finally:`-block aan het eind van `main()` (regel 745-751), stop het audioproces netjes bij shutdown:

```python
    finally:
        _stop_audio(audio_state, logger)
        if cap is not None:
            cap.release()
```

- [ ] **Step 4: Run de tests, bevestig dat ze slagen**

Run: `.venv/bin/python -m pytest tests/test_mirror_main.py -v`
Expected: alle tests slagen.

- [ ] **Step 5: Volledige backend-suite draaien**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: alle tests slagen.

- [ ] **Step 6: Commit**

```bash
git add mirror_node/main.py tests/test_mirror_main.py
git commit -m "feat: mirror_node speelt een onafhankelijk loopend audio-spoor af (players.audio_source_id)"
```

---

### Taak 7: Frontend — `types.ts`/`api/media.ts`/`MediaLibrary.tsx` + embeds naar `kind`

**Files:**
- Modify: `admin/frontend/src/types.ts`
- Modify: `admin/frontend/src/api/media.ts`
- Modify: `admin/frontend/src/components/MediaLibrary.tsx`
- Modify: `admin/frontend/src/pages/ScarePage.tsx`
- Modify: `admin/frontend/src/pages/MirrorScareVideoPage.tsx`
- Modify: `admin/frontend/src/components/PlayerWizardModal.tsx`

**Interfaces:**
- Consumes: `GET/POST /api/media?kind=...` uit Taak 2.
- Produces: `MediaItem.kind: "image" | "audio" | "video"`, `Source["kind"]` uitgebreid met `"video_loop" | "audio"`, `Player.audio_source_id: number | null`, `<MediaLibrary kind="image"|"audio"|"video" .../>` (prop hernoemd van `category`).

Dit is een mechanische, atomaire rename over meerdere bestanden — geen losse test-fase per bestand, want de wijziging is pas consistent (en compileert pas) als alle bestanden tegelijk zijn aangepast. Er bestaat geen `MediaLibrary.test.tsx` in deze codebase; de dekking komt van `npx tsc --noEmit` (typefouten bij een gemiste plek) plus de bestaande `PlayerGraphCanvas.test.tsx`-suite (regressie) en handmatige verificatie in Taak 9/10.

- [ ] **Step 1: `types.ts`**

Vervang `MediaItem` (regel 81-86):

```typescript
export interface MediaItem {
  hash: string;
  filename: string;
  kind: "image" | "audio" | "video";
  uploaded_at: string;
}
```

`Source["kind"]` (regel 31):

```typescript
  kind: "camera_stream" | "static_image" | "video_loop" | "audio";
```

`Player`-interface (regel 1-20): voeg toe na `source_id: number | null;` (regel 18):

```typescript
  source_id: number | null;
  audio_source_id: number | null;
```

- [ ] **Step 2: `api/media.ts`**

```typescript
import { apiFetch } from "./client";
import type { MediaItem } from "../types";

export function listMedia(kind?: string): Promise<MediaItem[]> {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return apiFetch<MediaItem[]>(`/api/media${query}`);
}

export async function uploadMedia(file: File, kind: string): Promise<MediaItem> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("kind", kind);
  const response = await fetch("/api/media", {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed?.detail === "string") detail = parsed.detail;
    } catch {
      /* geen JSON-body, val terug op de ruwe tekst */
    }
    throw new Error(detail || `Upload mislukt (${response.status})`);
  }
  return response.json();
}

export function deleteMedia(hash: string): Promise<void> {
  return apiFetch(`/api/media/${hash}`, { method: "DELETE" });
}
```

- [ ] **Step 3: `MediaLibrary.tsx`**

Vervang de hele inhoud van het bestand:

```tsx
import { useEffect, useState } from "react";
import { listMedia, uploadMedia, deleteMedia } from "../api/media";
import type { MediaItem } from "../types";
import "./MediaLibrary.css";

interface Props {
  kind: "image" | "audio" | "video";
  selected: string[];
  onSelectionChange: (hashes: string[]) => void;
  selectionMode: "single" | "multiple";
}

const KIND_COPY: Record<Props["kind"], { empty: string; upload: string }> = {
  image: {
    empty: "Nog geen afbeeldingen geüpload.",
    upload: "Afbeelding toevoegen",
  },
  audio: {
    empty: "Nog geen geluiden geüpload.",
    upload: "Geluid toevoegen",
  },
  video: {
    empty: "Nog geen video's geüpload.",
    upload: "Video toevoegen",
  },
};

function KindIcon({ kind }: { kind: Props["kind"] }) {
  if (kind === "image") {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
        <rect x="3" y="4" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="8.5" cy="9" r="1.4" fill="currentColor" />
        <path d="M4 15.5l4.5-4 3.5 3 3-2.5L21 15" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "video") {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
        <rect x="3" y="5" width="14" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <path d="M17 9.5l4-2.5v10l-4-2.5" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
      <path d="M4 12h2l2-6 3 12 2-9 2 6h1.5" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <path d="M17 8v10a1.5 1.5 0 11-1.5-1.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M17 8l3-1v10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export default function MediaLibrary({ kind, selected, onSelectionChange, selectionMode }: Props) {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const copy = KIND_COPY[kind];

  function refresh() {
    listMedia(kind)
      .then((result) => {
        setItems(result);
        setError(null);
      })
      .catch(() => setError("Bibliotheek kon niet worden geladen."));
  }

  useEffect(refresh, [kind]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await uploadMedia(file, kind);
      setError(null);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bestand kon niet worden geüpload.");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleDelete(hash: string) {
    try {
      await deleteMedia(hash);
      setError(null);
      onSelectionChange(selected.filter((h) => h !== hash));
      refresh();
    } catch {
      setError("Bestand kon niet worden verwijderd.");
    }
  }

  function toggleSelect(hash: string) {
    if (selectionMode === "single") {
      onSelectionChange([hash]);
    } else {
      onSelectionChange(
        selected.includes(hash) ? selected.filter((h) => h !== hash) : [...selected, hash],
      );
    }
  }

  return (
    <div className="media-library">
      <div className="media-library__toolbar">
        <label className={`media-upload ${uploading ? "media-upload--busy" : ""}`}>
          <input
            className="media-upload__input"
            type="file"
            onChange={handleUpload}
            disabled={uploading}
          />
          <span className="media-upload__plus" aria-hidden="true">
            +
          </span>
          {uploading ? "Bezig met uploaden…" : copy.upload}
        </label>
      </div>

      {error && (
        <p className="media-library__error" role="alert">
          {error}
        </p>
      )}

      {items.length === 0 ? (
        <p className="media-library__empty">{copy.empty}</p>
      ) : (
        <ul className="media-grid">
          {items.map((item) => {
            const isSelected = selected.includes(item.hash);
            return (
              <li key={item.hash} className="media-card" data-selected={isSelected}>
                <label className="media-card__select">
                  <input
                    className="media-card__input"
                    type={selectionMode === "single" ? "radio" : "checkbox"}
                    name={selectionMode === "single" ? `media-${kind}` : undefined}
                    checked={isSelected}
                    onChange={() => toggleSelect(item.hash)}
                  />
                  <span className="media-card__led" aria-hidden="true" />
                  <span className="media-card__icon">
                    <KindIcon kind={kind} />
                  </span>
                  <span className="media-card__name" title={item.filename}>
                    {item.filename}
                  </span>
                  <span className="media-card__hash">{item.hash.slice(0, 8)}</span>
                </label>
                <button
                  type="button"
                  className="media-card__delete"
                  onClick={() => handleDelete(item.hash)}
                  aria-label={`Verwijder ${item.filename}`}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Update de drie embed-plekken**

`admin/frontend/src/pages/ScarePage.tsx` (rond regel 106-111):

```tsx
        <MediaLibrary
          kind="audio"
          selectionMode="multiple"
          selected={enabledHashes}
          onSelectionChange={setEnabledHashes}
        />
```

`admin/frontend/src/pages/MirrorScareVideoPage.tsx` (rond regel 54-59):

```tsx
        <MediaLibrary
          kind="video"
          selectionMode="multiple"
          selected={enabledHashes}
          onSelectionChange={setEnabledHashes}
        />
```

`admin/frontend/src/components/PlayerWizardModal.tsx` (rond regel 322-327):

```tsx
              <MediaLibrary
                kind="image"
                selectionMode="single"
                selected={draft.overlay_hash ? [draft.overlay_hash] : []}
                onSelectionChange={(hashes) => update({ overlay_hash: hashes[0] ?? null })}
              />
```

- [ ] **Step 5: Typecheck en test**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen fouten (dit is de primaire regressie-vangst voor deze mechanische rename — een gemiste plek geeft hier een `Property 'category' does not exist`- of `Type '"mirror_overlay"' is not assignable`-achtige fout).

Run: `cd admin/frontend && npm test`
Expected: bestaande suite (`PlayerGraphCanvas.test.tsx`) slaagt ongewijzigd.

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/types.ts admin/frontend/src/api/media.ts admin/frontend/src/components/MediaLibrary.tsx admin/frontend/src/pages/ScarePage.tsx admin/frontend/src/pages/MirrorScareVideoPage.tsx admin/frontend/src/components/PlayerWizardModal.tsx
git commit -m "feat: frontend media-typen/component/embeds van category naar kind"
```

---

### Taak 8: Frontend — nieuwe `/media`-pagina

**Files:**
- Create: `admin/frontend/src/pages/MediaPage.tsx`
- Create: `admin/frontend/src/pages/MediaPage.css`
- Modify: `admin/frontend/src/App.tsx`
- Modify: `admin/frontend/src/components/Layout.tsx`

**Interfaces:**
- Consumes: `MediaLibrary` (kind-prop) uit Taak 7.
- Produces: route `/media`, navlink "Media".

**Ontwerp-keuze (kleinere afwijking van de letterlijke spec-tekst):** in plaats van één `MediaLibrary`-instantie met een los kind-keuzemenu erboven (wat een nieuwe "los van de lijst uploaden"-modus in `MediaLibrary` zou vereisen), toont deze pagina drie secties — Afbeeldingen/Audio/Video — elk met hun eigen ongewijzigde `MediaLibrary`-instantie. Zelfde eindresultaat (alles zien, in de juiste kind uploaden) met nul wijzigingen aan het al-geteste `MediaLibrary`-component.

- [ ] **Step 1: `MediaPage.tsx`**

```tsx
import { useState } from "react";
import MediaLibrary from "../components/MediaLibrary";
import "./MediaPage.css";

export default function MediaPage() {
  const [selectedImage, setSelectedImage] = useState<string[]>([]);
  const [selectedAudio, setSelectedAudio] = useState<string[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<string[]>([]);

  return (
    <div className="media-page">
      <header className="media-page__header">
        <p className="media-page__eyebrow">
          <span className="media-page__eyebrow-led" aria-hidden="true" />
          Mediabibliotheek
        </p>
        <h1 className="media-page__heading">Media</h1>
        <p className="media-page__hint">
          Foto's, video's en audio die je in de flow-graaf kunt gebruiken (als
          Source, overlay, of scare-video/-audio). Uploaden hieronder maakt het
          bestand meteen overal beschikbaar waar dat kind gekozen kan worden.
        </p>
      </header>

      <section className="media-page__section">
        <h2 className="media-page__section-heading">Afbeeldingen</h2>
        <MediaLibrary kind="image" selectionMode="multiple" selected={selectedImage} onSelectionChange={setSelectedImage} />
      </section>

      <section className="media-page__section">
        <h2 className="media-page__section-heading">Audio</h2>
        <MediaLibrary kind="audio" selectionMode="multiple" selected={selectedAudio} onSelectionChange={setSelectedAudio} />
      </section>

      <section className="media-page__section">
        <h2 className="media-page__section-heading">Video's</h2>
        <MediaLibrary kind="video" selectionMode="multiple" selected={selectedVideo} onSelectionChange={setSelectedVideo} />
      </section>
    </div>
  );
}
```

(`selectionMode="multiple"` met een lokale, verder ongebruikte `selected`-state: deze pagina is een pure bladeren/uploaden/verwijderen-overzicht, geen selectie-workflow — `MediaLibrary` vereist `selected`/`onSelectionChange` als props, dus die krijgen hier een no-op-achtige lokale state, zelfde patroon zou `single` ook toestaan maar `multiple` toont duidelijker dat er geen "actieve" keuze is.)

- [ ] **Step 2: `MediaPage.css`**

```css
.media-page {
  padding: 1.5rem 2rem;
  color: var(--bone);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

.media-page__header {
  margin-bottom: 1.5rem;
}

.media-page__eyebrow {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ash);
  margin: 0 0 0.3rem;
}

.media-page__eyebrow-led {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ember);
}

.media-page__heading {
  margin: 0 0 0.5rem;
  font-size: 1.5rem;
}

.media-page__hint {
  color: var(--ash);
  max-width: 60ch;
  margin: 0;
}

.media-page__section {
  margin-bottom: 2rem;
}

.media-page__section-heading {
  font-size: 1.1rem;
  margin: 0 0 0.75rem;
}
```

(Kleurvariabelen `--bone`/--ash`/`--ember`/`--panel`/`--panel-edge` bestaan al globaal — check `admin/frontend/src/pages/SourcesPage.css`/`DevicesPage.css` voor het referentiepatroon, geen nieuwe variabelen nodig.)

- [ ] **Step 3: Route + navlink**

`admin/frontend/src/App.tsx`: voeg import toe (na `import DevicesPage from "./pages/DevicesPage";`):

```tsx
import MediaPage from "./pages/MediaPage";
```

en een route (na `<Route path="/devices" element={<DevicesPage />} />`):

```tsx
          <Route path="/media" element={<MediaPage />} />
```

`admin/frontend/src/components/Layout.tsx`: voeg toe aan de `links`-array (na de `/devices`-regel):

```tsx
  { to: "/media", label: "Media", end: false },
```

- [ ] **Step 4: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen fouten.

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/pages/MediaPage.tsx admin/frontend/src/pages/MediaPage.css admin/frontend/src/App.tsx admin/frontend/src/components/Layout.tsx
git commit -m "feat: nieuwe /media-pagina met bladeren per kind"
```

---

### Taak 9: Frontend — `SourcesPage.tsx` picker voor image/video/audio-kinds

**Files:**
- Modify: `admin/frontend/src/pages/SourcesPage.tsx`
- Modify: `admin/frontend/src/pages/SourcesPage.css`

**Interfaces:**
- Consumes: `MediaLibrary` (kind-prop) uit Taak 7, `Source["kind"]` uitgebreid met `video_loop`/`audio` uit Taak 3/7.
- Produces: bij `kind` `static_image`/`video_loop`/`audio` toont de rij een "Kies media…"-knop die een `MediaLibrary`-picker (gefilterd op het bijbehorende media-kind) onder de rij opent; `camera_stream` behoudt het vrije-tekst-URL-veld.

- [ ] **Step 1: Implementeer**

Vervang de hele inhoud van `admin/frontend/src/pages/SourcesPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { listSources, createSource, updateSource, deleteSource } from "../api/sources";
import { ApiError } from "../api/client";
import MediaLibrary from "../components/MediaLibrary";
import type { Source } from "../types";
import "./SourcesPage.css";

interface Draft {
  name: string;
  kind: Source["kind"];
  value: string;
}

// video_loop kiest uit dezelfde media-kind als static_image (allebei
// beeldmateriaal); alleen static_image gebruikt "image", video_loop "video".
function mediaKindFor(kind: Draft["kind"]): "image" | "audio" | "video" | null {
  if (kind === "static_image") return "image";
  if (kind === "video_loop") return "video";
  if (kind === "audio") return "audio";
  return null; // camera_stream: geen media-kind, vrij-tekst-URL-veld
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
  // Eén picker tegelijk open: id van de bestaande source, of "new" voor de
  // aanmaak-rij, of null als er niks open staat.
  const [pickerOpenFor, setPickerOpenFor] = useState<number | "new" | null>(null);

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
      setPickerOpenFor(null);
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

  function valuePreview(draft: Draft): string {
    if (!draft.value) return "Kies media…";
    return draft.value.slice(0, 12) + "…";
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
          const mediaKind = mediaKindFor(draft.kind);
          return (
            <div key={source.id}>
              <div className="sources-row">
                <input
                  className="sources-field__input"
                  type="text"
                  value={draft.name}
                  onChange={(e) => updateDraft(source.id, { name: e.target.value })}
                />
                <select
                  className="sources-field__input"
                  value={draft.kind}
                  onChange={(e) => updateDraft(source.id, { kind: e.target.value as Draft["kind"], value: "" })}
                >
                  <option value="camera_stream">Camera-stream</option>
                  <option value="static_image">Statische afbeelding</option>
                  <option value="video_loop">Video-loop</option>
                  <option value="audio">Audio</option>
                </select>
                {mediaKind === null ? (
                  <input
                    className="sources-field__input sources-field__input--wide"
                    type="text"
                    value={draft.value}
                    placeholder="bijv. rtsp://gebruiker:wachtwoord@192.168.1.50:554/stream1"
                    onChange={(e) => updateDraft(source.id, { value: e.target.value })}
                  />
                ) : (
                  <button
                    type="button"
                    className="sources-field__input sources-field__input--wide sources-media-button"
                    onClick={() => setPickerOpenFor(pickerOpenFor === source.id ? null : source.id)}
                  >
                    {valuePreview(draft)}
                  </button>
                )}
                <button type="button" onClick={() => handleSave(source.id)} disabled={saving}>
                  Opslaan
                </button>
                <button type="button" onClick={() => handleDelete(source.id)} disabled={saving}>
                  Verwijderen
                </button>
              </div>
              {pickerOpenFor === source.id && mediaKind !== null && (
                <div className="sources-media-picker">
                  <MediaLibrary
                    kind={mediaKind}
                    selectionMode="single"
                    selected={draft.value ? [draft.value] : []}
                    onSelectionChange={(hashes) => {
                      updateDraft(source.id, { value: hashes[0] ?? "" });
                      setPickerOpenFor(null);
                    }}
                  />
                </div>
              )}
            </div>
          );
        })}

        <div>
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
              onChange={(e) => {
                setNewKind(e.target.value as Draft["kind"]);
                setNewValue("");
              }}
            >
              <option value="camera_stream">Camera-stream</option>
              <option value="static_image">Statische afbeelding</option>
              <option value="video_loop">Video-loop</option>
              <option value="audio">Audio</option>
            </select>
            {mediaKindFor(newKind) === null ? (
              <input
                className="sources-field__input sources-field__input--wide"
                type="text"
                placeholder="Camera-URL"
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
              />
            ) : (
              <button
                type="button"
                className="sources-field__input sources-field__input--wide sources-media-button"
                onClick={() => setPickerOpenFor(pickerOpenFor === "new" ? null : "new")}
              >
                {newValue ? newValue.slice(0, 12) + "…" : "Kies media…"}
              </button>
            )}
            <button type="button" onClick={handleCreate} disabled={saving || !newName.trim()}>
              + Source toevoegen
            </button>
          </div>
          {pickerOpenFor === "new" && mediaKindFor(newKind) !== null && (
            <div className="sources-media-picker">
              <MediaLibrary
                kind={mediaKindFor(newKind)!}
                selectionMode="single"
                selected={newValue ? [newValue] : []}
                onSelectionChange={(hashes) => {
                  setNewValue(hashes[0] ?? "");
                  setPickerOpenFor(null);
                }}
              />
            </div>
          )}
        </div>
      </section>

      <p className="sources-field__label">
        Een source is een camera-stream, statische afbeelding, video-loop of
        audio die je in de graaf aan een of meerdere players kunt koppelen.
        Een source met nog players eraan gekoppeld kan niet verwijderd worden.
      </p>
    </div>
  );
}
```

Let op: `.sources-row` is nu geen direct kind meer van `.sources-panel` (er zit nu een wrapper-`<div>` tussen, voor de optionele picker eronder) — `.sources-panel` blijft `display:flex; flex-direction:column`, dus dit heeft geen effect op de layout; controleer bij Step 3 hieronder wel visueel dat de gap-styling nog klopt.

- [ ] **Step 2: Nieuwe CSS**

Voeg toe aan `admin/frontend/src/pages/SourcesPage.css` (na de bestaande `.sources-row--new`-of-omliggende regels — check de exacte plek in het bestand):

```css
.sources-media-button {
  text-align: left;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 4px;
  color: var(--bone);
  cursor: pointer;
  padding: 0.4rem 0.6rem;
}

.sources-media-picker {
  margin-top: 0.5rem;
  padding: 0.75rem;
  background: var(--void);
  border: 1px solid var(--panel-edge);
  border-radius: 8px;
}
```

`.sources-row`'s bestaande `grid-template-columns: 1fr 1fr 2fr auto auto` (regel 56) en `.sources-row--new`'s `1fr 1fr 2fr auto` (regel 62) blijven ONGEWIJZIGD — het aantal grid-cellen per rij is niet veranderd (nog steeds 5 resp. 4), alleen de inhoud van de derde cel wisselt tussen `<input>` en `<button>`.

- [ ] **Step 3: Handmatige verificatie in de browser**

Start de backend en frontend lokaal (zelfde aanpak als eerdere sessies in dit project: `ADMIN_PASSWORD=<tijdelijk-wachtwoord>` env var, `npm run dev` in `admin/frontend`), navigeer naar `/sources`, en controleer via de browsertool:
- Een source met kind `static_image`/`video_loop`/`audio` toont de "Kies media…"-knop i.p.v. het tekstveld.
- Klikken opent de bijbehorende, kind-gefilterde `MediaLibrary` eronder; een upload/selectie sluit de picker en vult de knop-tekst.
- `camera_stream` toont nog steeds het vrije-tekst-URL-veld, ongewijzigd.
- Geen CSS-grid-mismatch (rijen ogen even breed als voorheen — dit is de bugklasse die twee keer eerder in dit project is voorgekomen).

Ruim daarna alle tijdelijke lokale testbestanden/processen op (zelfde conventie als eerdere sessies).

- [ ] **Step 4: Typecheck**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: geen fouten.

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/pages/SourcesPage.tsx admin/frontend/src/pages/SourcesPage.css
git commit -m "feat: media-picker op SourcesPage voor image/video/audio-kinds"
```

---

### Taak 10: Frontend — canvas: audio-Source aan een Player koppelen via edge

**Files:**
- Modify: `admin/frontend/src/components/PlayerGraphCanvas.tsx`
- Modify: `admin/frontend/src/components/PlayerGraphCanvas.css`
- Modify: `admin/frontend/src/components/PlayerGraphCanvas.test.tsx`

**Interfaces:**
- Consumes: `Player.audio_source_id`, `Source["kind"] === "audio"` (Taak 3/7).
- Produces: een tweede `target`-Handle (`id="audio-in"`) op het Player-knooppunt; een gesleepte verbinding vanaf een `audio`-kind Source-knooppunt naar een Player zet `audio_source_id` (i.p.v. `source_id`, dat blijft voor de andere drie kinds); een badge op het Player-knooppunt toont de gekoppelde audio-source-naam.

- [ ] **Step 1: Schrijf de falende tests**

Open `admin/frontend/src/components/PlayerGraphCanvas.test.tsx` en bekijk het bestaande `describe`-blok voor de toolbar-knoppen (uit de vorige feature) als referentiepatroon voor mocking/opzet. Voeg een nieuw blok toe:

```tsx
describe("PlayerGraphCanvas -- audio-source koppelen aan een player", () => {
  // (gebruik dezelfde players/sources/branches/triggers/outputs-fixtures en
  // render-helper als de rest van dit testbestand -- check de bestaande
  // top-of-file fixtures/render-functie en hergebruik die, voeg alleen een
  // audio-kind Source toe aan de sources-fixture voor deze tests)

  it("toont geen audio-badge als de player geen audio_source_id heeft", () => {
    // render met een player zonder audio_source_id
    // assert: geen element met de audio-source-naam zichtbaar
  });

  it("toont de naam van de gekoppelde audio-source als badge", () => {
    // render met een player met audio_source_id gezet naar een bestaande
    // audio-kind source
    // assert: screen.getByText bevat die source-naam
  });

  it("zet audio_source_id (niet source_id) bij een connect vanaf een audio-kind source", async () => {
    // simuleer handleConnect / onConnect met een verbinding van een
    // audio-kind source-node naar een player-node (via de al-geëxporteerde
    // parseOutputConnectionEdgeIds-achtige aanpak is hier niet van
    // toepassing -- roep de onConnect-callback die ReactFlow ontvangt
    // rechtstreeks aan als die testbaar is, of test via de al-bestaande
    // aanpak in dit bestand voor de bestaande source->player-connect-test
    // als die er is; volg dat patroon exact)
    // assert: updatePlayer aangeroepen met { ...draft, audio_source_id: <id> },
    // NIET met source_id gewijzigd
  });
});
```

Bekijk eerst hoe de bestaande, al-werkende `source->player`-connectietest (voor `source_id`, via `handleConnect`) in dit bestand is opgezet (zoek naar `onConnect` of `handleConnect` of een test die `startsWith("source-")` raakt) en volg exact diezelfde render/mock/assert-structuur voor de drie tests hierboven — dit voorkomt dat de tests op een andere manier renderen dan de rest van het bestand en daardoor niet representatief zijn.

- [ ] **Step 2: Run de tests, bevestig dat ze falen**

Run: `cd admin/frontend && npm test -- PlayerGraphCanvas`
Expected: FAIL — geen audio-badge, geen `audio-in`-handle, `handleConnect` zet altijd `source_id`.

- [ ] **Step 3: Implementeer**

In `PlayerGraphCanvas.tsx`, `PlayerNodeData` (regel 44-54): voeg toe:

```typescript
type PlayerNodeData = {
  player: Player;
  branches: PlayerBranch[];
  audioSourceName: string | null;
  onPlayerClick: Props["onPlayerClick"];
  onAddBranchTrigger: (branchId: number) => void;
  onMakeRoot: (playerId: number) => void;
  onRename: (playerId: number, name: string) => void;
  onSetColor: (playerId: number, color: string) => void;
  onDelete: (playerId: number) => void;
  [key: string]: unknown;
};
```

In `PlayerNodeComponent` (regel 155-314): destructure `audioSourceName` uit `data`, voeg een tweede Handle en een badge toe. De functiekop wordt:

```tsx
function PlayerNodeComponent({ data }: NodeProps<PlayerNode>) {
  const { player, branches, audioSourceName, onPlayerClick, onAddBranchTrigger, onMakeRoot, onRename, onSetColor, onDelete } = data;
```

Direct na de bestaande `<Handle type="target" position={Position.Left} />` (regel 211):

```tsx
      <Handle type="target" position={Position.Left} />
      <Handle type="target" position={Position.Top} id="audio-in" />
```

In de chips-sectie (regel 272-286), voeg de audio-badge toe als laatste chip, ná de bestaande drie (alleen zichtbaar als er een koppeling is — geen klikgedrag, uitsluitend informatief; loskoppelen gebeurt door een nieuwe edge naar een andere/geen audio-source te slepen, zelfde bestaande beperking als bij `source_id`):

```tsx
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
        {audioSourceName && (
          <span className="player-node__chip player-node__chip--audio nodrag" title="Gekoppelde audio-source">
            🔊 {audioSourceName}
          </span>
        )}
      </div>
```

`SourceNodeComponent` (regel 316-346): geef elk kind een eigen icoon (uitbreiding van de bestaande tweeledige ternary):

```tsx
function sourceIcon(kind: Source["kind"]): string {
  if (kind === "camera_stream") return "📷";
  if (kind === "static_image") return "🖼";
  if (kind === "video_loop") return "🎞";
  return "🔊"; // audio
}
```

en in de render: `<span className="source-node__icon">{sourceIcon(source.kind)}</span>` (vervangt de bestaande inline ternary op regel 329).

In `PlayerGraphCanvas` (het hoofdcomponent, vanaf regel 512): voeg een lookup toe voor audio-source-namen, direct na de bestaande `branchToPlayer`-memo (regel 519-522):

```tsx
  const audioSourceNameById = useMemo(
    () => Object.fromEntries(sources.filter((s) => s.kind === "audio").map((s) => [s.id, s.name])),
    [sources],
  );
```

In de `flowNodes`-memo (regel 677-733), geef `PlayerNode`s de nieuwe prop:

```tsx
      ...players.map(
        (player): PlayerNode => ({
          id: `player-${player.id}`,
          type: "player",
          position: { x: player.canvas_x, y: player.canvas_y },
          data: {
            player,
            branches: branches.filter((b) => b.player_id === player.id),
            audioSourceName: player.audio_source_id !== null ? audioSourceNameById[player.audio_source_id] ?? null : null,
            onPlayerClick,
            onAddBranchTrigger: handleAddBranchTrigger,
            onMakeRoot: handleMakeRoot,
            onRename: handleRenamePlayer,
            onSetColor: handleSetPlayerColor,
            onDelete: handleDeletePlayer,
          },
        }),
      ),
```

en voeg `audioSourceNameById` toe aan de dependency-array van die `useMemo` (regel 727-732).

In de `flowEdges`-memo (regel 735-779), voeg een edge toe voor `audio_source_id`, direct na de bestaande `source_id`-edge-lus:

```tsx
    for (const player of players) {
      if (player.source_id !== null) {
        result.push({
          id: `source-in-${player.id}`,
          source: `source-${player.source_id}`,
          target: `player-${player.id}`,
        });
      }
      if (player.audio_source_id !== null) {
        result.push({
          id: `audio-in-${player.id}`,
          source: `source-${player.audio_source_id}`,
          target: `player-${player.id}`,
          targetHandle: "audio-in",
          style: { strokeDasharray: "4 2" },
        });
      }
    }
```

`handleConnect` (regel 797-834): breid de bestaande `source-*`-naar-`player-*`-tak uit om op de kind van de gesleepte Source te routeren:

```tsx
      if (connection.source?.startsWith("source-") && connection.target?.startsWith("player-")) {
        const sourceId = parseInt(connection.source.replace("source-", ""), 10);
        const playerId = parseInt(connection.target.replace("player-", ""), 10);
        if (Number.isNaN(sourceId) || Number.isNaN(playerId)) return;
        const player = players.find((p) => p.id === playerId);
        const source = sources.find((s) => s.id === sourceId);
        if (!player || !source) return;
        const { id: _id, ...draft } = player;
        if (source.kind === "audio") {
          await updatePlayer(playerId, { ...draft, audio_source_id: sourceId });
        } else {
          await updatePlayer(playerId, { ...draft, source_id: sourceId });
        }
        onGraphChanged();
        return;
      }
```

- [ ] **Step 4: CSS voor de audio-badge**

Voeg toe aan `admin/frontend/src/components/PlayerGraphCanvas.css` (na de bestaande `.player-node__chip`-regel):

```css
.player-node__chip--audio {
  cursor: default;
}
```

- [ ] **Step 5: Run de tests, bevestig dat ze slagen**

Run: `cd admin/frontend && npm test -- PlayerGraphCanvas`
Expected: PASS.

- [ ] **Step 6: Volledige frontend-suite + typecheck**

Run: `cd admin/frontend && npx tsc --noEmit && npm test`
Expected: alle groen.

- [ ] **Step 7: Handmatige verificatie in de browser**

Start backend+frontend lokaal, navigeer naar de spelerscanvas-pagina, maak een `audio`-kind Source aan (via `/sources`, met een geüploade WAV), sleep een verbinding van dat Source-knooppunt naar een Player-knooppunt, en controleer:
- De verbinding komt op de Player aan bij een ander punt dan de bestaande video-source-edge (Position.Top vs. Position.Left).
- De player-node toont de 🔊-badge met de juiste naam.
- `GET /api/players/{id}` (of de Network-tab) bevestigt `audio_source_id` is gezet, `source_id` is ongewijzigd.

Ruim lokale testartefacten op na afloop.

- [ ] **Step 8: Commit**

```bash
git add admin/frontend/src/components/PlayerGraphCanvas.tsx admin/frontend/src/components/PlayerGraphCanvas.css admin/frontend/src/components/PlayerGraphCanvas.test.tsx
git commit -m "feat: audio-source koppelen aan een player via canvas-edge (audio_source_id)"
```

---

## Self-review (uitgevoerd bij het schrijven van dit plan)

**Spec-dekking:** elk onderdeel van de spec (`media`-kind-rename, `video_loop`/`audio`-Source-kinds, `players.audio_source_id` + validatie + cleanup, `mirror_node`-afspeellogica voor beide, frontend-typen/component/embeds, nieuwe `/media`-pagina, `SourcesPage`-picker, canvas-koppeling) heeft een taak. De spec's `MediaLibrary`-popover-suggestie voor de canvas is bewust gecorrigeerd naar een edge-koppeling (zie de uitleg bovenaan dit plan) — een reëel type-mismatch in de spec (Source-id vs. media-hash), geen scope-afwijking.

**Placeholder-scan:** geen TBD/TODO. Taak 10's teststappen bevatten meer proza dan letterlijke testcode omdat de exacte bestaande `handleConnect`-testopzet in `PlayerGraphCanvas.test.tsx` niet is ingezien tijdens het schrijven van dit plan (dat bestand is >20K tekens en niet volledig gelezen) — de instructie wijst de implementeerder expliciet naar het bestaande, analoge patroon in hetzelfde bestand om exact te volgen, in plaats van een geraden teststructuur te geven die niet zou passen bij de echte fixtures.

**Type-consistentie:** `MediaItem.kind`/`Source["kind"]`/`Player.audio_source_id` in Taak 7 komen overeen met wat Taak 1/3/4 backend-side opleveren. `mediaKindFor()` in Taak 9 mapt `Source["kind"]` (4 waarden) naar `MediaLibrary`'s `kind`-prop (3 waarden) consistent met Taak 7's `MediaLibrary`-typering. `_ensure_audio`'s signatuur (`state, player, sources_by_id, logger`) in Taak 6 is consistent tussen de tests en de hoofdlus-aanroep.
