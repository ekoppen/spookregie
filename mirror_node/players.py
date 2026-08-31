import time


class PlayerGraph:
    """Houdt de laatst via MQTT ontvangen graaf bij (players + live
    triggers) en de huidige-player-toestand. Elke trigger ontspringt aan
    een branch (een naambare aftakking op een player) en wijst naar een
    volgende player (from_branch_id -> to_player_id), met een kind
    (always/motion/schedule/ha_sensor). De branch-naar-player-indirectie
    wordt eenmalig opgelost in set_graph() (branch_id -> player_id), dus
    resolve() zelf blijft simpelweg per-player kijken, zoals voorheen."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._players = {}
        self._triggers = {}
        self._root_id = None
        self._current_id = None
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_graph(self, players, branches, triggers, root_player_id):
        # Disabled players tellen niet mee -- ze mogen nooit als winnaar
        # terugkomen. Een trigger naar zo'n player wordt vanzelf als
        # "target bestaat niet" behandeld door resolve() (zelfde pad als
        # een trigger naar een écht verwijderde player).
        self._players = {p["id"]: p for p in players if p.get("enabled", True)}
        branch_to_player = {b["id"]: b["player_id"] for b in branches}
        by_from = {}
        for t in triggers:
            if t.get("to_player_id") is None or t.get("kind") is None:
                continue  # niet-live: lege stub of ongeconfigureerde trigger
            from_player_id = branch_to_player.get(t.get("from_branch_id"))
            if from_player_id is None:
                continue  # branch niet (meer) meegestuurd -- verweesde trigger, negeren
            by_from.setdefault(from_player_id, []).append(t)
        for lst in by_from.values():
            lst.sort(key=lambda t: t["priority"])
        self._triggers = by_from
        self._root_id = root_player_id
        if self._current_id not in self._players:
            self._current_id = root_player_id

    def set_preview(self, player):
        self._preview = player
        self._preview_set_at = self._clock()

    def preview_recently_set(self):
        if self._preview_set_at is None:
            return False
        return self._clock() - self._preview_set_at <= self._preview_timeout

    def resolve(self, motion_active, now_hhmm, fired_ha_entities=frozenset()):
        """Geeft (player, transitioned) terug. `transitioned` is True als
        dit frame een trigger is gevolgd. `fired_ha_entities` is een
        eenmalige puls-set (net als `motion_active` een puls is, geen
        aanhoudend niveau) van HA-entity-ids die dit frame naar 'on' zijn
        gegaan."""
        if self.preview_recently_set():
            return self._preview, False
        if self._current_id not in self._players:
            self._current_id = self._root_id
        if self._current_id is None:
            return None, False
        for trigger in self._triggers.get(self._current_id, []):
            if trigger["to_player_id"] not in self._players:
                continue  # doel bestaat niet (of staat uit) -- val door naar de volgende trigger
            if _trigger_matches(trigger, motion_active, now_hhmm, fired_ha_entities):
                if trigger["to_player_id"] != self._current_id:
                    self._current_id = trigger["to_player_id"]
                    return self._players.get(self._current_id), True
                break
        return self._players.get(self._current_id), False


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
