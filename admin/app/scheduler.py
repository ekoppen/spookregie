import threading
import time
from datetime import datetime


def _to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def should_be_sleeping(now, on_time, off_time):
    """`now`/`on_time`/`off_time` zijn 'HH:MM'-strings. Ondersteunt een
    venster dat over middernacht loopt (bijv. aan=22:00, uit=02:00)."""
    now_m = _to_minutes(now)
    on_m = _to_minutes(on_time)
    off_m = _to_minutes(off_time)

    if on_m <= off_m:
        return not (on_m <= now_m < off_m)
    # venster loopt over middernacht
    return not (now_m >= on_m or now_m < off_m)


class Scheduler:
    """Controleert elke minuut het ingestelde tijdvenster en publiceert
    system/sleep bij iedere check (retained, dus idempotent/robuust tegen
    herstarts) — vervangt de oude HA-tijdvenster-automation volledig."""

    def __init__(self, bridge, get_schedule, check_interval=60):
        self._bridge = bridge
        self._get_schedule = get_schedule
        self._check_interval = check_interval
        self._stop_event = threading.Event()
        self._thread = None

    def _loop(self):
        while not self._stop_event.is_set():
            on_time, off_time, enabled = self._get_schedule()
            if enabled:
                now = datetime.now().strftime("%H:%M")
                self._bridge.publish_sleep(should_be_sleeping(now, on_time, off_time))
            self._stop_event.wait(self._check_interval)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
