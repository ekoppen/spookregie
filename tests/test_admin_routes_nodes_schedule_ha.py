from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app
from admin.app.runtime_settings import RuntimeSettings


class FakeBridge:
    def __init__(self):
        self.calls = []

    def start(self):
        pass

    def stop(self):
        pass

    def publish_sleep(self, is_sleeping):
        self.calls.append(("sleep", is_sleeping))


def _client(tmp_path, monkeypatch=None):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    bridge = FakeBridge()
    app.state.bridge = bridge
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app, bridge


def test_get_nodes_reflects_tracker_state(tmp_path):
    client, app, _ = _client(tmp_path)
    app.state.tracker.handle_message("status/mirror", "online")

    response = client.get("/api/nodes")

    assert response.json()["mirror"]["status"] == "online"


def test_get_and_put_schedule(tmp_path):
    client, app, _ = _client(tmp_path)

    put_response = client.put("/api/schedule", json={"on_time": "19:00", "off_time": "23:00", "enabled": True})
    assert put_response.status_code == 200

    get_response = client.get("/api/schedule")
    assert get_response.json() == {"on_time": "19:00", "off_time": "23:00", "enabled": True}


def test_put_schedule_rejects_malformed_time(tmp_path):
    client, app, _ = _client(tmp_path)
    client.put("/api/schedule", json={"on_time": "19:00", "off_time": "23:00", "enabled": True})

    response = client.put("/api/schedule", json={"on_time": "6pm", "off_time": "23:00", "enabled": True})

    assert response.status_code == 400
    # de oude, geldige waarde staat er nog: niets is weggeschreven
    assert client.get("/api/schedule").json() == {"on_time": "19:00", "off_time": "23:00", "enabled": True}


def test_put_schedule_rejects_out_of_range_time(tmp_path):
    client, app, _ = _client(tmp_path)

    assert client.put("/api/schedule", json={"on_time": "25:00", "off_time": "23:00"}).status_code == 400
    assert client.put("/api/schedule", json={"on_time": "18:00", "off_time": "22:70"}).status_code == 400
    # niets opgeslagen: GET geeft nog de defaults
    assert client.get("/api/schedule").json() == {"on_time": "18:00", "off_time": "22:00", "enabled": True}


def test_emergency_stop_publishes_sleep_on(tmp_path):
    client, app, bridge = _client(tmp_path)

    response = client.post("/api/system/emergency-stop")

    assert response.status_code == 200
    assert ("sleep", True) in bridge.calls


def test_wake_publishes_sleep_off(tmp_path):
    client, app, bridge = _client(tmp_path)

    response = client.post("/api/system/wake")

    assert response.status_code == 200
    assert ("sleep", False) in bridge.calls


def test_ha_states_proxies_to_ha_client(tmp_path, monkeypatch):
    client, app, _ = _client(tmp_path)
    app.state.runtime_settings = RuntimeSettings(
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="testtoken", mirror_stream_url="",
    )

    def fake_get_states(ha_url, ha_token, fetch=None):
        assert ha_url == "http://localhost:8123"
        assert ha_token == "testtoken"
        return [{"entity_id": "light.wled_voortuin", "state": "on"}]

    monkeypatch.setattr("admin.app.routers.ha.get_states", fake_get_states)

    response = client.get("/api/ha/states")

    assert response.json() == [{"entity_id": "light.wled_voortuin", "state": "on"}]


def test_ha_service_proxies_to_ha_client(tmp_path, monkeypatch):
    client, app, _ = _client(tmp_path)
    calls = []

    def fake_call_service(ha_url, ha_token, domain, service, data, fetch=None):
        calls.append((domain, service, data))

    monkeypatch.setattr("admin.app.routers.ha.call_service", fake_call_service)

    response = client.post("/api/ha/service", json={"domain": "light", "service": "turn_on", "data": {"entity_id": "light.wled_voortuin"}})

    assert response.status_code == 200
    assert calls == [("light", "turn_on", {"entity_id": "light.wled_voortuin"})]


def test_ha_service_returns_502_when_call_service_fails(tmp_path, monkeypatch):
    client, app, _ = _client(tmp_path)

    def failing_call_service(ha_url, ha_token, domain, service, data, fetch=None):
        raise OSError("HA onbereikbaar")

    monkeypatch.setattr("admin.app.routers.ha.call_service", failing_call_service)

    response = client.post("/api/ha/service", json={"domain": "light", "service": "turn_on", "data": {}})

    assert response.status_code == 502
