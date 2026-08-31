import threading

from admin.app.ha_client import get_states


class HaTriggerPoller:
    """Pollt periodiek Home Assistant-entity-states en publiceert een
    eenmalige MQTT-puls zodra een gekoppelde entiteit een STIJGENDE FLANK
    maakt naar 'on'/'detected' (nooit een aanhoudend signaal -- zelfde
    puls-niet-niveau-les als bewegingsdetectie: een blijvend 'aan'-
    signaal zou dezelfde scare-video oneindig laten herhalen)."""

    _FIRED_STATES = {"on", "detected"}

    def __init__(self, bridge, get_settings, get_watched_entity_ids, check_interval=5, logger=None):
        self._bridge = bridge
        self._get_settings = get_settings
        self._get_watched_entity_ids = get_watched_entity_ids
        self._check_interval = check_interval
        self._logger = logger
        self._last_states = {}
        self._stop_event = threading.Event()
        self._thread = None

    def _tick(self):
        """Eén controle. Vangt alles af: HA onbereikbaar of een kapotte
        entity-id mag de achtergrond-thread niet stilletjes doodmaken."""
        try:
            watched = self._get_watched_entity_ids()
            if not watched:
                return
            settings = self._get_settings()
            states = get_states(settings.ha_url, settings.ha_token)
            by_entity = {s.get("entity_id"): s.get("state") for s in states if isinstance(s, dict)}
            for entity_id in watched:
                if entity_id not in by_entity:
                    # Entiteit ontbreekt in dit antwoord -- bijna altijd
                    # een HA-uitval/-herstart (get_states geeft dan []
                    # terug), niet een echte state-wijziging. Laatst-
                    # bekende state ongemoeid laten: anders leest een
                    # entiteit die nog steeds 'on' is zodra HA weer
                    # online komt als een stijgende flank vanaf None, en
                    # vuurt een ongewenste scare voor niemand.
                    continue
                new_state = by_entity[entity_id]
                old_state = self._last_states.get(entity_id)
                is_rising_edge = new_state in self._FIRED_STATES and old_state not in self._FIRED_STATES
                # Laatst-bekende state VOOR de publishes bijwerken: als een
                # publish een exception gooit, mag _last_states niet stale
                # blijven staan op de oude waarde -- anders leest de
                # volgende succesvolle tick een allang-aanhoudend 'on'
                # opnieuw als stijgende flank en vuurt een valse puls.
                self._last_states[entity_id] = new_state
                if is_rising_edge:
                    self._bridge.publish_mirror_ha_trigger(entity_id)
                self._bridge.publish_mirror_ha_sensor_state(entity_id, new_state)
        except Exception as exc:
            if self._logger is not None:
                self._logger.error("HA-trigger-polling mislukt: %s", exc)

    def _loop(self):
        while not self._stop_event.is_set():
            self._tick()
            self._stop_event.wait(self._check_interval)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
