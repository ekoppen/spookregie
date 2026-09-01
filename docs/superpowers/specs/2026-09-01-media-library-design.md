# Algemene medialibrary — design

## Doel

Eén algemeen media-systeem (foto/video/audio) dat overal in de app gebruikt
wordt, in plaats van drie losse, hardgecodeerde categorieën
(`mirror_overlay`, `scare_audio`, `mirror_scare_video`). Sluit daarnaast een
bekend gat: een `static_image`-Source vereist vandaag een handmatig
getypte 64-tekens hash in een tekstveld. En breidt de flow-graaf uit met
twee nieuwe Source-kinds (`video_loop`, `audio`) zodat video en audio ook
als eigen source in de graaf bruikbaar zijn, niet alleen via de bestaande
trigger-gedreven scare-mechanismen.

## Niet-doelen

- Geen nieuwe bestandsformaten boven PNG (image), WAV (audio), MP4 (video).
- Geen nieuw node/edge-type in de canvas-graaf voor audio — audio hangt aan
  de Player (zie hieronder), niet aan een los knooppunt.
- Geen gelijktijdige meerdere audio-sources per player — precies één,
  zelfde exclusiviteit als video.
- Geen waveform-preview, video-thumbnails, of trim/edit-tools.
- Geen wijziging aan het bestaande one-shot scare-audio/scare-video
  trigger-mechanisme — dat blijft functioneel identiek, alleen de
  onderliggende kolomnaam verandert (`category` → `kind`).
- Geen publieke/externe base-url-instelling — `BACKEND_URL` (al
  aanwezig, al gebruikt door `mirror_node`) blijft het enige
  basis-url-mechanisme.

## Datamodel

### `media`-tabel: `category` → `kind`

De bestaande `media`-tabel (`hash`, `filename`, `category`, `uploaded_at`)
krijgt haar `category`-kolom hernoemd naar `kind`, met drie waarden:
`image`, `audio`, `video`. Migratie (één stap, in `admin/app/db.py`, naast
de bestaande migratiefuncties zoals `_migrate_sources`):

```sql
ALTER TABLE media RENAME COLUMN category TO kind;
UPDATE media SET kind = CASE kind
  WHEN 'mirror_overlay' THEN 'image'
  WHEN 'scare_audio' THEN 'audio'
  WHEN 'mirror_scare_video' THEN 'video'
  ELSE kind
END;
```

Guard deze migratie net als de bestaande migraties in `db.py`: check eerst
of de kolom `category` nog bestaat (via `PRAGMA table_info(media)`) voordat
je de rename uitvoert, zodat een herhaalde opstart geen fout geeft op een
al-gemigreerde database.

`admin/app/media.py`'s `validate_upload(data, category)` wordt
`validate_upload(data, kind)`, met dezelfde magic-byte-checks maar op de
nieuwe waarden:

```python
if kind == "image" and not data.startswith(b"\x89PNG"):
    return "afbeelding moet een PNG-bestand zijn"
if kind == "audio" and not (data[:4] == b"RIFF" and data[8:12] == b"WAVE"):
    return "audio moet een WAV-bestand zijn"
if kind == "video" and data[4:8] != b"ftyp":
    return "video moet een MP4-bestand zijn"
```

`extract_audio_if_video` (die bij een scare-video-upload het geluidsspoor
alvast extraheert naar `<hash>.audio`) checkt voortaan `kind == "video"`
in plaats van `kind == "mirror_scare_video"` — ongewijzigd gedrag,
gegeneraliseerd.

Alle SQL/Python-referenties naar `category` in `admin/app/media.py` en
`admin/app/routers/media.py` worden `kind`. De route-parameter
`GET /api/media?category=...` wordt `GET /api/media?kind=...`.

### `sources`-tabel: twee nieuwe kinds

`sources.kind` (`TEXT NOT NULL DEFAULT 'camera_stream'`) accepteert twee
nieuwe waarden naast de bestaande `camera_stream`/`static_image`:

- **`video_loop`** — `value` is een media-hash (kind=`video`). Gedraagt
  zich exclusief zoals `static_image`: vervangt het camerabeeld zolang de
  player met deze source actief is.
