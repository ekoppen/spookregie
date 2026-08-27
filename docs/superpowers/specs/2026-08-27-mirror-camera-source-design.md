# Mirror-node camera-bron (RTSP/netwerkcamera) — Design

**Datum:** 2026-08-27
**Status:** Goedgekeurd, klaar voor implementatieplan
**Vervolg op:** `2026-08-27-mqtt-topic-prefix-design.md`

## Doel

`mirror_node` kan nu alleen een lokale, direct aangesloten camera gebruiken
(`cv2.VideoCapture(<index>)`). Er is (nog) geen camera direct beschikbaar om
tegen te testen — dat bracht de vraag naar boven of het spiegel-effect ook
met een bestaande netwerkcamera (bijv. een Reolink) kan werken. Dit maakt
`mirror_node`'s camera-bron generiek: elke camera die een RTSP- of
HTTP-stream aanbiedt werkt, naast de bestaande lokale index — en, net als de
andere verbindingsinstellingen, volledig beheerbaar vanuit de
Instellingen-pagina, geen env var die je per node moet aanpassen.

## Niet-doelen

- **Geen camera-merk-specifieke code.** De implementatie geeft een URL door
  aan OpenCV/FFmpeg; welk merk daarachter zit maakt niets uit. Reolink was
  de aanleiding, niet een vereiste.
- **Geen extra authenticatie op `/api/node-config`.** Expliciet met de
  gebruiker besproken: dit is een vertrouwd thuis-LAN, één beheerder — het
  risico dat iemand anders op het netwerk de camera-URL (met eventuele
  inloggegevens erin) opvraagt via dit publieke endpoint wordt bewust
  geaccepteerd, net zoals dat nu al geldt voor de MQTT-topic-prefix. Geen
  token-systeem, geen scope-beperking.
- **Geen persoons-/gebarendetectie.** Apart onderwerp, aangekaart door de
  gebruiker maar bewust losgekoppeld — te groot en te anders van aard
  (ML-inferentie, evt. Coral Edge TPU) om in dezelfde spec mee te nemen.
  Eigen brainstorm/spec als dat wordt opgepakt.
- **Geen wijziging aan `scare_node`.** Camera-bron is uitsluitend relevant
  voor `mirror_node`; `scare_node` blijft ongewijzigd (het gedeelde
  `/api/node-config`-endpoint krijgt wel het nieuwe veld, `scare_node`
  negeert het simpelweg, zoals het nu ook al met andere velden zou doen).

## Architectuur

Zelfde patroon als de MQTT-topic-prefix-feature: backend is de bron van
waarheid (nieuw veld in `RuntimeSettings`/`app_settings`, beheerd via de
Instellingen-pagina), `mirror_node` haalt de actuele waarde bij het
opstarten op via het al bestaande publieke `GET /api/node-config` (nu
uitgebreid met dit veld), met terugval op een lokale env var als de backend
onbereikbaar is — exact dezelfde reden als bij de topic-prefix: de node
blijft zelfstandig bruikbaar zonder backend.

```
┌──────────────────────────┐   PUT  ┌─────────────────────────┐
│ Instellingen-pagina         │───────▶│ /api/settings              │
│ ("Camera-bron"-veld)        │◀──GET──│  runtime_settings.mirror_   │
└──────────────────────────┘        │  camera_source               │
                                     └───────────┬─────────────┘
                                                 │
                                     ┌───────────▼─────────────┐
                                     │ GET /api/node-config       │
                                     │  {"mqtt_topic_prefix": ...,│
                                     │   "mirror_camera_source":  │
                                     │    "..."}                   │
                                     └───────────┬─────────────┘
                                                 │ bij opstarten,
                                                 │ eenmalig
                                     ┌───────────▼─────────────┐
                                     │ mirror_node/main.py         │
                                     │  _open_camera(source)        │
                                     │  - leeg -> lokale index 0     │
                                     │  - cijfer -> lokale index      │
                                     │  - anders -> cv2.VideoCapture(  │
                                     │      url, cv2.CAP_FFMPEG)        │
                                     └───────────────────────────┘
```

## Componenten

### Backend (`admin/app/`)

