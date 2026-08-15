# Voortuin Halloween audio/video-ervaring — Design

**Datum:** 2026-08-15
**Status:** Goedgekeurd, klaar voor implementatieplan

## Doel

Een audiovisuele Halloween-ervaring in de voortuin die passanten/trick-or-treaters
verrast met motion-getriggerde scares: een live "spiegel-effect" bij een raam
(camera + beamer, rear-projectie), aangevuld met 1-2 losse audio-scarezones en
WLED-verlichting. Doelavond: 31 oktober. Vandaag: 15 augustus — ruime tijd om
te bouwen en meerdere keren te testen.

## Niet-doelen

- Geen strak gesynchroniseerde show (geen centrale klok/tijdlijn) — zones zijn
  losjes gekoppeld, niet frame-exact gesynchroniseerd.
- Geen geautomatiseerde testsuite voor de fysieke effecten (camera/audio/licht);
  wel een self-check per node.
- Geen centrale logstack (ELK e.d.) — logging loopt over de MQTT-infra die er
  toch al is.

## Architectuur

Home Assistant (al draaiend) is de coördinatielaag: MQTT-broker (Mosquitto),
dashboard (aan/uit, tijdvenster, noodstop, node-status) en automations. Elke
fysieke zone is een losstaand proces op zijn eigen machine en praat uitsluitend
via MQTT-topics met HA — nooit rechtstreeks met een andere node. Elke node kan
altijd zelfstandig blijven werken als MQTT/HA wegvalt; MQTT is een extra laag
"meepraten" bovenop dat zelfstandige gedrag, nooit een harde vereiste.

```
                    ┌─────────────────────────┐
                    │   Home Assistant (HA)    │
                    │  - MQTT broker (Mosquitto)│
                    │  - Dashboard (aan/uit,    │
                    │    tijdvenster, override) │
                    │  - Automations (schema,   │
                    │    WLED-koppeling)        │
                    └───────────┬──────────────┘
                                │ MQTT
              ┌─────────────────┼─────────────────┬──────────────┐
              │                 │                 │              │
     ┌────────▼────────┐ ┌──────▼──────┐  ┌───────▼───────┐ ┌────▼────┐
     │ Mirror-node       │ │ Scare-node A │  │ Scare-node B   │ │ WLED    │
     │ (computer, raam)  │ │ (Pi, zone 2) │  │ (Pi, zone 3)   │ │ (native │
     │ camera+trigger+    │ │ PIR+speaker  │  │ PIR+speaker    │ │ HA-int.)│
     │ effect+beamer      │ │              │  │                │ │         │
     └────────────────────┘ └──────────────┘  └────────────────┘ └─────────┘
```

## Componenten

### Mirror-node (hoofdervaring, bij het raam)

- Camera (USB-webcam) filmt de bezoeker buiten.
- Python + OpenCV verwerkt elk frame live tot een spook-effect (concreet filter
  — desaturatie/ghosting/contrast — wordt in de implementatiefase gekozen/
  geëxperimenteerd).
- Output naar de beamer (HDMI/tweede scherm), die van binnenuit op het raam
  rear-projecteert.
- **Trigger-detectie is een vervangbaar onderdeel achter een simpele interface**
  (nu: frame-diff op het camerabeeld zelf; later evt. te vervangen door een
  losse PIR-sensor of een detectiemodel, zonder de rest van de node te hoeven
  aanpassen).
- Bij rust: idle-loop of uit.
- Publiceert `mirror/triggered` (payload: timestamp) naar MQTT zodra het
  effect start.
- Publiceert logregels naar `log/mirror` (zie Logging).

### Scare-node(s) (Pi + PIR + speaker, 1-2 stuks, zone A/B)

- PIR-sensor op GPIO detecteert beweging → speelt lokaal een willekeurig
  geluidsfragment af uit een mapje.
- Triggert **onafhankelijk** op eigen PIR (geen afhankelijkheid van de
  mirror-node nodig om te kunnen scaren).
- Abonneert daarnaast op `mirror/triggered`: als dat bericht binnenkomt, speelt
  de node ook af — met een klein random delay (0-2s) zodat het niet als één
  mechanisch salvo klinkt.
- Debounce/cooldown (bijv. niet vaker dan 1x per 10-15s) tegen vals-positieven
  (wind, dieren, koplampen).
- Publiceert `scare/<zone>/triggered` en logregels naar `log/scare-<zone>`.

### WLED-verlichting

