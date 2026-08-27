# Mirror scare-video's (fase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een contentsectie waarin de beheerder video-clips (bliksem,
vuurbal, spook, zombie, heks) uploadt en inschakelt; bij de bestaande
beweging-trigger vervangt de mirror-node het live beeld tijdelijk
volledig door een willekeurige ingeschakelde clip (+ automatisch
geëxtraheerd geluid), en schakelt daarna terug naar live beeld.

**Architecture:** Backend: nieuwe DB-tabel + GET/PUT-API +
live-MQTT-publish (retained), exact hetzelfde patroon als de
bestaande scare-audio-selectie (`scare_zone_config`/`config_scare`).
Geluid wordt bij upload automatisch uit de mp4 geëxtraheerd via
`ffmpeg` en als afgeleid bestand (geen eigen content-hash) opgehaald
via een nieuwe publieke sub-route. mirror_node: een achtergrondthread
synct de ingeschakelde clips + hun geluid; op trigger kiest de node
willekeurig een clip en speelt 'm blokkerend af (frames naar de
MJPEG-stream/beamer, geluid via `aplay`) i.p.v. het normale
effect-render.

**Tech Stack:** Python (FastAPI, SQLite, `ffmpeg`/`aplay` als
subprocess), TypeScript/React.

**Spec:** `docs/superpowers/specs/2026-08-27-mirror-scare-video-design.md`

## Global Constraints

- Fase 1 kiest willekeurig uit *alle* ingeschakelde clips, ongeacht
  thema — geen aparte selectie-dimensie per thema in de code.
- Geen alphakanaal/chroma-key — de clip vervangt het volledige beeld,
  geen compositing.
- Zijn er geen ingeschakelde scare-video's, dan blijft het bestaande
  effect-gedrag (xray/thermal/contour/posterize, `MIRROR_ACTIVE_SECONDS`)
  exact ongewijzigd.
- Audio-extractie en -afspelen zijn allebei best-effort: geen
  geluidsspoor, een mislukte `ffmpeg`-extractie, of een falende `aplay`
  (bv. geen ALSA-hardware in de Docker-testmodus) mag nooit een crash
  of een geblokkeerde upload veroorzaken — altijd stil doorgaan.
- `GET /api/media/<hash>/audio` is publiek (geen sessie nodig),
  exact zoals `GET /api/media/<hash>` dat al is. `GET`/`PUT
  /api/mirror/scare-video-config` vereisen wél de bestaande sessie-auth.
- `mirror_scare_video_config` is een nieuwe tabel (geen kolom op een
  bestaande) — gewoon `CREATE TABLE IF NOT EXISTS`, geen
  `_ensure_column`-migratie nodig.

---

### Task 1: Backend — DB-tabel + media-validatie/audio-extractie

**Files:**
- Modify: `admin/app/db.py`
- Modify: `admin/app/media.py`
- Test: `tests/test_admin_media.py`

**Interfaces:**
- Produces: nieuwe tabel `mirror_scare_video_config` (kolommen `id`,
  `enabled_hashes`); `extract_audio_if_video(media_dir, hash_,
  category)` (geen return-waarde, schrijft best-effort `<hash>.audio`
  in `media_dir`); `get_media_audio_path(media_dir, hash_) -> str |
  None`. Beide gebruikt door Task 2.
- Consumes: `subprocess` (stdlib), `os.path.exists`/`is_content_hash`
  (al aanwezig in `admin/app/media.py`).

- [ ] **Step 1: Voeg de nieuwe tabel toe aan `admin/app/db.py`**

