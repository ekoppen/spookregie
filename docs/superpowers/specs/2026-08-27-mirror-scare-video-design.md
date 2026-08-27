# Mirror scare-video's (fase 1) — Design

**Datum:** 2026-08-27
**Status:** Goedgekeurd, klaar voor implementatieplan
**Vervolg op:** `2026-08-27-mirror-node-inline-start-design.md`

## Doel

De mirror-node kan nu alleen live-camerabeeld tonen met een simpel
effect (xray/thermal/contour/posterize) plus optioneel één statische
PNG-overlay. De gebruiker wil daarnaast korte, realistische
video-clips (bliksem, vuurbal, spook, zombie, heks) die bij een
beweging-trigger het live beeld tijdelijk vervangen — inclusief geluid
— om bezoekers echt te laten schrikken. Dit maakt dat mogelijk: een
nieuwe contentsectie om die clips te beheren, en een nieuwe
afspeel-modus in `mirror_node` die op trigger een willekeurige
ingeschakelde clip toont in plaats van het huidige effect.

Getest met een eerste Runway-gegenereerde clip (720×1280, 10s, 24fps,
H264, geen alphakanaal — zoals verwacht van elke AI-videotool).

## Niet-doelen

- **Geen avond-opbouw/escalatie.** Vroeg-op-de-avond subtiele
  verrassingen vs. laat-op-de-avond volle jump-scares is een aparte
  beslissingslaag bovenop dit fase-1-mechanisme (waarschijnlijk
  gekoppeld aan het bestaande schema-systeem). Eigen spec, aparte
  sessie.
- **Geen alphakanaal/chroma-key-compositing.** De gebruiker koos
  expliciet voor volledige beeld-vervanging op trigger (de clip *is*
  de scène, geen laag over het live-beeld heen) — precies om de
  gedoe-volle transparantie-compositing te vermijden die de eerdere
  overlay-aanpak (statische PNG) zou hebben.
- **Geen automatische keuze per thema.** Fase 1 kiest willekeurig uit
  alle *ingeschakelde* clips, ongeacht thema — thema is puur een
  bestandsnaam/label voor de beheerder, geen aparte
  selectie-dimensie in de code.
- **Geen wijziging aan `scare_node`.** Dit is uitsluitend een
  mirror-node-feature; het gedeelde `/api/node-config`-endpoint blijft
  ongewijzigd (deze feature gebruikt live MQTT-config, niet dat
  boot-time endpoint — zie Architectuur).
- **Geen garantie op geluid in de Docker-testmodus.** `aplay` heeft
  echte ALSA-hardware nodig; in de container (de headless
  test-/ontwerp-modus uit de vorige feature) is er geen geluidskaart
  doorgezet, dus audio zal daar naar verwachting stil falen
  (best-effort, geen crash). Echte audio-verificatie gebeurt op de
  uiteindelijke Pi met aangesloten speaker.

## Architectuur

Twee delen: (1) content-beheer in de backend (upload, opslag,
selectie), (2) live afspeel-mechanisme in `mirror_node`.

**Content-beheer volgt het bestaande `scare_zone_config`-patroon
één-op-één**, toegepast op de mirror i.p.v. een scare-zone: één nieuwe
DB-tabel met een JSON-lijst ingeschakelde media-hashes, een
GET/PUT-API-paar, en een live MQTT-publish (retained) zodra de
beheerder opslaat — precies zoals `scare_zone_config`/`config_scare`
nu al werkt. Bewust géén boot-time-only `/api/node-config`-veld (zoals
`mirror_camera_source`): scare-video-selectie moet direct effect
hebben zonder herstart, exact zoals scare-audio-selectie dat nu al
doet.