- Off-the-shelf WLED-controller(s), geen eigen code — praat al native
  MQTT/HTTP en heeft kant-en-klare HA-integratie.
- Koppeling loopt via een HA-automation: bij `mirror/triggered` of
  `scare/<zone>/triggered` roept HA een WLED-preset/effect aan (bijv. rood
  geflikker). Deze logica hoort in HA, niet in een Python-node.

### Home Assistant

- Mosquitto MQTT-broker (add-on).
- Automation: tijdvenster (bijv. alleen 18:00-22:00 actief); buiten dat venster
  stuurt HA een `system/sleep`-bericht zodat nodes in stand-by gaan (geen
  camera-verwerking, geen sensor-polling) — voorkomt nachtelijke
  vals-positieven.
- Dashboard: handmatige aan/uit per node, noodstop, live node-status via MQTT
  last-will-testament.
- WLED-automations (zie boven).
- Geen "wie triggert wie"-logica tussen scare-nodes in HA — dat regelen de
  nodes zelf via topics; HA is schakelaar + zichtbaarheid.

## Data flow (typisch scare-moment)

1. Bezoeker loopt het pad op → camera bij het raam detecteert beweging →
   mirror-node start het spook-effect op de beamer.
2. Mirror-node publiceert `mirror/triggered`.
3. HA logt/toont dit op het dashboard (geen verplichte actie nodig) en de
   WLED-automation vuurt een lichteffect af.
4. Scare-node(s) die geabonneerd zijn op `mirror/triggered` spelen (met
   0-2s random delay) hun eigen geluid af en publiceren zelf
   `scare/<zone>/triggered`.
5. Onafhankelijk: een PIR bij een scare-node die zelf iets detecteert (zonder
   dat er eerst iets bij het raam gebeurde) triggert gewoon lokaal.
6. Buiten het HA-tijdvenster: nodes negeren triggers / staan in stand-by na
   `system/sleep`.

## Foutafhandeling & robuustheid

- **MQTT/HA weg:** nodes blijven lokaal functioneren; reconnect met backoff
  zodra HA terugkomt.
- **Camera/OpenCV crash (mirror-node):** watchdog (systemd `Restart=always`
  of vergelijkbaar) herstart het proces; bij herhaald falen toont de beamer
  zwart/idle i.p.v. een bevroren frame.
- **PIR-vals-positieven:** debounce/cooldown per node.
- **Node offline:** zichtbaar via MQTT last-will op het HA-dashboard; geen
  automatisch herstel nodig (fysiek ding, handmatig ingrijpen volstaat).
- **Ontbrekende/corrupte media:** elke node valideert zijn eigen mediamap bij
  opstarten en logt duidelijk welk bestand het probleem is, i.p.v. stil te
  falen tijdens een scare-moment.

## Logging

Elke node logt lokaal (bestand) én publiceert logregels naar een eigen
`log/<node>`-MQTT-topic. Tijdens ontwikkeling meeluisteren via bijv.
`mosquitto_sub` of een klein verzamel-scriptje geeft zicht op alle nodes
tegelijk, zonder een aparte logstack op te tuigen. Lokale logs zijn het
fallback-vangnet als MQTT wegvalt. Richting Halloween-avond zelf kan het
logniveau worden teruggeschroefd zonder de opzet te veranderen.

## Testen

- Elke node (mirror, scare-nodes, WLED-koppeling) wordt eerst los getest,
  inclusief het lokale fail-safe gedrag zonder dat MQTT/HA aanstaat.
- MQTT-koppeling testen door handmatig berichten te publiceren
  (`mosquitto_pub`), zonder fysiek langs sensoren te hoeven lopen.
- Pas daarna een end-to-end avond-simulatie op locatie (schemer/donker, echte
  afstanden, echte WiFi-bereik).
- Geen geautomatiseerde testsuite voor de fysieke effecten; wel een kleine
  `demo`/self-check per node om zelfstandig gedrag snel te verifiëren.

## Hardware-toewijzing (indicatief, verfijnen tijdens implementatie)

| Rol | Hardware |
|---|---|
| Mirror-node | Volwaardige computer (CPU-headroom voor OpenCV) + USB-camera + beamer |
| Scare-node A/B | Raspberry Pi + PIR-sensor (GPIO) + speaker |
| WLED | Bestaande/aan te schaffen WLED-controller(s) |
| Coördinatie | Home Assistant-instantie (bestaand) |
