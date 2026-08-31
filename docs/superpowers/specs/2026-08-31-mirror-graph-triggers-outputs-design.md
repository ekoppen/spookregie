# Mirror-graaf: triggers als knoop + outputs — Design

## Doel

De net opgeleverde scenegraaf (scenes als knopen, triggers als eigenschap
van een verbinding) krijgt drie uitbreidingen, direct gevraagd na het
eerste gebruik van de nieuwe node-editor:

1. **Triggers worden een eigen, zichtbaar knooptype** in de graaf (niet
   langer een onzichtbare eigenschap van een lijn), inclusief een nieuwe
   trigger-soort: een Home Assistant-sensor.
2. **Outputs worden een eerste-klas concept**: een fysieke uitgang
   (spiegel/beamer) met een eigen camera-bron, los van een scene. Nu is
   er precies één output; het datamodel is klaar voor meerdere, de
   daadwerkelijke uitvoering van meerdere fysieke mirror-node-processen
   is bewust een latere, aparte stap.
3. **UI-polish**: scenes en triggers kunnen hernoemd en van een kleur
   voorzien worden; er komt een los voorbeeldpaneel dat de admin-backend
   zelf rendert (raakt de fysieke spiegel nooit aan tijdens bewerken).

Een vierde punt — dat klikken op een stap-chip in een scene-knoop niet
werkt — is een mogelijke bug in reeds opgeleverde code, geen ontwerpvraag.
Wordt als eerste implementatiestap live gereproduceerd en gefixt.

## Architectuur — samenvatting

- `scene_edges` wordt herzien tot `triggers`: elke trigger is nu een
  eigen rij met een eigen `kind` (voorheen `trigger_type`), een eigen
  canvas-positie, een optionele naam/kleur, en (nieuw) een
  `ha_entity_id` voor het HA-sensor-type. Een verbinding tussen twee
  scenes is dus altijd `scene → trigger → scene`, twee sprongen.
- Nieuwe `outputs`-tabel: naam + camera-bron. Scenes krijgen een
  `output_id`. Bij migratie ontstaat automatisch één output ("Spiegel"),
  gevuld met de huidige `mirror_camera_source`-instelling, en alle
  bestaande scenes worden eraan gekoppeld.
- HA-sensor-triggers vereisen een nieuw achtergrondmechanisme in de
  backend: periodiek pollen van gekoppelde HA-entiteiten, en bij een
  *stijgende flank* (niet-`on` → `on`/`detected`) een eenmalige puls
  naar de mirror-node sturen — exact dezelfde puls-niet-niveau-regel als
  bewegingsdetectie (zie de recente Critical-1-fix: een aanhoudend
  "aan"-signaal zou dezelfde scare-video oneindig laten herhalen).
- Het voorbeeldpaneel wordt gevuld door de backend zelf: één frame van
  de gekozen output's camera-bron ophalen, het effect + overlay van de
  concept-scene erover renderen (dezelfde rendercode als de mirror-node,
  hergebruikt in de backend), en dat beeld terugsturen — zonder ooit
  `control/mirror/scene-preview` of de fysieke installatie aan te raken.

## Datamodel

### `outputs`-tabel (nieuw)

```sql
CREATE TABLE IF NOT EXISTS outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    camera_source TEXT NOT NULL DEFAULT ''
)
```

Migratie (idempotent, zelfde `PRAGMA user_version`-patroon als de vorige
graaf-migratie — zie de les uit de vorige feature over
edge-count-als-gate die faalt op een verse installatie):

- Als er nog geen enkele output bestaat: maak er één aan, naam
  `"Spiegel"`, `camera_source` = de huidige waarde van
  `app_settings.mirror_camera_source`.
- `app_settings.mirror_camera_source` blijft in de DB staan (geen
  destructieve wijziging), maar wordt niet meer gelezen/getoond op de
  Instellingen-pagina — de output is voortaan de bron van waarheid.

### `scenes`-tabel — nieuwe kolommen

```
_ensure_column(conn, "scenes", "output_id", "INTEGER")
_ensure_column(conn, "scenes", "color", "TEXT")
```

Migratie: elke bestaande scene zonder `output_id` krijgt de zojuist
aangemaakte default-output toegewezen. `color` blijft `NULL` (frontend
toont dan een neutrale standaardkleur).

`create_scene_route`/`update_scene_route` (backend) krijgen `output_id`
verplicht (default: de eerste/enige output als er geen expliciet
gekozen is) en `color` optioneel.

### `scene_edges` → `triggers` (hernoemd + uitgebreid)

```sql
CREATE TABLE IF NOT EXISTS triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_scene_id INTEGER NOT NULL,
    to_scene_id INTEGER,
    kind TEXT,
    schedule_from TEXT,
    schedule_until TEXT,
    ha_entity_id TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    canvas_x REAL NOT NULL DEFAULT 0,
    canvas_y REAL NOT NULL DEFAULT 0,
    name TEXT,
    color TEXT
)
```

