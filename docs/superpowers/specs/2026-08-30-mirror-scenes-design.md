# Mirror-scenes (regie-programmering) — Design

**Datum:** 2026-08-30
**Status:** Goedgekeurd, klaar voor implementatieplan
**Vervolg op:** `2026-08-27-mirror-scare-video-design.md`,
`2026-08-27-mirror-node-inline-start-design.md`

## Doel

De Mirror-pagina heeft nu precies één globale configuratie (effect,
overlay, weergaveformaat, camera-bron) die altijd geldt zodra er
beweging is. De gebruiker wil kunnen *programmeren*: meerdere losse
"scenes" bouwen — elk met een eigen bron (live camera of een
scare-video), eigen regie (effect/overlay/weergaveformaat) en een
eigen trigger-voorwaarde (beweging / tijdschema / altijd) — die
allemaal tegelijk "actief" zijn. De mirror-node kiest continu, op
basis van een vaste prioriteitsvolgorde, welke scene op dat moment
matcht en toont die. Bouwen gebeurt via een "+"-knop op het Dashboard
die een stapsgewijze modal opent (Input → Animatie → Output →
Trigger); het resultaat wordt een kaart op het Dashboard. De overige
pagina's (Instellingen, Overlay-bibliotheek, Scare-video's) blijven
puur beheer van gedeelde bronnen/verbindingen waar scenes naar
verwijzen.

Dit vervangt de bestaande enkelvoudige Mirror-pagina/-config volledig.
Alle bouwstenen die daar al staan (effect-picker, `OverlayCanvas`
sleep/schaal-tool, weergaveformaat-velden) worden ongewijzigd
hergebruikt binnen de nieuwe wizard-modal — geen weggegooid werk, wel
een nieuwe plek en een nieuwe, rijkere databron eromheen.

## Niet-doelen

- **Geen HA-integratie als triggertype.** Trigger-types nu: Beweging
  (bestaande frame-diff), Tijdschema (van–tot), Altijd. HA-events als
  vierde triggertype is een aparte, latere sessie — deze spec houdt
  er in de datamodel-vorm (`trigger_type` als open string/enum) wel
  rekening mee, maar bouwt 'm niet.
- **Geen gelijktijdige meervoudige output.** Precies één scene is op
  elk moment "actief" (eerste match in prioriteitsvolgorde wint) —
  geen laag-over-laag-compositing van meerdere scenes tegelijk.
- **Geen wijziging aan de bestaande scare-video-selectie/-afspeel-
  logica.** Een scene met bron "Scare-video" verwijst naar de
  *bestaande* ingeschakelde-scare-video's-pool
  (`mirror_scare_video_config`, willekeurige keuze bij trigger) —
  ongewijzigd hergebruikt, geen los "kies precies deze ene clip"-veld
  per scene. Zo blijft de al-geteste (en al eerder van een kritieke
  bugfix voorziene) afspeel-pad volledig intact.
- **Geen weergaveformaat/compositing voor scare-video-scenes.** Zelfde
  bewuste keuze als de oorspronkelijke scare-video-feature: een
  scare-video vervangt het beeld volledig, geen canvas-plaatsing.
  De wizard slaat de Animatie- en Output-stap dus over voor dit
  brontype.
- **Geen complexe schema's.** Tijdschema is één simpel van–tot-venster
  per dag (met middernacht-doorloop ondersteund, bijv. 22:00–02:00);
  geen dagen-van-de-week-selectie, geen meerdere vensters per scene.
- **Geen drag-and-drop-herordenen.** Prioriteitsvolgorde wijzig je met
  simpele ▲/▼-knoppen per kaart — zelfde resultaat, veel minder
  frontend-complexiteit dan een drag-interactie.
- **Geen validatie/waarschuwing voor onbereikbare scenes** (bijv. een
  beweging-scene die ná een altijd-scene staat en dus nooit kan
  winnen). De prioriteitsvolgorde is expliciet de gebruiker z'n
  verantwoordelijkheid; geen slimme linting hierover in v1.
- **`scare_node` blijft ongewijzigd.**

## Architectuur

**Nieuw kernbegrip: Scene.** Vervangt de huidige singleton
`mirror_config`. Elke scene bundelt exact de velden die de wizard
uitvraagt, plus een prioriteit en een trigger-voorwaarde:

