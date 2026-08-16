# Beheerpagina (admin-tool) — Design

**Datum:** 2026-08-16
**Status:** Goedgekeurd, klaar voor implementatieplan
**Vervolg op:** `2026-08-15-voortuin-halloween-ervaring-design.md`

## Doel

Eén webpagina waarmee de hele Halloween-voortuinervaring beheerd en live
bediend kan worden: scare-audio uploaden/aan-uit zetten, mirror-effecten en
overlays kiezen/instellen met live preview, node-status zien, handmatig
testen, noodstop, en WLED/tijdvenster-instellingen — inclusief het
tijdvenster dat nu nog in Home Assistant zit. Geen enkele bestaande functie
mag alleen via code-aanpassingen bereikbaar blijven.

## Niet-doelen

- Geen gebruikersbeheer — één gedeeld wachtwoord volstaat.
- Geen ondersteuning voor gebruik buiten het eigen LAN (live preview gaat
  rechtstreeks browser↔mirror-node, dat vereist hetzelfde netwerk).
- WLED-hardwarebesturing zelf blijft in Home Assistant — alleen het
  tijdvenster/schema verhuist naar de nieuwe backend (zie Migratie).
- Geen zware E2E-testsuite voor de frontend, tenzij later expliciet
  gevraagd.

## Architectuur

```
                    ┌────────────────────────────────────┐
                    │  Backend (FastAPI) — "admin/app"     │
                    │  - MQTT-client (status/log lezen,    │
                    │    config publiceren)                │
                    │  - HA REST-client (WLED-status,       │
                    │    tijdvenster-vervanger)             │
                    │  - Media-opslag (content-addressed,   │
                    │    SQLite-metadata)                   │
                    │  - Achtergrond-scheduler (tijdvenster) │
                    │  - Wachtwoord-auth + sessie-cookie     │
                    │  - WebSocket → live status/logs        │
                    └───────────┬──────────────┬───────────┘
                       REST/WS  │              │ MQTT + HTTP (media-sync)
                                │              │
                    ┌───────────▼──────┐   ┌───▼─────────────────┐
                    │ Frontend (React/  │   │ mirror-node          │
                    │ Vite SPA)         │   │ - effect-register     │
                    │ Dashboard/Mirror/ │   │ - overlay-compositing │
                    │ Scare/HA/Logs     │◄──┤ - MJPEG-endpoint      │
                    └───────────────────┘   │   (rechtstreeks LAN)  │
                                             └───────────────────────┘
                                             ┌───────────────────────┐
                                             │ scare-node(s)          │
                                             │ - enabled-lijst per    │
                                             │   zone via MQTT-config │
                                             └───────────────────────┘
```

De browser praat voor besturing/config/status met de backend (REST +
WebSocket). Voor de live camera-preview verbindt de browser **rechtstreeks**
met mirror-node's eigen MJPEG-endpoint op het LAN — geen video door de
backend heen, lagere latency, minder bewegende delen.

## Componenten

### Gedeeld MQTT-contract (uitbreiding van `shared/mqtt_contract.py`)

- `config/mirror` — backend → mirror-node, persistente config: actief
  effect, parameters, overlay-hash, schaal, positie.
- `control/mirror/preview` — backend → mirror-node, tijdelijke
  proefconfig voor live-preview tijdens het slepen/schuiven in de UI.
  Vervalt na een timeout (geen interactie) terug naar de opgeslagen
  `config/mirror`-stand.
- `config/scare/<zone>` — backend → scare-node, lijst van ingeschakelde
  audiobestand-hashes voor die zone.
- `control/mirror/test-trigger`, `control/scare/<zone>/test-trigger` —
  backend → node, forceert een test-moment, negeert cooldown.
- Hergebruikt (geen nieuwe topics): `system/sleep` voor zowel noodstop als
  het nieuwe tijdvenster-schema; bestaande `status/<node>`,
  `log/<node>`, `mirror/triggered`, `scare/<zone>/triggered` blijven
  ongewijzigd en worden door de backend meegelezen voor het dashboard.

### Media-opslag & sync

Backend bewaart geüploade audio/overlay-bestanden content-addressed (hash
van de inhoud) in één pool, met metadata (originele bestandsnaam,
categorie, uploaddatum) in SQLite. MQTT-configberichten verwijzen alleen
naar hashes, nooit naar bestandsinhoud. Nodes houden een lokale cache bij:
bij een onbekende hash in een configbericht doen ze `GET
/api/media/<hash>` bij de backend, op de achtergrond, zonder de hoofdloop
te blokkeren. Bij een mislukte fetch blijft de node op zijn laatst-bekende
config draaien en probeert het later opnieuw.

