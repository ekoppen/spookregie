# Mirror-scenegraaf (node-editor) — Design

**Datum:** 2026-08-31
**Status:** Goedgekeurd, klaar voor implementatieplan
**Vervolg op:** `2026-08-30-mirror-scenes-design.md`

## Doel

De net gebouwde scenes zijn een platte, prioriteit-geordende lijst: de
mirror-node scant elke frame van boven naar beneden en de eerste scene
met een matchende trigger wint — stateless, geen geheugen van "waar we
nu zijn". De gebruiker wil een echte **flow tussen scenes** kunnen
bouwen: bijvoorbeeld één continue "mirror"-scene met drie verschillende
triggers die elk naar een eigen, andere scare-scene leiden, en na
afloop weer terug. Dat is met een prioriteitslijst niet uit te
drukken zodra het gedrag van de huidige toestand afhangt (een scare
die specifiek naar een ándere scare leidt, niet terug naar de basis).

Dit maakt scenes tot knopen in een **graaf**: elke scene krijgt eigen,
losse uitgaande verbindingen ("outputs"), elk met een eigen trigger en
een doel-scene. De mirror-node onthoudt welke scene nu actief is en
controleert alleen de uitgaande verbindingen van díe scene. Bewerkt
wordt via een sleepbare node-editor op het Dashboard (vervangt de
scene-kaarten-grid), naar het interactiemodel van
callcenter-routeringssoftware (genoemd door de gebruiker, bijv. Siemens
ProCenter): een node toont zijn outputs, inclusief lege (nog niet
gekoppelde); een lege output slepen naar een andere node koppelt 'm;
een gekoppelde-maar-nog-niet-getriggerde lijn stel je in door op de
doelnode (of de lijn) te klikken.

Dit is een aanzienlijk grotere wijziging dan de vorige scenes-feature
zelf — een nieuw datamodel, een herschreven mirror-node-evaluatie, en
een compleet nieuw frontend-component (waarschijnlijk met een
node-editor-library als nieuwe dependency).

## Niet-doelen

- **Geen automatische migratie van complexe bestaande prioriteitslijsten
  naar een equivalente graaf.** De huidige live installatie heeft op
  dit moment precies één scene ("Basis", altijd-trigger) — de
  migratieregel hieronder dekt het praktische geval (N
  trigger-scenes + 1 basis-scene) expliciet, niet elke denkbare
  historische lijst.
- **Geen validatie die afdwingt dat elke scare-scene een terugpad
  heeft.** Een scene zonder (volledig geconfigureerde) uitgaande
  verbinding blijft na afloop simpelweg "hangen" (geen nieuwe
  render, geen crash) tot de gebruiker het bewerkt — de graaf mag
  bewust half bekabeld zijn tijdens het opbouwen, zonder dat de
  live installatie stukgaat. De editor mag dit als visuele hint tonen
  (bijv. een node zonder outputs anders kleuren), maar blokkeert niets.
- **Geen automatisch onderscheid tussen meerdere gelijktijdig
  matchende triggers van hetzelfde type vanaf dezelfde node.** Twee
  "motion"-outputs zonder onderscheidende voorwaarde (bijv. een
  tijdvenster) vanaf dezelfde node zijn ambigu — eerste in
  prioriteit-volgorde (per node, net als scenes dat eerder globaal
  hadden) wint, de tweede is dan onbereikbaar. Dat is de
  verantwoordelijkheid van de gebruiker (geef ze een onderscheidend
  tijdvenster), geen linting in v1.
- **Geen ondersteuning voor meerdere gelijktijdig-actieve
  "huidige" scenes.** Precies één mirror-node-instantie, precies één
  huidige-scene-toestand — geen parallelle takken.
- **Canvas-positie (`canvas_x`/`canvas_y`) is puur een editor-aangelegenheid.**
  Wordt opgeslagen zodat de layout blijft staan, maar nooit naar de
  mirror-node gepubliceerd — die heeft er niets aan.
- **Geen wijziging aan de bestaande trigger-tijdvenster-semantiek**
  (`_time_in_window`, middernacht-doorloop) — die verhuist ongewijzigd
  van scene-niveau naar edge-niveau.

