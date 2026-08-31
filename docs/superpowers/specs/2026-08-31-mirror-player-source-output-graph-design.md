# Mirror-graaf: Player/Source/Trigger/Output — Design

## Doel

De net opgeleverde graaf (Scene + Trigger, met Outputs als losse
beheerpagina) wordt uitgebreid tot een echte 4-knooptype-flow, direct
gevraagd na het eerste gebruik van de vorige uitbreiding:

1. **Scene wordt Player** (volledige hernoeming, overal: tabellen,
   routes, types, MQTT-payload, UI) — een player heeft playout-
   instellingen (effect/overlay, zoals nu) plus nieuwe afspeel-
   instellingen (eenmaal / eenmaal herhalen / doorlopen zolang een
   sensor actief is).
2. **Source wordt een eigen knooptype**: een camerastream of een
   statische afbeelding, losgekoppeld van Output. Eén source kan
   meerdere players voeden; een player heeft precies één source.
3. **Trigger** blijft functioneel ongewijzigd (altijd/beweging/
   tijdschema/HA-sensor), maar ontspringt voortaan aan een naambare
   aftakking (branch) op een player in plaats van aan de player zelf.
4. **Output wordt ook een knooptype in de graaf** (naast de bestaande
   beheerpagina, die blijft bestaan als registratie van fysieke
   schermen). Een output-knoop kan meerdere inkomende verbindingen
   hebben; bij gelijktijdigheid wint de laatst binnengekomen.
5. **Aftakkingen (branches)**: in een player-element kun je, via zijn
   instellingen, genoemde uitgaande punten aanmaken. Elke aftakking
   verschijnt als een sleepbare dot op de knoop-vorm, en kan naar een
   Trigger óf rechtstreeks naar een Output gesleept worden. De naam is
   puur een label voor overzicht, geen technische betekenis.
6. **Sources-pagina**: nieuwe beheerpagina, symmetrisch met de
   bestaande Outputs-pagina.

## Architectuur — samenvatting

- `scenes` → `players`, volledig hernoemd (tabel, kolommen waar
  relevant, routes `/api/scenes` → `/api/players`, frontend-types,
  MQTT-payloadveld `scenes` → `players`). Verliest `output_id` (dat
  concept verhuist naar branches/output_connections); wint `source_id`,
  `playback_mode`, `repeat_while_ha_entity_id`.
- Nieuwe `sources`-tabel: naam, kind (`camera_stream`/`static_image`),
  waarde. Bestaande `outputs.camera_source` migreert hierheen als
  eerste, automatisch aangemaakte source.
- Nieuwe `player_branches`-tabel: de naambare aftakkingen. Elke player
  krijgt bij migratie automatisch één standaard-branch, zodat bestaande
  triggers ergens vandaan blijven komen zonder dat de gebruiker iets
  hoeft te doen.
- `triggers`-tabel: `from_scene_id` → `from_branch_id` (wijst nu naar
  een branch, niet meer rechtstreeks naar een player), `to_scene_id` →
  `to_player_id`. Verder ongewijzigd (kind/schedule/ha_entity_id/
  priority/canvas-positie/naam/kleur).
- `outputs`-tabel: verliest `camera_source` (naar sources gemigreerd),
  wint `canvas_x`/`canvas_y` — elke output-rij is voortaan meteen ook
  zijn eigen knoop in de graaf, geen aparte node-tabel nodig.
- Nieuwe `output_connections`-tabel: koppelt een branch rechtstreeks
  aan een output (playout-routing, geen Trigger ertussen). Bij
  migratie krijgt elke player's standaard-branch automatisch zo'n
  koppeling naar de (ene, bestaande) output, zodat alles na migratie
  gewoon op het scherm blijft verschijnen.