### Mirror-node uitbreiding (`mirror_node/effects/`)

- Een register van filters volgens het bestaande `(frame_bgr, params) ->
  frame_bgr`-contract: de huidige x-ray/invert blijft (hernoemd tot
  `"xray"` in het register), plus drie nieuwe, elk met OpenCV-functies die
  al beschikbaar zijn (geen nieuwe dependency):
  - `"thermal"` — `cv2.applyColorMap(gray, cv2.COLORMAP_JET)`.
  - `"contour"` — `cv2.Canny` op het grijswaardenbeeld, wit op zwart.
  - `"posterize"` — kleuren reduceren via een instelbaar aantal niveaus
    (`params["levels"]`, bijv. `np.floor(frame / step) * step`).
  Elk filter accepteert een `params`-dict met tenminste één instelbare
  waarde (bijv. `intensity` voor xray/thermal, `threshold1`/`threshold2`
  voor contour, `levels` voor posterize) zodat de "instelbare parameters
  per effect"-eis (uit het brainstormgesprek) voor elk filter concreet
  ingevuld is.
- Een losstaande compositing-stap die na het filter optioneel een
  PNG-overlay met alpha-blending overheen legt, gepositioneerd/geschaald
  volgens `scale`/`position` uit de config.
- `main.py` abonneert op `config/mirror` én `control/mirror/preview`;
  houdt één "actieve weergave-config" bij (preview overschrijft
  tijdelijk, valt terug op de opgeslagen config na de timeout) en wisselt
  die atomisch tussen frames.
- Nieuw MJPEG-streaming-endpoint (lichte ingebouwde HTTP-server) dat het
  frame na filter+overlay serveert — hergebruikt het frame dat de
  hoofdloop toch al verwerkt, geen aparte camera-toegang nodig.

### Scare-node uitbreiding

- `playback.py`'s bestandsselectie filtert voortaan op een expliciete
  "ingeschakeld"-lijst (hashes/bestandsnamen) in plaats van "alles in de
  map is geldig".
- `main.py` abonneert op `config/scare/<zone>` en `control/scare/<zone>/
  test-trigger`; synchroniseert nieuwe bestanden zoals hierboven
  beschreven.

### Backend (`admin/app/`, FastAPI)

- MQTT-client: leest status/log/trigger-topics, bridged naar WebSocket
  voor de frontend; publiceert config/control-berichten wanneer de
  gebruiker iets aanpast.
- HA-client: dunne wrapper om de HA REST API voor WLED-status/-bediening,
  met het bestaande, door de gebruiker beheerde long-lived token.
- Achtergrond-scheduler (stdlib, geen nieuwe dependency): controleert elke
  minuut het ingestelde aan/uit-tijdstip en publiceert `system/sleep`
  (retained) bij een overgang — vervangt de HA-automation voor het
  tijdvenster (zie Migratie).
- Media-opslag + metadata (SQLite via stdlib `sqlite3`).
- Auth: één gehasht wachtwoord (env var/config), sessie-cookie,
  middleware op alle beheer-routes en de WebSocket.

### Frontend (`admin/frontend/`, React + Vite)

- **Dashboard** — node-status (online/offline via `status/<node>`),
  noodstop-knop, tijdvenster-instelling.
- **Mirror** — effect kiezen, parameters instellen, overlay uploaden/
  kiezen, live preview (rechtstreekse MJPEG-stream) met sleep/schaal-
  handles bovenop het beeld, "toepassen"-knop.
- **Scare** — per zone: audiobestanden uploaden/in-uitschakelen/
  verwijderen, test-trigger-knop.
- **HA** — WLED-snelbediening (status tonen, testflits triggeren via de
  bestaande automation).
- **Logs** — live tail per node via WebSocket, filterbaar.

## Data flow

**Mirror-effect + overlay live instellen**
1. Upload PNG → `POST /api/media` → backend hasht/slaat op, geeft hash
   terug.
2. Gebruiker sleept/schuift overlay op de live preview → frontend stuurt
   (gethrottled) naar `control/mirror/preview` → mirror-node past het
   direct toe op zijn MJPEG-stream, niets wordt nog opgeslagen.