## Architectuur

**Kernbegrip-wijziging:** de trigger-velden (`trigger_type`,
`trigger_from`, `trigger_until`) en de globale `order_index` verdwijnen
van Scene — die beschrijven nu een **verbinding (edge)**, niet een
scene. Een Scene blijft verder exact wat 'ie was (bron + regie + doel:
`source_mode`, `effect`, `params`, `overlay_hash`, `scale`, `position`,
`canvas_size`, `source_scale`, `source_position`), plus twee nieuwe
velden: `is_root` (precies één scene is het startpunt) en
`canvas_x`/`canvas_y` (positie in de editor).

```
Scene:
  id, name, source_mode, effect, params, overlay_hash, scale, position,
  canvas_size, source_scale, source_position   # ongewijzigd
  is_root: bool                                 # nieuw
  canvas_x, canvas_y: float                      # nieuw, editor-only

SceneEdge:
  id, from_scene_id
  to_scene_id: int | null        # null = lege output-stub, nog niet gekoppeld
  trigger_type: "motion" | "schedule" | "always" | null   # null = nog niet ingesteld
  trigger_from, trigger_until: str | null   # alleen bij "schedule"
  priority: int                  # volgorde tussen de outputs van dezelfde from_scene_id
```

Een edge is pas **live** (telt mee in de mirror-node-evaluatie) zodra
`to_scene_id` én `trigger_type` allebei gezet zijn. Een lege output-stub
of een gekoppelde-maar-ongetriggerde lijn wordt door de mirror-node
genegeerd — veilig om tussentijds op te bouwen.

**Evaluatie op de mirror-node (state machine, vervangt de stateless
`SceneEngine`):**

```
┌─────────────────────────────────────────────┐
│ SceneGraph (mirror_node/scenes.py)              │
│  scenes: {id: scene}                             │
│  edges: {from_scene_id: [live edges, by prio]}     │
│  root_scene_id                                      │
│  current_scene_id  <-- state, overleeft frames         │
└─────────────────────┬───────────────────────┘
                       │ elke frame:
                       │ 1. is current_scene_id onbekend? -> reset naar root
                       │ 2. loop edges[current_scene_id] in prioriteit-volgorde,
                       │    eerste match -> current_scene_id = edge.to_scene_id
                       │ 3. geef (scenes[current_scene_id], transitioned) terug
                       ▼
                 render / scare-video-afspelen
```

**Waarom "current-node-relatief" i.p.v. globaal:** dit is precies wat
een graaf van een lijst onderscheidt — welke triggers er nu toe doen
hangt af van waar je bent. Een scare-scene hoeft alleen te reageren op
zíjn eigen terugpad (typisch één "altijd"-output naar de basis), niet
op de triggers van andere scenes. Dit elimineert ook de "zwart beeld
na afloop van een scare"-klasse bugs die de vorige feature met een
losse re-resolve-hack moest oplappen: omdat een scare-video-afspeel
blokkerend is, is de eerstvolgende `resolve()`-aanroep na afloop
automatisch de eerste kans om de terug-edge te volgen — geen apart
"staart van het venster"-geval meer nodig.

**`transitioned`-vlag:** `resolve()` geeft niet alleen de huidige scene
terug, maar ook of er dít frame een overgang plaatsvond. De hoofdlus
gebruikt dat om `_handle_trigger()` (scare-video afspelen) precies één
keer aan te roepen — op het moment van aankomst — in plaats van elke
cyclus dat de node toevallig nog "huidig" is.

```
┌────────────────────────────┐   sleep     ┌─────────────────────────────┐
│ Node-editor (Dashboard)        │──────────▶│ /api/scenes, /api/scene-edges    │
│ (@xyflow/react-canvas)         │◀───lezen──│  (backend, twee nieuwe tabellen)   │
└──────────────┬─────────────┘            └────────────────┬────────────┘
               │                                              │ publish (retained,
               │                                              │ + republish-on-connect)
               │                                   config/mirror/graph
               │                                   {scenes, edges, root_scene_id}
               │                                              │
               │                                 ┌────────────▼────────────┐
               │                                 │ mirror_node: SceneGraph      │
               │                                 │ (stateful, current_scene_id)  │
               │                                 └──────────────────────────────┘
```