- Runtime (mirror_node): de bestaande resolve-lus (welke player is
  actief, welke trigger vuurt) blijft ongewijzigd van opzet. Nieuw is
  een "nog bezig"-gate vóór trigger-evaluatie: zolang een player's
  `playback_mode` nog niet is voldaan (once: nog niet 1x afgespeeld;
  repeat_once: nog niet 2x; repeat_while: sensor staat nog aan — een
  bewust *niveau*-gebaseerd mechanisme, in tegenstelling tot de
  puls-gebaseerde triggers), worden zijn uitgaande triggers genegeerd.
  Zodra voldaan, evalueren triggers zoals altijd.
- Output-routing loopt via MQTT: zodra de actieve player wisselt en
  diens (default- of gekozen) branch een `output_connections`-rij
  heeft, publiceert de backend welke player nu bij die output hoort.
  Laatste bericht wint.

## Datamodel

### `sources`-tabel (nieuw)

```sql
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'camera_stream',
    value TEXT NOT NULL DEFAULT '',
    canvas_x REAL NOT NULL DEFAULT 0,
    canvas_y REAL NOT NULL DEFAULT 0
)
```

`kind` is `'camera_stream'` (waarde = camera-URL, zoals de huidige
`camera_source`) of `'static_image'` (waarde = pad naar een media-
bestand, zelfde media-opslag als scene-overlays gebruiken).

Migratie (idempotent, zelfde `PRAGMA user_version`-gate-patroon als de
vorige twee graaf-migraties): als er nog geen enkele source bestaat,
maak er één aan met `kind='camera_stream'`, `value` = de huidige
(enige) `outputs.camera_source`, `name` = `"<output-naam> camera"`.
Canvas-positie: naast de bestaande output geplaatst (vaste offset).

### `player_branches`-tabel (nieuw)

```sql
CREATE TABLE IF NOT EXISTS player_branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    name TEXT NOT NULL DEFAULT 'Uitgang 1'
)
```

Geen eigen canvas-positie: de frontend rendert de dots gelijkmatig
verdeeld op de rechterrand van de player-knoop, op basis van hoeveel
branches er zijn (React Flow meerdere source-handles per node,
identiek qua patroon aan de bestaande enkele output-handle).

Migratie: voor elke bestaande scene/player precies één branch
aanmaken, naam `"Uitgang 1"`.

### `players`-tabel (hernoemd van `scenes`)

```
ALTER TABLE scenes RENAME TO players
```

Nieuwe kolommen (via `_ensure_column`):

```
_ensure_column(conn, "players", "source_id", "INTEGER")
_ensure_column(conn, "players", "playback_mode", "TEXT")
_ensure_column(conn, "players", "repeat_while_ha_entity_id", "TEXT")
```

`playback_mode` is `'once'` | `'repeat_once'` | `'repeat_while'`,
default `'once'` bij migratie (komt overeen met hoe scare-video's nu al
werken). `repeat_while_ha_entity_id` is alleen relevant bij
`playback_mode='repeat_while'`.

`output_id`-kolom (uit de vorige migratie) wordt bij deze migratie
losgelaten als bron van waarheid voor playout-routing (die loopt nu
via branches/output_connections) — de kolom zelf hoeft niet
verwijderd te worden (SQLite `DROP COLUMN` is duurder dan nodig; hij
blijft ongebruikt staan, net zoals `app_settings.mirror_camera_source`
dat nu al doet). Bij migratie krijgt elke player zijn `source_id`
gezet naar de zojuist aangemaakte default-source.

`create_player_route`/`update_player_route` (hernoemd van
`create_scene_route`/`update_scene_route`) krijgen `source_id`
optioneel (default: de eerste/enige source), `playback_mode` verplicht
met default `'once'`, `repeat_while_ha_entity_id` optioneel (alleen
zinvol bij `playback_mode='repeat_while'`, niet hard afgedwongen op
API-niveau — een player zonder ingevulde sensor bij repeat_while
gedraagt zich dan gewoon als een player die nooit "klaar" is, tot de
gebruiker alsnog een sensor kiest).

### `triggers`-tabel — kolommen hernoemd