Direct na het bestaande `mirror_config`-`CREATE TABLE`-blok, vóór het
`schedule`-blok:

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mirror_scare_video_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled_hashes TEXT NOT NULL DEFAULT '[]'
        )"""
    )
```

- [ ] **Step 2: Werk `admin/app/media.py` bij**

Voeg `import subprocess` toe bovenaan (naast de bestaande `import os`/
`import time`).

Werk `validate_upload` bij — voeg de mp4-check toe vóór de
`return None`:

```python
def validate_upload(data, category):
    """Geeft een foutmelding terug, of None als de upload in orde is.
    Alleen de magic bytes worden gecheckt — genoeg om een verkeerd bestand
    bij upload te weigeren in plaats van een node er later op te laten
    stuklopen (zie spec)."""
    if len(data) > MAX_UPLOAD_SIZE:
        return f"bestand is groter dan {MAX_UPLOAD_SIZE // (1024 * 1024)} MB"
    if category == "mirror_overlay" and not data.startswith(b"\x89PNG"):
        return "overlay moet een PNG-bestand zijn"
    if category == "scare_audio" and not (data[:4] == b"RIFF" and data[8:12] == b"WAVE"):
        return "scare-audio moet een WAV-bestand zijn"
    if category == "mirror_scare_video" and data[4:8] != b"ftyp":
        return "scare-video moet een MP4-bestand zijn"
    return None
```

Voeg twee nieuwe functies toe, na `save_media`:

```python
def extract_audio_if_video(media_dir, hash_, category):
    """Extraheert het geluidsspoor van een geüploade scare-video naar
    <hash>.audio via ffmpeg. Best-effort: geen geluidsspoor, een
    ontbrekende ffmpeg-binary, of een mislukte extractie levert gewoon
    geen bestand op -- de video-upload zelf mag hier nooit op stuklopen."""
    if category != "mirror_scare_video":
        return
    video_path = os.path.join(media_dir, hash_)
    audio_path = video_path + ".audio"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-ar", "44100", "-ac", "2", audio_path],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0 and os.path.exists(audio_path):
            os.remove(audio_path)
    except Exception:
        if os.path.exists(audio_path):
            os.remove(audio_path)


def get_media_audio_path(media_dir, hash_):
    if not is_content_hash(hash_):
        return None
    path = os.path.join(media_dir, hash_ + ".audio")
    return path if os.path.exists(path) else None
```

`is_content_hash` is al geïmporteerd bovenaan het bestand (`from
shared.media_sync import content_hash, is_content_hash`) -- controleer
dat en voeg toe als het ontbreekt.

- [ ] **Step 3: Voeg tests toe aan `tests/test_admin_media.py`**

Voeg bovenaan het bestand `extract_audio_if_video` en
`get_media_audio_path` toe aan de bestaande import van
`admin.app.media`, en `import subprocess` als losse import. Voeg deze
tests toe aan het eind van het bestand:

```python
def _mp4_bytes():
    return b"\x00\x00\x00\x18ftypisom" + b"fake-mp4-body"


def test_validate_upload_accepts_valid_mp4_header():
    assert validate_upload(_mp4_bytes(), "mirror_scare_video") is None


def test_validate_upload_rejects_video_without_mp4_header():
    assert validate_upload(b"GIF89a-niet-een-mp4", "mirror_scare_video") is not None


def test_extract_audio_if_video_creates_companion_file(tmp_path, monkeypatch):
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)
    video_hash = "a" * 64
    with open(os.path.join(media_dir, video_hash), "wb") as f:
        f.write(b"fake-mp4-bytes")

    def fake_run(cmd, capture_output=True, timeout=30):
        with open(cmd[-1], "wb") as f:
            f.write(b"fake-wav-bytes")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run)

    extract_audio_if_video(media_dir, video_hash, "mirror_scare_video")

    assert get_media_audio_path(media_dir, video_hash) is not None
    with open(get_media_audio_path(media_dir, video_hash), "rb") as f:
        assert f.read() == b"fake-wav-bytes"


def test_extract_audio_if_video_skips_non_video_category(tmp_path, monkeypatch):
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)
    calls = []
    monkeypatch.setattr("admin.app.media.subprocess.run", lambda *a, **k: calls.append(1))

    extract_audio_if_video(media_dir, "a" * 64, "mirror_overlay")

    assert calls == []


def test_extract_audio_if_video_cleans_up_on_ffmpeg_failure(tmp_path, monkeypatch):
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)
    video_hash = "b" * 64

    def fake_run(cmd, capture_output=True, timeout=30):
        with open(cmd[-1], "wb"):
            pass  # ffmpeg laat soms een leeg bestand achter bij falen
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run)

    extract_audio_if_video(media_dir, video_hash, "mirror_scare_video")

    assert get_media_audio_path(media_dir, video_hash) is None


def test_extract_audio_if_video_handles_missing_ffmpeg_binary(tmp_path, monkeypatch):
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)

    def fake_run(cmd, capture_output=True, timeout=30):
        raise FileNotFoundError("ffmpeg niet gevonden")

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run)

    extract_audio_if_video(media_dir, "c" * 64, "mirror_scare_video")  # mag niet crashen

    assert get_media_audio_path(media_dir, "c" * 64) is None


def test_get_media_audio_path_rejects_malformed_hash(tmp_path):
    media_dir = str(tmp_path / "media")
    assert get_media_audio_path(media_dir, "not-a-hash") is None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_admin_media.py -v`
Expected: alle PASS (bestaande + nieuwe).

- [ ] **Step 5: Commit**

```bash
git add admin/app/db.py admin/app/media.py tests/test_admin_media.py
git commit -m "feat: mirror_scare_video_config-tabel + mp4-validatie + ffmpeg-audio-extractie"
```

---

### Task 2: Backend — media-routes (audio-download, extractie-koppeling, publiek pad)

**Files:**
- Modify: `admin/app/routers/media.py`
- Modify: `admin/app/main.py`
- Modify: `tests/test_admin_routes_media.py`
- Modify: `tests/test_admin_routes_auth.py`

**Interfaces:**
- Consumes: `extract_audio_if_video`, `get_media_audio_path` van
  Task 1 (exacte functie-namen/signatuur).
- Produces: `GET /api/media/{hash}/audio` (publiek, 200 met bytes of
  404).

- [ ] **Step 1: Werk `admin/app/routers/media.py` bij**

Vervang de volledige inhoud door:

```python
from fastapi import APIRouter, HTTPException, Request, UploadFile, Form, Response

from admin.app.media import (
    save_media,
    get_media_path,
    get_media_audio_path,
    list_media,
    delete_media,
    validate_upload,
    extract_audio_if_video,
)

router = APIRouter()


@router.post("/api/media")
async def upload_media(request: Request, file: UploadFile, category: str = Form(...)):
    data = await file.read()
    error = validate_upload(data, category)
    if error is not None:
        raise HTTPException(status_code=400, detail=error)
    h = save_media(request.app.state.db, request.app.state.settings.media_dir, data, file.filename, category)
    extract_audio_if_video(request.app.state.settings.media_dir, h, category)
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


@router.get("/api/media/{hash_}/audio")
def download_media_audio(hash_: str, request: Request):
    path = get_media_audio_path(request.app.state.settings.media_dir, hash_)
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

- [ ] **Step 2: Werk `_is_public_media_download` bij in `admin/app/main.py`**

Vervang:

```python
def _is_public_media_download(path, method):
    """Alleen GET /api/media/<64-char hash> is publiek. Een simpele
    startswith("/api/media/") zou ook toekomstige beheer-endpoints onder
    dat pad (bijv. een lijst-endpoint) per ongeluk publiek maken."""
    if method != "GET":
        return False
    prefix = "/api/media/"
    if not path.startswith(prefix):
        return False
    remainder = path[len(prefix):]
    return "/" not in remainder and is_content_hash(remainder)
```

door:

```python
def _is_public_media_download(path, method):
    """Alleen GET /api/media/<64-char hash> (en zijn /audio-companion)
    zijn publiek. Een simpele startswith("/api/media/") zou ook
    toekomstige beheer-endpoints onder dat pad (bijv. een
    lijst-endpoint) per ongeluk publiek maken."""
    if method != "GET":
        return False
    prefix = "/api/media/"
    if not path.startswith(prefix):
        return False
    remainder = path[len(prefix):]
    if remainder.endswith("/audio"):
        return is_content_hash(remainder[: -len("/audio")])
    return "/" not in remainder and is_content_hash(remainder)
```

- [ ] **Step 3: Voeg tests toe aan `tests/test_admin_routes_media.py`**

Aan het eind van het bestand:

```python
def _mp4_bytes():
    return b"\x00\x00\x00\x18ftypisom" + b"fake-mp4-body"


def test_upload_scare_video_extracts_audio_via_ffmpeg(tmp_path, monkeypatch):
    client = _client(tmp_path)

    def fake_run(cmd, capture_output=True, timeout=30):
        import subprocess
        with open(cmd[-1], "wb") as f:
            f.write(b"fake-wav-bytes")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run)

    upload_resp = _upload(client, "zombie.mp4", _mp4_bytes(), "mirror_scare_video")
    assert upload_resp.status_code == 200
    h = upload_resp.json()["hash"]

    from fastapi.testclient import TestClient as PlainTestClient
    anon_client = PlainTestClient(client.app)
    audio_resp = anon_client.get(f"/api/media/{h}/audio")
    assert audio_resp.status_code == 200
    assert audio_resp.content == b"fake-wav-bytes"


def test_download_audio_for_video_without_sound_returns_404(tmp_path, monkeypatch):
    client = _client(tmp_path)

    def fake_run_no_audio(cmd, capture_output=True, timeout=30):
        import subprocess
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run_no_audio)

    upload_resp = _upload(client, "bliksem.mp4", _mp4_bytes(), "mirror_scare_video")
    h = upload_resp.json()["hash"]

    from fastapi.testclient import TestClient as PlainTestClient
    anon_client = PlainTestClient(client.app)
    audio_resp = anon_client.get(f"/api/media/{h}/audio")
    assert audio_resp.status_code == 404


def test_upload_rejects_video_without_mp4_header(tmp_path):
    client = _client(tmp_path)

    response = _upload(client, "zombie.mp4", b"GIF89a-niet-een-mp4", "mirror_scare_video")

    assert response.status_code == 400
```

- [ ] **Step 4: Voeg assertions toe aan `tests/test_admin_routes_auth.py`**

In de bestaande functie `test_media_download_with_valid_hash_bypasses_auth_check`,
direct na de regel
`assert _is_public_media_download(f"/api/media/{valid_hash}/extra", "GET") is False`,
voeg toe:

```python
    assert _is_public_media_download(f"/api/media/{valid_hash}/audio", "GET") is True
    assert _is_public_media_download(f"/api/media/{valid_hash}/audio", "POST") is False
    assert _is_public_media_download("/api/media/not-a-hash/audio", "GET") is False
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_admin_routes_media.py tests/test_admin_routes_auth.py tests/test_admin_media.py -v`
Expected: alle PASS.

- [ ] **Step 6: Run de volledige suite (regressiecheck)**

Run: `pytest tests/ -q`
Expected: alle bestaande tests blijven ook slagen.

- [ ] **Step 7: Commit**

```bash
git add admin/app/routers/media.py admin/app/main.py tests/test_admin_routes_media.py tests/test_admin_routes_auth.py
git commit -m "feat: GET /api/media/<hash>/audio -- publiek, gekoppeld aan ffmpeg-extractie"
```

---

### Task 3: Backend — mirror-scare-video-config API + MQTT

**Files:**
- Create: `admin/app/routers/mirror_scare_video.py`
- Modify: `shared/mqtt_contract.py`
- Modify: `admin/app/mqtt_bridge.py`
- Modify: `admin/app/main.py`
- Test: `tests/test_admin_routes_mirror_scare_video.py`
- Modify: `tests/test_admin_mqtt_bridge.py`

**Interfaces:**
- Consumes: `mirror_scare_video_config`-tabel van Task 1 (kolommen
  `id`, `enabled_hashes`).
- Produces: `GET`/`PUT /api/mirror/scare-video-config` (auth vereist);
  `Topics.config_mirror_scare_video` (topic
  `config/mirror/scare-video`); `MqttBridge.publish_mirror_scare_video_config(enabled_hashes)`.
  Gebruikt door Task 6 (mirror_node abonneert zich op dit topic).

- [ ] **Step 1: Voeg de topic-property toe aan `shared/mqtt_contract.py`**

Direct na de bestaande `config_scare`-methode:

```python
    @property
    def config_mirror_scare_video(self) -> str:
        return self._p("config/mirror/scare-video")
```

- [ ] **Step 2: Voeg de publish-methode toe aan `admin/app/mqtt_bridge.py`**

Direct na de bestaande `publish_mirror_test`-methode:

```python
    def publish_mirror_scare_video_config(self, enabled_hashes):
        self._client.publish(
            self._topics.config_mirror_scare_video,
            json.dumps({"enabled_hashes": enabled_hashes}),
            retain=True,
        )
```

- [ ] **Step 3: Schrijf `admin/app/routers/mirror_scare_video.py`**

```python
import json

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/mirror/scare-video-config")
def get_mirror_scare_video_config(request: Request):
    row = request.app.state.db.execute(
        "SELECT enabled_hashes FROM mirror_scare_video_config WHERE id = 1"
    ).fetchone()
    if row is None:
        return {"enabled_hashes": []}
    return {"enabled_hashes": json.loads(row[0])}


@router.put("/api/mirror/scare-video-config")
async def put_mirror_scare_video_config(request: Request):
    body = await request.json()
    enabled_hashes = body.get("enabled_hashes", [])
    db = request.app.state.db
    db.execute(
        """INSERT INTO mirror_scare_video_config (id, enabled_hashes) VALUES (1, ?)
           ON CONFLICT(id) DO UPDATE SET enabled_hashes=excluded.enabled_hashes""",
        (json.dumps(enabled_hashes),),
    )
    db.commit()
    request.app.state.bridge.publish_mirror_scare_video_config(enabled_hashes)
    return {"ok": True}
```

- [ ] **Step 4: Wire in `admin/app/main.py`**

Voeg de router-import toe, direct na de bestaande regel
`from admin.app.routers import mirror_process as mirror_process_router`:

```python
from admin.app.routers import mirror_scare_video as mirror_scare_video_router
```

Voeg de include toe, direct na `app.include_router(mirror_process_router.router)`:

```python
    app.include_router(mirror_scare_video_router.router)
```

- [ ] **Step 5: Schrijf `tests/test_admin_routes_mirror_scare_video.py`**

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

    def publish_mirror_scare_video_config(self, enabled_hashes):
        self.calls.append(("mirror_scare_video_config", enabled_hashes))


def _settings(tmp_path):
    return Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"),
        media_dir=str(tmp_path / "media"),
        port=8000,
    )


def _client(tmp_path):
    app = create_app(settings=_settings(tmp_path))
    app.state.bridge = FakeBridge()
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app.state.bridge


def test_get_mirror_scare_video_config_defaults_to_empty(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/mirror/scare-video-config")

    assert response.json() == {"enabled_hashes": []}


def test_put_mirror_scare_video_config_saves_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put(
        "/api/mirror/scare-video-config", json={"enabled_hashes": ["a" * 64, "b" * 64]}
    )

    assert response.status_code == 200
    assert ("mirror_scare_video_config", ["a" * 64, "b" * 64]) in bridge.calls
    assert client.get("/api/mirror/scare-video-config").json() == {
        "enabled_hashes": ["a" * 64, "b" * 64]
    }


def test_mirror_scare_video_config_requires_auth(tmp_path):
    app = create_app(settings=_settings(tmp_path))
    app.state.bridge = FakeBridge()
    client = TestClient(app)  # geen login

    assert client.get("/api/mirror/scare-video-config").status_code == 401
    assert client.put("/api/mirror/scare-video-config", json={"enabled_hashes": []}).status_code == 401
```

- [ ] **Step 6: Voeg een test toe aan `tests/test_admin_mqtt_bridge.py`**

Voeg `import json` toe bovenaan het bestand. Voeg deze test toe aan
het eind:

```python
def test_publish_mirror_scare_video_config_uses_configured_prefix(monkeypatch):
    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)

    bridge = MqttBridge(_settings(mqtt_topic_prefix="test"), tracker=object())

    bridge.publish_mirror_scare_video_config(["a" * 64])

    topic, payload, retain = bridge._client.published[-1]
    assert topic == "test/config/mirror/scare-video"
    assert json.loads(payload) == {"enabled_hashes": ["a" * 64]}
    assert retain is True
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_admin_routes_mirror_scare_video.py tests/test_admin_mqtt_bridge.py -v`
Expected: alle PASS.

- [ ] **Step 8: Run de volledige suite (regressiecheck)**

Run: `pytest tests/ -q`
Expected: alle bestaande tests blijven ook slagen.

- [ ] **Step 9: Commit**

```bash
git add admin/app/routers/mirror_scare_video.py shared/mqtt_contract.py admin/app/mqtt_bridge.py admin/app/main.py tests/test_admin_routes_mirror_scare_video.py tests/test_admin_mqtt_bridge.py
git commit -m "feat: /api/mirror/scare-video-config -- live MQTT-config voor scare-video-selectie"
```

---

### Task 4: Docker — ffmpeg + alsa-utils

**Files:**
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: niets van eerdere tasks (onafhankelijk qua code).
- Produces: een image waarin `ffmpeg` (audio-extractie, backend) en
  `aplay` (audio-afspelen, mirror-node-testmodus) beschikbaar zijn.

- [ ] **Step 1: Werk `Dockerfile` bij**

Voeg, direct na `WORKDIR /app` en vóór `COPY admin/requirements.txt
./admin/requirements.txt`, toe:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg alsa-utils \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Commit**

```bash
git add Dockerfile
git commit -m "feat: ffmpeg + alsa-utils in het beheerpagina-image (scare-video-audio)"
```

*(Build- en importverificatie gebeurt in Task 8 tegen lan01 -- lokale
`docker compose build` op deze ontwikkelmachine is momenteel niet
betrouwbaar, zie de eerdere ruling over de Docker-proxy op deze Mac.)*

---

### Task 5: `shared/media_sync.py` — audio-companion ophalen

**Files:**
- Modify: `shared/media_sync.py`
- Test: `tests/test_media_sync.py`

**Interfaces:**
- Produces: `fetch_scare_video_audio(base_url, cache_dir, video_hash,
  fetch=None) -> str | None`. Gebruikt door Task 6.

- [ ] **Step 1: Voeg de functie toe aan `shared/media_sync.py`**

Aan het eind van het bestand:

```python
def fetch_scare_video_audio(base_url, cache_dir, video_hash, fetch=None):
    """Haalt het (optionele) geluidsspoor bij een scare-video op en
    cachet het lokaal als <video_hash>.audio. Geen content-hash-
    verificatie mogelijk (het geluid is een afgeleid bestand, niet
    zelf-content-addressed zoals sync_media's hashes) -- een 404 (geen
    geluid voor deze clip) of elke andere fout betekent gewoon 'stil
    afspelen', geen foutpad."""
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(url, timeout=10) as resp:
                return _read_with_size_cap(resp)
    if not is_content_hash(video_hash):
        return None
    os.makedirs(cache_dir, exist_ok=True)
    local_path = os.path.join(cache_dir, f"{video_hash}.audio")
    if os.path.exists(local_path):
        return local_path
    try:
        data = fetch(f"{base_url}/api/media/{video_hash}/audio")
    except Exception:
        return None
    with open(local_path, "wb") as f:
        f.write(data)
    return local_path
