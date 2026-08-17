import threading

from admin.app.scheduler import Scheduler, should_be_sleeping


class FakeBridge:
    def __init__(self):
        self.calls = []

    def publish_sleep(self, is_sleeping):
        self.calls.append(is_sleeping)


class _FixedClock:
    """Vervangt datetime in scheduler.py zodat de tests niet van de echte
    klok afhangen."""

    def __init__(self, hhmm):
        self.hhmm = hhmm

    def now(self):
        return self

    def strftime(self, _fmt):
        return self.hhmm


def _fixed_now(monkeypatch, hhmm):
    monkeypatch.setattr("admin.app.scheduler.datetime", _FixedClock(hhmm))


def test_scheduler_publishes_once_for_an_unchanging_schedule(monkeypatch):
    _fixed_now(monkeypatch, "19:00")
    bridge = FakeBridge()
    scheduler = Scheduler(bridge, lambda: ("18:00", "22:00", True))

    for _ in range(5):
        scheduler._tick()

    assert bridge.calls == [False]


def test_scheduler_publishes_again_when_state_flips(monkeypatch):
    _fixed_now(monkeypatch, "19:00")
    bridge = FakeBridge()
    schedule = ["18:00", "22:00"]
    scheduler = Scheduler(bridge, lambda: (schedule[0], schedule[1], True))

    scheduler._tick()
    # venster verschuift zodat 19:00 er nu buiten valt
    schedule[0], schedule[1] = "20:00", "22:00"
    scheduler._tick()
    scheduler._tick()

    assert bridge.calls == [False, True]


def test_scheduler_skips_publishing_when_disabled():
    bridge = FakeBridge()
    scheduler = Scheduler(bridge, lambda: ("18:00", "22:00", False))

    scheduler._tick()

    assert bridge.calls == []


def test_scheduler_survives_malformed_time_in_db():
    bridge = FakeBridge()
    scheduler = Scheduler(bridge, lambda: ("6pm", "22:00", True))

    scheduler._tick()  # mag niet raisen
    scheduler._tick()

    assert bridge.calls == []


def test_scheduler_thread_stays_alive_and_stops_cleanly(monkeypatch):
    _fixed_now(monkeypatch, "19:00")
    bridge = FakeBridge()
    scheduler = Scheduler(bridge, lambda: ("18:00", "22:00", True), check_interval=0.01)
    scheduler.start()
    try:
        # ruim genoeg ticks om een publish-per-tick te betrappen
        threading.Event().wait(0.2)
        assert bridge.calls == [False]
    finally:
        scheduler.stop()
        scheduler._thread.join(timeout=1)
    assert not scheduler._thread.is_alive()


def test_should_be_sleeping_within_window_is_awake():
    assert should_be_sleeping("19:00", "18:00", "22:00") is False


def test_should_be_sleeping_before_window_is_asleep():
    assert should_be_sleeping("10:00", "18:00", "22:00") is True


def test_should_be_sleeping_after_window_is_asleep():
    assert should_be_sleeping("23:00", "18:00", "22:00") is True


def test_should_be_sleeping_at_exact_on_time_is_awake():
    assert should_be_sleeping("18:00", "18:00", "22:00") is False


def test_should_be_sleeping_at_exact_off_time_is_asleep():
    assert should_be_sleeping("22:00", "18:00", "22:00") is True


def test_should_be_sleeping_handles_overnight_window():
    # bijv. aan om 22:00, uit om 02:00 (loopt over middernacht)
    assert should_be_sleeping("23:30", "22:00", "02:00") is False
    assert should_be_sleeping("03:00", "22:00", "02:00") is True