- **`audio`** — `value` is een media-hash (kind=`audio`). Is NIET geldig
  in een Player's `source_id`-veld (dat blijft uitsluitend video-kinds:
  `camera_stream`/`static_image`/`video_loop`). Alleen geldig als het
  doel van het nieuwe `players.audio_source_id`-veld.

`admin/app/routers/sources.py`'s `_VALID_KINDS` wordt
`{"camera_stream", "static_image", "video_loop", "audio"}`. Verder geen
wijziging in deze router: een Source is op zichzelf altijd geldig voor elk
van de vier kinds. De beperking — welke kind in welk Player-veld mag —
wordt afgedwongen in de **players**-router (zie hieronder), niet hier.

### `players`-tabel: nieuw `audio_source_id`-veld

```sql
ALTER TABLE players ADD COLUMN audio_source_id INTEGER;
```

Nullable, geen DB-FK (zelfde no-FK-conventie als de rest van deze
codebase — zie `devices.output_id`). App-level cleanup: wanneer een
Source verwijderd wordt, zet `UPDATE players SET audio_source_id = NULL
WHERE audio_source_id = ?` vóór de delete (zelfde patroon als
`outputs.py`'s bestaande cleanup van `devices.output_id`).

`admin/app/routers/players.py`'s create/update-validatie:
- `source_id` moet, indien gezet, verwijzen naar een Source met
  `kind IN ('camera_stream', 'static_image', 'video_loop')`.
- `audio_source_id` moet, indien gezet, verwijzen naar een Source met
  `kind = 'audio'`.

Beide validaties geven een 400 met een duidelijke Nederlandse foutmelding
bij een kind-mismatch (zelfde stijl als bestaande validatiefouten in deze
router).

## Graph-publish

`admin/app/graph_publish.py`'s gepubliceerde player-payload krijgt het
veld `audio_source_id` naast het bestaande `source_id`.

## `mirror_node`: afspelen

### `video_loop` in `_ensure_source`

`_ensure_source` (in `mirror_node/main.py`) krijgt een derde tak naast
`camera_stream`/`static_image`. Bij `kind == "video_loop"`: open het
videobestand (via de bestaande media-cache — zelfde sync-mechanisme als
`static_image` al gebruikt, zie `_sync_sources_in_background`, die
voortaan ook `video_loop`-sources meeneemt in de te synchroniseren set)
met OpenCV (`cv2.VideoCapture`), en lever elk frame van de loop; bij het
bereiken van het laatste frame, spring terug naar frame 0 (`cap.set(cv2.
CAP_PROP_POS_FRAMES, 0)`). Dezelfde open/heropen-alleen-bij-wijziging-
logica als nu al voor `camera_stream`/`static_image` geldt onverkort:
`state.source_id`/`state.kind`/`state.value` ongewijzigd → geen
heropening.

### `audio` via een nieuwe `_AudioState`-tracker

Nieuwe klasse `_AudioState` in `mirror_node/main.py`, zelfde vorm als de
bestaande `_SourceState`: houdt `player_id`, `audio_source_id`, `value`
(hash) bij plus het lopende subprocess. Bij elke hoofdlus-iteratie wordt
— naast de bestaande video-source-resolutie — ook de actieve player's
`audio_source_id` opgezocht in `_current_sources` (dezelfde lijst, nu ook
`audio`-kind sources bevattend).

- Als de geresolvede audio-hash ongewijzigd is: niets doen (subprocess
  blijft draaien).
- Als hij gewijzigd is (inclusief naar `None`): stop het lopende
  subprocess (indien aanwezig) en start, indien de nieuwe hash niet
  `None` is, een nieuw loopend afspeelproces.

Het loopende afspeelproces: een `ffmpeg -stream_loop -1 -i <pad> -f wav -
| aplay`-pipeline via `subprocess.Popen` met `shell=False` (twee
gekoppelde processen, of één `ffmpeg`-aanroep die direct naar een
ALSA-device schrijft via `-f alsa default` — kies bij implementatie de
eenvoudigste variant die al met de bestaande `aplay`/`ffmpeg`-aanwezigheid
op deze devices werkt, zie `_play_scare_video` en
`extract_audio_if_video` voor het bestaande gebruik van beide tools).
Faalt het starten (ontbrekende tool, kapot bestand): loggen en doorgaan
zonder audio — nooit de video-pipeline blokkeren, zelfde
best-effort-filosofie als `extract_audio_if_video`.

Bij het wisselen van speler (niet alleen bij het wisselen van
audio-hash) moet de audiotracker ook herevalueren: een nieuwe actieve
player met een andere (of geen) `audio_source_id` triggert dezelfde
stop/start-logica.

### Media-sync

`shared/media_sync.py`'s bestaande `sync_media`/`fetch_scare_video_audio`
generaliseren niet mee in deze scope — `video_loop`- en
`audio`-sourcebestanden syncen via hetzelfde generieke hash-gebaseerde
ophaalmechanisme dat `static_image` al gebruikt
(`_sync_sources_in_background`), dus geen nieuwe sync-functie nodig, enkel
de filter in `_sync_sources_in_background` die nu ook `video_loop`- en
`audio`-kinds meeneemt (niet alleen `static_image`).

## Frontend

### `types.ts`

```ts
export interface MediaItem {
  hash: string;
  filename: string;
  kind: "image" | "audio" | "video";
  uploaded_at: string;
}
```

`Source["kind"]` wordt
`"camera_stream" | "static_image" | "video_loop" | "audio"`.

`Player` krijgt `audio_source_id: number | null;`.

### `api/media.ts`

`listMedia(kind?)`, `uploadMedia(file, kind)` — `category`-parameter
overal hernoemd naar `kind`.

### `MediaLibrary.tsx`: generaliseren

De component-prop `category: "mirror_overlay" | "scare_audio" |
"mirror_scare_video"` wordt `kind: "image" | "audio" | "video"`.
`CATEGORY_COPY`/`CategoryIcon` worden `KIND_COPY`/`KindIcon` met
dezelfde drie iconen/teksten, nu gekoppeld aan de nieuwe kind-waarden in
plaats van de oude categorienamen. Verder ongewijzigd (upload/lijst/
selectie-gedrag blijft identiek).

### Bestaande embed-plekken: geen zichtbare wijziging

`PlayerWizardModal` (overlay-picker), `ScarePage` (scare-audio-picker),
`MirrorScareVideoPage` (scare-video-picker) geven voortaan `kind="image"`
/`kind="audio"`/`kind="video"` door in plaats van de oude
category-strings. Geen andere wijziging.

### Nieuwe `/media`-pagina

`admin/frontend/src/pages/MediaPage.tsx` (nieuw): toont `MediaLibrary`
zonder kind-filter (alle media), met een kind-keuze (radiogroep of
dropdown: Afbeelding/Audio/Video) die bepaalt met welk `kind` een nieuwe
upload wordt gevalideerd/opgeslagen. Route `/media` + navlink in
`Layout.tsx`, zelfde patroon als de bestaande `/apparaten`-route.

### `SourcesPage.tsx`: picker in plaats van hash-tekstveld

Wanneer een Source's `kind` `static_image` of `video_loop` is, toont de
pagina een `MediaLibrary`-picker (`selectionMode="single"`, gefilterd op
`kind="image"` resp. `kind="video"`) in plaats van het huidige
tekstinvoerveld voor `value`. Voor `camera_stream` blijft het bestaande
vrije-tekst-URL-veld ongewijzigd (geen media-hash, een stream-URL). Voor
de nieuwe `audio`-kind Source geldt dezelfde picker, gefilterd op
`kind="audio"`.

### Canvas: audio-koppeling op het Player-knooppunt

`PlayerGraphCanvas.tsx`'s player-node krijgt, naast de bestaande
branch-chips, een audio-chip (zelfde visuele patroon: een klikbaar
label met de naam van de gekoppelde audio-source, of "+ Audio" als er
nog geen gekoppeld is). Klikken opent dezelfde `MediaLibrary`-picker
(`kind="audio"`) in een popover (zelfde constructie als de bestaande
trigger-picker-popover uit de add-buttons-feature), en slaat de keuze op
via `updatePlayer(id, { audio_source_id })`. Een leeg/geen-selectie-optie
zet `audio_source_id` terug naar `null`.

## Out of scope — expliciet

Zie "Niet-doelen" hierboven. Aanvullend: deze spec verandert niets aan
hoe `outputs`, `triggers`, `devices`, of het bestaande
scare-video-trigger-mechanisme werken — enkel de onderliggende
media-opslag en twee nieuwe Source-kinds worden toegevoegd.
