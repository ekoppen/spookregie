from admin.app.ha_trigger_poller import HaTriggerPoller


class _FakeSettings:
    ha_url = "http://ha"
    ha_token = "tok"


class _FakeBridge:
    def __init__(self):
        self.fired = []

    def publish_mirror_ha_trigger(self, entity_id):
        self.fired.append(entity_id)

    def publish_mirror_ha_sensor_state(self, entity_id, state):
        pass


def test_rising_edge_fires_a_pulse(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "off"}],
    )
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()
    assert bridge.fired == []

    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "on"}],
    )
    poller._tick()
    assert bridge.fired == ["binary_sensor.tuin"]


def test_sustained_on_state_does_not_refire(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "on"}],
    )
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()
    poller._tick()
    poller._tick()

    assert bridge.fired == ["binary_sensor.tuin"]


def test_falling_then_rising_edge_fires_again(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    states = {"state": "off"}
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": states["state"]}],
    )
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    states["state"] = "on"
    poller._tick()
    states["state"] = "off"
    poller._tick()
    states["state"] = "on"
    poller._tick()

    assert bridge.fired == ["binary_sensor.tuin", "binary_sensor.tuin"]


def test_no_watched_entities_skips_the_ha_call(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    called = []
    monkeypatch.setattr(poller_module, "get_states", lambda url, token: called.append(1) or [])
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: [], check_interval=999)

    poller._tick()

    assert called == []
    assert bridge.fired == []


def test_ha_unreachable_does_not_crash_the_tick(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module

    def _raise(url, token):
        raise ConnectionError("HA onbereikbaar")

    monkeypatch.setattr(poller_module, "get_states", _raise)
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()  # mag niet raisen

    assert bridge.fired == []


def test_ha_outage_recovery_with_sensor_still_on_does_not_fire(monkeypatch):
    """Regression voor Finding 3: als HA even niets teruggeeft (uitval/
    herstart, get_states -> []) en de sensor blijkt bij herstel nog
    steeds 'on' te zijn, mag dat niet als stijgende flank gelden -- de
    persoon stond er al voor de uitval."""
    import admin.app.ha_trigger_poller as poller_module
    states = {"reachable": True, "state": "on"}

    def _fake_get_states(url, token):
        if not states["reachable"]:
            return []
        return [{"entity_id": "binary_sensor.tuin", "state": states["state"]}]

    monkeypatch.setattr(poller_module, "get_states", _fake_get_states)
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()  # rising edge None -> on, vuurt (verwacht)
    assert bridge.fired == ["binary_sensor.tuin"]

    states["reachable"] = False
    poller._tick()  # HA-uitval, sensor blijft ongewijzigd 'on'
    states["reachable"] = True
    poller._tick()  # HA terug, sensor nog steeds 'on' -- geen nieuwe flank

    assert bridge.fired == ["binary_sensor.tuin"]


def test_detected_state_also_counts_as_fired(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.deur", "state": "detected"}],
    )
    bridge = _FakeBridge()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.deur"], check_interval=999)

    poller._tick()

    assert bridge.fired == ["binary_sensor.deur"]


class _FakeBridgeWithState(_FakeBridge):
    def __init__(self):
        super().__init__()
        self.states = []

    def publish_mirror_ha_sensor_state(self, entity_id, state):
        self.states.append((entity_id, state))


def test_every_tick_publishes_current_state_for_every_watched_entity(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "off"}],
    )
    bridge = _FakeBridgeWithState()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()
    poller._tick()

    assert bridge.states == [("binary_sensor.tuin", "off"), ("binary_sensor.tuin", "off")]


def test_state_publish_happens_even_without_a_rising_edge(monkeypatch):
    """Onderscheid met de puls: state wordt ELKE tick gepubliceerd, ook
    als er niets verandert -- repeat_while moet weten dat de sensor nog
    steeds 'on' is, niet alleen het moment waarop hij dat werd."""
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(
        poller_module, "get_states",
        lambda url, token: [{"entity_id": "binary_sensor.tuin", "state": "on"}],
    )
    bridge = _FakeBridgeWithState()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()
    poller._tick()
    poller._tick()

    assert bridge.fired == ["binary_sensor.tuin"]  # puls: alleen de eerste keer
    assert bridge.states == [("binary_sensor.tuin", "on")] * 3  # state: elke keer


def test_state_not_published_for_entity_absent_from_ha_response(monkeypatch):
    import admin.app.ha_trigger_poller as poller_module
    monkeypatch.setattr(poller_module, "get_states", lambda url, token: [])
    bridge = _FakeBridgeWithState()
    poller = HaTriggerPoller(bridge, lambda: _FakeSettings(), lambda: ["binary_sensor.tuin"], check_interval=999)

    poller._tick()

    assert bridge.states == []
