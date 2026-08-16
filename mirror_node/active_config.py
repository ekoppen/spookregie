import time


class ActiveMirrorConfig:
    """Houdt de actieve effect-config bij: een opgeslagen (persistente)
    config en een tijdelijke preview-config die na `preview_timeout`
    seconden zonder update automatisch vervalt. `.get()` geeft altijd de
    config die nu getoond moet worden, zodat een vergeten open
    beheerpagina-tab de projectie niet voor altijd in een proefstand
    laat hangen."""

    def __init__(self, preview_timeout=30, clock=time.monotonic):
        self._persistent = {
            "effect": "xray",
            "params": {},
            "overlay_hash": None,
            "scale": 1.0,
            "position": [0.5, 0.5],
        }
        self._preview = None
        self._preview_set_at = None
        self._preview_timeout = preview_timeout
        self._clock = clock

    def set_persistent(self, config):
        self._persistent = config
        self._preview = None

    def set_preview(self, config):
        self._preview = config
        self._preview_set_at = self._clock()

    def get(self):
        if self._preview is not None:
            if self._clock() - self._preview_set_at <= self._preview_timeout:
                return self._preview
            self._preview = None
        return self._persistent
