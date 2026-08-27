# Mirror-node starten/stoppen vanaf de Spiegel-pagina — Design

**Datum:** 2026-08-27
**Status:** Goedgekeurd, klaar voor implementatieplan
**Vervolg op:** `2026-08-27-mirror-camera-source-design.md`

## Doel

`mirror_node` kan nu (dankzij `MIRROR_HEADLESS`) draaien zonder fysieke
beamer, puur om het spiegeleffect te ontwerpen/testen tegen een
netwerkcamera. Dat proces moet je nu handmatig via SSH starten. Deze
feature voegt een Start/Stop-knop + live logpaneel toe aan de
Spiegel-pagina, zodat je tijdens het ontwerpen niet steeds hoeft in te
loggen op de server.

## Niet-doelen

- **Geen beheer van de echte productie-node.** De uiteindelijke installatie
  (Raspberry Pi + beamer, via `mirror-node.service`/systemd) blijft volledig
  los hiervan — dit is uitsluitend een ontwikkel/test-gemak. `MIRROR_HEADLESS`
  wordt door dit nieuwe subprocess altijd geforceerd op `1`.
- **Geen aparte container of Docker-socket.** Overwogen en expliciet
  afgewezen (zie brainstorm): het beheer-image krijgt de `mirror_node`-code
  en -dependencies erbij en start het als kindproces van zichzelf — geen
  extra rechten (Docker-socket-mount) nodig.
- **Geen meerdere gelijktijdige instanties.** Eén globale aan/uit-toggle;
  nogmaals starten terwijl het al draait is een no-op, geen fout.
- **Geen automatisch herstarten bij een crash.** Als het kindproces zelf
  stopt (bv. `cap.isOpened()` faalt direct bij een verkeerde RTSP-URL),
  blijft de status "gestopt" tot de beheerder opnieuw op Start drukt. Geen
  supervisor-logica — dat hoort bij de echte systemd-service, niet hier.
- **Geen wijziging aan `scare_node` of de echte `mirror-node.service`.**

## Architectuur

Zelfde container, nieuw subprocess. De beheerpagina-backend krijgt de
`mirror_node`-dependencies (`opencv-python-headless`, `numpy` — `paho-mqtt`
zit al in `admin/requirements.txt`) en de `mirror_node/`-broncode in zijn
image, en start `python -m mirror_node.main` als kindproces van zichzelf via
`subprocess.Popen`, met `MIRROR_HEADLESS=1` en de huidige runtime-settings
als omgevingsvariabelen. `BACKEND_URL` wijst naar zichzelf
(`http://localhost:8000`), dus het kindproces haalt `mirror_camera_source`
op dezelfde manier op als een echte node zou doen — geen aparte
config-doorgeefluik nodig.

```
┌─────────────────────────────────────┐
│ Spiegel-pagina                          │
│  [Start] [Stop]   status: draait        │
│  ┌─ logpaneel ─────────────────────┐    │
│  │ 19:00:04 mirror-node gestart      │    │
│  │ 19:02:03 mirror triggered          │    │
│  └───────────────────────────────┘    │
└──────────────┬───────────────────────┘
       POST /api/mirror-node/start|stop
       GET  /api/mirror-node/status
               │
┌──────────────▼───────────────────────┐
│ Beheerpagina-backend (Docker)           │
│  MirrorProcessManager                    │
│   - subprocess.Popen(mirror_node.main)   │
│   - achtergrondthread leest stdout       │
│   - elke regel → ws_hub.broadcast(       │
│       {"type":"log",                     │
│        "topic":"process/mirror-node",    │
│        "payload": regel})                │
└──────────────┬───────────────────────┘
        (zelfde WebSocket die
         dashboard/logs al gebruiken)
               │
┌──────────────▼───────────────────────┐
│ Browser: useWebSocket-hook (bestaand)    │
│  filtert op topic "process/mirror-node"  │
└───────────────────────────────────────┘
```

Dit hergebruikt de bestaande `WebSocketHub`/`useWebSocket`-infrastructuur
(nu gevoed door MQTT-logberichten) één op één voor een nieuwe bron
(subprocess-stdout) — geen nieuw polling-mechanisme, geen nieuwe
frontend-transportlaag. Het vangt ook opstartfouten/crashes op die nóóit via
MQTT zouden binnenkomen (die route werkt pas ná een geslaagde
broker-verbinding).

## Componenten

### Backend: `admin/app/mirror_process.py` (nieuw)

