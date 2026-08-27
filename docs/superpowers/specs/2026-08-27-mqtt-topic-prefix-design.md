# MQTT-topic-prefix — Design

**Datum:** 2026-08-27
**Status:** Goedgekeurd, klaar voor implementatieplan
**Vervolg op:** `2026-08-27-beheerpagina-instellingen-design.md`

## Doel

Alle MQTT-topics in dit project zijn nu hardcoded, platte strings zonder
namespace (`mirror/triggered`, `status/mirror`, ...). Zodra er een
test-opstelling en de echte installatie op dezelfde broker draaien (precies
het scenario waar de gebruiker nu heen gaat: testen tegen een echt
spiegel-device), delen ze dezelfde topics — een testbericht kan zo de echte
installatie triggeren, of andersom, zonder enige foutmelding. Een instelbaar
topic-prefix lost dat op: één namespace per opstelling, in te stellen op de
Instellingen-pagina, met een default van "" (leeg = huidig, ongewijzigd
gedrag).

## Niet-doelen

- **Geen live-herconfiguratie van nodes.** Een prefix-wijziging op de
  Instellingen-pagina vraagt een herstart van elke node om 'm op te pikken —
  geen polling, geen live push. Bevestigd met de gebruiker: dit is een
  bewuste, gedocumenteerde grens, niet een gemiste eis.
- **Geen wijziging van MQTT-host/poort/credentials via het nieuwe
  node-endpoint.** Dat blijft per node zijn eigen env-var, exact zoals nu.
  Alleen de topic-prefix wordt centraal opgehaald — dat is het enige stuk
  config waarvoor een mismatch stille, onzichtbare gevolgen heeft (een
  verkeerde host geeft een duidelijke connectiefout; een verkeerde prefix
  geeft niets dan stilte).
- **Geen encryptie/authenticatie op het nieuwe `/api/node-config`-endpoint.**
  Een topic-prefix is geen secret (het dient alleen namespacing, niet
  toegangscontrole — dat blijft bij de MQTT-broker-credentials). Zelfde
  vertrouwensniveau als het al-publieke `GET /api/media/<hash>`.
- **Geen wijziging aan `mqtt_state.py` of de frontend.** Door de prefix op
  precies één plek te strippen (bij ontvangst in `MqttBridge._on_message`)
  blijven de node-tracker, de WebSocket-payload en de dashboard/logs-pagina's
  volledig ongemoeid — zij zien nooit een geprefixt topic.

## Architectuur

```
┌─────────────────────────┐        ┌──────────────────────────┐
│ Instellingen-pagina       │─PUT──▶│ /api/settings              │
│ (mqtt_topic_prefix-veld)  │◀─GET──│  runtime_settings.mqtt_    │
└───────────────────────────┘       │  topic_prefix               │
                                     └──────────┬──────────────┘
                                                │ bridge.reconfigure(...)
                                     ┌──────────▼──────────────┐
                                     │ MqttBridge                 │
                                     │  self._topics = Topics(     │
                                     │    prefix=runtime_settings   │
                                     │      .mqtt_topic_prefix)     │
                                     │  _on_message: strip_prefix   │
                                     │    vóór tracker/WS-broadcast  │
                                     └──────────┬──────────────┘
                                                │ GET /api/node-config
                                                │ (publiek, geen auth)
                        ┌───────────────────────┼───────────────────────┐
                        ▼                                                ▼
              ┌───────────────────┐                          ┌───────────────────┐
              │ mirror_node/main.py │                          │ scare_node/main.py  │
              │  bij opstarten:      │                          │  bij opstarten:       │
              │  fetch_topic_prefix(  │                          │  fetch_topic_prefix(   │
              │    BACKEND_URL,        │                          │    BACKEND_URL,          │
              │    env-fallback)        │                          │    env-fallback)          │
              │  topics = Topics(prefix)│                          │  topics = Topics(prefix)  │
              └───────────────────────┘                          └───────────────────────────┘
```

`shared/mqtt_contract.py` levert de `Topics`-klasse die alle drie de
processen gebruiken — één definitie van hoe een prefix wordt toegepast,
nooit losse string-concatenatie op meerdere plekken.

## Componenten

### `shared/mqtt_contract.py` (herschreven)