```
ALTER TABLE triggers RENAME COLUMN from_scene_id TO from_branch_id
ALTER TABLE triggers RENAME COLUMN to_scene_id TO to_player_id
```

`from_branch_id` wijst nu naar `player_branches.id` in plaats van
rechtstreeks naar een player. Verder ongewijzigd: `kind`,
`schedule_from`, `schedule_until`, `ha_entity_id`, `priority`,
`canvas_x`/`canvas_y`, `name`, `color`. Migratie: elke bestaande
trigger's `from_scene_id`-waarde wordt opgezocht in de zojuist
aangemaakte `player_branches` (via `player_id`) en vervangen door de
bijbehorende branch-id — elke player heeft op dit punt in de migratie-
volgorde precies één branch, dus deze koppeling is ondubbelzinnig.

### `outputs`-tabel — kolomwijziging

```
_ensure_column(conn, "outputs", "canvas_x", "REAL")
_ensure_column(conn, "outputs", "canvas_y", "REAL")
```

`camera_source`-kolom blijft ongebruikt staan (zelfde reden als
`players.output_id` hierboven — niet droppen, wel niet meer lezen).
Migratie: de bestaande (enige) output krijgt een canvas-positie
rechts van de players geplaatst.

### `output_connections`-tabel (nieuw)

```sql
CREATE TABLE IF NOT EXISTS output_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    output_id INTEGER NOT NULL,
    from_branch_id INTEGER NOT NULL
)
```

Migratie: voor elke player's standaard-branch (uit de
`player_branches`-migratie) één rij aanmaken die naar de (ene,
bestaande) output wijst.

### Backend-routes

- `admin/app/routers/scenes.py` → `admin/app/routers/players.py`
  (routepad `/api/scenes` → `/api/players`), CRUD-vorm ongewijzigd,
  uitgebreid met `source_id`/`playback_mode`/
  `repeat_while_ha_entity_id`. `delete_player_route` ruimt bij
  verwijdering ook de player's `player_branches`-rijen op (en via
  cascade in code, niet DB-FK: bijbehorende `triggers`- en
  `output_connections`-rijen die naar die branches verwezen).
- Nieuwe `admin/app/routers/sources.py`: `GET/POST /api/sources`,
  `PUT/DELETE /api/sources/{id:int}` — zelfde CRUD-vorm als
  outputs/players. `DELETE` op een source die nog players heeft, wordt
  geweigerd (400), zelfde patroon als outputs vandaag.
- Nieuwe `admin/app/routers/player_branches.py` (of toegevoegd aan
  `players.py` als sub-resource, implementatiedetail voor het plan):
  `GET /api/players/{player_id:int}/branches`,
  `POST /api/players/{player_id:int}/branches` (naam),
  `PUT/DELETE /api/branches/{id:int}`. `DELETE` op een branch die nog
  triggers of output_connections heeft, wordt geweigerd (400) — eerst
  ontkoppelen, dan verwijderen (zelfde "geen impliciete cascade"-
  conventie als outputs).
- `admin/app/routers/outputs.py`: uitgebreid met `canvas_x`/
  `canvas_y` in de CRUD-payload (voor de graaf-canvas-positie); verder
  ongewijzigd qua vorm.
- Nieuwe `admin/app/routers/output_connections.py` (of sub-resource
  op outputs): `POST /api/output-connections` (`output_id`,
  `from_branch_id`), `DELETE /api/output-connections/{id:int}`. Geen
  `PUT` nodig — een verbinding wijzig je door 'm te verwijderen en
  opnieuw te slepen, zelfde patroon als triggers vandaag als je van
  bron verandert.
- `publish_graph(db, bridge)`: payload wordt
  `{"output_id": ..., "players": [...], "sources": [...],
  "branches": [...], "triggers": [...], "output_connections": [...],
  "root_player_id": ...}`. Elk `players`-item bevat zijn
  `source_id`/`playback_mode`/`repeat_while_ha_entity_id`.

