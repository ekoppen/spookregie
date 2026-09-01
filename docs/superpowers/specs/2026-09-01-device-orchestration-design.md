# Apparaat-orchestratie: zelf-updatende clients per fysieke output — Design

## Doel

De vorige uitbreiding (Player/Source/Trigger/Output-graaf) maakte het datamodel
klaar voor meerdere fysieke outputs, maar de daadwerkelijke uitvoering bleef
bewust beperkt tot precies één fysiek proces met een hardcoded node-naam.
Directe aanleiding: een rechtsklik-menu-bugfix leidde tot de vraag hoe een
nieuwe fysieke output (een oude MacBook Pro, of wat er verder beschikbaar is)
concreet ingezet kan worden zonder handmatig code te moeten bijwerken op elk
apparaat.

Deze uitbreiding voegt toe:

1. **Een lichte, altijd-actieve agent per apparaat** die zichzelf via `git
   pull` bijwerkt (interval + directe MQTT-duw vanuit de beheerpagina) en
   zich bij de beheerpagina meldt (naam, platform, huidige commit).
2. **Een `devices`-tabel + beheerpagina** waarin je geregistreerde apparaten
   ziet en aan een fysieke Output koppelt — de koppeling is de enige
   handmatige stap na de eenmalige installatie.
3. **Per-apparaat output-scoping**: het globale `output_id`-veld in de
   gepubliceerde graaf (dat impliciet "de ene output" aannam) wordt
   vervangen door een per-apparaat toewijzing over een eigen MQTT-topic,
   zodat twee apparaten daadwerkelijk verschillende dingen kunnen tonen.
4. **Eenmalig, handmatig install-script** (macOS + Linux) dat de twee
   processen (mirror_node zelf + de nieuwe agent) bij de servicemanager
   registreert. Daarna is een apparaat zelfstandig.

De GitHub-repo wordt hiervoor publiek gemaakt (elk apparaat moet kunnen
`git pull`en zonder dat je per apparaat credentials moet beheren). De
volledige git-historie is vooraf doorzocht op eerder gecommitte geheimen
(MQTT-wachtwoorden, HA-tokens, admin-wachtwoord) — niets gevonden; het
project heeft consistent env-vars gebruikt, nooit letterlijke waarden.

## Architectuur — samenvatting

- Elk apparaat draait voortaan **twee processen**, beide door de
  servicemanager (launchd/systemd) herstart bij een crash:
  - `mirror_node/main.py` (bestaand) — de camera/render-lus. Zijn
    `NODE_NAME` (nu hardcoded `"mirror"`) wordt vervangen door een lokaal
    gegenereerde `device_uuid`; hij abonneert zich op zijn eigen
    `device-assignment/{device_uuid}`-topic om te weten welke output hij
    voedt.
  - `mirror_node/agent.py` (nieuw) — publiceert periodiek een
    device-info-checkin, doet periodiek + op MQTT-duw een `git pull`, en
    herstart `mirror_node` via de servicemanager bij nieuwe commits. Geen
    rollback-logica: bij een kapotte update gewoon opnieuw proberen bij de
    volgende cyclus.
- Nieuwe `devices`-tabel + `/api/devices`-routes + `DevicesPage.tsx`
  (zelfde vorm als Sources/Outputs): apparaten melden zichzelf aan, jij
  koppelt ze in de beheerpagina aan een Output.
- `graph_publish.py` verliest het `output_id`-veld — elk apparaat filtert
  voortaan op zijn eigen, apart ontvangen toewijzing.
- Installatie blijft een bewuste, eenmalige handmatige stap per apparaat
  (install-script, macOS + Linux) — geen SSH-push vanaf de beheerpagina.

## Datamodel

### `devices`-tabel (nieuw)

```sql
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT '',
    git_sha TEXT,
    last_seen_at TEXT,
    output_id INTEGER
)
```