**Eén gecombineerd, retained topic** (`config/mirror/graph`) i.p.v. de
huidige twee losse (`config/mirror/scenes` + het idee van een aparte
edges-topic) — bewuste les uit de vorige feature: het
republish-on-connect-mechanisme moet maar één topic dekken, niet
riskeren dat een tweede topic bij een toekomstige uitbreiding vergeten
wordt. De bestaande `MqttBridge.on_connect_extra`-hook (net gebouwd)
publiceert voortaan dit ene topic i.p.v. de losse
`config/mirror/scenes`/`config/mirror/scare-video`-aanroepen (het
scare-video-topic blijft overigens ongewijzigd apart bestaan — dat gaat
over de gedeelde video-bibliotheek, niet over de graaf-structuur).

## Componenten

### Backend: database (`admin/app/db.py`)

Nieuwe tabel:

```sql
CREATE TABLE IF NOT EXISTS scene_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_scene_id INTEGER NOT NULL,
    to_scene_id INTEGER,
    trigger_type TEXT,
    trigger_from TEXT,
    trigger_until TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (from_scene_id) REFERENCES scenes(id) ON DELETE CASCADE,
    FOREIGN KEY (to_scene_id) REFERENCES scenes(id) ON DELETE SET NULL
)
```

(`ON DELETE SET NULL` op `to_scene_id`: een scene verwijderen die
ergens het doel van een lijn was, laat die lijn terugvallen op een lege
output-stub in plaats van een kapotte verwijzing — consistent met "een
lege output is een geldige, veilige tussenstand".)

Kolommen op `scenes` (via `_ensure_column`, bestaande tabel):
`is_root INTEGER NOT NULL DEFAULT 0`, `canvas_x REAL NOT NULL DEFAULT 0`,
`canvas_y REAL NOT NULL DEFAULT 0`. De oude `order_index`,
`trigger_type`, `trigger_from`, `trigger_until`-kolommen blijven
ongebruikt bestaan (zelfde "nooit droppen"-precedent als
`mirror_config`) — de routes lezen/schrijven ze niet meer.

**Migratie** (in `init_db`, ná de kolom-toevoegingen, vóór de
bestaande `_migrate_mirror_config_to_scenes`-aanroep hoeft niet te
wijzigen — dit is een tweede, latere migratiestap die na de eerdere
draait): als `scene_edges` leeg is én er scenes bestaan met de oude
`trigger_type`-kolom nog ingevuld (d.w.z. deze DB heeft de vorige
schema-versie gebruikt en is nog niet naar de graaf gemigreerd):
- De scene met `trigger_type = 'always'` en de laagste `order_index`
  wordt de root (`is_root = 1`).
- Voor elke andere scene met een niet-lege `trigger_type`: maak één
  live edge `root → die_scene` met die scene's oude trigger-velden.
- Voor elke scene met `source_mode = 'scare_video'` (ongeacht z'n oude
  trigger): maak ook één live edge `die_scene → root` met
  `trigger_type = 'always'` (het vanzelfsprekende terugpad).
- Als er geen root gevonden wordt (geen enkele oude `always`-scene):
  de scene met de laagste `order_index` wordt root, zonder extra edges
  — een lege graaf met alleen een startpunt, veilig, gebruiker bouwt
  de rest zelf op.

Dit reproduceert exact de ster-topologie uit het concrete voorbeeld
van de gebruiker en dekt de huidige live productiestand (één
"Basis"-scene) triviaal (wordt root, geen edges nodig).

### Backend: routes

`admin/app/routers/scenes.py` (bestaand, aanpassen):
- `_DEFAULT_SCENE`/`_row_to_scene`/create/update: `trigger_type`,
  `trigger_from`, `trigger_until`, `order_index` verdwijnen uit de
  velden-set; `is_root`, `canvas_x`, `canvas_y` komen erbij.
- `PUT /api/scenes/{id}` met `is_root: true`: zet in dezelfde
  transactie `is_root = 0` op alle ándere scenes (precies één root
  afgedwongen op applicatieniveau, geen DB-constraint nodig voor dit
  soort eenvoudige invariant).
- Nieuwe, lichte route `PUT /api/scenes/{id}/position` — body
  `{canvas_x, canvas_y}`, schrijft alleen die twee kolommen, **publiceert
  niets** naar MQTT (positie is geen mirror-node-aangelegenheid, en dit
  endpoint wordt tijdens het slepen vaak aangeroepen — geen reden om
  daarbij elke keer de hele graaf te herpubliceren).
- `PUT /api/scenes/order` **vervalt** (er is geen globale volgorde
  meer — volgorde bestaat nu per-node, op edges, via `priority`).

Nieuw bestand `admin/app/routers/scene_edges.py`:

```
GET    /api/scene-edges           → alle edges (elke from_scene_id's outputs
                                     samen, gesorteerd op priority)
POST   /api/scene-edges           → aanmaken; body mag to_scene_id/trigger_type
                                     leeg laten (lege output-stub)
PUT    /api/scene-edges/{id}      → bijwerken (koppelen en/of trigger instellen)
DELETE /api/scene-edges/{id}      → verwijderen
```

Zelfde structuur/patroon als `routers/scenes.py`. Elke schrijvende
route (op alle vier, inclusief create/delete) publiceert na de
DB-write de **volledige graaf** — nieuwe gedeelde helper
`_publish_graph(request)` in bijv. `admin/app/graph_publish.py`
(gebruikt door zowel `routers/scenes.py` als `routers/scene_edges.py`,
vandaar een eigen klein module-bestand i.p.v. 'm in één van de twee
routers te laten wonen):

```python
def _publish_graph(request):
    db = request.app.state.db
    scenes = _list_scenes(db)          # ongewijzigde helper, nu zonder trigger-velden
    edges = _list_edges(db)            # nieuwe helper, alle edges (ook niet-live, voor de editor)
    root = next((s["id"] for s in scenes if s["is_root"]), None)
    request.app.state.bridge.publish_mirror_graph(
        {"scenes": scenes, "edges": edges, "root_scene_id": root}
    )
```

`admin/app/main.py`: registreer `scene_edges_router`; de bestaande
`on_connect_extra`-hook (van de vorige feature) roept nu
`_publish_graph(...)` aan i.p.v. losse `publish_mirror_scenes`-calls.

### Backend: MQTT

`shared/mqtt_contract.py`: `config_mirror_scenes` wordt
`config_mirror_graph` (`"config/mirror/graph"`) — enige naamswijziging,
verder identiek patroon (retained). `control_mirror_scene_preview`
blijft ongewijzigd (preview blijft één losse scene pushen, niet de
hele graaf).

`admin/app/mqtt_bridge.py`: `publish_mirror_scenes` wordt
`publish_mirror_graph(graph_dict)` — publiceert het hele
`{scenes, edges, root_scene_id}`-object.

### mirror_node: `SceneGraph` (vervangt `SceneEngine` in
`mirror_node/scenes.py`)