## Runtime-gedrag (mirror_node)

`mirror_node/scenes.py` wordt `mirror_node/players.py` (hernoeming
consistent met de rest). `PlayerGraph.resolve(...)` krijgt, naast de
bestaande parameters, een `playback_done: bool` per aangeroepen
player-context — of preciezer: de resolve-functie krijgt de huidige
player's playback-status (hoeveel keer al afgespeeld, of de
repeat_while-sensor nog actief is) als extra argument, en telt een
player pas als "klaar om over te schakelen" als aan zijn
`playback_mode`-voorwaarde is voldaan. Zolang niet voldaan, worden
diens uitgaande triggers simpelweg niet geëvalueerd (dezelfde
resolve-lus, met deze extra gate ervóór).

**Puls versus niveau, expliciet**: `repeat_while` is bewust
niveau-gebaseerd (loopt door zolang de sensor "aan" rapporteert, stopt
zodra hij weer "uit" gaat) — dit stuurt de *afspeelduur* van een
player, niet het vuren van een trigger. Dit is een ander mechanisme
dan de bestaande HA-sensor-*trigger* (die juist puls/stijgende-flank-
gebaseerd blijft, exact zoals nu, om de eerder gefixte Critical-bug
— een aanhoudend "aan"-signaal dat een scare-video oneindig laat
herhalen — niet opnieuw te introduceren). Beide mechanismen bestaan
naast elkaar met bewust tegenovergestelde semantiek voor twee
verschillende doelen.

**Source-resolutie**: een player kijkt zijn `source_id` op, haalt de
bijbehorende `sources`-rij op. Bij `kind='camera_stream'`: ongewijzigd
gedrag (huidige `open_camera`-pad). Bij `kind='static_image'`: het
beeld wordt eenmalig geladen (niet elke frame opnieuw van schijf) en
gebruikt als basisbeeld in plaats van een camera-frame — de rest van
de rendering (effect + overlay compositen) is ongewijzigd, dezelfde
`shared/render.py`-pijplijn die het voorbeeldpaneel ook gebruikt.

**Output-routing**: elke fysieke mirror_node-instantie hoort bij
precies één output (zoals nu, één proces). Zodra de actieve player
wisselt, kijkt de backend of de betrokken branch een
`output_connections`-rij heeft; zo ja, publiceert hij (niet-retained,
zelfde patroon als de HA-trigger-puls) welke player nu bij die output
hoort. Bij twee gelijktijdige berichten voor dezelfde output geldt:
laatste wint — geen prioriteitslogica.

## UI-uitwerking

- **Player-knoop** (hernoemd van scene-knoop): rename/kleur ongewijzigd
  (dubbelklik-patroon). Eén input-handle links (source-verbinding),
  rechts één dot per branch (standaard 1). De instellingen-modal
  (bestaande stappen/tabs) krijgt twee nieuwe tabs: "Bron" (dropdown
  met geregistreerde sources) en "Afspelen" (playback_mode-keuze +
  HA-entiteit-dropdown bij repeat_while), plus een sectie "Aftakkingen"
  (lijst van branches, +/hernoem/verwijder — verwijderen geweigerd met
  duidelijke foutmelding als de branch nog een trigger of
  output-verbinding heeft, zelfde patroon als output-verwijdering nu).
- **Source-knoop** (nieuw): klein blokje, naam + icoon naar kind
  (camera/afbeelding), rechts één output-handle. Dropdown in de knoop
  om te kiezen welke geregistreerde source het is (zelfde patroon als
  vandaag al bij scene→output). Slepen naar een player's input-handle
  zet `source_id`.
- **Trigger-knoop**: visueel ongewijzigd. Ontspringt nu aan een
  branch-dot in plaats van de player zelf; verder identiek
  (kind-keuze, HA-entiteit-dropdown, schedule-velden).
