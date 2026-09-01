# Camera-apparaatrol — ontwerp

Datum: 2026-09-01
Status: goedgekeurd, klaar voor implementatieplan

## Aanleiding

`spookregie` kent tot nu toe één soort self-registering apparaat: een
"mirror-node" (via `deploy/install-agent.sh` geinstalleerd), dat
`mirror_node.main` (GUI-venster voor de beamer-output) en
`mirror_node.agent` (check-in bij de backend, output-koppeling) draait.

Een camera is tot nu toe alleen een `sources`-rij met een handmatig
ingevoerde `value` (netwerk-URL of lokale apparaat-index). Dat werkt,
maar:

- een lokale index (bijv. `0`) werkt alleen voor de machine die de
  camera fysiek heeft aangesloten — zowel mirror-node elders in het
  netwerk als de admin-backend's voorbeeldpaneel (`preview.py`, draait
  op de backend-host) kunnen zo'n index niet gebruiken;
- er is geen manier om een camera als zelfstandig, zichtbaar apparaat
  te beheren (online/offline-status, welke stream-URL 'ie serveert).

Concrete aanleiding: een Raspberry Pi (Hallo1) combineert nu
mirror-node + lokaal aangesloten camera; de gebruiker wil daarnaast een
losse MacBook puur als camera-server inzetten voor een andere
player/source. Eén apparaat moet ook beide rollen tegelijk kunnen
hebben (zoals Hallo1 nu al doet).

## Doel

Een apparaat kan zich melden met twee onafhankelijke, niet-exclusieve
capabilities:

- **mirror** — draait `mirror_node.main` (GUI-beamer-output) +
  `mirror_node.agent`, wordt in Apparaten aan een **Output** gekoppeld
  (bestaand gedrag, ongewijzigd).
- **camera** — draait een lichtgewicht MJPEG-streaming-server voor een
  lokaal aangesloten camera + `mirror_node.agent`, rapporteert zijn
  eigen stream-URL, en wordt (via een handmatige, niet-blijvende
  actie) gekoppeld aan een **Source**.

Een apparaat kan beide vlaggen hebben (zoals Hallo1).

## Datamodel

`devices` krijgt drie nieuwe kolommen, via het bestaande
`_ensure_column`-migratiepatroon (zie `admin/app/db.py`, zelfde aanpak
als eerder bij `players.audio_source_id`):

```
is_mirror INTEGER NOT NULL DEFAULT 1
is_camera INTEGER NOT NULL DEFAULT 0
camera_stream_url TEXT
```

`camera_stream_url` wordt bij elke check-in overschreven (net als
`git_sha`/`last_seen_at` nu al) — géén apart live-only mechanisme zoals
de online/offline-status (die loopt via een MQTT-retained topic omdat
het over verbinding gaat, niet over een door het apparaat gerapporteerd
feit). Voor een apparaat zonder camera-rol blijft de kolom `NULL`.

Bestaande apparaten blijven dus ongewijzigd mirror-only na de migratie
— geen datamigratie-stap nodig, alleen de kolom-default.

Geen wijziging aan `sources`, `outputs`, of enige andere tabel. Er komt
**geen** foreign key tussen `devices` en `sources` — de koppeling is een
eenmalige, kopiërende actie (zie "UI: Apparaten" hieronder), geen
levende relatie. Dat vermijdt sync-logica voor IP-wijzigingen; het
IP-drift-risico (zie "Niet-doelen") is expliciet geaccepteerd.

## Agent: rolrapportage

`mirror_node/agent.py`'s check-in-payload krijgt twee velden erbij:
`is_mirror` en `is_camera`, gelezen uit nieuwe env-vars
`SPOOKREGIE_IS_MIRROR` / `SPOOKREGIE_IS_CAMERA` (`"1"`/`"0"`,
ontbrekend → default `is_mirror=1`, `is_camera=0`, backward compatible
met bestaande installaties zonder deze vars).

Is `is_camera` waar, dan rapporteert de check-in ook een
`camera_stream_url` (`http://<eigen-LAN-ip>:${CAMERA_SERVER_PORT:-8080}/stream`)
— het eigen IP bepaalt de agent zelf (simpelste implementatie: een
UDP-socket naar de MQTT-broker openen en het lokale `getsockname()`-IP
aflezen, zonder een pakket te hoeven versturen).

`admin/app/routers/devices.py`'s check-in-handler slaat `is_mirror`,
`is_camera` en `camera_stream_url` op in de bijbehorende kolommen (zie
"Datamodel" hierboven).

## Nieuwe component: `mirror_node/camera_server.py`

- Opent de lokale camera via de bestaande `open_camera()`
  (`mirror_node/camera.py`) — dezelfde bron-resolutie (kaal getal →
  lokale index) als mirror-node al gebruikt.
- Leest frames in een loop, serveert ze als
  `multipart/x-mixed-replace` MJPEG via Python's ingebouwde
  `http.server` op poort `CAMERA_SERVER_PORT` (default **8080**,
  zelfde configureerbaarheid-patroon als `MIRROR_STREAM_PORT` elders
  in het project), endpoint `GET /stream`.
- Geen authenticatie — zelfde "vertrouwd LAN"-uitgangspunt dat de rest
  van het project al hanteert (MQTT zonder verplichte auth,
  `/api/node-config` zonder sessie).
- Camera-open-fouten: loggen en blijven retryen (zelfde patroon als
  mirror-node's bestaande `_reopen_capture_after_failures`), nooit de
  service laten crashen.
- Draait als eigen proces/service, los van `mirror_node.main` (geen
  GUI-afhankelijkheid) en los van `mirror_node.agent` (die blijft
  alleen check-in doen).

Geen nieuwe dependency: gebruikt `cv2` (al in
`mirror_node/requirements.txt`) en de Python-stdlib `http.server`.

## `deploy/install-agent.sh`

Twee nieuwe ja/nee-vragen, vroeg in het script (na platform-detectie,
vóór de service-installatie):

```
Draait hier een mirror/beamer? [J/n]
Draait hier een camera? [j/N]
```

Validatie: minstens één moet ja zijn. Antwoorden worden weggeschreven
als `SPOOKREGIE_IS_MIRROR=1`/`0` en `SPOOKREGIE_IS_CAMERA=1`/`0` in het
bestaande env-bestand.

Op basis van de antwoorden:

- **mirror=ja:** ongewijzigd huidig gedrag — DISPLAY/XAUTHORITY-vragen
  (Linux), `spookregie-mirror`-service/LaunchAgent.
- **mirror=nee:** DISPLAY/XAUTHORITY-vragen worden overgeslagen, geen
  `spookregie-mirror`-service.
- **camera=ja:** nieuwe `spookregie-camera`-service/LaunchAgent
  (`python -m mirror_node.camera_server`), zelfde
  systemd-(Linux)/launchd-(macOS)-route als de bestaande services.
- **camera=nee:** geen camera-service.
- **`spookregie-agent`:** altijd geinstalleerd, ongeacht de combinatie
  (dat is de enige service die er sowieso al was voor check-in/
  output-koppeling).

De bestaande `libgl1`-installatiestap (Linux) blijft alleen relevant
voor de mirror-rol (cv2's GUI-venster) — camera-only-installaties
slaan die stap over indien mirror=nee.

## UI: Apparaten

Elke apparaat-rij toont voortaan de secties die bij zijn
gerapporteerde vlaggen horen:

- **is_mirror:** de bestaande output-picker (ongewijzigd).
- **is_camera:** de zelf-gerapporteerde stream-URL, read-only, plus
  een knop **"Maak hiervan een source"** — client-side actie die
  `POST /api/sources` aanroept met die URL vooringevuld
  (`kind: "camera_stream"`), gebruikmakend van het al bestaande
  endpoint. Geen nieuw backend-endpoint. Na aanmaken is het een heel
  normale, los bewerkbare Source — geen blijvende koppeling.
- Een apparaat met beide vlaggen toont beide secties onder elkaar.

## UI: Sources

Geen wijziging aan de pagina zelf. Het vrije-tekstveld voor
`camera_stream`-sources bestaat al; door de camera-rol wordt het
vaker al correct vooringevuld in plaats van handmatig getypt.

## Niet-doelen

- **Geen IP-drift-bescherming.** De aangemaakte Source bevat een kaal
  IP-adres; als DHCP dat later wijzigt, wordt de Source stil incorrect.
  Expliciet geaccepteerd risico (zelfde risico dat er al was vóór dit
  ontwerp). Geen mDNS-hostnaam, geen achtergrond-sync.
- **Geen blijvende device↔source-koppeling/foreign key.** De "maak
  hiervan een source"-actie is eenmalig kopiërend.
- **Geen authenticatie op de MJPEG-stream.**
- **Geen wijziging aan het bestaande mirror/output-koppelmodel** —
  alleen uitgebreid met een parallelle camera/source-koppeling.
- **Geen arbitrage tussen mirror en camera voor dezelfde fysieke
  camera.** Een apparaat met beide vlaggen (zoals Hallo1) en maar één
  lokaal aangesloten camera mag de mirror-source **niet** op de ruwe
  lokale index laten wijzen — dan openen `mirror_node/main.py` (via
  zijn lokale-camera-fallback) en `mirror_node/camera_server.py`
  allebei hetzelfde apparaat, wat op Linux/V4L2 typisch resulteert in
  een stille `EBUSY` voor wie als tweede opent. In plaats daarvan moet
  de mirror-source voor zo'n apparaat wijzen naar
  `http://127.0.0.1:<CAMERA_SERVER_PORT>/stream` (default poort 8080)
  — de eigen camera-server, zodat alleen `camera_server.py` het
  fysieke apparaat aanraakt en `mirror_node.main` de camera als een
  gewone netwerkbron consumeert. Dit is een operator-/
  deploymentstap (in te stellen op de Sources-pagina), geen door de
  software afgedwongen check — bewuste keuze, zie de inleiding over
  een kleine, single-maintainer-fleet.