`MirrorProcessManager`, met een referentie naar `runtime_settings` (voor
MQTT-credentials) en `ws_hub`+`loop` (voor logregels — zelfde constructor-
patroon als `MqttBridge`):

- `start() -> dict`: als er al een levend kindproces is (`self._proc is not
  None and self._proc.poll() is None`), niets doen en de huidige status
  teruggeven. Anders: `subprocess.Popen([sys.executable, "-m",
  "mirror_node.main"], env={**os.environ,
  "MIRROR_HEADLESS": "1", "MQTT_HOST": settings.mqtt_host, "MQTT_PORT":
  str(settings.mqtt_port), "MQTT_USER": settings.mqtt_user, "MQTT_PASS":
  settings.mqtt_pass, "BACKEND_URL": "http://localhost:8000", "LOG_DIR":
  "/data/logs"}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
  text=True, bufsize=1)`, en een achtergrondthread starten die regelsgewijs
  leest en doorstuurt (zie hieronder). Geeft `{"running": True, "pid":
  <pid>}` terug.
- `stop() -> dict`: als er geen levend proces is, niets doen. Anders:
  `proc.terminate()`, tot 5s wachten (`proc.wait(timeout=5)`), bij timeout
  `proc.kill()`; de leesthread stopt vanzelf zodra de pipe sluit (EOF). Geeft
  `{"running": False, "pid": None}` terug.
- `status() -> dict`: `{"running": self._proc is not None and
  self._proc.poll() is None, "pid": self._proc.pid if running else None}`.
  Dit detecteert ook een proces dat zelfstandig is gestopt (bv. foute
  RTSP-URL) — geen aparte crash-melding nodig, de status springt gewoon
  terug naar "gestopt".
- Leesthread: `for line in self._proc.stdout: <broadcast via ws_hub>` —
  zelfde `asyncio.run_coroutine_threadsafe(ws_hub.broadcast({"type": "log",
  "topic": "process/mirror-node", "payload": line.rstrip()}), loop)`-patroon
  als `MqttBridge._broadcast_to_websockets`. Geen buffering/geschiedenis
  nodig: een nieuwe browser-sessie ziet vanaf dat moment nieuwe regels, niet
  de historie — consistent met hoe de bestaande Logs-pagina nu ook al werkt
  (live-only, geen backlog via WebSocket).

### Backend: `admin/app/routers/mirror_process.py` (nieuw)

- `POST /api/mirror-node/start` → `manager.start()`
- `POST /api/mirror-node/stop` → `manager.stop()`
- `GET /api/mirror-node/status` → `manager.status()`

Alle drie vereisen een ingelogde sessie (zelfde auth-dependency als
`PUT /api/settings` — geen publiek endpoint, in tegenstelling tot
`/api/node-config`: dit start/stopt een proces, dat is een ander
risiconiveau dan config uitlezen).

### `admin/app/main.py`

`create_app()`: `app.state.mirror_process = MirrorProcessManager(settings,
ws_hub=app.state.ws_hub)` (loop wordt, net als bij `bridge`, pas in
`_startup()` gezet — zelfde bekende FastAPI-volgorde-reden). `_shutdown()`
krijgt een extra regel: `app.state.mirror_process.stop()`, zodat een
backend-herstart nooit een wees-kindproces achterlaat dat MQTT/camera bezet
houdt.

### Docker

`admin/requirements.txt` krijgt twee pins erbij, met een reden-comment:
`opencv-python-headless==4.9.0.80` en `numpy==1.24.4` — bewust deze exacte,
onderling compatibele oudere versies (niet de nieuwste): lan01 (de huidige
deploy-target) is een KVM-VM met een CPU-model dat geen SSSE3 aanbiedt, en
recente numpy-wheels (≥1.25-stijl) weigeren te laden op zo'n CPU
(`RuntimeError: NumPy was built with baseline optimizations ... X86_V2`).
Deze combinatie is al handmatig geverifieerd te werken (import + echte
array-encode/decode) op lan01.

`Dockerfile` krijgt `COPY mirror_node/ ./mirror_node/` naast de bestaande
`COPY shared/`/`COPY admin/app/`-regels, en de bovenste toelichtings-comment
wordt aangepast: niet langer "mirror-node en scare-node horen hier bewust
niet bij", maar iets als "dit image bevat ook `mirror_node`'s code, alleen
om 'm headless als test-/ontwerp-hulpmiddel te kunnen starten vanaf de
Spiegel-pagina — de échte node-deployment (Pi + beamer + systemd) blijft
hier volledig los van staan."