```
Scene:
  id, name, order_index (prioriteit, laag = eerst geëvalueerd), enabled
  source_mode: "camera" | "scare_video"
  # alleen bij source_mode == "camera":
  effect, params, overlay_hash, scale, position,
  canvas_size, source_scale, source_position
  # trigger:
  trigger_type: "always" | "motion" | "schedule"
  trigger_from, trigger_until  # "HH:MM", alleen bij "schedule"
```

**Evaluatie op de mirror-node, elke loop-iteratie:** de node houdt de
volledige, geordende scene-lijst in het geheugen (live gepusht via
MQTT, retained — zelfde patroon als de bestaande
`config/mirror/scare-video`). Per frame:

1. Bepaal `motion_active` (blijft de bestaande `FrameDiffTrigger` +
   cooldown-venster, ongewijzigd qua mechaniek — alleen wat er ná het
   afgaan gebeurt is nieuw).
2. Bepaal de huidige tijd (`HH:MM`) voor tijdschema-matching.
3. Loop de scenes in `order_index`-volgorde, eerste met een matchende
   trigger wint:
   - `always` → matcht altijd.
   - `schedule` → matcht als de huidige tijd binnen
     `[trigger_from, trigger_until)` valt (met middernacht-doorloop).
   - `motion` → matcht zolang `motion_active` waar is (het bestaande
     `ACTIVE_SECONDS`-venster na een echte trigger).
4. Geen enkele scene matcht → zwart beeld (huidig gedrag buiten het
   actieve venster, ongewijzigd).
5. Winnende scene met `source_mode == "camera"` → render exact zoals
   vandaag (`_render()`), nu geparametriseerd met de scene i.p.v. de
   globale config.
6. Winnende scene met `source_mode == "scare_video"` → bestaande
   `_handle_trigger()`-pad (willekeurige clip uit de ingeschakelde
   pool), alleen aangeroepen op het moment dat de beweging-trigger
   zelf afgaat (niet elke loop-cyclus opnieuw).

```
┌────────────────────────┐  +  ┌──────────────────────────────┐
│ Dashboard: scene-kaarten   │───▶│ Wizard-modal (4 stappen)         │
│ (▲▼ volgorde, aan/uit)     │◀───│ Input → Animatie → Output → Trigger │
└──────────┬─────────────┘     └──────────────┬──────────────┘
           │ CRUD                                │ opslaan
           ▼                                     ▼
   ┌───────────────────────────────────────────────────┐
   │ /api/scenes  (backend, DB-tabel `scenes`)              │
   └───────────────────────┬───────────────────────────┘
                            │ publish (retained) bij elke wijziging
                config/mirror/scenes  [{scene}, {scene}, ...]
                            │
                ┌───────────▼────────────┐
                │ mirror_node: scene-lijst   │
                │ in geheugen, geëvalueerd    │
                │ elke frame (prioriteit +    │
                │ trigger-match)               │
                └────────────────────────────┘
```

**Waarom live MQTT (retained) i.p.v. het boot-time
`/api/node-config`-patroon:** exact dezelfde reden als de
scare-video-config destijds — een scene-wijziging moet direct effect
hebben, geen herstart vereisen, en `retain=True` zorgt dat een
(her)startende node de laatste stand meteen krijgt zonder aparte
REST-call.

## Componenten

### Backend: database (`admin/app/db.py`)

Nieuwe tabel (nieuwe tabel = gewoon `CREATE TABLE IF NOT EXISTS`,
geen `_ensure_column`-migratie nodig — dat is alleen vereist voor een
kolom op een tabel die al bestaat, zoals eerder bij
`mirror_camera_source` op `app_settings`):

```sql
CREATE TABLE IF NOT EXISTS scenes (
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
    trigger_until TEXT
)
```

**Eenmalige data-migratie** (in `init_db`, ná het aanmaken van de
tabel): als `scenes` leeg is én er nog een rij in `mirror_config`
bestaat, kopieer die naar één nieuwe scene (`name="Basis"`,
`order_index=0`, `trigger_type="always"`, `enabled=1`, alle overige
velden 1-op-1 overgenomen). Zo blijft een bestaande deploy na de
upgrade precies hetzelfde beeld tonen als vandaag, zonder handmatige
stap. De `mirror_config`-tabel zelf blijft ongebruikt bestaan (geen
`DROP TABLE` — dat is nooit nodig en voegt alleen risico toe).

