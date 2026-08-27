# Beheerpagina — Instellingen-pagina (runtime-config) — Design

**Datum:** 2026-08-27
**Status:** Goedgekeurd, klaar voor implementatieplan
**Vervolg op:** `2026-08-16-beheerpagina-design.md`

## Doel

MQTT-, Home Assistant- en mirror-stream-verbinding zijn nu alleen via
env vars in te stellen — voor een echte spiegel-node instellen moet je nu de
service herstarten of (voor `VITE_MIRROR_STREAM_URL`) de hele frontend
herbouwen. Dat maakt itereren tegen echte hardware onnodig omslachtig. Deze
instellingen worden in-app beheerbaar, met directe toepassing (geen herstart
nodig).

## Niet-doelen

- **Geen** UI voor `ADMIN_PASSWORD`, `ADMIN_PORT`, `ADMIN_DB_PATH`,
  `ADMIN_MEDIA_DIR`, `LOG_DIR` — dat zijn opstart-vereisten van het proces
  zelf (je hebt het wachtwoord al nodig om bij de pagina te komen die het
  beheert), die blijven env-var. Bevestigd met de gebruiker.
- Geen "test verbinding"-knop of live broker-health-indicator in de nieuwe
  pagina — bestaande node-online-indicatoren op het dashboard blijven het
  enige verbindingssignaal, zoals nu ook al het geval is. Toevoegen kan
  later als het gemist wordt.
- Geen encryptie van `mqtt_pass`/`ha_token` in de database — dat zijn nu ook
  al platte env vars op dezelfde machine/bestandssysteem; opslag in
  `admin.db` (zelfde trust-niveau, zelfde bestandsrechten) is geen
  achteruitgang. Wél: nooit in platte tekst terug naar de browser.

## Architectuur

Volgt het bestaande patroon van `mirror_config`/`schedule`: een
singleton-rij in SQLite, een router eroverheen, een React-pagina eronder.
Nieuw punt t.o.v. dat patroon: een wijziging moet een **al lopende**
MQTT-verbinding herconfigureren, niet alleen de volgende keer dat het
proces opstart.

```
┌─────────────┐   PUT /api/settings   ┌──────────────────────────┐
│ SettingsPage │──────────────────────▶│ routers/settings.py       │
│ (frontend)   │◀──────────────────────│  - schrijft app_settings   │
└─────────────┘   GET /api/settings   │  - update app.state         │
                                        │    .runtime_settings        │
                                        │  - bridge.reconfigure(...)   │
                                        └───────────┬──────────────┘
                                                     │
                                        ┌────────────▼─────────────┐
                                        │ MqttBridge.reconfigure    │
                                        │  disconnect → nieuwe       │
                                        │  credentials → reconnect   │
                                        └───────────────────────────┘
```

`routers/ha.py` leest nu `ha_url`/`ha_token` per request uit
`request.app.state.settings`; dat wordt `request.app.state.runtime_settings`
(zie hieronder) — verder blijft `ha_client.py` ongewijzigd, die krijgt de
waarden nog steeds gewoon als parameters mee.

## Componenten

### Database (`admin/app/db.py`)