```

- [ ] **Step 2: Voeg tests toe aan `tests/test_media_sync.py`**

Voeg `fetch_scare_video_audio` toe aan de bestaande import bovenaan.
Voeg deze tests toe aan het eind van het bestand:

```python
def test_fetch_scare_video_audio_uses_cache_when_file_exists(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    video_hash = "a" * 64
    (cache_dir / f"{video_hash}.audio").write_bytes(b"cached-audio")
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"should not be called"

    result = fetch_scare_video_audio("http://backend", str(cache_dir), video_hash, fetch=fake_fetch)

    assert result == str(cache_dir / f"{video_hash}.audio")
    assert calls == []


def test_fetch_scare_video_audio_fetches_missing_file(tmp_path):
    cache_dir = tmp_path / "cache"
    video_hash = "b" * 64
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"fresh-audio-bytes"

    result = fetch_scare_video_audio("http://backend", str(cache_dir), video_hash, fetch=fake_fetch)

    assert calls == [f"http://backend/api/media/{video_hash}/audio"]
    assert result == str(cache_dir / f"{video_hash}.audio")
    assert (cache_dir / f"{video_hash}.audio").read_bytes() == b"fresh-audio-bytes"


def test_fetch_scare_video_audio_returns_none_on_fetch_failure(tmp_path):
    cache_dir = tmp_path / "cache"
    video_hash = "c" * 64

    def failing_fetch(url):
        raise OSError("404")

    result = fetch_scare_video_audio("http://backend", str(cache_dir), video_hash, fetch=failing_fetch)

    assert result is None


def test_fetch_scare_video_audio_rejects_malformed_hash(tmp_path):
    cache_dir = tmp_path / "cache"

    result = fetch_scare_video_audio(
        "http://backend", str(cache_dir), "not-a-hash", fetch=lambda url: b"x"
    )

    assert result is None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_media_sync.py -v`
Expected: alle PASS.

- [ ] **Step 4: Commit**

```bash
git add shared/media_sync.py tests/test_media_sync.py
git commit -m "feat: fetch_scare_video_audio -- haalt het afgeleide geluidsspoor van een scare-video op"
```

---

### Task 6: mirror_node — scare-video sync + afspelen + trigger-integratie

**Files:**
- Modify: `mirror_node/main.py`
- Test: `tests/test_mirror_main.py`

**Interfaces:**
- Consumes: `fetch_scare_video_audio` van Task 5;
  `topics.config_mirror_scare_video` van Task 3.
- Produces: `synced_scare_videos` (module-dict), `_play_scare_video`,
  `_handle_trigger`, `_apply_scare_video_config_message`.

- [ ] **Step 1: Werk de imports bovenaan `mirror_node/main.py` bij**

Vervang:

```python
import json
import os
import re
import sys
import tempfile
import time
import threading

import cv2
import paho.mqtt.client as mqtt

from shared.mqtt_contract import SLEEP_PAYLOAD_ON, Topics, trigger_payload
from shared.topic_prefix import fetch_topic_prefix, fetch_mirror_camera_source
from shared.logging_setup import setup_logging
from shared.media_sync import sync_media
```

door:

```python
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import threading

import cv2
import paho.mqtt.client as mqtt

from shared.mqtt_contract import SLEEP_PAYLOAD_ON, Topics, trigger_payload
from shared.topic_prefix import fetch_topic_prefix, fetch_mirror_camera_source
from shared.logging_setup import setup_logging
from shared.media_sync import sync_media, fetch_scare_video_audio
```

- [ ] **Step 2: Voeg module-state toe**

Direct na de bestaande regel `active_config = ActiveMirrorConfig()`:

```python
synced_scare_videos = {}
```

- [ ] **Step 3: Voeg de sync-functies toe**

Direct na `_sync_overlay_in_background` (en vóór `_apply_config_message`):

```python
def _sync_scare_videos_in_background(enabled_hashes):
    """Haalt de ingeschakelde scare-video's (en hun optionele geluid) op de
    achtergrond op -- zelfde reden als _sync_overlay_in_background:
    sync_media kan ~10s blokkeren en mag de MQTT-callbackthread niet
    ophouden."""
    def _do_sync():
        global synced_scare_videos
        videos = sync_media(BACKEND_URL, MEDIA_CACHE_DIR, enabled_hashes)
        result = {}
        for h, video_path in videos.items():
            audio_path = fetch_scare_video_audio(BACKEND_URL, MEDIA_CACHE_DIR, h)
            result[h] = {"video": video_path, "audio": audio_path}
        synced_scare_videos = result
    threading.Thread(target=_do_sync, daemon=True).start()


def _apply_scare_video_config_message(payload, logger):
    try:
        config = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige scare-video-config-JSON ontvangen, genegeerd")
        return
    if not isinstance(config, dict):
        logger.error("Scare-video-config is geen JSON-object, genegeerd: %r", config)
        return
    hashes = config.get("enabled_hashes", [])
    if not isinstance(hashes, list):
        logger.error("enabled_hashes is geen lijst, genegeerd: %r", hashes)
        return
    _sync_scare_videos_in_background(hashes)
```

- [ ] **Step 4: Werk `make_on_message` bij**

Vervang:

```python
            if msg.topic == topics.control_mirror_test:
                test_trigger_requested.set()
        except Exception as exc:
```

door:

```python
            if msg.topic == topics.control_mirror_test:
                test_trigger_requested.set()
                return
            if msg.topic == topics.config_mirror_scare_video:
                _apply_scare_video_config_message(msg.payload.decode(), logger)
        except Exception as exc:
```

- [ ] **Step 5: Abonneer op het nieuwe topic**

In `main()`'s `on_connect`-functie, direct na
`client.subscribe(topics.control_mirror_test)`:

```python
        client.subscribe(topics.config_mirror_scare_video)
```

- [ ] **Step 6: Voeg `_play_scare_video` en `_handle_trigger` toe**

Direct na `_open_camera` (en vóór `_redact_source`):

```python
def _play_scare_video(video_path, audio_path, streamer, logger):
    """Speelt één scare-video (+ optioneel geluid) volledig af, blokkerend
    -- vervangt het live camerabeeld voor de duur van de clip. Een falende
    audio-subprocess (bv. geen ALSA-hardware in de Docker-testmodus) mag
    de video niet onderbreken -- best-effort, gewoon stil doorspelen."""
    if audio_path:
        try:
            subprocess.Popen(["aplay", audio_path])
        except Exception as exc:
            logger.warning("Kon geluid niet starten: %s", exc)

    cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frame_delay = 1.0 / fps
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            streamer.publish_frame(frame)
            if not MIRROR_HEADLESS:
                cv2.imshow("mirror", frame)
                cv2.waitKey(1)
            time.sleep(frame_delay)
    finally:
        cap.release()


def _handle_trigger(streamer, logger):
    """Reageert op een trigger (echt of test): speelt een willekeurige
    ingeschakelde scare-video af als er minstens één is gesynct, anders
    geeft het het aantal seconden terug dat het gewone effect actief moet
    blijven. Geeft None terug als er een video is afgespeeld (active_until
    moet dan ongewijzigd blijven -- de video's eigen duur bepaalde al hoe
    lang het live beeld vervangen werd)."""
    if synced_scare_videos:
        chosen = random.choice(list(synced_scare_videos.values()))
        _play_scare_video(chosen["video"], chosen["audio"], streamer, logger)
        return None
    return ACTIVE_SECONDS
```

- [ ] **Step 7: Werk de trigger-afhandeling bij in `main()`**

Vervang:

```python
            if trigger.detect(gray) and now > active_until:
                active_until = now + ACTIVE_SECONDS
                client.publish(topics.mirror_triggered, trigger_payload())
                logger.info("mirror triggered")

            # Handmatige test vanaf de beheerpagina: wel het effect tonen, maar
            # bewust géén mirror/triggered publiceren — dat topic betekent
            # "echte beweging gezien" en laat de scare-nodes meedoen.
            if test_trigger_requested.is_set():
                test_trigger_requested.clear()
                active_until = now + ACTIVE_SECONDS
                logger.info("mirror test-trigger")
```

door:

```python
            if trigger.detect(gray) and now > active_until:
                client.publish(topics.mirror_triggered, trigger_payload())
                logger.info("mirror triggered")
                extra_seconds = _handle_trigger(streamer, logger)
                if extra_seconds is not None:
                    active_until = now + extra_seconds

            # Handmatige test vanaf de beheerpagina: wel het effect tonen, maar
            # bewust géén mirror/triggered publiceren — dat topic betekent
            # "echte beweging gezien" en laat de scare-nodes meedoen.
            if test_trigger_requested.is_set():
                test_trigger_requested.clear()
                logger.info("mirror test-trigger")
                extra_seconds = _handle_trigger(streamer, logger)
                if extra_seconds is not None:
                    active_until = now + extra_seconds
```

- [ ] **Step 8: Voeg tests toe aan `tests/test_mirror_main.py`**

```python
def test_apply_scare_video_config_message_ignores_non_dict_json():
    logger = _FakeLogger()
    mirror_main._apply_scare_video_config_message("[1, 2, 3]", logger)
    assert logger.errors


def test_apply_scare_video_config_message_ignores_malformed_json():
    logger = _FakeLogger()
    mirror_main._apply_scare_video_config_message("{niet-geldig-json", logger)
    assert logger.errors


def test_apply_scare_video_config_message_ignores_non_list_hashes():
    logger = _FakeLogger()
    mirror_main._apply_scare_video_config_message('{"enabled_hashes": "niet-een-lijst"}', logger)
    assert logger.errors


def test_apply_scare_video_config_message_triggers_background_sync(monkeypatch):
    calls = []
    monkeypatch.setattr(mirror_main, "_sync_scare_videos_in_background", lambda hashes: calls.append(hashes))

    mirror_main._apply_scare_video_config_message('{"enabled_hashes": ["a"]}', _FakeLogger())

    assert calls == [["a"]]


def test_play_scare_video_publishes_all_frames(monkeypatch):
    class FakeCap:
        def __init__(self):
            self._remaining = 3

        def get(self, prop):
            return 24.0

        def read(self):
            if self._remaining > 0:
                self._remaining -= 1
                return True, f"frame-{self._remaining}"
            return False, None

        def release(self):
            pass

    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: FakeCap())
    monkeypatch.setattr(mirror_main.time, "sleep", lambda s: None)
    monkeypatch.setattr(mirror_main, "MIRROR_HEADLESS", True)

    published = []

    class FakeStreamer:
        def publish_frame(self, frame):
            published.append(frame)

    mirror_main._play_scare_video("video.mp4", None, FakeStreamer(), _FakeLogger())

    assert published == ["frame-2", "frame-1", "frame-0"]