### Backend: routes (nieuw bestand `admin/app/routers/scenes.py`)

```
GET    /api/scenes            → lijst, gesorteerd op order_index
POST   /api/scenes            → aanmaken (body zonder id/order_index;
                                 order_index = max(bestaande) + 1)
GET    /api/scenes/{id}       → één scene (voor het vooraf invullen
                                 van de edit-wizard)
PUT    /api/scenes/{id}       → bijwerken
DELETE /api/scenes/{id}       → verwijderen
PUT    /api/scenes/order      → body {"order": [id, id, ...]};
                                 herschrijft order_index in die volgorde
POST   /api/scenes/{id}/preview → publiceert een tijdelijke preview
                                 van deze scene (net als het bestaande
                                 `/api/mirror/preview`, nu scene-scoped)
```

Elke schrijvende route publiceert na de DB-write de **volledige,
geordende scene-lijst** naar `config/mirror/scenes` (retained) — één
plek die dat doet (`_publish_scenes(app, db)`-helper), niet
losse per-route publish-calls die uit sync kunnen raken.

Route- en validatiestijl volgt de bestaande `routers/mirror.py`
(defaults-dict, partial-payload-normalisatie) en `routers/scare.py`
(zone-achtige CRUD-vorm, hier per `id` i.p.v. per zone-string).

`/api/mirror/config`, `/api/mirror/preview` (`routers/mirror.py`)
**vervallen** — volledig vervangen door de routes hierboven.
`/api/mirror/test` (los manueel trigger-signaal, simuleert een
beweging-event systeembreed) **blijft ongewijzigd** — orthogonaal aan
scenes, precies zoals vandaag.

### Backend: MQTT (`shared/mqtt_contract.py`, `admin/app/mqtt_bridge.py`)

Nieuwe topic-property, vervangt `config_mirror` en
`control_mirror_preview`:

```python
@property
def config_mirror_scenes(self) -> str:
    return self._p("config/mirror/scenes")

@property
def control_mirror_scene_preview(self) -> str:
    return self._p("control/mirror/scene-preview")
```

`config_mirror`/`control_mirror_preview` (en de bijbehorende
`MqttBridge.publish_mirror_config`/`publish_mirror_preview`) worden
verwijderd; `control_mirror_test` blijft. Nieuwe bridge-methoden
`publish_mirror_scenes(scenes)` (retained) en
`publish_mirror_scene_preview(scene)` (niet retained) volgen exact
het patroon van de bestaande scare-video-config-publish.

### mirror_node: scene-engine (nieuw bestand `mirror_node/scenes.py`,
vervangt `mirror_node/active_config.py`)

```python
class SceneEngine:
    """Houdt de laatst ontvangen scene-lijst (via MQTT) en een optionele
    tijdelijke preview-scene bij (zelfde TTL-mechanisme als de oude
    ActiveMirrorConfig, nu op scene-niveau i.p.v. één globale config)."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._scenes = []
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_scenes(self, scenes):
        self._scenes = scenes

    def set_preview(self, scene):
        self._preview = scene
        self._preview_set_at = self._clock()

    def preview_recently_set(self):
        if self._preview_set_at is None:
            return False
        return self._clock() - self._preview_set_at <= self._preview_timeout

    def resolve(self, motion_active, now_hhmm):
        """Geeft de winnende scene terug (of None): de preview-scene als
        die recent gezet is, anders de eerste ingeschakelde scene in
        volgorde wiens trigger nu matcht."""
        if self.preview_recently_set():
            return self._preview
        for scene in self._scenes:
            if not scene.get("enabled", True):
                continue
            trigger = scene.get("trigger_type")
            if trigger == "always":
                return scene
            if trigger == "motion" and motion_active:
                return scene
            if trigger == "schedule" and _time_in_window(
                now_hhmm, scene.get("trigger_from"), scene.get("trigger_until")
            ):
                return scene
        return None


def _time_in_window(now_hhmm, start, end):
    """"HH:MM"-vergelijking met middernacht-doorloop (bijv. 22:00-02:00)."""
    if not start or not end:
        return False
    if start <= end:
        return start <= now_hhmm < end
    return now_hhmm >= start or now_hhmm < end
```

### mirror_node: hoofdlus (`mirror_node/main.py`)