- `db.py`: `app_settings` krijgt kolom `mirror_camera_source TEXT NOT NULL
  DEFAULT ''`, toegevoegd via `_ensure_column` (dezelfde migratie-aanpak als
  `mqtt_topic_prefix` — de les uit de vorige review: een kolom toevoegen aan
  een bestaande tabel moet altijd via die route, nooit alleen in de
  `CREATE TABLE`-statement, anders crasht een bestaande deploy).
- `runtime_settings.py`: `RuntimeSettings` krijgt `mirror_camera_source: str
  = ""` (laatste veld, gedefaulte, zelfde reden als eerder: geen bestaande
  directe `RuntimeSettings(...)`-constructie hoeft aangepast). Geen
  env-var-eerste-opstart-seed nodig voor dit veld (er was nooit een
  backend-kant env var voor camera-bron) — default gewoon `""`.
- `routers/settings.py`: `mirror_camera_source` in `GET`/`PUT
  /api/settings`, **niet gemaskeerd** (net als `mqtt_topic_prefix` en
  `mirror_stream_url` — expliciet besproken: geen extra beveiliging, dus ook
  geen reden om het als secret te behandelen zoals `mqtt_pass`/`ha_token`).
  Lichte validatie: leeg, een geheel getal, of een string die met
  `rtsp://` of `http://`/`https://` begint — anders `400`.
- `routers/node_config.py`: response krijgt het extra veld
  `"mirror_camera_source": request.app.state.runtime_settings
  .mirror_camera_source`.

### Frontend (`admin/frontend/`)

- `types.ts`: `AppSettings`/`AppSettingsUpdate` krijgen
  `mirror_camera_source: string`.
- `SettingsPage.tsx`: nieuw veld "Camera-bron (optioneel)" in de
  Spiegel-node-sectie (waar nu al `mirror_stream_url` staat), placeholder
  `bijv. rtsp://gebruiker:wachtwoord@192.168.1.50:554/stream1`, helptekst
  dat leeg = de lokale cameraverbinding op de node zelf, en dat de node dit
  pas bij een herstart oppikt (zelfde patroon/tekst als bij de
  topic-prefix).

### `mirror_node/main.py`

- Nieuwe module-level env var `MIRROR_CAMERA_SOURCE_ENV = os.environ.get(
  "MIRROR_CAMERA_SOURCE", "")` — terugval, niet de primaire manier van
  instellen. (Vervangt `MIRROR_CAMERA_INDEX` niet per se qua bestaan, maar
  wordt de facto de enige die je in de praktijk ooit zou zetten, en dan nog
  alleen als noodgreep zonder bereikbare backend.)
- `main()` haalt bij opstarten, ná de bestaande `fetch_topic_prefix`-call,
  `mirror_camera_source` op via een NIEUWE, eigen functie
  `fetch_mirror_camera_source(backend_url, fallback, fetch=None, timeout=3)`
  in `shared/topic_prefix.py` — zelfde vorm/fail-safe-patroon als
  `fetch_topic_prefix`, maar een eigen, kleine functie in plaats van die
  ene functie te verbreden. Dat kost een tweede (goedkope, eenmalige)
  `GET /api/node-config`-aanroep bij opstarten in plaats van de twee velden
  in één request te delen, maar houdt `fetch_topic_prefix` zelf — en
  `scare_node`, die 'm ongewijzigd blijft gebruiken — volledig onaangeroerd
  en al-geteste. Twee kleine, gelijkvormige functies in plaats van één
  generieke; bij een derde veld is een gedeelde helper de moeite waard, nu
  nog niet.
- Nieuwe functie `_open_camera(source)` (module-level, dus apart
  testbaar zonder de rest van `main()` te draaien):
  ```python
  def _open_camera(source):
      if not source:
          return cv2.VideoCapture(CAMERA_INDEX)  # bestaand gedrag
      try:
          return cv2.VideoCapture(int(source))
      except ValueError:
          return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
  ```
  Gebruikt door zowel `main()` als `selfcheck()` (die laatste kan zo een
  netwerkcamera ook los testen, zonder de hele node te starten).
- **Reconnect bij aanhoudende faalpogingen** in de hoofdloop: een lokale USB-
  camera geeft bij een gemiste read meestal vanzelf weer een goed frame; een
  netwerkstream die wegvalt niet — `cap.read()` blijft dan `False` geven tot
  de verbinding actief opnieuw wordt geopend. Na een reeks mislukte reads
  (bijv. 30 op rij, ≈15s bij de bestaande `time.sleep(0.5)`) doet de loop
  `cap.release()` + `cap = _open_camera(camera_source)` opnieuw. Werkt ook
  als (kleine) extra robuustheid voor de bestaande lokale-cameracasus (bijv.
  een kabel die eventjes los zat).