def test_play_scare_video_starts_audio_when_provided(monkeypatch):
    class FakeCap:
        def get(self, prop):
            return 24.0

        def read(self):
            return False, None

        def release(self):
            pass

    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: FakeCap())
    monkeypatch.setattr(mirror_main.time, "sleep", lambda s: None)
    monkeypatch.setattr(mirror_main, "MIRROR_HEADLESS", True)

    popen_calls = []
    monkeypatch.setattr(mirror_main.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))

    class FakeStreamer:
        def publish_frame(self, frame):
            pass

    mirror_main._play_scare_video("video.mp4", "audio.wav", FakeStreamer(), _FakeLogger())

    assert popen_calls == [["aplay", "audio.wav"]]


def test_play_scare_video_survives_audio_start_failure(monkeypatch):
    class FakeCap:
        def get(self, prop):
            return 24.0

        def read(self):
            return False, None

        def release(self):
            pass

    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: FakeCap())
    monkeypatch.setattr(mirror_main.time, "sleep", lambda s: None)
    monkeypatch.setattr(mirror_main, "MIRROR_HEADLESS", True)

    def failing_popen(cmd):
        raise FileNotFoundError("aplay niet gevonden")

    monkeypatch.setattr(mirror_main.subprocess, "Popen", failing_popen)

    published = []

    class FakeStreamer:
        def publish_frame(self, frame):
            published.append(frame)

    mirror_main._play_scare_video("video.mp4", "audio.wav", FakeStreamer(), _FakeLogger())

    assert published == []  # FakeCap.read() geeft meteen False terug, mag niet crashen


