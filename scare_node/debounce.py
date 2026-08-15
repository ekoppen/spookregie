import time


class Cooldown:
    """Laat `.ready()` maar één keer per `seconds` True teruggeven, tegen
    PIR-vals-positieven (wind, dieren, koplampen) die anders continu
    zouden triggeren."""

    def __init__(self, seconds, clock=time.monotonic):
        self.seconds = seconds
        self._clock = clock
        self._last = None

    def ready(self):
        now = self._clock()
        if self._last is None or now - self._last >= self.seconds:
            self._last = now
            return True
        return False
