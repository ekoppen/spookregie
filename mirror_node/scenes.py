import time


class SceneGraph:
    """Houdt de laatst via MQTT ontvangen graaf bij (scenes + live
    triggers) en de huidige-scene-toestand. Elke trigger is een eigen
    knoop tussen twee scenes (from_scene_id -> to_scene_id), met een
    kind (always/motion/schedule/ha_sensor)."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._scenes = {}
        self._triggers = {}
        self._root_id = None
        self._current_id = None
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_graph(self, scenes, triggers, root_scene_id):
        # Disabled scenes tellen niet mee -- ze mogen nooit als winnaar
        # terugkomen. Een trigger naar zo'n scene wordt vanzelf als
        # "target bestaat niet" behandeld door resolve() (zelfde pad als
        # een trigger naar een écht verwijderde scene).
        self._scenes = {s["id"]: s for s in scenes if s.get("enabled", True)}
        by_from = {}
        for t in triggers:
            if t.get("to_scene_id") is None or t.get("kind") is None:
                continue  # niet-live: lege stub of ongeconfigureerde trigger
            by_from.setdefault(t["from_scene_id"], []).append(t)
        for lst in by_from.values():
            lst.sort(key=lambda t: t["priority"])
        self._triggers = by_from
        self._root_id = root_scene_id
        if self._current_id not in self._scenes:
            self._current_id = root_scene_id

    def set_preview(self, scene):
        self._preview = scene
        self._preview_set_at = self._clock()

    def preview_recently_set(self):
        if self._preview_set_at is None:
            return False
        return self._clock() - self._preview_set_at <= self._preview_timeout

    def resolve(self, motion_active, now_hhmm, fired_ha_entities=frozenset()):
        """Geeft (scene, transitioned) terug. `transitioned` is True als
        dit frame een trigger is gevolgd. `fired_ha_entities` is een
        eenmalige puls-set (net als `motion_active` een puls is, geen
        aanhoudend niveau) van HA-entity-ids die dit frame naar 'on' zijn
        gegaan."""
        if self.preview_recently_set():
            return self._preview, False
        if self._current_id not in self._scenes:
            self._current_id = self._root_id
        if self._current_id is None:
            return None, False
        for trigger in self._triggers.get(self._current_id, []):
            if trigger["to_scene_id"] not in self._scenes:
                continue  # doel bestaat niet (of staat uit) -- val door naar de volgende trigger
            if _trigger_matches(trigger, motion_active, now_hhmm, fired_ha_entities):
                if trigger["to_scene_id"] != self._current_id:
                    self._current_id = trigger["to_scene_id"]
                    return self._scenes.get(self._current_id), True
                break
        return self._scenes.get(self._current_id), False


def _trigger_matches(trigger, motion_active, now_hhmm, fired_ha_entities):
    kind = trigger["kind"]
    if kind == "always":
        return True
    if kind == "motion":
        return motion_active
    if kind == "schedule":
        return _time_in_window(now_hhmm, trigger.get("schedule_from"), trigger.get("schedule_until"))
    if kind == "ha_sensor":
        return trigger.get("ha_entity_id") in fired_ha_entities
    return False


def _time_in_window(now_hhmm, start, end):
    """"HH:MM"-vergelijking met middernacht-doorloop ondersteund
    (bijv. 22:00-02:00). Ontbrekende grenzen matchen nooit."""
    if not start or not end:
        return False
    if start <= end:
        return start <= now_hhmm < end
    return now_hhmm >= start or now_hhmm < end