Nieuwe tabel, zelfde stijl als `mirror_config`:

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    mqtt_host TEXT NOT NULL,
    mqtt_port INTEGER NOT NULL,
    mqtt_user TEXT NOT NULL DEFAULT '',
    mqtt_pass TEXT NOT NULL DEFAULT '',
    ha_url TEXT NOT NULL,
    ha_token TEXT NOT NULL DEFAULT '',
    mirror_stream_url TEXT NOT NULL DEFAULT ''
)
```

`init_db` seedt deze tabel bij het aanmaken (rij ontbreekt nog) door
rechtstreeks `os.environ.get("MQTT_HOST", ...)` etc. te lezen, met exact
dezelfde variabelenamen/defaults als `config.get_settings()` nu al gebruikt
voor deze velden — een eenmalige bootstrap-lezing, losstaand van de
(hieronder verkleinde) `Settings`-dataclass, zodat een bestaande deploy bij
het updaten niet leegloopt zonder eerst de nieuwe pagina te bezoeken. Daarna
is de database leidend; deze env vars worden voor deze velden verder
genegeerd (geen laag-op-laag-precedentie — dat zou "waarom verandert mijn
UI-wijziging niks" opleveren als de env var toevallig ook nog gezet is).

### `admin/app/config.py`

`Settings`-dataclass verliest `mqtt_host/port/user/pass`, `ha_url`,
`ha_token` (die horen nu bij de DB-backed runtime-settings, niet bij de
proces-opstart-settings). Blijft: `admin_password`, `db_path`, `media_dir`,
`port`, `log_dir`.

### Nieuw: `admin/app/runtime_settings.py`

Analoog aan `read_schedule` in `routers/schedule.py`:

- `read_runtime_settings(conn) -> RuntimeSettings` (dataclass met de 7
  velden hierboven).
- `write_runtime_settings(conn, **updates)` — partiële update; `mqtt_pass`/
  `ha_token` alleen overschrijven als de aanroeper een niet-lege waarde
  meestuurt (leeg/afwezig = "laat ongewijzigd").

`app.state.runtime_settings` wordt bij opstart gevuld met
`read_runtime_settings(app.state.db)` en na elke succesvolle `PUT
/api/settings` in-place bijgewerkt — dit is het object dat `MqttBridge` en
`routers/ha.py` voortaan gebruiken in plaats van (delen van) `app.state
.settings`.

### `admin/app/mqtt_bridge.py`

De constructor neemt voortaan `runtime_settings` (i.p.v. de nu verkleinde
`settings`) als bron voor `mqtt_host/port/user/pass` — `main.py`'s
`MqttBridge(...)`-aanroep in `create_app` verandert mee. Nieuwe methode
`reconfigure(runtime_settings)`: `loop_stop()` +
`disconnect()` op de bestaande client, credentials bijwerken
(`username_pw_set` opnieuw of overslaan als geen user), dan `start()`
opnieuw met de nieuwe host/port. Enkel-gebruiker hobbytool, dus geen
lock/race-bescherming nodig voor het geval iemand twee keer snel achter
elkaar opslaat — ponytail: laatste `PUT` wint, geen wachtrij.

### Nieuw: `admin/app/routers/settings.py`

- `GET /api/settings` → `{mqtt_host, mqtt_port, mqtt_user, ha_url,
  mirror_stream_url, mqtt_pass_set: bool, ha_token_set: bool}` — de twee
  secrets zelf komen nooit terug, alleen of ze gezet zijn (voor de
  placeholder-tekst in de UI, "•••• (ingesteld)" vs. leeg).
- `PUT /api/settings` → body met dezelfde velden, secrets optioneel. Valideert
  `mqtt_port` (1–65535) en dat `ha_url`/`mirror_stream_url` met `http(s)://`
  beginnen als niet-leeg — zelfde soort lichte validatie als
  `schedule.py`'s tijd-regex, niets zwaarders. Schrijft naar de DB, ververst
  `app.state.runtime_settings`, roept `app.state.bridge.reconfigure(...)`
  aan, geeft `{"ok": true}` terug.

### Frontend (`admin/frontend/src/`)

- `api/settings.ts` — `getSettings()` / `putSettings(partial)`, zelfde
  vorm als `api/schedule.ts`.
- `pages/SettingsPage.tsx` + `.css` — formulier met dezelfde
  sectie-kaartstijl als de andere pagina's (frontend-design-skill voor de
  uitwerking, geen nieuw stijlsysteem). Wachtwoord/token-velden tonen een
  placeholder als ze al gezet zijn en laten "leeg = ongewijzigd" expliciet
  zien in de helptekst.
