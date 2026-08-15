# Voortuin Halloween-ervaring

Motion-getriggerde audio/video-ervaring voor de voortuin. Een **mirror-node**
(computer + USB-camera + beamer) filmt bezoekers bij het raam, draait het beeld
door een spook-effect en rear-projecteert dat op de ruit. Eén of meer
**scare-nodes** (Raspberry Pi + PIR + speaker) spelen willekeurige geluiden af,
zowel op hun eigen PIR als (met 0-2s random delay) op een mirror-trigger.
Home Assistant is de losse coördinatielaag: MQTT-broker, tijdvenster,
dashboard en de WLED-koppeling. Elke node blijft zelfstandig werken als
MQTT/HA wegvalt. Volledig ontwerp: `docs/superpowers/specs/`.

## Layout

| Map | Inhoud |
|---|---|
| `shared/` | MQTT-topiccontract (`mqtt_contract.py`) en logging-opzet, gedeeld door beide nodes |
| `mirror_node/` | Camera + trigger + ghost-effect + beamer-output, plus systemd-unit |
| `scare_node/` | PIR + audio-afspelen + cooldown, plus systemd-unit |
| `home_assistant/` | Automations (tijdvenster, WLED) — zie `home_assistant/README.md` |
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

Alleen mirror-node:

| Variabele | Default | Betekenis |
|---|---|---|
| `MIRROR_CAMERA_INDEX` | `0` | OpenCV camera-index |
| `MIRROR_ACTIVE_SECONDS` | `6` | Hoe lang het effect na een trigger aanblijft |

Alleen scare-node:

| Variabele | Default | Betekenis |
|---|---|---|
| `SCARE_ZONE` | `zone-a` | **Per fysieke node uniek maken** (zone-a, zone-b, ...) |
| `SCARE_MEDIA_DIR` | `/opt/halloween/media` | Map met `.wav`-bestanden (alleen wav: `aplay` kan geen mp3) |
| `SCARE_PIR_PIN` | `4` | GPIO-pin van de PIR-sensor |
| `SCARE_COOLDOWN_SECONDS` | `12` | Minimale tijd tussen twee scares |

## Deployment

De systemd-units gaan uit van de code in `/opt/halloween` en logs in
`/var/log/halloween` (aangemaakt via `LogsDirectory=`).

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

## MQTT-topics

Alle namen komen uit `shared/mqtt_contract.py`:

| Topic | Richting | Payload |
|---|---|---|
| `mirror/triggered` | mirror-node → | `{"ts": ...}` |
| `scare/<zone>/triggered` | scare-node → | `{"ts": ...}` |
| `system/sleep` | HA → nodes | `on` / `off` (retained) |
| `log/<node>` | nodes → | JSON-logregels |
| `status/<node>` | nodes → | `online` / `offline` (retained, last-will) |

HA-kant (broker, automations, dashboard-sensoren): zie
[`home_assistant/README.md`](home_assistant/README.md).
