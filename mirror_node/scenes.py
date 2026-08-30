import time


class SceneEngine:
    """Houdt de laatst via MQTT ontvangen scene-lijst bij, plus een
    optionele tijdelijke preview-scene (zelfde TTL-mechanisme als de
    vroegere ActiveMirrorConfig, nu op scene-niveau)."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._scenes = []
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_scenes(self, scenes):
        self._scenes = scenes

    def set_preview(self, scene):
        self._preview = scene
        self._preview_set_at = self._clock()

    def preview_recently_set(self):
        if self._preview_set_at is None:
            return False
        return self._clock() - self._preview_set_at <= self._preview_timeout

    def resolve(self, motion_active, now_hhmm):
        """Geeft de winnende scene terug (of None): de preview-scene als
        die recent gezet is, anders de eerste ingeschakelde scene in
        volgorde wiens trigger nu matcht."""
        if self.preview_recently_set():
            return self._preview
        for scene in self._scenes:
            if not scene.get("enabled", True):
                continue
            trigger = scene.get("trigger_type")
            if trigger == "always":
                return scene
            if trigger == "motion" and motion_active:
                return scene
            if trigger == "schedule" and _time_in_window(
                now_hhmm, scene.get("trigger_from"), scene.get("trigger_until")
            ):
                return scene
        return None


def _time_in_window(now_hhmm, start, end):
    """"HH:MM"-vergelijking met middernacht-doorloop ondersteund
    (bijv. 22:00-02:00). Ontbrekende grenzen matchen nooit."""
    if not start or not end:
        return False
    if start <= end:
        return start <= now_hhmm < end
    return now_hhmm >= start or now_hhmm < end