- Nieuwe route `/settings` + navigatie-item "Instellingen" in
  `Layout.tsx`/`App.tsx`, zelfde patroon als de bestaande vijf.
- `MirrorPage.tsx`: `const STREAM_URL = import.meta.env
  .VITE_MIRROR_STREAM_URL ?? ""` wordt vervangen door een waarde uit
  `getSettings()`, opgehaald op dezelfde manier als de bestaande
  `getMirrorConfig()`-call. De foutmelding-tekst ("... is niet ingesteld
  bij het bouwen van de frontend") wordt "... is nog niet ingesteld op de
  Instellingen-pagina".

## Data flow

**MQTT-verbinding wijzigen voor een test-sessie met een echte spiegel**
1. Gebruiker vult host/port (en evt. user/pass) in op `/settings`, klikt
   opslaan.
2. `PUT /api/settings` valideert, schrijft naar `app_settings`, ververst
   `app.state.runtime_settings`.
3. `bridge.reconfigure(...)` verbreekt de oude broker-verbinding en
   verbindt met de nieuwe — binnen enkele seconden zichtbaar aan
   nodes/logs die weer binnenkomen, zonder dat de beheerpagina zelf herstart.

**Mirror-stream-URL instellen**
1. Gebruiker vult de URL van de mirror-node's MJPEG-stream in, slaat op.
2. Volgende keer dat `/mirror` geladen wordt (of na een refresh) haalt
   `MirrorPage` de URL op via `GET /api/settings` in plaats van een
   ingebakken build-waarde — geen `docker compose build` meer nodig.

## Foutafhandeling

- Ongeldige `mqtt_port`/url-vorm: `400` met duidelijke Nederlandse melding,
  zelfde stijl als `schedule.py`.
- Nieuwe MQTT-instellingen kloppen niet (verkeerd wachtwoord, onbereikbare
  host): `reconfigure` faalt asynchroon net als de bestaande `_on_connect`
  rc-afhandeling nu al doet (gelogd, geen crash) — de `PUT` zelf slaagt
  altijd als de invoer geldig was; het bestaande dashboard laat via
  node-status zien of het écht verbonden is. Geen synchrone
  connectiviteitstest bij opslaan (zie Niet-doelen).

## Testen

- Backend: pytest voor `read_runtime_settings`/`write_runtime_settings`
  (seed-gedrag, partiële update, "leeg = ongewijzigd" voor secrets) en de
  router (validatie, dat `GET` nooit een secret-waarde teruggeeft) — zelfde
  aanpak als de bestaande `schedule`-tests.
- `MqttBridge.reconfigure`: test met een nep-paho-client (zoals de
  bestaande bridge-tests) dat disconnect/reconnect met de juiste nieuwe
  credentials gebeurt.
- Frontend: TypeScript-check bij het bouwen; geen nieuwe E2E-suite,
  consistent met de rest van het project.

## Migratie (impact op bestaand werk)

- `Dockerfile`: `ARG VITE_MIRROR_STREAM_URL` + bijbehorende `ENV`-regel in
  de frontend-build-stage vervallen — niet meer nodig zodra de waarde
  runtime uit de API komt.
- `docker-compose.yml`: `args: VITE_MIRROR_STREAM_URL: ...` onder `build`
  vervalt.
- `.env.example` / `admin/frontend/.env.example`: `VITE_MIRROR_STREAM_URL`
  wordt verwijderd; `MQTT_*`/`HA_*` regels blijven staan met een
  toelichting dat ze alleen als eerste-opstart-seed dienen en daarna via de
  Instellingen-pagina beheerd worden.
- `README.md`: Docker- en systemd-secties bijwerken — de waarschuwing over
  "wijzig je 'm, dan moet je `docker compose build` draaien" bij
  `VITE_MIRROR_STREAM_URL` klopt niet meer en wordt vervangen door een
  verwijzing naar de Instellingen-pagina.