```python
import time


class SceneGraph:
    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._scenes = {}
        self._edges = {}          # from_scene_id -> [edge, ...] (alleen live edges, op priority)
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
    """Ongewijzigd overgenomen van de vorige feature."""
    if not start or not end:
        return False
    if start <= end:
        return start <= now_hhmm < end
    return now_hhmm >= start or now_hhmm < end
```

### mirror_node: hoofdlus (`mirror_node/main.py`)

- `scene_engine = SceneEngine()` → `scene_graph = SceneGraph()`.
- `_apply_scenes_message` → hernoemd `_apply_graph_message`, parseert
  `{"scenes": [...], "edges": [...], "root_scene_id": ...}` i.p.v. een
  kale lijst, roept `scene_graph.set_graph(...)` aan, synct overlays
  voor elke scene zoals nu.
- MQTT-subscribe: `topics.config_mirror_graph` i.p.v.
  `topics.config_mirror_scenes`.
- Hoofdlus: vervangt de bestaande `_resolve_action`-wrapper
  (inclusief de dubbele-resolve-hack uit de vorige fix-golf, die
  hiermee vervalt — de state machine heeft 'm niet meer nodig) door:
  ```python
  winning, transitioned = scene_graph.resolve(now < active_until, now_hhmm)

  if winning is not None and winning.get("source_mode") == "scare_video" and transitioned:
      cooldown = _handle_trigger(streamer, logger)
      active_until = time.time() + cooldown
      rendered = frame * 0
  elif winning is None or winning.get("source_mode") == "scare_video":
      rendered = frame * 0
  else:
      try:
          rendered = _render(frame, winning, logger)
      except Exception as exc:
          logger.error("Fout bij renderen: %s", exc)
          rendered = frame
  ```
  (`_decide_action` als apart-testbare pure functie vervalt hiermee —
  de beslissing is nu kort genoeg om inline te blijven, of blijft als
  eigen functie als de implementatie dat leesbaarder vindt; in beide
  gevallen blijft 'm apart unit-testbaar, zie Testen.)
- `fired`/`test_trigger_requested`-afhandeling: ongewijzigd (bepaalt
  nog steeds `motion_active` via `active_until`, dat voedt nu
  `scene_graph.resolve(...)` i.p.v. de oude `SceneEngine.resolve(...)`).

### Frontend: node-editor

Nieuwe dependency: `@xyflow/react` (voorheen `react-flow`) — de
gangbare, onderhouden React-library voor precies dit
(sleepbare nodes, custom node-rendering, edges met labels). Geen
bestaande dependency dekt dit; zelf een sleep/verbindings-canvas
bouwen met ruwe SVG/pointer-events is voor deze reikwijdte (custom
node-content, edge-labels, klik-op-edge) meer werk en breekbaarder
dan een gevestigde library gebruiken.

**Interactiemodel** (naar het voorbeeld van
callcenter-routeringssoftware, zoals de gebruiker aangaf):

- Elke scene is een node met een korte samenvatting (naam, bron-icoon)
  en een rij **output-stubs** — één per uitgaande edge, inclusief lege
  (nog niet gekoppelde).
- Een "+"-knopje op de node voegt een nieuwe, lege output toe
  (`POST /api/scene-edges` met `to_scene_id: null, trigger_type: null`).
- Een output-stub slepen naar een andere node zet `to_scene_id`
  (`PUT /api/scene-edges/{id}`) — de lijn verschijnt, nog zonder
  trigger-label (grijs/gestippeld: "nog niet ingesteld").
- Op een ongeconfigureerde lijn (of de doelnode) klikken opent een klein
  inline trigger-formulier (dezelfde drie opties als de bestaande
  Trigger-stap in de wizard: Altijd/Beweging/Tijdschema) om
  `trigger_type`(`/from`/`until`) op die edge te zetten. Zodra dat
  compleet is, krijgt de lijn een label (bijv. "Beweging" of
  "20:00–23:00") en wordt 'm live.
- Op een node zelf klikken opent de bestaande `SceneWizardModal`,
  maar dan **zonder** de Trigger-stap (die hoort nu bij edges, niet bij
  de node) — dus alleen Input/Animatie/Output voor een camera-scene, of
  alleen Input voor een scare_video-scene. Zie ook de eerder
  afgesproken kleinere verbetering: losse elementen op de node
  (bron/effect/weergave) zijn zelf ook klikbaar en openen de wizard
  direct op die stap.
- Verwijderen van een output-stub (of lijn): `DELETE
  /api/scene-edges/{id}`.
- Eén node is gemarkeerd als root (bijv. een sterretje/kroontje-icoon);
  klikken op "maak root" op een andere node zet `is_root` daar en
  ontzet 'm overal elders (`PUT /api/scenes/{id}` met `is_root: true`).
- Slepen van een hele node (niet een output) update alleen
  `canvas_x`/`canvas_y` via de aparte, MQTT-stille positie-route —
  getroffeld (bijv. 200ms) om niet elke pixel een PUT te sturen, zelfde
  soort overweging als de al bestaande live-preview-throttle.
- De bestaande "+ Nieuwe scene"-kaart blijft bestaan als een knop die
  een nieuwe, ongekoppelde node op het canvas neerzet (starten met een
  Input-stap in de wizard, zonder outputs — die voeg je er daarna zelf
  aan toe).

Vervangt: de scene-kaarten-grid + ▲/▼-herordenen op het Dashboard
(`order_index`/reorder-UI bestaat niet meer als concept). De
"Mirror-node"-sectie (start/stop/log/test, uit de vorige feature)
blijft ongewijzigd op het Dashboard staan, los van het canvas.

## Data flow

**Verbinding maken tussen twee bestaande scenes**
1. Gebruiker sleept een output-stub van node A naar node B.
2. `PUT /api/scene-edges/{id}` zet `to_scene_id = B` (trigger nog leeg)
   → backend publiceert de bijgewerkte (nog niet-live) graaf.
3. Gebruiker klikt de lijn, kiest "Beweging" → `PUT
   /api/scene-edges/{id}` zet `trigger_type = "motion"` → backend
   publiceert opnieuw; deze keer is de edge live.
4. mirror-node ontvangt de nieuwe graaf via het retained topic, past 'm
   toe op de volgende evaluatie-cyclus — geen herstart nodig.

**Normale werking**
1. mirror-node houdt `current_scene_id` bij (begint bij de root, of bij
   een onbekende/verwijderde staat na een graaf-wijziging).
2. Elke frame: kijk naar de live outputs van de huidige scene, eerste
   matchende trigger (in `priority`-volgorde) wint → spring naar die
   scene.
3. Camera-scene: render zoals nu. Scare-video-scene, net aangekomen:
   speel de clip (bestaand `_handle_trigger`-pad, ongewijzigd) en
   publiceer `mirror/triggered` zoals altijd.
4. Zonder matchende output: blijf op de huidige scene (camera-scene
   rendert door; scare-video-scene zonder terugpad blijft "hangen",
   zie Niet-doelen).

## Foutafhandeling

- **Onbekende/verwijderde `current_scene_id`** (bijv. de huidige scene
  is net verwijderd terwijl de node daar "stond"): `resolve()` valt
  terug op de root. Geen crash, geen foutmelding — vergelijkbaar met
  hoe de vorige feature al terugvalt op "geen enkele scene matcht".
- **Geen root ingesteld (nooit een scene, of niemand ooit als root
  gemarkeerd):** `resolve()` geeft `(None, False)` terug, hoofdlus
  rendert zwart — zelfde patroon als "geen enkele scene matcht" in de
  vorige feature.
- **Edge naar een verwijderde scene:** DB-`ON DELETE SET NULL` maakt
   'm automatisch weer een lege output-stub; de volgende
  graaf-publicatie (bij de eerstvolgende schrijf-actie via de API)
  neemt dat mee. Tussentijds (vóór die volgende publicatie) kan de
  mirror-node nog een stale `to_scene_id` hebben die niet meer bestaat
  — `resolve()` matcht die edge dan gewoon niet (het doel zit niet in
  `self._scenes`), valt door naar de volgende output of blijft op de
  huidige scene; geen crash.
- **Cirkel van uitsluitend "altijd"-edges** (bijv. A →altijd→ B →altijd→
  A, geen enkele conditionele output): elke cyclus precies één hop,
  dus dit wisselt elke frame tussen A en B i.p.v. vast te lopen — geen
  oneindige lus binnen één evaluatie (er wordt maximaal één edge per
  `resolve()`-aanroep gevolgd), maar wel zichtbaar knipperend gedrag.
  Geen validatie hiertegen in v1 (zie Niet-doelen) — een ongebruikelijke
  configuratiefout, zichtbaar genoeg om zelf te herkennen en te fixen.

## Beveiliging

Geen nieuwe risico's t.o.v. het bestaande patroon: `/api/scene-edges/*`
vereist dezelfde sessie-auth als alle andere config-routes;
`config/mirror/graph` op MQTT is niet gevoeliger dan de huidige
`config/mirror/scenes` (zelfde LAN-vertrouwd-aanname).

## Testen

- `mirror_node/scenes.py` (`SceneGraph`): root-fallback bij onbekende
  `current_scene_id`; precies één hop per `resolve()`-aanroep;
  `transitioned` is `True` alleen bij een daadwerkelijke sprong;
  niet-live edges (lege `to_scene_id` of `trigger_type`) worden
  genegeerd; prioriteit-volgorde tussen meerdere outputs van dezelfde
  node; `motion`/`schedule`/`always`-matching (hergebruikt exact de
  bestaande `_time_in_window`-tests); preview overschrijft de
  graaf-evaluatie zolang die recent gezet is, ongeacht `current_scene_id`.
- `mirror_node/main.py`: `_handle_trigger` wordt aangeroepen bij
  `transitioned=True` + `scare_video`, niet bij een cyclus waarin de
  node toevallig al "huidig" scare_video is zonder nieuwe transitie
  (dekt precies de bugklasse die de vorige feature's fix-golf moest
  oplappen — nu door het ontwerp zelf voorkomen, niet door een lapje).
- `admin/app/routers/scene_edges.py`: CRUD-round-trip; een edge met
  `to_scene_id: null` en/of `trigger_type: null` wordt correct
  opgeslagen en teruggegeven (blijft "leeg" zolang niet compleet); elke
  schrijvende actie publiceert de volledige graaf.
- `admin/app/routers/scenes.py`: `is_root`-exclusiviteit (zetten op één
  scene ontzet 'm elders); de nieuwe `/position`-route schrijft alleen
  `canvas_x`/`canvas_y` en publiceert niets naar MQTT (test met een
  fake bridge die een `AssertionError` geeft als 'm wél wordt
  aangeroepen).
- `admin/app/db.py`: migratietest — een bestaande scenes-tabel met
  oude `trigger_type`-waarden migreert naar de verwachte
  ster-topologie (root + N inkomende edges + terugpad-edges voor
  scare_video-scenes); idempotent.
- Frontend: `tsc --noEmit` + `vite build`, zelfde niveau als eerdere
  features (geen componenttestinfrastructuur in deze repo).
- Handmatige verificatie: het exacte voorbeeld van de gebruiker
  opbouwen (één continue mirror-scene, drie outputs naar drie
  verschillende scare-scenes met onderscheidende tijdvensters, elk met
  een terugpad-edge) en bevestigen dat beweging binnen elk venster de
  juiste clip toont en daarna weer teruggaat naar de mirror-scene.

## Migratie (impact op bestaand werk)

- `mirror_node/scenes.py`: `SceneEngine` → `SceneGraph` (zie
  Componenten); `mirror_node/main.py` navenant aangepast.
- `admin/app/routers/scenes.py`: trigger/order-velden eruit,
  `is_root`/`canvas_x`/`canvas_y` erbij, nieuwe `/position`-route,
  `/order`-route eruit.
- Nieuw bestand `admin/app/routers/scene_edges.py` +
  `admin/app/graph_publish.py`.
- `shared/mqtt_contract.py`/`admin/app/mqtt_bridge.py`:
  `config_mirror_scenes`/`publish_mirror_scenes` →
  `config_mirror_graph`/`publish_mirror_graph`. De
  `on_connect_extra`-hook (vorige feature) wijst voortaan hierheen.
- Frontend: `DashboardPage.tsx`'s scene-kaarten-grid + ▲/▼-reorder
  worden vervangen door het nieuwe canvas-component (nieuw bestand,
  bijv. `SceneGraphCanvas.tsx`); `SceneWizardModal.tsx` verliest de
  Trigger-stap (verhuist naar een nieuw, klein
  `EdgeTriggerPopover.tsx`-achtig component) en krijgt een
  `initialStep`-prop (de eerder afgesproken "klikbare elementen"
  -verbetering, die hiermee natuurlijk in deze feature meelift in
  plaats van los gebouwd te worden).
- `admin/frontend/package.json`: nieuwe dependency `@xyflow/react`.
- Bestaande deploys migreren automatisch (zie Componenten → database)
  — geen handmatige stap.