Geen DB-foreign-key naar `outputs` (project-conventie) — bij verwijdering
van een output moet de bijbehorende `devices`-rij(en) in applicatiecode
ontkoppeld worden (`output_id` terug naar `NULL`), niet cascade-verwijderd.

`name`: gezet bij eerste registratie (hostname/zelf-gerapporteerde naam
uit de checkin), daarna vrij te hernoemen in de beheerpagina — latere
checkins overschrijven 'm niet meer, zelfde patroon als
Sources/Outputs/Players.

`output_id`: `NULL` totdat jij een koppeling maakt. Een niet-toegewezen
apparaat voedt bewust geen enkele output (veilige standaard, geen
giswerk).

### `outputs`-router — ontkoppel-guard

`DELETE /api/outputs/{id:int}` krijgt, naast de bestaande
output_connections-guard, ook: alle `devices`-rijen met dit `output_id`
worden losgekoppeld (`output_id = NULL`) vóór de output zelf verwijderd
wordt — een device blijft dan bestaan, maar voedt niets meer totdat je 'm
opnieuw koppelt.

## MQTT-contract (nieuwe topics op `shared/mqtt_contract.py`)

```
control/mirror/device-info/{device_uuid}         (retained)
  payload: {"name": "...", "platform": "darwin"|"linux", "git_sha": "..."}
  publisher: mirror_node/agent.py, bij opstart + elke ~5 minuten
  subscriber: admin backend (wildcard control/mirror/device-info/+),
              upsert in devices

control/mirror/device-assignment/{device_uuid}   (retained)
  payload: {"output_id": <int> | null}
  publisher: admin backend, zodra jij een koppeling (aan)past in de UI
  subscriber: mirror_node/main.py (alleen zijn eigen device_uuid-topic)

control/mirror/device-update-check                (niet-retained)
  payload: {} (leeg, puur een signaal)
  publisher: admin backend, na een device-info-update of op verzoek
  subscriber: mirror_node/agent.py (elk apparaat, allemaal tegelijk) --
              triggert een directe git-pull-check i.p.v. te wachten op
              het volgende interval
```

`status/{node}` (bestaand, `shared/mqtt_contract.py`'s `status()`-
property) blijft ongewijzigd van vorm — alleen de waarde die
`mirror_node/main.py` als `node` doorgeeft verandert van de hardcoded
`"mirror"` naar de eigen `device_uuid`. Dit is de bestaande, al werkende
online/offline-LWT-mechaniek (`client.will_set(topics.status(NODE_NAME),
"offline", retain=True)`), nu bruikbaar voor meerdere apparaten in plaats
van kunstmatig beperkt tot één.

## `graph_publish.py` — contractwijziging

Het `output_id`-veld verdwijnt uit de gepubliceerde payload (was toch al
"de eerste/enige output", betekenisloos zodra meerdere apparaten
onafhankelijk aan verschillende outputs gekoppeld kunnen zijn). Payload
wordt `{players, sources, branches, triggers, output_connections,
root_player_id}` — geen `output_id` meer.

## `mirror_node/main.py` — aanpassingen

- `NODE_NAME = "mirror"` (hardcoded) wordt vervangen door: lees
  `device_uuid` uit een lokaal bestand (locatie: zie Agent-sectie
  hieronder), val terug op een nieuw gegenereerde uuid als het bestand nog
  niet bestaat (zelfde bestand dat de agent ook leest/schrijft — één bron
  van waarheid per apparaat).
- Nieuwe module-state `_assigned_output_id: int | None = None` (vervangt
  `_current_output_id`, dat nu uit `graph.get("output_id")` kwam — die
  bron verdwijnt).
- Nieuwe MQTT-subscriptie op `topics.device_assignment(device_uuid)` (een
  nieuwe property op `Topics`, analoog aan de bestaande `status()`- en
  `mirror_ha_trigger`-properties); het ontvangen `output_id` (kan `null`
  zijn) wordt direct in `_assigned_output_id` gezet.