- Vervangt `active_config = ActiveMirrorConfig()` door
  `scene_engine = SceneEngine()`.
- Nieuwe MQTT-subscribe op `topics.config_mirror_scenes` (retained,
  dus meteen de laatste stand bij (her)verbinden — zelfde reden als
  de scare-video-config); `on_message`-branch parseert de JSON-array
  en roept `scene_engine.set_scenes(...)` aan. Ongeldige payloads
  (geen lijst, kapotte JSON) worden gelogd en genegeerd — bestaand
  fail-safe-patroon, render-loop mag hier nooit op vastlopen.
- Nieuwe branch op `topics.control_mirror_scene_preview` →
  `scene_engine.set_preview(...)`.
- Hoofdlus: motion-detectie/cooldown-boekhouding blijft ongewijzigd
  (`trigger.detect(gray)`, `active_until`, `MAX_FAILURES_BEFORE_REOPEN`
  voor de camera-heropen-logica). Nieuw is wat er ná een afgaande
  trigger gebeurt:
  ```python
  motion_active = now < active_until
  if trigger.detect(gray) and now > active_until:
      client.publish(topics.mirror_triggered, trigger_payload())
      active_until = time.time() + ACTIVE_SECONDS
      motion_active = True
      winning = scene_engine.resolve(motion_active, now_hhmm)
      if winning and winning.get("source_mode") == "scare_video":
          cooldown = _handle_trigger(streamer, logger)  # ongewijzigd
          active_until = time.time() + cooldown

  winning = scene_engine.resolve(motion_active, now_hhmm)
  if winning is None:
      rendered = frame * 0
  elif winning.get("source_mode") == "camera":
      rendered = _render(frame, winning, logger)  # nu scene-param i.p.v. active_config.get()
  else:
      rendered = frame  # scare-video-afspelen gebeurde hierboven al blokkerend
  streamer.publish_frame(rendered)
  ```
  (Vereenvoudigde weergave — de exacte plaatsing in de bestaande
  `try/except`/`consecutive_failures`-structuur volgt tijdens de
  implementatie de huidige code zo veel mogelijk 1-op-1.)
- `_render(frame, scene, logger)`: zelfde functie als vandaag, alleen
  leest hij zijn config nu uit het `scene`-argument i.p.v.
  `active_config.get()`. De `place_on_canvas`/`composite_overlay`-
  aanroepen blijven ongewijzigd (die kregen hun eigen parameters al
  mee, zie de weergaveformaat-feature van eerder).
- `MIRROR_CAMERA_SOURCE`/topic-prefix-boot-fetch: ongewijzigd (nog
  steeds boot-time via `/api/node-config`, scenes zijn puur MQTT).

### Frontend: types (`admin/frontend/src/types.ts`)

```ts
export interface Scene {
  id: number;
  name: string;
  order_index: number;
  enabled: boolean;
  source_mode: "camera" | "scare_video";
  effect: MirrorConfig["effect"];
  params: Record<string, number>;
  overlay_hash: string | null;
  scale: number;
  position: [number, number];
  canvas_size: [number, number] | null;
  source_scale: number;
  source_position: [number, number];
  trigger_type: "always" | "motion" | "schedule";
  trigger_from: string | null;
  trigger_until: string | null;
}
```
`MirrorConfig` (het huidige type) vervalt; `Scene` is de opvolger.

### Frontend: API (nieuw bestand `admin/frontend/src/api/scenes.ts`)

`listScenes`, `createScene`, `updateScene`, `deleteScene`,
`reorderScenes(ids: number[])`, `previewScene(id, scene)` — zelfde
`apiFetch`-patroon als de rest. `admin/frontend/src/api/mirror.ts`
verliest `getMirrorConfig`/`putMirrorConfig`/`previewMirrorConfig`;
`testMirror` blijft (ongewijzigd endpoint).

### Frontend: Dashboard (`admin/frontend/src/pages/DashboardPage.tsx`)

Nieuwe sectie **bovenaan** de pagina (dit is "waar geprogrammeerd
wordt", dus de primaire sectie): een kaartenrij met één kaart per
scene (naam, aan/uit-toggle, trigger-samenvatting, ▲/▼ voor
volgorde, bewerken/verwijderen) plus een "+"-kaart die de
wizard-modal opent. Bestaande secties (node-status, noodstop,
tijdvenster) blijven eronder ongewijzigd staan.

### Frontend: wizard-modal (nieuw bestand
`admin/frontend/src/components/SceneWizardModal.tsx`)