```
┌──────────────────────────────┐  PUT   ┌──────────────────────────────┐
│ Scare-video-pagina               │───────▶│ /api/mirror/scare-video-config │
│ (MediaLibrary, multi-select)     │◀──GET──│  mirror_scare_video_config      │
└──────────────────────────────┘        └───────────────┬──────────────┘
                                                          │ publish (retained)
                                              config/mirror/scare-video
                                             {"enabled_hashes": [...]}
                                                          │
                                          ┌───────────────▼──────────────┐
                                          │ mirror_node: achtergrondthread  │
                                          │  sync_media() + audio-fetch      │
                                          │  → synced_scare_videos{hash: ..} │
                                          └───────────────┬──────────────┘
                                                          │
                                          ┌───────────────▼──────────────┐
                                          │ Trigger (bestaande PIR/frame-  │
                                          │ diff): random keuze uit synced │
                                          │ → volledige video+audio-       │
                                          │   takeover i.p.v. effect-render │
                                          └────────────────────────────────┘
```

**Video+audio-koppeling:** bij upload extraheert de backend
automatisch het geluidsspoor uit de mp4 via `ffmpeg` (best-effort — een
clip zonder geluid of een mislukte extractie levert gewoon geen
begeleidend bestand op, geen foutmelding bij de upload). Het geluid
wordt bewaard als een *afgeleid* bestand naast de video
(`<hash>.audio` in `media_dir`, geen eigen DB-rij/content-hash, want
het is niet zelfstandig content-addressed) en opgehaald via een nieuwe
sub-route `GET /api/media/<video-hash>/audio` — publiek toegankelijk,
net als `GET /api/media/<hash>` zelf.

**Afspelen in `mirror_node`:** op het moment dat de bestaande
`FrameDiffTrigger` afgaat, kiest de node — als er minstens één
gesynchroniseerde scare-video is — willekeurig een clip i.p.v. het
normale effect toe te passen op het live frame. Het `mirror/triggered`
MQTT-bericht wordt nog steeds gepubliceerd (scare-nodes elders reageren
zoals nu). De duur van de "actieve periode" volgt de lengte van de
clip zelf (framecount/fps), niet de vaste `MIRROR_ACTIVE_SECONDS`. Zijn
er geen ingeschakelde scare-video's, dan blijft het huidige
effect-gedrag exact ongewijzigd.

## Componenten

### Backend: database (`admin/app/db.py`)

Nieuwe tabel, singleton-rij zoals `mirror_config` (geen migratie-issue
— dit is een nieuwe tabel, geen kolom op een bestaande, dus gewoon
`CREATE TABLE IF NOT EXISTS` is hier correct):

```sql
CREATE TABLE IF NOT EXISTS mirror_scare_video_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled_hashes TEXT NOT NULL DEFAULT '[]'
)
```

### Backend: media-validatie en audio-extractie (`admin/app/media.py`)

- `validate_upload`: nieuwe categorie `mirror_scare_video`, gevalideerd
  op MP4-magic-bytes (`data[4:8] == b"ftyp"` — de ISO-base-media-format
  `ftyp`-box, aanwezig in elke geldige mp4, ongeacht de exacte
  `major_brand`).
- Nieuwe functie `extract_audio_if_video(media_dir, hash_, category)`:
  als `category == "mirror_scare_video"`, roept
  `subprocess.run(["ffmpeg", "-y", "-i", <video_pad>, "-vn", "-ar",
  "44100", "-ac", "2", <video_pad> + ".audio"], capture_output=True)`
  aan. Best-effort: bij een non-zero returncode (geen geluidsspoor,
  corrupte extractie) simpelweg geen bestand aanmaken, geen exception
  naar boven laten komen — de video-upload zelf mag hier nooit op
  stuklopen.
- Nieuwe functie `get_media_audio_path(media_dir, hash_)`: zelfde
  patroon als `get_media_path`, maar checkt `<hash>.audio` i.p.v.
  `<hash>`; `None` als het niet bestaat.

### Backend: routes (`admin/app/routers/media.py`)

