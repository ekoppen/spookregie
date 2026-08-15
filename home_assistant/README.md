# Home Assistant setup voor de Halloween-ervaring

1. Installeer/activeer de Mosquitto broker add-on (Settings > Add-ons >
   Mosquitto broker) als die nog niet draait.
2. Zorg dat de MQTT-integratie in HA naar die broker wijst (meestal
   automatisch gedetecteerd na installatie van de add-on).
3. Kopieer de inhoud van `automations/time_window.yaml` en
   `automations/wled_trigger.yaml` naar je HA-automations (via de
   Automations-UI "Edit in YAML", of in `automations.yaml` als je die
   beheert via bestanden).
4. Pas `entity_id: light.wled_voortuin` in `wled_trigger.yaml` aan naar de
   werkelijke entity-id van je WLED-controller (te vinden onder
   Settings > Devices & Services > WLED).
5. Voeg op het dashboard MQTT-sensoren toe voor node-status
   (last-will-topic `log/<node>` of een aparte `status/<node>`-topic, naar
   smaak) zodat je in één oogopslag ziet welke nodes online zijn.