3. Gebruiker klikt "Toepassen" → `PUT /api/mirror/config` → backend slaat
   op in SQLite én publiceert `config/mirror` (persistent).
4. mirror-node haalt de overlay op via `GET /api/media/<hash>` als nog
   niet lokaal gecached, wisselt de opgeslagen config atomisch in — geen
   herstart nodig.
5. mirror-node bevestigt via `status/mirror`; backend zet dit door naar de
   browser via WebSocket.

**Noodstop / tijdvenster**
Zowel de noodstop-knop als de achtergrond-scheduler publiceren naar
hetzelfde bestaande `system/sleep`-topic (retained) — geen nieuwe topic,
hergebruikt de bestaande fail-safe-plumbing van elke node.

**Scare-audio beheren**
Upload → hash/opslag zoals bij mirror. In-/uitschakelen → `PUT
/api/scare/<zone>/config` → backend publiceert bijgewerkte lijst naar
`config/scare/<zone>` → scare-node synchroniseert en filtert
`pick_audio_file` voortaan op die lijst.

## Foutafhandeling

- Backend-MQTT of HA-API onbereikbaar: het betreffende UI-paneel toont
  duidelijk "niet bereikbaar", de rest van de pagina blijft werken — past
  bij de bestaande fail-safe-filosofie van het project.
- Node kan een mediabestand niet ophalen: blijft draaien op de
  laatst-bekende config, probeert later opnieuw op de achtergrond,
  blokkeert nooit de hoofdloop.
- Live preview verlopen (geen interactie/tab dicht): mirror-node valt na
  een timeout automatisch terug op de opgeslagen config — de projectie
  blijft nooit in een proefstand hangen.
- Upload-validatie (bestandstype/grootte: PNG voor overlays, WAV voor
  audio — consistent met de bestaande `aplay`-beperking) gebeurt bij
  upload, niet pas als een node er later op stukloopt.
- Verkeerd wachtwoord: generieke foutmelding, geen accountopsomming
  (irrelevant bij één gedeeld wachtwoord, maar voorkomt timing-lekken).

## Testen

- Backend: pytest met FastAPI's `TestClient`, een nep-MQTT-client en
  gemockte HA-HTTP-calls — geen echte broker/HA nodig voor de
  pure/logica-lagen (hash-berekening, config-diffing, HA-request-opbouw,
  MQTT-topic/payload-constructie).
- Nieuwe node-logica (effect-lookup, overlay-compositing-wiskunde,
  enabled-bestanden-filtering, hash-diffing voor media-sync) krijgt
  dezelfde pytest-dekking als de rest van het project. De
  MQTT/HTTP-verbindingslogica en het MJPEG-endpoint zelf blijven
  handmatig getest op locatie, zoals nu ook al met mirror/scare-node
  `main.py` gebeurt.
- Frontend: TypeScript voor type-veiligheid tijdens het bouwen; geen
  zware E2E-suite voor dit hobbyproject tenzij later expliciet gevraagd.

## Migratie (impact op bestaand werk)

- `home_assistant/automations/time_window.yaml` wordt **verwijderd** —
  de nieuwe achtergrond-scheduler in de backend neemt deze rol over.
  Zonder verwijdering zouden twee systemen op hetzelfde retained
  `system/sleep`-topic publiceren en elkaar kunnen tegenspreken.
- `home_assistant/automations/wled_trigger.yaml` blijft ongewijzigd — WLED
  zelf blijft in HA's beheer.
- `mirror_node/effect.py`'s huidige `ghost_effect`-functie verhuist naar
  het nieuwe effect-register (hernoemd, gedrag ongewijzigd) in plaats van
  de enige/hardcoded optie te blijven.
- `scare_node/playback.py`'s `pick_audio_file` krijgt een extra parameter
  voor de ingeschakelde-bestanden-filter; bestaand gedrag (willekeurige
  keuze binnen de toegestane set) blijft hetzelfde.

## Hardware/dependency-toewijzing (indicatief)

| Rol | Waar |
|---|---|
| Backend + frontend | Bestaande server (per eerdere keuze van de gebruiker) |
| Mirror-node | Zelfde computer als nu, plus een lichte MJPEG-server erbij |
| Scare-node(s) | Zelfde Pi's als nu, ongewijzigde hardware |
| Media-opslag | SQLite + bestanden op de backend-server, geen aparte databaseserver |