- `upload_media`: na een geslaagde `save_media`, roep
  `extract_audio_if_video(...)` aan vóór het response teruggeeft.
- Nieuwe route `GET /api/media/{hash_}/audio`: zelfde vorm als
  `download_media`, maar gebruikt `get_media_audio_path`; 404 als er
  geen begeleidend audiobestand is.

### Backend: publieke paden (`admin/app/main.py`)

`_is_public_media_download` matcht nu alleen `/api/media/<hash>`
(geen `/` in het restpad na de prefix). Moet uitgebreid worden zodat
`/api/media/<hash>/audio` óók publiek is (mirror-node haalt dit op
zonder sessie, exact zoals de video zelf) — zonder per ongeluk andere
toekomstige sub-paden onder `/api/media/` publiek te maken. Concreet:
naast de bestaande exacte-hash-match ook een match toestaan voor
`<hash>/audio` waarbij `<hash>` een geldige content-hash is.

### Backend: mirror-scare-video-config-route (nieuw bestand
`admin/app/routers/mirror_scare_video.py`)

```
GET  /api/mirror/scare-video-config  → {"enabled_hashes": [...]}
PUT  /api/mirror/scare-video-config  → body {"enabled_hashes": [...]}
```

Zelfde structuur als `admin/app/routers/scare.py`'s
`get_scare_config`/`put_scare_config`, maar zonder zone-parameter
(één globale lijst voor de mirror, zoals `mirror_config` ook al
zonder zone-concept is). `PUT` schrijft de tabel (upsert) én
publiceert via een nieuwe bridge-methode.

### Backend: MQTT (`shared/mqtt_contract.py`, `admin/app/mqtt_bridge.py`)

Nieuwe topic-property op `Topics`:

```python
@property
def config_mirror_scare_video(self) -> str:
    return self._p("config/mirror/scare-video")
```

Nieuwe methode op `MqttBridge`:

```python
def publish_mirror_scare_video_config(self, enabled_hashes):
    self._client.publish(
        self._topics.config_mirror_scare_video,
        json.dumps({"enabled_hashes": enabled_hashes}),
        retain=True,
    )
```

### Backend: Docker (`Dockerfile`)