Vervangt de losse `TOPIC_*`-constanten en `*_topic()`-functies door één
`Topics`-klasse:

```python
class Topics:
    def __init__(self, prefix: str = ""):
        self._prefix = prefix.strip("/")

    def _p(self, topic: str) -> str:
        return f"{self._prefix}/{topic}" if self._prefix else topic

    @property
    def mirror_triggered(self) -> str: return self._p("mirror/triggered")
    @property
    def system_sleep(self) -> str: return self._p("system/sleep")
    @property
    def config_mirror(self) -> str: return self._p("config/mirror")
    @property
    def control_mirror_preview(self) -> str: return self._p("control/mirror/preview")
    @property
    def control_mirror_test(self) -> str: return self._p("control/mirror/test-trigger")
    @property
    def status_wildcard(self) -> str: return self._p("status/+")
    @property
    def log_wildcard(self) -> str: return self._p("log/+")
    @property
    def scare_triggered_wildcard(self) -> str: return self._p("scare/+/triggered")

    def scare(self, zone: str) -> str: return self._p(f"scare/{zone}/triggered")
    def log(self, node: str) -> str: return self._p(f"log/{node}")
    def status(self, node: str) -> str: return self._p(f"status/{node}")
    def config_scare(self, zone: str) -> str: return self._p(f"config/scare/{zone}")
    def control_scare_test(self, zone: str) -> str: return self._p(f"control/scare/{zone}/test-trigger")

    def strip_prefix(self, topic: str) -> str:
        """Geeft het topic terug zonder de geconfigureerde prefix. Voor
        logica die op de kale topic-naam matcht (tracker, WS-broadcast) —
        die code hoeft nooit te weten dát er een prefix is."""
        if self._prefix and topic.startswith(f"{self._prefix}/"):
            return topic[len(self._prefix) + 1:]
        return topic
```

`SLEEP_PAYLOAD_ON`/`SLEEP_PAYLOAD_OFF`/`trigger_payload()` blijven ongewijzigd
— dat zijn payloads, geen topics.

**Validatie van de prefix zelf:** geen `#`/`+` toestaan (MQTT-wildcardtekens
die een topic-structuur zouden corrumperen) — gevalideerd in de
`/api/settings`-router (zie hieronder), niet in `Topics` zelf (die blijft een
kale, altijd-correcte bouwsteen; ongeldige invoer wordt al bij het opslaan
geweerd).

### `shared/logging_setup.py` (ontkoppeld van het contract)

`setup_logging` bouwde intern zelf een `log/<node>`-topic via een import van
`shared.mqtt_contract`. Dat kán straks niet meer kloppen zonder dat deze
module ook de prefix kent — in plaats daarvan krijgt de aanroeper 'm mee:

```python
def setup_logging(node_name, log_dir, mqtt_client=None, mqtt_log_topic=None):
    ...
    if mqtt_client is not None and mqtt_log_topic is not None:
        logger.addHandler(MqttLogHandler(mqtt_client, mqtt_log_topic))
    return logger
```

Verwijdert de `from shared.mqtt_contract import log_topic`-import volledig —
kleine, verdiende ontkoppeling: logging hoeft het topic-contract niet te
kennen. Aanroepers (mirror-node, scare-node) geven `mqtt_log_topic=topics.log(NODE_NAME)`
mee; de backend-aanroep (geen `mqtt_client`) verandert niet.

### Nieuw: `shared/topic_prefix.py`

Analoog aan `ha_client.py`'s `fetch=None`-parameter-patroon (injecteerbaar
voor tests):

```python
def fetch_topic_prefix(backend_url: str, fallback: str, fetch=None, timeout=3) -> str:
    """Haalt de actuele topic-prefix op bij de backend. Lukt dat niet
    (backend onbereikbaar, ongeldig antwoord), dan `fallback` (de lokale
    MQTT_TOPIC_PREFIX-env-var) -- nooit een uitzondering naar de aanroeper,
    consistent met de fail-safe-filosofie van de nodes."""
```

Gebruikt `urllib.request` net als `ha_client._default_fetch`, geen nieuwe
dependency.

### Backend (`admin/app/`)

