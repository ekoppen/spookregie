# Voortuin Halloween-ervaring

Motion-getriggerde audio/video-ervaring voor de voortuin. Een **mirror-node**
(computer + USB-camera + beamer) filmt bezoekers bij het raam, draait het beeld
door een spook-effect en rear-projecteert dat op de ruit. Eén of meer
**scare-nodes** (Raspberry Pi + PIR + speaker) spelen willekeurige geluiden af,
zowel op hun eigen PIR als (met 0-2s random delay) op een mirror-trigger.
Home Assistant is de losse coördinatielaag: MQTT-broker, dashboard en de
WLED-koppeling; het tijdvenster zit in de beheerpagina-backend (`admin/`),
die als enige `system/sleep` publiceert. Elke node blijft zelfstandig werken als
MQTT/HA wegvalt. Volledig ontwerp: `docs/superpowers/specs/`.

## Layout

| Map | Inhoud |
|---|---|
| `shared/` | MQTT-topiccontract (`mqtt_contract.py`) en logging-opzet, gedeeld door beide nodes |
| `mirror_node/` | Camera + trigger + ghost-effect + beamer-output, plus systemd-unit |
| `scare_node/` | PIR + audio-afspelen + cooldown, plus systemd-unit |
| `admin/` | Beheerpagina-backend (FastAPI): media, config, tijdvenster, noodstop, plus systemd-unit |
| `home_assistant/` | Automations (WLED) — zie `home_assistant/README.md` |
| `tests/` | Pytest-suite over de pure logica (geen hardware nodig) |

## Tests draaien

```bash
pip install -r requirements-dev.txt
pytest tests/
```

De tests dekken alleen de pure logica (topics, effect, trigger, cooldown,
playback-keuze). Fysieke effecten test je met de self-check hieronder.

## Self-check per node

```bash
python3 -m mirror_node.main --selfcheck   # pakt 1 frame, toont/bewaart ghost-beeld
python3 -m scare_node.main --selfcheck    # speelt 1 fragment af, publiceert testbericht
```

Beide werken zonder bereikbare MQTT-broker; de scare-check werkt ook zonder
aangesloten PIR.

## Environment-variabelen

Beide nodes:

| Variabele | Default | Betekenis |
|---|---|---|
| `MQTT_HOST` | `homeassistant.local` | Broker-hostname |
| `MQTT_PORT` | `1883` | Broker-poort |
| `MQTT_USER` | *(leeg)* | Optioneel; alleen ingesteld als niet leeg |
| `MQTT_PASS` | *(leeg)* | Wachtwoord bij `MQTT_USER` |
| `LOG_DIR` | `./logs` | Map voor lokale logbestanden; systemd zet dit op `/var/log/halloween` |
| `BACKEND_URL` | `http://localhost:8000` | Beheerpagina-backend waar media-bestanden (`GET /api/media/<hash>`) vandaan komen |

Alleen mirror-node:

| Variabele | Default | Betekenis |
|---|---|---|
| `MIRROR_CAMERA_INDEX` | `0` | OpenCV camera-index |
| `MIRROR_ACTIVE_SECONDS` | `6` | Hoe lang het effect na een trigger aanblijft |
| `MIRROR_MEDIA_CACHE_DIR` | `./media_cache` | Schrijfbare map voor opgehaalde overlays; systemd zet dit op `/var/lib/halloween/media_cache` |
| `MIRROR_STREAM_PORT` | `8091` | Poort van de MJPEG-live-preview (`/stream`) |

Alleen scare-node:

| Variabele | Default | Betekenis |
|---|---|---|
| `SCARE_ZONE` | `zone-a` | **Per fysieke node uniek maken** (zone-a, zone-b, ...) |
| `SCARE_MEDIA_DIR` | `/opt/halloween/media` | Map met `.wav`-bestanden (alleen wav: `aplay` kan geen mp3) |
| `SCARE_PIR_PIN` | `4` | GPIO-pin van de PIR-sensor |
| `SCARE_COOLDOWN_SECONDS` | `12` | Minimale tijd tussen twee scares |
| `SCARE_MEDIA_CACHE_DIR` | `./media_cache` | Schrijfbare map voor van de backend opgehaalde audio; systemd zet dit op `/var/lib/halloween/media_cache` |

Alleen de beheerpagina-backend (`admin/`):