Vier stappen, met een lokale `draft: Scene`-state (zelfde
opslaan-pas-bij-"Toepassen"-model als de huidige Mirror-pagina):

1. **Input** — naam-veld + keuze "Live camera-bron" / "Scare-video
   (uit bibliotheek)" (`source_mode`).
2. **Animatie** — alleen getoond bij `source_mode === "camera"`:
   effect-select + parameters + `MediaLibrary`
   (`category="mirror_overlay"`) voor de overlay — 1-op-1 hergebruikt
   van de huidige Mirror-pagina-sectie.
3. **Output** — alleen getoond bij `source_mode === "camera"`:
   breedte/hoogte + de `OverlayCanvas`-compositietool — 1-op-1
   hergebruikt (inclusief de camera-bron/verwerkt-beeld-schakelaar).
4. **Trigger** — radiogroep Beweging/Tijdschema/Altijd; bij
   Tijdschema twee tijd-inputs (van/tot).

Live-preview tijdens het bewerken: dezelfde 150ms-throttle die de
Mirror-pagina al had, nu gericht op `POST /api/scenes/{id}/preview`
(bij een nieuwe, nog niet opgeslagen scene: preview pas beschikbaar
ná de eerste keer opslaan — geen aparte "preview zonder id"-route,
dat is geen extra complexiteit waard voor dat ene moment).

Opslaan (laatste stap) roept `createScene`/`updateScene` aan en sluit
de modal; het Dashboard herlaadt de scene-lijst.

### Frontend: navigatie (`admin/frontend/src/components/Layout.tsx`,
`admin/frontend/src/App.tsx`)

De `/mirror`-link en -route vervallen. `MirrorPage.tsx`/`.css` worden
verwijderd (hun inhoud leeft nu in de wizard-modal + Dashboard).

### Frontend: "Mirror-node testen" verhuist mee naar het Dashboard

De bestaande start/stop/logpaneel-sectie en de globale "Test"-knop
(handmatige trigger) horen niet meer bij een scene-specifieke pagina
— die verhuizen naar een eigen, kleine sectie op het Dashboard,
apart van de scene-kaarten (het gaat over het node-proces/de
trigger-simulatie, niet over één specifieke scene).

## Data flow

**Scene aanmaken/bewerken**
1. Gebruiker klikt "+" (of een bestaande kaart) → wizard-modal opent,
   optioneel voorgevuld via `GET /api/scenes/{id}`.
2. Tijdens het invullen: throttled `POST /api/scenes/{id}/preview`
   (alleen bij een bestaande scene) toont live wat er verandert via
   dezelfde `OverlayCanvas`-tool als vandaag.
3. Opslaan → `POST`/`PUT /api/scenes` → backend persisteert, publiceert
   de volledige lijst (retained) naar `config/mirror/scenes`.
4. mirror-node ontvangt de nieuwe lijst, neemt 'm meteen mee in de
   eerstvolgende evaluatie — geen herstart nodig.

**Normale werking (geen editor open)**
1. mirror-node leest elke frame de camera, detecteert beweging zoals
   nu.
2. Evalueert de scene-lijst in volgorde tegen (beweging-venster,
   tijdschema, altijd) → wint een scene.
3. Rendert (camera-scene) of speelt een scare-video af
   (scare_video-scene) — beide paden functioneel ongewijzigd t.o.v.
   vandaag, alleen de *keuze welke* config/pool van toepassing is, is
   nieuw.

## Foutafhandeling

- **Geen enkele scene matcht** (bijv. alleen tijdschema-scenes en het
  is nu buiten alle vensters, geen "altijd"-vangnet aangemaakt):
  zwart beeld — zelfde als het bestaande "buiten actief venster"
  gedrag, geen foutstatus.
- **Ongeldige/kapotte scene-lijst-payload op MQTT:** loggen, negeren,
  laatst bekende lijst blijft van kracht (bestaand fail-safe-patroon,
  zie ook de scare-video-config-afhandeling).