Migratie: hernoem de bestaande `scene_edges`-tabel naar `triggers` via
`ALTER TABLE scene_edges RENAME TO triggers`, voeg de nieuwe kolommen
toe met `_ensure_column`, en hernoem de kolom `trigger_type`→`kind`,
`trigger_from`→`schedule_from`, `trigger_until`→`schedule_until` via
`ALTER TABLE triggers RENAME COLUMN ...` (SQLite ondersteunt dit sinds
3.25 — geverifieerd nodig, val terug op een table-rebuild als de
draaiende SQLite-versie dit niet ondersteunt). `canvas_x`/`canvas_y`
krijgen bij migratie een berekende default: het midden tussen
`from_scene`'s en (indien aanwezig) `to_scene`'s positie, anders
`from_scene`'s positie + een vaste offset.

**Live-regel, ongewijzigd qua strekking maar herzien qua velden:** een
trigger telt alleen mee in de evaluatie van de mirror-node als zowel
`to_scene_id` als `kind` gezet zijn — een lege output-stub (nog geen
doel) of een net aangemaakte, nog niet geconfigureerde trigger-knoop
wordt genegeerd.

`kind` krijgt een vierde geldige waarde naast `always`/`motion`/
`schedule`: `ha_sensor`. Bij `kind = 'ha_sensor'` is `ha_entity_id`
verplicht; bij `kind = 'schedule'` blijven `schedule_from`/
`schedule_until` verplicht, zoals nu.

### Backend-routes

`admin/app/routers/scene_edges.py` wordt `admin/app/routers/triggers.py`
(bestandsnaam + routepad `/api/triggers`, zelfde CRUD-vorm als nu:
`GET/POST /api/triggers`, `PUT/DELETE /api/triggers/{id:int}`), met de
uitgebreide velden. `PUT` valideert bij `kind='ha_sensor'` dat
`ha_entity_id` een niet-lege string is (geen verificatie tegen HA zelf
nodig — een tijdelijk onbereikbare entiteit mag je best alvast
invoeren).

Nieuwe `admin/app/routers/outputs.py`: `GET/POST /api/outputs`,
`PUT/DELETE /api/outputs/{id:int}` — zelfde CRUD-vorm als scenes/
triggers. `DELETE` op een output die nog scenes heeft, wordt geweigerd
(400) — een output moet eerst leeg zijn, geen impliciete cascade-delete
van scenes.

`publish_graph(db, bridge)` (bestaand) filtert voortaan op één output
(voorlopig: de eerste/enige — een `output_id`-parameter wordt
toegevoegd aan de functie-signatuur zodat een toekomstige
multi-output-uitrol 'm per output kan aanroepen, maar er is nu maar één
aanroeppunt). Het gepubliceerde payload krijgt een `output_id`-veld
erbij: `{"output_id": ..., "scenes": [...], "triggers": [...],
"root_scene_id": ...}` (het veld `edges` in het bestaande contract
wordt `triggers` genoemd, consistent met de hernoemde tabel).

## HA-sensor-triggers: vuurmechanisme

Nieuwe achtergrondtaak in de admin-backend (een `asyncio`-taak of een
losse polling-thread, consistent met hoe de bestaande `Scheduler` al
periodiek werkt): elke N seconden (voorstel: 5s — snel genoeg voor een
scare-effect, niet zo snel dat het HA onnodig belast) `GET
/api/ha/states` aanroepen (bestaande `ha_client.get_states`), en voor
elke `ha_entity_id` die ergens in een `triggers`-rij met
`kind='ha_sensor'` voorkomt, de laatst geziene `state`-waarde
vergelijken met de nieuwe. Bij een overgang naar `"on"`/`"detected"`
(niet: blijft al op `"on"` staan) publiceert de backend een nieuwe,
niet-retained MQTT-boodschap:

```
control/mirror/ha-trigger   payload: {"entity_id": "binary_sensor.tuin_beweging"}
```

`mirror_node/main.py` abonneert zich hierop, en houdt — net als het
bestaande `test_trigger_requested`-patroon (`threading.Event`) — een
klein setje recent-gevuurde entity-ids bij dat precies één camera-frame
lang geldig is. `SceneGraph.resolve()` krijgt een derde parameter naast
`motion_active`/`now_hhmm`: `fired_ha_entities: frozenset[str]` (leeg op
de meeste frames). `_edge_matches` (binnenkort mogelijk hernoemd naar
`_trigger_matches`, consistent met de tabelnaam) krijgt een tak voor
`kind == "ha_sensor"`: `edge["ha_entity_id"] in fired_ha_entities`.

**Foutafhandeling:** als HA onbereikbaar is, blijft `get_states()` (al
bestaand gedrag) een lege lijst teruggeven — geen crash, simpelweg geen
HA-triggers vuren totdat HA weer bereikbaar is. Er komt geen aparte
foutmelding op de scene-graaf-pagina hiervoor (dat hoort al thuis in de
generieke node/verbindingsstatus die de admin-UI al toont).