def test_handle_trigger_plays_scare_video_when_available(monkeypatch):
    mirror_main.synced_scare_videos = {"h1": {"video": "v.mp4", "audio": "a.wav"}}
    play_calls = []
    monkeypatch.setattr(mirror_main, "_play_scare_video", lambda v, a, s, l: play_calls.append((v, a)))

    try:
        result = mirror_main._handle_trigger("streamer", _FakeLogger())
        assert result is None
        assert play_calls == [("v.mp4", "a.wav")]
    finally:
        mirror_main.synced_scare_videos = {}


def test_handle_trigger_returns_active_seconds_when_no_scare_videos():
    mirror_main.synced_scare_videos = {}

    result = mirror_main._handle_trigger("streamer", _FakeLogger())

    assert result == mirror_main.ACTIVE_SECONDS
```

- [ ] **Step 9: Run tests**

Run: `pytest tests/test_mirror_main.py -v`
Expected: alle PASS (bestaande + nieuwe).

- [ ] **Step 10: Run de volledige suite (regressiecheck)**

Run: `pytest tests/ -q`
Expected: alle bestaande tests blijven ook slagen.

- [ ] **Step 11: Commit**

```bash
git add mirror_node/main.py tests/test_mirror_main.py
git commit -m "feat: mirror-node speelt scare-video's af op trigger (beeld+geluid, volledige vervanging)"
```

---

### Task 7: Frontend — contentpagina voor scare-video's

**Files:**
- Modify: `admin/frontend/src/components/MediaLibrary.tsx`
- Modify: `admin/frontend/src/types.ts`
- Create: `admin/frontend/src/api/mirrorScareVideo.ts`
- Create: `admin/frontend/src/pages/MirrorScareVideoPage.tsx`
- Create: `admin/frontend/src/pages/MirrorScareVideoPage.css`
- Modify: `admin/frontend/src/components/Layout.tsx`
- Modify: `admin/frontend/src/App.tsx`

**Interfaces:**
- Consumes: `ScareConfig`-type (al aanwezig in `types.ts`,
  `{enabled_hashes: string[]}` -- exact de vorm van
  `/api/mirror/scare-video-config`, geen nieuw type nodig);
  `MediaLibrary`-component (bestaand, `selectionMode="multiple"`).

- [ ] **Step 1: Voeg de categorie toe aan `MediaLibrary.tsx`**

Vervang de `Props`-interface en `CATEGORY_COPY`:

```typescript
interface Props {
  category: "mirror_overlay" | "scare_audio" | "mirror_scare_video";
  selected: string[];
  onSelectionChange: (hashes: string[]) => void;
  selectionMode: "single" | "multiple";
}