- `db.py`: `app_settings` krijgt een kolom `mqtt_topic_prefix TEXT NOT NULL DEFAULT ''`.
- `runtime_settings.py`: `RuntimeSettings` krijgt het veld `mqtt_topic_prefix: str`;
  `_env_defaults()` leest `MQTT_TOPIC_PREFIX` (default `""`) — zelfde
  lazy-default-patroon als de rest.
- `mqtt_bridge.py`: `_build_client` blijft ongewijzigd (topics horen niet bij
  de MQTT-client zelf); `MqttBridge` krijgt een `self._topics = Topics(prefix=settings.mqtt_topic_prefix)`,
  opnieuw opgebouwd in zowel `__init__` als `reconfigure`. Alle
  `client.subscribe(...)`/`client.publish(...)`-aanroepen en de
  `_STATUS_WILDCARD`/`_LOG_WILDCARD`/`_SCARE_TRIGGERED_WILDCARD`-module-
  constanten worden vervangen door `self._topics.*`. `_on_message` strip de
  prefix vóórdat het topic naar `self._tracker.handle_message` of
  `self._broadcast_to_websockets` gaat.
- `routers/settings.py`: `GET`/`PUT /api/settings` krijgen het veld
  `mqtt_topic_prefix` (geen secret, dus gewoon in de `GET`-response, geen
  `_set`-boolean-behandeling nodig). `PUT` valideert: geen `#` of `+` in de
  waarde → `400` anders.
- Nieuw: `routers/node_config.py` — `GET /api/node-config`, publiek (zelfde
  aanpak als `_is_public_media_download`, hier gewoon toegevoegd aan
  `_PUBLIC_EXACT_PATHS` in `main.py`), retourneert
  `{"mqtt_topic_prefix": request.app.state.runtime_settings.mqtt_topic_prefix}`.

### Frontend

- `types.ts`: `AppSettings`/`AppSettingsUpdate` krijgen `mqtt_topic_prefix: string`.
- `SettingsPage.tsx`: nieuw veld in het MQTT-paneel, label "Topic-prefix
  (optioneel)", placeholder `bijv. spookregie of test`, helptekst die uitlegt
  dat nodes dit pas bij hun volgende herstart oppikken.

### Nodes (`mirror_node/main.py`, `scare_node/main.py`)

Bij het opstarten, vóór het aanmaken van de MQTT-client:

```python
from shared.topic_prefix import fetch_topic_prefix
from shared.mqtt_contract import Topics

TOPIC_PREFIX_ENV = os.environ.get("MQTT_TOPIC_PREFIX", "")
TOPIC_PREFIX = fetch_topic_prefix(BACKEND_URL, fallback=TOPIC_PREFIX_ENV)
topics = Topics(prefix=TOPIC_PREFIX)
logger.info("MQTT-topic-prefix: %r", TOPIC_PREFIX)
```

Alle bestaande `TOPIC_*`-constanten en `*_topic()`-aanroepen in beide
bestanden (`on_message`-vergelijkingen, `client.subscribe(...)`,
`client.publish(...)`, `client.will_set(...)`) worden vervangen door
`topics.*`. `scare_node`'s `selfcheck()` gebruikt dezelfde fetch-met-
terugval-aanroep voor consistentie (het is toch al de plek die een losse
MQTT-testverbinding opzet).

**Waarom bij opstarten en niet doorlopend:** een node die al draait hoeft
niet ineens van topic te wisselen — dat zou een node midden in een sessie
laten "verdwijnen" voor de rest van het systeem. Een herstart is een
bewuste, expliciete actie; dat is het juiste moment om een nieuwe prefix op
te pikken.

## Data flow

**Prefix instellen vóór een test-sessie**
1. Gebruiker vult "Topic-prefix" in op `/settings` (bijv. `test`), slaat op.
2. `PUT /api/settings` valideert, schrijft naar `app_settings`, ververst
   `app.state.runtime_settings`, roept `bridge.reconfigure(...)` aan — de
   backend praat vanaf nu met `test/...`-topics.
3. Gebruiker herstart de mirror-node (en eventuele scare-nodes) — elke node
   haalt bij het opstarten `GET /api/node-config` op, krijgt `"test"` terug,
   bouwt zijn `Topics("test")` en verbindt/publiceert/abonneert voortaan
   allemaal onder `test/...`.