- `_player_feeds_this_output` en de bestaande output-routing-publish
  (`mirror/output`-topic, uit de vorige fix-ronde) lezen voortaan
  `_assigned_output_id` in plaats van `_current_output_id` — verder
  ongewijzigd. Is `_assigned_output_id is None`, dan voedt dit apparaat
  niets (geen output-routing-publish, `_player_feeds_this_output` altijd
  `False`).

## `mirror_node/agent.py` (nieuw)

Klein, langlevend proces — geen render-lus, geen camera-toegang nodig.
Verantwoordelijkheden:

1. **Device-identiteit**: bij opstart, `device_uuid` lezen uit
   `~/.spookregie/device-id`; bestaat het bestand nog niet, genereer een
   `uuid4()` en schrijf 'm weg. Zelfde bestand als `mirror_node/main.py`
   leest.
2. **Checkin**: publiceert bij opstart en daarna elke ~5 minuten (retained)
   naar `control/mirror/device-info/{device_uuid}` — naam (hostname via
   Python's `socket.gethostname()`), platform (`sys.platform`,
   herkenbaar als `darwin`/`linux`), huidige git-commit (`git rev-parse
   HEAD` in de repo-directory).
3. **Update-check**: elke ~10 minuten, én direct bij een bericht op
   `control/mirror/device-update-check`: `git fetch` + vergelijk lokale
   met remote `HEAD` van de geconfigureerde branch (`main`); bij verschil:
   `git pull --ff-only`, dan `mirror_node` herstarten via de
   servicemanager (macOS: `launchctl kickstart -k
   gui/$UID/nl.spookregie.mirror`; Linux: `systemctl restart
   spookregie-mirror` — exacte unit-namen worden in het implementatieplan
   vastgelegd). Geen rollback bij een falende herstart — de volgende
   update-cyclus (of een handmatige ingreep) is de enige herstelweg,
   bewust zo gekozen.
4. Gebruikt dezelfde `MQTT_HOST`/`MQTT_PORT`/`MQTT_USER`/`MQTT_PASS`/
   `MQTT_TOPIC_PREFIX`-omgevingsvariabelen als `mirror_node/main.py` al
   gebruikt — geen nieuwe configuratie nodig, één gedeeld env-bestand per
   apparaat (zie install-script).

## Backend: `admin/app/routers/devices.py` (nieuw)

- `GET /api/devices` — lijst, gesorteerd op naam.
- `PUT /api/devices/{device_id:int}` — body: `{name, output_id}` (volledige
  vervanging, zelfde patroon als andere entiteiten in dit project). Bij
  een gewijzigde `output_id`: publiceert meteen (retained) de nieuwe
  toewijzing naar `control/mirror/device-assignment/{device_uuid}` via de
  MQTT-bridge.
- `DELETE /api/devices/{device_id:int}` — verwijdert de rij. Het fysieke
  apparaat blijft gewoon draaien en checkt gewoon weer in bij de
  eerstvolgende checkin (registreert zichzelf dan opnieuw, ongekoppeld).

`admin/app/mqtt_bridge.py` abonneert zich op
`control/mirror/device-info/+`; bij een ontvangen bericht: upsert in
`devices` op `device_uuid` (insert met de gerapporteerde naam als er nog
geen rij bestaat; op een bestaande rij alleen `platform`/`git_sha`/
`last_seen_at` bijwerken, `name` met rust laten).

## Frontend: `DevicesPage.tsx` (nieuw)

Zelfde vormtaal als Sources/Outputs-pagina's: lijst met apparaten (naam
bewerkbaar, platform, git-sha ingekort tot 7 tekens, online/offline-badge
op basis van de bestaande `NodeStatusMap`/status-topic-mechaniek die de
Dashboard-pagina al gebruikt, laatst-gezien-tijdstip), en een dropdown per
rij om een Output te koppelen (of "geen"). Nieuwe navigatie-link, zelfde
patroon als de Sources-link.