const CATEGORY_COPY: Record<Props["category"], { empty: string; upload: string }> = {
  mirror_overlay: {
    empty: "Nog geen overlays geüpload.",
    upload: "Overlay toevoegen",
  },
  scare_audio: {
    empty: "Nog geen geluiden geüpload.",
    upload: "Geluid toevoegen",
  },
  mirror_scare_video: {
    empty: "Nog geen scare-video's geüpload.",
    upload: "Video toevoegen",
  },
};
```

Voeg een derde branch toe aan `CategoryIcon` (na de bestaande
`if (category === "mirror_overlay") { ... }` en vóór de `return` die
het scare_audio-icoon tekent):

```typescript
  if (category === "mirror_scare_video") {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
        <rect x="3" y="5" width="14" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <path d="M17 9.5l4-2.5v10l-4-2.5" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
    );
  }
```

- [ ] **Step 2: Werk `MediaItem` bij in `admin/frontend/src/types.ts`**

Vervang:

```typescript
export interface MediaItem {
  hash: string;
  filename: string;
  category: "mirror_overlay" | "scare_audio";
  uploaded_at: string;
}
```

door:

```typescript
export interface MediaItem {
  hash: string;
  filename: string;
  category: "mirror_overlay" | "scare_audio" | "mirror_scare_video";
  uploaded_at: string;
}
```

- [ ] **Step 3: Schrijf `admin/frontend/src/api/mirrorScareVideo.ts`**

```typescript
import { apiFetch } from "./client";
import type { ScareConfig } from "../types";