- **Output-knoop** (nieuw op canvas, was alleen op de beheerpagina):
  klein blokje, dropdown om te kiezen welk geregistreerd fysiek
  scherm het is. Accepteert meerdere inkomende verbindingen
  rechtstreeks vanaf branch-dots (geen Trigger ertussen) —
  verbindingsvalidatie in `handleConnect` staat dit specifiek toe
  naast de bestaande branch→Trigger-regel.
- **Verbindingsregels** (uitbreiding van de bestaande
  `handleConnect`-validatie): Source-handle → Player-input (zet
  `source_id`) · branch-dot → Trigger-input (bestaand, nu vanaf een
  branch) · branch-dot → Output-input (nieuw, rechtstreeks). Niet
  toegestaan: Output → alles (eindpunt), Source → Source, Trigger →
  Source.
- **Sources-pagina**: nieuwe navigatiepagina, zelfde vormtaal als de
  bestaande Outputs-pagina — inline-bewerkbare lijst (naam, kind,
  waarde), nieuwe-rij-aanmaken, verwijderen geweigerd (met
  foutmelding) als de source nog players heeft.
- **Outputs-pagina**: ongewijzigd qua CRUD-vorm, verliest het
  camera_source-veld uit het formulier (dat hoort nu bij Sources).

## Migratie-volgorde (belangrijk voor de implementatieplanning)

1. `sources`-tabel + default-source-migratie (uit `outputs.camera_source`).
2. `players`-tabel (hernoemd van `scenes`) + nieuwe kolommen
   (`source_id`/`playback_mode`/`repeat_while_ha_entity_id`) + koppel
   bestaande players aan de default-source.
3. `player_branches`-tabel + één standaard-branch per bestaande player.
4. `triggers`-tabel: kolommen hernoemen (`from_branch_id`/
   `to_player_id`) + waarde-migratie naar de zojuist aangemaakte
   branches.
5. `outputs`-tabel: canvas-positie-kolommen + migratie van de
   bestaande output naar een zichtbare graaf-positie.
6. `output_connections`-tabel + één rij per standaard-branch naar de
   bestaande output.
7. Backend-routes herzien: `players.py` i.p.v. `scenes.py`, nieuwe
   `sources.py`, `player_branches`-sub-resource, `output_connections`-
   sub-resource, `outputs.py` uitgebreid met canvas-positie.
8. `publish_graph` herzien naar het nieuwe payload-contract.
9. `mirror_node`: `players.py` (hernoemd van `scenes.py`) met de
   playback_mode-gate, source-resolutie (camera_stream/static_image),
   output-routing-publicatie.
10. Frontend: Player-knoop (rename + tabs + branches), Source-knoop,
    Output-knoop op canvas, nieuwe verbindingsregels, Sources-pagina,
    Outputs-pagina-aanpassing.

## Wat expliciet buiten scope blijft

- Daadwerkelijk meerdere fysieke mirror-node-processen tegelijk laten
  draaien. Het datamodel ondersteunt meerdere outputs met eigen
  routing, maar er wordt nog steeds precies één fysieke spiegel
  gebouwd en getest — zelfde afspraak als de vorige uitbreiding.
  Meerdere Output-knopen tegelijk in de graaf hebben is dus vooral
  alvast-goed-ontworpen, niet volledig end-to-end uitvoerbaar.
- Eigen instellingen per branch buiten de naam (geen voorwaarden, geen
  losse canvas-positie-opslag — automatisch gelijkmatig verdeeld).
- Geavanceerde beeldovergangen/animaties voor statische-afbeelding-
  sources — een los beeld door dezelfde overlay-pijplijn die nu al
  cameraframes verwerkt, niets meer.
- Complexere output-conflictresolutie dan laatste-wint (geen
  prioriteiten, geen wachtrij).
- Uitfaseren/droppen van de nu ongebruikte kolommen
  `players.output_id`, `outputs.camera_source`,
  `app_settings.mirror_camera_source` — blijven ongebruikt in de DB
  staan, geen destructieve schema-opschoning in deze ronde.