- **Scene met `source_mode="scare_video"` maar een lege
  ingeschakelde-pool:** exact het bestaande gedrag van
  `_handle_trigger()` bij een lege `synced_scare_videos` — er gebeurt
  dan niets bijzonders (geen crash, geen video, gewoon geen
  scare-afspeel deze keer).
- **Tijdschema-veld leeg/ongeldig format:** `_time_in_window` geeft
  `False` terug (matcht nooit) i.p.v. te crashen — een half-ingevulde
  scene faalt dus stil (matcht nooit) i.p.v. de hele node onderuit te
  halen.
- **Backend onbereikbaar tijdens opslaan in de wizard:** bestaande
  foutmelding-in-de-UI-stijl (rode balk), geen dataverlies — de
  concept-scene blijft in de modal staan tot een geslaagde opslag.

## Beveiliging

Geen nieuwe risico's t.o.v. het bestaande patroon:
`/api/scenes/*`-routes vereisen sessie-auth zoals alle
config-wijzigende endpoints; `config/mirror/scenes` op MQTT is niet
gevoeliger dan de huidige `config/mirror`/`config/mirror/scare-video`
(zelfde LAN-vertrouwd-aanname, al eerder expliciet geaccepteerd).

## Testen

- `mirror_node/scenes.py`: `SceneEngine.resolve` — always-scene wint
  altijd zonder trigger-voorwaarden; motion-scene wint alleen als
  `motion_active`; schedule-scene met/zonder middernacht-doorloop;
  prioriteitsvolgorde (eerste match wint, latere scenes met een
  matchende trigger worden genegeerd); preview overschrijft alles
  zolang die recent gezet is, vervalt na `preview_timeout`;
  uitgeschakelde (`enabled=False`) scene wordt overgeslagen ondanks
  matchende trigger.
- `mirror_node/main.py`: hoofdlus-integratie met een gemockte
  `SceneEngine`/`cv2.VideoCapture` — bevestigt dat een camera-scene
  `_render()` gebruikt en een scare_video-scene het bestaande
  `_handle_trigger()`-pad, en dat dat laatste alleen op het moment
  van de trigger zelf gebeurt (niet elke loop-cyclus opnieuw).
- `admin/app/routers/scenes.py`: volledige CRUD-round-trip
  (aanmaken, ophalen, bijwerken, verwijderen, herordenen), auth
  vereist, en dat elke schrijvende actie de volledige geordende lijst
  publiceert.
- `admin/app/db.py`: migratietest — een bestaande `mirror_config`-rij
  in een verse DB resulteert na `init_db()` in precies één
  "Basis"-scene met dezelfde waarden; idempotent (`init_db()` twee
  keer migreert niet twee keer).
- Frontend: `tsc --noEmit` + `vite build`, zelfde niveau als eerdere
  features (geen componenttestinfrastructuur aanwezig om aan toe te
  voegen).
- Handmatige verificatie: minstens twee scenes aanmaken (bijv. een
  "Altijd"-basis-scene met xray, en een "Beweging"-scene met een
  overlay) en bevestigen dat de juiste scene verschijnt bij
  respectievelijk rust en een trigger; een tijdschema-scene testen
  door de systeemtijd (of `trigger_from`/`trigger_until`) rond de
  huidige tijd te zetten.

## Migratie (impact op bestaand werk)

- `mirror_node/active_config.py` verwijderd, vervangen door
  `mirror_node/scenes.py`.
- `admin/app/routers/mirror.py` verwijderd (samen met z'n tests);
  `admin/frontend/src/pages/MirrorPage.tsx`/`.css` verwijderd.
- `shared/mqtt_contract.py`: `config_mirror`/`control_mirror_preview`
  verwijderd, `config_mirror_scenes`/`control_mirror_scene_preview`
  toegevoegd. `control_mirror_test` ongewijzigd.
- Bestaande deploys migreren automatisch (zie
  Componenten → database) — geen handmatige stap voor de gebruiker,
  wél een Docker-rebuild+restart zoals bij elke feature.
- README: env-var-tabellen en de MQTT-topic-tabel bijwerken (nieuwe
  topics, `MIRROR_HEADLESS`/`DISPLAY`/`XAUTHORITY` blijven zoals ze
  zijn — de eerdere "Doel"-uitleg hierover (welk fysiek scherm is
  per-node systemd-config) verhuist mee van de Mirror-pagina naar de
  nieuwe Dashboard-sectie).
