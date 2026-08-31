import time


class SceneGraph:
    """Houdt de laatst via MQTT ontvangen graaf bij (scenes + live
    edges) en de huidige-scene-toestand. Vervangt de vorige stateless
    SceneEngine: welke triggers ertoe doen hangt nu af van waar we nu
    zijn, niet van een globale prioriteitsscan."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._scenes = {}
        self._edges = {}
        self._root_id = None
        self._current_id = None
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_graph(self, scenes, edges, root_scene_id):
        self._scenes = {s["id"]: s for s in scenes}
        by_from = {}
        for e in edges:
            if e.get("to_scene_id") is None or e.get("trigger_type") is None:
                continue  # niet-live: lege stub of ongeconfigureerde trigger
            by_from.setdefault(e["from_scene_id"], []).append(e)
        for lst in by_from.values():
            lst.sort(key=lambda e: e["priority"])
        self._edges = by_from
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

    def resolve(self, motion_active, now_hhmm):
        """Geeft (scene, transitioned) terug. `transitioned` is True als
        dit frame een edge is gevolgd -- de hoofdlus gebruikt dat om
        _handle_trigger() precies bij aankomst aan te roepen, niet elke
        cyclus dat een scare-video-scene toevallig nog 'huidig' is."""
        if self.preview_recently_set():
            return self._preview, False
        if self._current_id not in self._scenes:
            self._current_id = self._root_id
        if self._current_id is None:
            return None, False
        for edge in self._edges.get(self._current_id, []):
            if _edge_matches(edge, motion_active, now_hhmm):
                if edge["to_scene_id"] != self._current_id:
                    self._current_id = edge["to_scene_id"]
                    return self._scenes.get(self._current_id), True
                break
        return self._scenes.get(self._current_id), False


def _edge_matches(edge, motion_active, now_hhmm):
    t = edge["trigger_type"]
    if t == "always":
        return True
    if t == "motion":
        return motion_active
    if t == "schedule":
        return _time_in_window(now_hhmm, edge.get("trigger_from"), edge.get("trigger_until"))
    return False


def _time_in_window(now_hhmm, start, end):
    """"HH:MM"-vergelijking met middernacht-doorloop ondersteund
    (bijv. 22:00-02:00). Ontbrekende grenzen matchen nooit."""
    if not start or not end:
        return False
    if start <= end:
        return start <= now_hhmm < end
    return now_hhmm >= start or now_hhmm < end