export function getMirrorScareVideoConfig(): Promise<ScareConfig> {
  return apiFetch<ScareConfig>("/api/mirror/scare-video-config");
}

export function putMirrorScareVideoConfig(config: ScareConfig): Promise<void> {
  return apiFetch("/api/mirror/scare-video-config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}
```

- [ ] **Step 4: Schrijf `admin/frontend/src/pages/MirrorScareVideoPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { getMirrorScareVideoConfig, putMirrorScareVideoConfig } from "../api/mirrorScareVideo";
import MediaLibrary from "../components/MediaLibrary";
import "./MirrorScareVideoPage.css";

export default function MirrorScareVideoPage() {
  const [enabledHashes, setEnabledHashes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getMirrorScareVideoConfig()
      .then((c) => {
        setEnabledHashes(c.enabled_hashes);
        setError(null);
      })
      .catch(() => setError("Configuratie kon niet worden geladen."));
  }, []);

  async function handleSave() {
    setSaving(true);
    try {
      await putMirrorScareVideoConfig({ enabled_hashes: enabledHashes });
      setError(null);
    } catch {
      setError("Opslaan is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mirror-scare-video-page">
      <header className="mirror-scare-video-header">
        <p className="mirror-scare-video-eyebrow">
          <span className="mirror-scare-video-eyebrow__led" aria-hidden="true" />
          Spiegel-node
        </p>
        <h1 className="mirror-scare-video-heading">Scare-video's</h1>
      </header>

      {error && (
        <p className="mirror-scare-video-error" role="alert">
          {error}
        </p>
      )}

      <section className="mirror-scare-video-panel">
        <p className="mirror-scare-video-panel__eyebrow">Video-bibliotheek</p>
        <p className="mirror-scare-video-hint">
          Ingeschakelde video's worden willekeurig gekozen en vervangen bij een trigger tijdelijk
          het live beeld (inclusief geluid, indien aanwezig).
        </p>
        <MediaLibrary
          category="mirror_scare_video"
          selectionMode="multiple"
          selected={enabledHashes}
          onSelectionChange={setEnabledHashes}
        />
      </section>

      <div className="mirror-scare-video-actions">
        <button
          className="mirror-scare-video-save"
          type="button"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? "Bezig…" : "Opslaan"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Schrijf `admin/frontend/src/pages/MirrorScareVideoPage.css`**

```css
.mirror-scare-video-page {
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

.mirror-scare-video-header {
  margin-bottom: 1.75rem;
}

.mirror-scare-video-eyebrow {
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

.mirror-scare-video-eyebrow__led {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--signal);
  box-shadow: 0 0 6px 1px rgba(255, 184, 77, 0.7);
  animation: mirror-scare-video-pulse 1.6s ease-in-out infinite;
}

@keyframes mirror-scare-video-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

.mirror-scare-video-heading {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--bone);
}

.mirror-scare-video-error {
  margin: 0 0 1.5rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 92, 92, 0.08);
  border: 1px solid var(--alarm);
  border-radius: 6px;
  font-size: 0.85rem;
  color: var(--alarm);
}

.mirror-scare-video-panel {
  margin-bottom: 1.5rem;
  padding: 1.25rem;
  background: var(--panel);
  border: 1px solid var(--panel-edge);
  border-radius: 10px;
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.03) inset,
    0 12px 40px rgba(0, 0, 0, 0.4);
}

.mirror-scare-video-panel__eyebrow {
  margin: 0 0 1rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ash);
}

.mirror-scare-video-hint {
  margin: 0 0 1rem;
  font-size: 0.85rem;
  color: var(--ash);
}

.mirror-scare-video-actions {
  display: flex;
  gap: 1rem;
}

.mirror-scare-video-save {
  padding: 0.75rem 1.5rem;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
  background: var(--ember);
  border: none;
  color: var(--void);
  transition: background-color 0.15s ease;
}

.mirror-scare-video-save:hover:not(:disabled) {
  background: var(--ember-dim);
}

.mirror-scare-video-save:focus-visible {
  outline: 2px solid var(--bone);
  outline-offset: 2px;
}

.mirror-scare-video-save:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (prefers-reduced-motion: reduce) {
  .mirror-scare-video-eyebrow__led {
    animation: none;
  }
}
```

- [ ] **Step 6: Voeg navigatie toe aan `admin/frontend/src/components/Layout.tsx`**

Vervang de `links`-array:

```typescript
const links = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/mirror", label: "Mirror", end: false },
  { to: "/mirror-scare", label: "Scare-video's", end: false },
  { to: "/scare", label: "Scare", end: false },
  { to: "/ha", label: "Home Assistant", end: false },
  { to: "/logs", label: "Logs", end: false },
  { to: "/settings", label: "Instellingen", end: false },
];
```

- [ ] **Step 7: Voeg de route toe aan `admin/frontend/src/App.tsx`**

Voeg de import toe (naast de bestaande `import MirrorPage from
"./pages/MirrorPage";`):

```typescript
import MirrorScareVideoPage from "./pages/MirrorScareVideoPage";
```

Voeg de route toe, direct na `<Route path="/mirror"
element={<MirrorPage />} />`:

```tsx
          <Route path="/mirror-scare" element={<MirrorScareVideoPage />} />
```

- [ ] **Step 8: Build**

Run: `cd admin/frontend && npm run build`
Expected: succeeds, geen TypeScript-fouten.

- [ ] **Step 9: Commit**

```bash
git add admin/frontend/src/components/MediaLibrary.tsx admin/frontend/src/types.ts admin/frontend/src/api/mirrorScareVideo.ts admin/frontend/src/pages/MirrorScareVideoPage.tsx admin/frontend/src/pages/MirrorScareVideoPage.css admin/frontend/src/components/Layout.tsx admin/frontend/src/App.tsx
git commit -m "feat: contentpagina voor mirror scare-video's"
```

---

### Task 8: Whole-feature verification

**Files:** geen (alleen verificatie).

- [ ] **Step 1: Volledige backend-testsuite**

Run: `pytest tests/ -q`
Expected: alle tests PASS.

- [ ] **Step 2: Frontend build**

Run: `cd admin/frontend && npm run build`
Expected: succeeds, geen TypeScript-fouten.

- [ ] **Step 3: Build + importverificatie op lan01**

```bash
ssh eelko@lan01 "cd /home/eelko/spookregie && git pull --ff-only && docker compose build"
ssh eelko@lan01 "cd /home/eelko/spookregie && docker compose run --rm beheerpagina bash -c 'ffmpeg -version >/dev/null && aplay --version >/dev/null && echo OK'"
```

Expected: build slaagt, `OK` (ffmpeg en aplay allebei aanwezig in het
image).

- [ ] **Step 4: Handmatige eind-tot-eind-verificatie met de echte
  zombie-clip**

Herstart de container (`docker compose up -d`), log in op de
beheerpagina, upload de eerder gebruikte
`Pale_decayed_zombie_emerging.mp4` via de nieuwe
"Scare-video's"-pagina, schakel 'm in en sla op. Start de mirror-node
(zoals eerder deze sessie, via de Spiegel-pagina se Start-knop of
handmatig met `MIRROR_HEADLESS=1`), en trigger 'm (bewegen voor de
Reolink, of de bestaande test-trigger). Bevestig:
- het live-preview-beeld wordt tijdelijk volledig vervangen door de
  zombie-video
- (indien er audio-hardware aanwezig is) het geluid speelt mee
- na afloop van de clip gaat het beeld terug naar het normale
  spiegel-gedrag (zwart/idle totdat er weer beweging is)

- [ ] **Step 5: Eindreview**

Dispatch een eindreview over alle bestanden uit Tasks 1-7 (zelfde
conventie als eerdere plannen in deze repo): controleer specifiek dat
`GET /api/media/<hash>/extra` (of enig ander sub-pad behalve
`/audio`) nog steeds NIET publiek is, dat een lege
`enabled_hashes`-lijst het bestaande effect-gedrag geen millimeter
verandert, dat `_handle_trigger`'s `None`-return-conventie op beide
aanroepplekken in `main()` consistent wordt gebruikt, en dat er geen
ongebruikte imports zijn achtergebleven in `mirror_node/main.py` of
`MirrorScareVideoPage.tsx`.