### Frontend: `admin/frontend/src/api/mirrorProcess.ts` (nieuw)

Drie functies (`startMirrorProcess`, `stopMirrorProcess`,
`getMirrorProcessStatus`), zelfde `fetch`-met-credentials-patroon als
`admin/frontend/src/api/settings.ts`.

### Frontend: `admin/frontend/src/pages/MirrorPage.tsx`

- Nieuwe state: `running: boolean`, `logLines: string[]` (cap op bv. 200
  regels — `slice(-200)` bij elke append, voorkomt onbegrensde groei tijdens
  een lange sessie).
- `useEffect` bij mount: `getMirrorProcessStatus()` om de knop-state te
  initialiseren (bv. na een pagina-refresh terwijl het al draaide).
- `useWebSocket`-hook (al gebruikt op andere pagina's, hier voor het eerst
  op MirrorPage): callback filtert `msg.type === "log" && msg.topic ===
  "process/mirror-node"` en append't `msg.payload` aan `logLines`.
- Start/Stop-knop (disabled tijdens de fetch, zelfde patroon als de
  bestaande `saving`/`testing`-knoppen op deze pagina) + een simpel
  scrollbaar `<pre>`-logpaneel, geplaatst naast de bestaande live-preview
  (`<img src={streamUrl}>`).

## Foutafhandeling

- **Start terwijl al draait / stop terwijl al gestopt:** idempotent, 200
  met de huidige status — geen foutmelding (zie Niet-doelen).
- **RTSP-URL leeg of fout bij start:** het kindproces start wel (subprocess
  spawnt altijd), maar `main()` retourneert meteen als `cap.isOpened()`
  faalt — de eerste logregel legt dat al uit (`"Kon camera-bron niet
  openen: ..."`, credentials al geredact via de bestaande
  `_redact_source`), en `status()` toont kort daarna weer "gestopt". Geen
  aparte foutcode nodig, het logpaneel + status samen zijn voldoende
  signaal.
- **Backend zelf herstart terwijl het kindproces draait:** `_shutdown()`
  stopt het kindproces eerst (zie hierboven) — nooit een wees-proces dat de
  RTSP-verbinding of MQTT-client bezet houdt na een container-restart.
- **WebSocket niet verbonden (bv. even een reconnect):** logregels die in
  die periode verschijnen gaan simpelweg verloren voor de UI (consistent
  met hoe de bestaande Logs-pagina al werkt) — het proces zelf blijft
  gewoon draaien, dit is puur een UI-weergavekwestie.

## Beveiliging

Alle drie endpoints vereisen de bestaande sessie-auth (niet publiek, in
tegenstelling tot `/api/node-config`). Er is geen vrije command-execution:
een ingelogde beheerder kan alleen dit ene, vaste, in de codebase
aanwezige commando starten/stoppen — geen parameter uit de request komt in
het gespawnde commando terecht. Dit voegt geen nieuw geheimenlek toe: de
MQTT-credentials die als env var worden meegegeven zaten al in
`runtime_settings` en worden nergens extra gelogd (de credential-redactie
uit `mirror_node/main.py` blijft van kracht voor de RTSP-URL in
logregels).

## Testen

- `MirrorProcessManager`: `subprocess.Popen` wordt in tests gemockt (zoals
  elders in deze suite externe I/O gemockt wordt) — geen echte camera/MQTT
  nodig. Dekken: start spawnt met de verwachte env-variabelen, dubbele
  start is een no-op (geen tweede `Popen`-call), stop terminate't en wacht,
  stop terwijl niets draait is een no-op, status detecteert een
  zelfstandig gestopt proces (`poll()` geeft een exit-code) als "gestopt".
- Routers: FastAPI `TestClient`, zelfde patroon als
  `tests/test_admin_routes_mirror_scare.py` — auth vereist (401 zonder
  sessie), 200 met de verwachte JSON-vorm met sessie.
- Frontend: geen bestaande testinfrastructuur voor componenten in dit
  project (alleen `tsc`+build als kwaliteitscheck, zie eerdere features) —
  dit blijft consistent, geen nieuwe testlaag hiervoor optuigen.
- Handmatige verificatie (zoals bij eerdere features): start/stop via curl
  tegen een lokaal draaiende backend, en één keer écht vanaf lan01 tegen de
  geconfigureerde Reolink-URL, zoals nu al handmatig is gedaan.