| Variabele | Default | Betekenis |
|---|---|---|
| `ADMIN_PASSWORD` | **geen** — verplicht | Wachtwoord voor de beheerpagina. Zonder deze variabele start de backend niet (bewust geen standaardwaarde) |
| `MQTT_HOST` / `MQTT_PORT` / `MQTT_USER` / `MQTT_PASS` | zie tabel hierboven | Dezelfde broker als de nodes |
| `LOG_DIR` | `./logs` | Map voor logbestanden (`beheerpagina.log`); systemd zet dit op `/var/log/halloween` |
| `ADMIN_DB_PATH` | `./admin.db` | SQLite-bestand met config/media-index; systemd zet dit op `/var/lib/halloween/admin.db` |
| `ADMIN_MEDIA_DIR` | `./media_store` | Map met geüploade media (bestandsnaam = content-hash); systemd zet dit op `/var/lib/halloween/media_store` |
| `ADMIN_PORT` | `8000` | Poort van de beheerpagina; de nodes halen hier hun media op (`BACKEND_URL`) |
| `HA_URL` | `http://homeassistant.local:8123` | Home Assistant voor WLED-status/bediening |
| `HA_TOKEN` | *(leeg)* | Long-lived access token uit je HA-profiel; leeg laat de HA-proxy zonder resultaat |

De mirror-node luistert op `MIRROR_STREAM_PORT` (standaard 8091) voor de
live-preview. Die poort moet bereikbaar zijn vanaf de machine/browser waarop je
de beheerpagina bekijkt — open hem dus in een eventuele firewall.

## Deployment

De systemd-units gaan uit van de code in `/opt/halloween`, logs in
`/var/log/halloween` (aangemaakt via `LogsDirectory=`) en een mediacache in
`/var/lib/halloween/media_cache` (aangemaakt via `StateDirectory=`).

```bash
sudo mkdir -p /opt/halloween
sudo rsync -a ./ /opt/halloween/          # of: git clone naar die map
sudo cp scare_node/scare-node.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now scare-node
```

Voor mirror-node hetzelfde met `mirror_node/mirror-node.service`.

Aanpassen vóór installatie:

- **`scare-node.service`:** `SCARE_ZONE` per Pi uniek zetten. Twee nodes met
  dezelfde zone delen hetzelfde MQTT client-id en gooien elkaar er continu uit.
  Ook `SCARE_PIR_PIN` en `SCARE_MEDIA_DIR` controleren.
- **`mirror-node.service`:** `User=halloween` en `XAUTHORITY` naar de
  gebruiker die de desktop-/X-sessie draait. De node heeft een draaiende
  X-sessie nodig (`DISPLAY=:0`) voor de beamer-output.
- Draait de broker met authenticatie, voeg dan
  `Environment=MQTT_USER=...` en `Environment=MQTT_PASS=...` toe.

### Beheerpagina-backend

De backend draait op één machine (mag dezelfde zijn als een node) en is de
enige die `system/sleep` publiceert — installeer de oude HA-tijdvenster-
automation dus niet meer.

```bash
sudo python3 -m pip install -r admin/requirements.txt
cd admin/frontend && npm install && npm run build && cd ../..
sudo cp admin/admin-backend.service /etc/systemd/system/
sudoedit /etc/systemd/system/admin-backend.service   # ADMIN_PASSWORD zetten!
sudo systemctl daemon-reload && sudo systemctl enable --now admin-backend
```

`ADMIN_PASSWORD` is verplicht: zonder die variabele stopt de service direct
met een `RuntimeError`. Zet `BACKEND_URL` in de node-units op
`http://<backend-host>:8000` zodat de nodes hun media kunnen ophalen.

De `npm run build`-stap zet `admin/frontend/dist/` neer; de backend serveert
die map zelf mee (geen aparte webserver nodig), dus na het starten van de
service is de beheerpagina bereikbaar op `http://<backend-host>:<ADMIN_PORT>/`
(standaard poort 8000).

## MQTT-topics

Alle namen komen uit `shared/mqtt_contract.py`:

| Topic | Richting | Payload |
|---|---|---|
| `mirror/triggered` | mirror-node → | `{"ts": ...}` |
| `scare/<zone>/triggered` | scare-node → | `{"ts": ...}` |
| `system/sleep` | backend → nodes | `on` / `off` (retained) |
| `log/<node>` | nodes → | JSON-logregels |
| `status/<node>` | nodes → | `online` / `offline` (retained, last-will) |

HA-kant (broker, automations, dashboard-sensoren): zie
[`home_assistant/README.md`](home_assistant/README.md).