Systeempakket `ffmpeg` nodig voor de upload-time audio-extractie (subprocess-aanroep, geen Python-library), en `alsa-utils` (voor `aplay`)
zodat de in-container headless testmodus uit de vorige feature ook
deze afspeelpad kan uitoefenen (ook al zal er zonder doorgezette
geluidshardware geen geluid uit komen — zie Niet-doelen):

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg alsa-utils \
    && rm -rf /var/lib/apt/lists/*
```

### Shared: audio-companion ophalen (`shared/media_sync.py`)

Nieuwe functie naast het bestaande `sync_media` — bewust apart, want
de content-hash-verificatie die `sync_media` doet is hier niet
mogelijk (het geluid is een afgeleid bestand, niet zelf-content-addressed):

```python
def fetch_scare_video_audio(base_url, cache_dir, video_hash, fetch=None):
    """Haalt het (optionele) geluidsspoor bij een scare-video op en
    cachet het lokaal als <video_hash>.audio. Een 404 (geen geluid
    voor deze clip) of elke andere fout betekent gewoon 'stil afspelen',
    geen foutpad -- vangt alles af via de brede except, net als
    sync_media's eigen fetch-fout-afhandeling."""
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(url, timeout=10) as resp:
                return _read_with_size_cap(resp)
    if not is_content_hash(video_hash):
        return None
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

### mirror_node: config synchroniseren (`mirror_node/main.py`)

- Module-niveau: `synced_scare_videos = {}` (leeg dict bij opstarten —
  in tegenstelling tot `scare_node`'s `None`-vs-`{}`-onderscheid is
  hier geen legacy statische-map-fallback nodig, dus "nog geen config
  binnengekomen" en "config binnengekomen maar leeg" mogen hetzelfde
  gedrag hebben: geen scare-video's, gewoon het huidige effect-gedrag).
  Het topic is `retain=True` gepubliceerd, dus een node die (her)start
  krijgt de laatst bekende stand meteen bij het (her)verbinden, geen
  aparte boot-time REST-call nodig.
- `on_connect`: extra `client.subscribe(topics.config_mirror_scare_video)`.
- `make_on_message`: nieuwe branch voor dit topic — parseert
  `{"enabled_hashes": [...]}`, start een achtergrondthread (zelfde
  fire-and-forget-patroon als `scare_node/main.py`'s
  `_sync_and_apply`, om de MQTT-callbackthread niet te blokkeren) die
  voor elke hash (a) de video zelf synct via het bestaande
  `sync_media`-mechanisme en (b) `fetch_scare_video_audio` aanroept,
  en het resultaat atomisch toewijst aan een module-variabele
  `synced_scare_videos = {hash: {"video": pad, "audio": pad_of_None}}`.

### mirror_node: afspelen (`mirror_node/main.py`)

Nieuwe functie:

```python
def _play_scare_video(video_path, audio_path, streamer, logger):
    """Speelt één scare-video (+ optioneel geluid) volledig af, blokkerend
    -- vervangt het live camerabeeld voor de duur van de clip. Faalt de
    audio-subprocess (geen ALSA-hardware, bv. in de Docker-testmodus),
    dan speelt de video gewoon stil door (best-effort, geen crash)."""
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
```

In de hoofdlus, in de bestaande trigger-detectie
(`if trigger.detect(gray) and now > active_until:`): als
`synced_scare_videos` niet leeg is, kies willekeurig één item, publiceer
`mirror/triggered` zoals nu, roep `_play_scare_video(...)` aan (dit
blokkeert de lus voor de duur van de clip -- geen probleem, tijdens een
scare hoeft er toch niet gelijktijdig live camerabeeld verwerkt te
worden), en sla daarna de gewone `active_until`/effect-render-tak voor
deze cyclus over. Is `synced_scare_videos` leeg, dan blijft precies het
huidige gedrag (effect-render met `MIRROR_ACTIVE_SECONDS`) van kracht.

### Frontend: `MediaLibrary`-component uitbreiden
(`admin/frontend/src/components/MediaLibrary.tsx`)

`Props["category"]`-union krijgt `"mirror_scare_video"` erbij, met een
eigen `CATEGORY_COPY`-entry (leeg-tekst, upload-knoptekst) en een
nieuwe `CategoryIcon`-variant. Geen video-preview-thumbnail nodig — de
component toont nu al alleen bestandsnaam + hash-prefix voor bestaande
categorieën, dat patroon blijft voor video's hetzelfde (geen
scope-uitbreiding, zie Niet-doelen).

### Frontend: nieuwe pagina
`admin/frontend/src/pages/MirrorScareVideoPage.tsx`

Rechtstreeks gemodelleerd naar `ScarePage.tsx`, maar zonder
zone-concept: laadt/toont `enabled_hashes` via nieuwe
`admin/frontend/src/api/mirrorScareVideo.ts`
(`getMirrorScareVideoConfig`/`putMirrorScareVideoConfig`, zelfde
`apiFetch`-patroon als `api/scare.ts`), en gebruikt `MediaLibrary`
met `category="mirror_scare_video"` en `selectionMode="multiple"`.
Geen "Test"-knop nodig zoals bij Scare (fase 1 heeft geen losse
test-trigger-eis voor dit specifieke pad; de bestaande
`control/mirror/test-trigger` blijft werken en zal, als er
scare-video's ingeschakeld zijn, er ook automatisch één afspelen via
dezelfde trigger-logica).

### Frontend: navigatie (`admin/frontend/src/components/Layout.tsx`,
`admin/frontend/src/App.tsx`)

Nieuwe link `{ to: "/mirror-scare", label: "Scare-video's", end: false }`
in `Layout.tsx`'s `links`-array, en een corresponderende
`<Route path="/mirror-scare" element={<MirrorScareVideoPage />} />`
in `App.tsx`.

## Foutafhandeling

- **Video zonder geluidsspoor, of ffmpeg-extractie mislukt:** geen
  begeleidend audiobestand, geen foutmelding bij de upload — de clip
  speelt straks gewoon stil af.
- **`aplay` niet beschikbaar of geen hardware (Docker-testmodus):**
  `_play_scare_video` vangt de `Popen`-fout af, logt een waarschuwing,
  speelt de video gewoon door zonder geluid.
- **Ongeschikte/corrupte video-upload:** magic-byte-check bij upload
  weigert alles dat niet met een geldige mp4-`ftyp`-box begint —
  zelfde niveau van bescherming als de bestaande PNG/WAV-checks.
- **Geen ingeschakelde scare-video's:** `synced_scare_videos` blijft
  leeg, trigger-gedrag is exact zoals vandaag (effect-render), geen
  aparte foutstatus nodig.
- **Backend onbereikbaar tijdens sync:** `fetch_scare_video_audio`
  en `sync_media` falen allebei stil (bestaand gedrag) — de node
  blijft draaien op de laatst bekende `synced_scare_videos`-stand.

## Beveiliging

Geen nieuwe risico's t.o.v. het bestaande patroon: `GET
/api/media/<hash>/audio` is publiek, precies zoals `GET
/api/media/<hash>` dat al is voor overlays/audio — dezelfde
LAN-vertrouwd-aanname die dit project al eerder expliciet heeft
geaccepteerd voor media-downloads en `/api/node-config`. De
scare-video-config-endpoints (`GET`/`PUT
/api/mirror/scare-video-config`) vereisen wél de bestaande
sessie-auth, zoals alle andere config-wijzigende endpoints.

## Testen

- `admin/app/media.py`: `extract_audio_if_video` met een gemockte
  `subprocess.run` (succes → bestand aangemaakt-simulatie; falen →
  geen bestand, geen exception); `validate_upload` met een geldige en
  een ongeldige mp4-magic-byte-payload.
- `admin/app/routers/media.py`: `GET /api/media/{hash}/audio` — 200
  met de juiste bytes als het bestand bestaat, 404 als niet.
- `admin/app/main.py`: `_is_public_media_download` — nieuwe testcases
  voor `<hash>/audio` (publiek) en dat andere sub-paden onder
  `/api/media/` publiek verboden blijven.
- `admin/app/routers/mirror_scare_video.py`: GET/PUT, zelfde
  testpatroon als de bestaande scare-config-routes (auth vereist,
  DB-persistentie, bridge-publish-call).
- `shared/media_sync.py`: `fetch_scare_video_audio` met een
  geïnjecteerde fake-fetch — succes, 404-simulatie, cache-hit
  (bestand bestaat al lokaal).
- `mirror_node/main.py`: `_play_scare_video` met gemockte
  `cv2.VideoCapture`/`subprocess.Popen`/`streamer` — bevestigt dat
  frames worden gepubliceerd en dat een falende audio-`Popen` de
  video-afspeel niet onderbreekt. Trigger-branch: met een niet-lege
  `synced_scare_videos` kiest de code het scare-video-pad i.p.v. de
  normale effect-render (met een gemockte `_play_scare_video`, geen
  echte videobestanden nodig in de test).
- Frontend: `tsc --noEmit` + `vite build` als kwaliteitscheck, zelfde
  als bij eerdere features — geen bestaande componenttestinfrastructuur
  om aan toe te voegen.
- Handmatige verificatie: upload de geteste Runway-zombie-clip via de
  nieuwe pagina, schakel 'm in, trigger de mirror (test-knop of echte
  beweging) en bevestig dat het live-beeld tijdelijk vervangen wordt
  door de clip en daarna teruggaat naar live beeld.