## Data flow

**Camera-bron instellen**
1. Gebruiker vult een RTSP-URL in op `/settings`, slaat op.
2. `PUT /api/settings` valideert (leeg/getal/`rtsp(s)`/`http(s)`-prefix),
   persisteert.
3. Gebruiker herstart `mirror_node` — die haalt bij opstarten de nieuwe
   bron op via `GET /api/node-config` en verbindt ermee via `_open_camera`.

**Netwerkstream valt weg tijdens een sessie**
1. `cap.read()` blijft `False` teruggeven, elke keer gelogd als waarschuwing
   (bestaand gedrag, ongewijzigd).
2. Na de faaldrempel: `cap.release()` + `_open_camera(...)` opnieuw — als de
   camera/het netwerk inmiddels hersteld is, komt de stream vanzelf weer op
   gang; zo niet, dan blijft de node het gewoon periodiek blijven proberen
   (zelfde fail-safe-filosofie als de MQTT-reconnect elders in dit project).

## Foutafhandeling

- `PUT /api/settings` met een ongeldige `mirror_camera_source` (niet leeg,
  geen geldig getal, begint niet met `rtsp://`/`http(s)://`): `400`,
  duidelijke Nederlandse melding, niets weggeschreven.
- Camera-bron onbereikbaar bij opstarten (verkeerd wachtwoord, netwerk down,
  camera uit): `_open_camera` faalt niet hard — `cv2.VideoCapture(...)`
  retourneert een object waarvan `cap.isOpened()` `False` is; de bestaande
  `if not cap.isOpened(): logger.error(...); return`-check in `main()`
  vangt dit al af voor de allereerste keer opstarten. De reconnect-lus vangt
  het geval op waarbij de bron *tijdens* een sessie wegvalt.
- Backend onbereikbaar bij het ophalen van `mirror_camera_source` bij
  opstarten: terugval op `MIRROR_CAMERA_SOURCE`-env-var (default leeg =
  lokale index), zelfde patroon/risico-afweging als de topic-prefix.

## Testen

- `shared/topic_prefix.py`: `fetch_mirror_camera_source` krijgt dezelfde
  testdekking als het bestaande `fetch_topic_prefix` (succesvol antwoord,
  onbereikbare backend, ongeldig/non-JSON antwoord, ontbrekend veld —
  allemaal terugval).
- `mirror_node/main.py`: `_open_camera` is puur en testbaar met een
  gemockte `cv2.VideoCapture` — lege bron → lokale index, numerieke string
  → lokale index (als int), URL-string → `cv2.VideoCapture(url,
  cv2.CAP_FFMPEG)`.
- De reconnect-lus zelf blijft, zoals de rest van de hoofdloop nu ook al,
  handmatig getest op locatie — consistent met hoe dit project I/O-gebonden
  loops behandelt (zie eerdere specs).
- Backend: `mirror_camera_source` in `RuntimeSettings`/`app_settings`/
  `/api/settings`/`/api/node-config` volgt exact dezelfde teststructuur als
  `mqtt_topic_prefix` eerder kreeg (round-trip, validatie-afwijzing,
  migratietest voor de nieuwe kolom op een bestaande tabel).

## Migratie (impact op bestaand werk)

- `README.md`: `MIRROR_CAMERA_SOURCE` toevoegen aan de "Alleen mirror-node"
  env-var-tabel, met dezelfde soort toelichting als bij
  `MQTT_TOPIC_PREFIX` (terugval, normaal gesproken bepaalt de
  Instellingen-pagina dit). `MIRROR_CAMERA_INDEX` blijft bestaan voor wie
   'm toch wil zetten, maar wordt in de doc niet meer als primaire weg
  gepresenteerd.
- `shared/topic_prefix.py` krijgt er een tweede, kleine functie bij
  (`fetch_mirror_camera_source`) naast de bestaande `fetch_topic_prefix` —
  geen nieuw bestand, geen wijziging aan de bestaande functie of aan
  `scare_node/main.py`.