## Install-script (`deploy/install-agent.sh`, nieuw)

Eén script, detecteert het platform (`uname`) en vertakt:

1. Controleert dat `git` en `python3` aanwezig zijn — faalt met een
   duidelijke melding als dat niet zo is (geen automatische
   package-manager-installatie, te veel variatie tussen platformen voor
   dit hobby-project).
2. Kloont de repo naar een vaste locatie (`~/spookregie` op beide
   platformen — geen sudo nodig voor de repo zelf).
3. Zet een Python-venv op, installeert `mirror_node`'s requirements.
4. Vraagt interactief (of via flags) om `MQTT_HOST`, `MQTT_PORT`,
   `MQTT_USER`, `MQTT_PASS`, `MQTT_TOPIC_PREFIX`, `BACKEND_URL` — exact de
   env-vars die `mirror_node/main.py` nu al gebruikt, niets nieuws om te
   configureren. Schrijft ze naar één gedeeld env-bestand dat beide
   services (mirror_node + agent) inlezen.
5. Registreert twee services bij de servicemanager:
   - **macOS**: twee LaunchAgents in `~/Library/LaunchAgents/`
     (`KeepAlive=true`, `RunAtLoad=true`) — geen sudo nodig, draait zolang
     de gebruiker ingelogd is (passend bij een MacBook die je aan laat
     staan).
   - **Linux**: twee systemd system-services (`Restart=always`) — vereist
     sudo tijdens installatie, draait vanaf boot zonder ingelogde sessie
     (passend bij een Raspberry Pi die los ergens staat).

## Migratie-volgorde (voor de implementatieplanning)

1. `devices`-tabel (nieuwe tabel, row-count-gated zoals `sources`/
   `outputs` — geen bestaande tabel om te migreren, dus geen
   `PRAGMA user_version`-ophoging nodig).
2. `shared/mqtt_contract.py`: drie nieuwe topic-properties
   (`device_info`, `device_assignment`, `device_update_check`).
3. `admin/app/routers/devices.py` + registratie in `admin/app/main.py`.
4. `admin/app/mqtt_bridge.py`: device-info-subscriptie + upsert-logica,
   device-assignment-publish-methode.
5. `admin/app/graph_publish.py`: `output_id`-veld verwijderen uit de
   payload.
6. `admin/app/routers/outputs.py`: ontkoppel-guard bij output-verwijdering.
7. `mirror_node/main.py`: `NODE_NAME` → `device_uuid` uit lokaal bestand,
   `_assigned_output_id` i.p.v. `_current_output_id` uit de graaf-payload,
   nieuwe device-assignment-subscriptie.
8. `mirror_node/agent.py` (nieuw bestand).
9. Frontend: `types.ts`/`api/devices.ts`, `DevicesPage.tsx`, navigatie.
10. `deploy/install-agent.sh` (nieuw bestand).
11. Repo publiek maken (los, operationele stap — niet iets wat in een
    commit zit).

## Wat expliciet buiten scope blijft

- Automatische rollback bij een kapotte update op een apparaat — bewust
  gekozen: gewoon opnieuw proberen bij de volgende cyclus, geen
  "laatst-werkende-commit"-onthouding.
- Zelf-installatie op afstand (de beheerpagina die zelf via SSH een nieuw
  apparaat opzet) — installatie blijft een bewuste, eenmalige handmatige
  stap per apparaat.
- Een aparte packaging-/bundelstap die alleen `mirror_node`/`shared`
  meestuurt — elk apparaat kloont de volledige repo.
- Schaal-/bandbreedte-optimalisaties voor veel gelijktijdige apparaten
  (dit project heeft er een handvol, geen honderden).
- Automatische package-manager-installatie van ontbrekende
  systeemdependencies (git/python3) door het install-script.
