# Home Assistant setup voor de Halloween-ervaring

1. Installeer/activeer de Mosquitto broker add-on (Settings > Add-ons >
   Mosquitto broker) als die nog niet draait.
2. Zorg dat de MQTT-integratie in HA naar die broker wijst (meestal
   automatisch gedetecteerd na installatie van de add-on).
3. Kopieer de inhoud van `automations/wled_trigger.yaml` naar je
   HA-automations (via de Automations-UI "Edit in YAML", of in
   `automations.yaml` als je die beheert via bestanden). Het tijdvenster
   hoort hier *niet* meer: dat publiceert de beheerpagina-backend zelf op
   `system/sleep` (zie de root-README). Draai het niet ook in HA, anders
   overschrijven de twee elkaar.

   **Let op:** is er op de beheerpagina (Instellingen-pagina) een
   MQTT-topic-prefix ingesteld, dan moet je die handmatig voor elk topic in
   dit bestand zetten (`mirror/triggered`, `scare/+/triggered`,
   `status/mirror`, `status/scare-<zone>`) — HA volgt die instelling niet
   automatisch.
4. Pas `entity_id: light.wled_voortuin` in `wled_trigger.yaml` aan naar de
   werkelijke entity-id van je WLED-controller (te vinden onder
   Settings > Devices & Services > WLED).
5. Voeg op het dashboard MQTT-sensoren toe voor node-status. Elke node
   publiceert `online` (retained) op `status/<node>` zodra hij verbindt, en
   heeft `offline` als MQTT last-will op datzelfde topic staan. Node-namen:
   `status/mirror` en `status/scare-<zone>` (bijv. `status/scare-zone-a`).

   ```yaml
   mqtt:
     binary_sensor:
       - name: "Halloween mirror-node"
         state_topic: "status/mirror"
         payload_on: "online"
         payload_off: "offline"
         device_class: connectivity
   ```

   Herhaal dat blok per scare-node met het bijbehorende `status/scare-<zone>`.
   Ook hier geldt: staat er een topic-prefix ingesteld, zet die dan handmatig
   voor de `state_topic`.