## Voorbeeldpaneel (server-side render, geen hardware-aanraking)

`mirror_node/overlay.py`'s rendercode (effect toepassen + overlay
compositen) wordt verplaatst naar `shared/render.py` (een nieuwe,
gedeelde module zonder OpenCV-camera-afhankelijkheden anders dan de
pure beeldbewerking), zodat zowel `mirror_node/main.py` als de
admin-backend 'm kunnen aanroepen. Nieuwe route:

```
POST /api/scenes/preview-frame
body: SceneDraft (dezelfde vorm als create/update)
response: image/jpeg (binary)
```

Implementatie: backend haalt één frame op van de camera-bron die bij
`SceneDraft.output_id` hoort (hergebruikt de bestaande
camera-fetch-logica die `OverlayCanvas`/`MediaLibrary` al voor
livebeeld gebruiken), past `shared/render.py`'s render-functie toe met
de concept-instellingen (effect, params, overlay, scale, position), en
geeft het resultaat als JPEG terug. Geen MQTT, geen mirror-node, geen
retained state — een pure, stateless request/response.

Frontend: een "Preview"-knop in `SceneWizardModal` (en/of op de
canvas-knoop) opent een los paneel (niet-blokkerende modal/zijpaneel)
met een `<img>` die naar deze route wijst, ververst bij elke wijziging
in de concept-instellingen (zelfde 150ms-throttle-patroon als de
bestaande live-preview, alleen nu request/response i.p.v. MQTT-push).

## UI-uitwerking

- **Hernoemen**: dubbelklikken op de naam van een scene- of
  trigger-knoop maakt er een tekstveld van; Enter of wegklikken slaat
  op via de bestaande update-route van die entiteit.
- **Kleur**: een klein rond swatch-knopje op elke knoop opent een vast
  palet van 8 kleuren (geen vrije kleurenkiezer). Gekozen kleur kleurt
  de rand/achtergrond van de knoop op de canvas.
- **Trigger-knoop**: visueel een klein blokje op de lijn tussen twee
  scenes (zelfde stijl-taal als een scene-knoop, kleiner). Aanklikken
  opent het uitgebreide trigger-paneel (voorheen `EdgeTriggerPopover`,
  nu bruikbaar als de "instellingen" van een echte knoop i.p.v. een
  lijn-klik): keuze uit beweging/tijdschema/altijd/HA-sensor, en bij
  HA-sensor een dropdown met entiteiten opgehaald via `/api/ha/states`
  (gefilterd op `domain == "binary_sensor"` als eerste, praktische
  filter — andere domeinen blijven via een "toon alles"-toggle
  bereikbaar, voor het geval iemand toch een andere entiteitssoort wil
  koppelen).
- **Outputs-pagina**: nieuwe navigatie-pagina, lijst met outputs
  (naam + camera-bron), simpele +/bewerk/verwijder-CRUD, zelfde
  vormtaal als de Instellingen-pagina. Instellingen-pagina verliest het
  `mirror_camera_source`-veld.
- **Scene-knoop toont voortaan ook zijn output-naam en kleur** (klein
  label/badge), zodat je bij meerdere outputs in één oogopslag ziet
  welke scene bij welke fysieke uitgang hoort.

## Migratie-volgorde (belangrijk voor de implementatieplanning)

1. `outputs`-tabel + default-output-migratie (uit `mirror_camera_source`).
2. `scenes.output_id`/`scenes.color` + koppel bestaande scenes aan de
   default-output.
3. `scene_edges` → `triggers` hernoemen + nieuwe kolommen + waarde-
   migratie van `trigger_type`/`trigger_from`/`trigger_until`.
4. Backend-routes herzien (scenes met output_id/color,
   `triggers.py` i.p.v. `scene_edges.py`, nieuwe `outputs.py`).
5. HA-trigger-pollingtaak + MQTT-puls + mirror-node-consumptie.
6. `shared/render.py`-extractie + preview-frame-route.
7. Frontend: hernoemen/kleur, trigger-knoop-visual + uitgebreid paneel,
   Outputs-pagina, voorbeeldpaneel.
8. Klik-op-stap-bug: reproduceren en fixen (los, vroeg in de
   implementatie, voordat er verder op hetzelfde canvas-component
   gebouwd wordt).

## Wat expliciet buiten scope blijft

- Daadwerkelijk meerdere fysieke mirror-node-processen tegelijk laten
  draaien, elk gekoppeld aan een eigen output. Nu blijft er precies één
  proces; de graaf die gepubliceerd wordt, is impliciet "voor de enige
  output die er is". Multi-proces-uitvoering is een aparte, latere
  spec.
- Een volledige kleurenkiezer (vrije hex-waarde) — het vaste palet van
  8 kleuren is voldoende voor "onderscheid maken".
- HA-triggers op basis van een specifieke state-waarde (bijv.
  temperatuur > 20) — alleen de aan/uit-vorm (`on`/`detected`) wordt nu
  ondersteund.