4. Backend en nodes praten weer met elkaar, nu volledig geïsoleerd van een
   eventuele parallelle opstelling zonder (of met een andere) prefix op
   dezelfde broker.

**Backend onbereikbaar bij node-opstarten**
1. Node kan `GET /api/node-config` niet bereiken (timeout, DNS-fout, non-200).
2. `fetch_topic_prefix` geeft de lokale `MQTT_TOPIC_PREFIX`-env-var terug
   (default `""`), nooit een uitzondering.
3. Node start gewoon door, precies zoals nu met een onbereikbare MQTT-broker
   — de node blijft primair zelfstandig functioneren.

## Foutafhandeling

- `PUT /api/settings` met een `#` of `+` in `mqtt_topic_prefix`: `400`,
  duidelijke Nederlandse melding, niets weggeschreven.
- Node kan de backend niet bereiken bij opstarten: stille terugval op de
  env-var, gelogd op info-niveau (niet als fout — dit is een verwacht pad,
  geen storing).
- Backend-topic-prefix wijzigt terwijl een node al draait: die node blijft
  gewoon op zijn oude prefix draaien tot een herstart (zie Niet-doelen) —
  geen foutmelding nodig, dit is het bewust gekozen gedrag.

## Testen

- `shared/mqtt_contract.py`: `Topics` is pure logica — tests voor elk topic
  met en zonder prefix, plus `strip_prefix` (met/zonder prefix, topic dat
  niet met de prefix begint blijft ongewijzigd).
- `shared/topic_prefix.py`: `fetch_topic_prefix` met een injectable `fetch`
  — succesvol antwoord, onbereikbare backend (fallback), ongeldig/non-JSON
  antwoord (fallback).
- `admin/app/mqtt_bridge.py`: uitbreiding van de bestaande
  `FakeMqttClient`-tests — `reconfigure` met een nieuwe prefix past
  subscribe/publish-topics aan; `_on_message` strip de prefix vóór het naar
  de tracker/WS-broadcast gaat (nieuwe test: bericht op `test/status/mirror`
  komt bij de tracker aan als `status/mirror`).
- `admin/app/routers/node_config.py`: `GET /api/node-config` retourneert de
  huidige prefix, werkt zonder sessie-cookie (publiek).
- `admin/app/routers/settings.py`: `mqtt_topic_prefix` rondt correct door
  `GET`/`PUT`; `#`/`+` wordt geweigerd.
- Bestaande tests die `Settings`/`RuntimeSettings`/`mqtt_contract`-constanten
  gebruiken (`tests/test_mqtt_contract.py` en overal in `mirror_node`/
  `scare_node`-tests waar topics voorkomen) worden aangepast aan de nieuwe
  `Topics`-API — geen nieuwe testbehoefte, wel een mechanische
  aanpassingsronde.

## Migratie (impact op bestaand werk)

- `shared/mqtt_contract.py`'s publieke API verandert volledig (constanten →
  klasse). Enige importeurs op dit moment (geverifieerd): `mirror_node/main.py`,
  `scare_node/main.py`, `admin/app/mqtt_bridge.py` en `shared/logging_setup.py`
  — die vier moeten mee. De routers (`routers/mirror.py`, `routers/scare.py`,
  ...) publiceren altijd via `app.state.bridge`, nooit rechtstreeks naar MQTT,
  en importeren het contract niet — die blijven ongewijzigd. `admin/app/mqtt_state.py`
  en de hele frontend blijven eveneens volledig ongemoeid (zie Niet-doelen).
- `shared/logging_setup.py`'s signatuur wijzigt (`mqtt_log_topic`-parameter
  erbij) — beide node-`main.py`'s die 'm met `mqtt_client=` aanroepen moeten
  ook `mqtt_log_topic=` meegeven; de backend-aanroep (zonder `mqtt_client`)
  hoeft niet te wijzigen maar mag voor de duidelijkheid wel.
- Bestaande deployments zonder ooit een prefix ingesteld te hebben: default
  `""` overal — functioneel identiek aan nu, geen enkele topic verandert.
- `README.md`: nieuwe rij in de env-var-tabellen van beide nodes
  (`MQTT_TOPIC_PREFIX`, default leeg), en een korte alinea over
  `/api/node-config` en het herstart-vereiste bij een prefix-wijziging.
