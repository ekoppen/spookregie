from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.ha_client import sign_camera_entity
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


class _FakeHaStreamResponse:
    def __init__(self, chunks, content_type="multipart/x-mixed-replace; boundary=x"):
        self._chunks = list(chunks)
        self.headers = {"Content-Type": content_type}
        self.closed = False

    def read(self, size=8192):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def close(self):
        self.closed = True


def test_ha_camera_stream_proxies_bytes_and_content_type(tmp_path, monkeypatch):
    client, app, _ = _client(tmp_path)
    app.state.runtime_settings = RuntimeSettings(
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="testtoken", mirror_stream_url="",
    )
    fake_resp = _FakeHaStreamResponse([b"jpeg-bytes-1", b"jpeg-bytes-2"])

    def fake_open_camera_stream(ha_url, ha_token, entity_id):
        assert ha_url == "http://localhost:8123"
        assert ha_token == "testtoken"
        assert entity_id == "camera.voordeur"
        return fake_resp

    monkeypatch.setattr("admin.app.routers.ha.open_camera_stream", fake_open_camera_stream)
    sig = sign_camera_entity("testwachtwoord", "camera.voordeur")

    response = client.get(f"/api/ha/camera-stream/camera.voordeur?sig={sig}")

    assert response.status_code == 200
    assert response.content == b"jpeg-bytes-1jpeg-bytes-2"
    assert response.headers["content-type"] == "multipart/x-mixed-replace; boundary=x"
    assert fake_resp.closed


def test_ha_camera_stream_rejects_invalid_entity_id(tmp_path):
    client, app, _ = _client(tmp_path)
    sig = sign_camera_entity("testwachtwoord", "light.woonkamer")

    response = client.get(f"/api/ha/camera-stream/light.woonkamer?sig={sig}")

    assert response.status_code == 400


def test_ha_camera_stream_rejects_missing_signature(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.get("/api/ha/camera-stream/camera.voordeur")

    assert response.status_code == 403


def test_ha_camera_stream_rejects_wrong_signature(tmp_path):
    client, app, _ = _client(tmp_path)
    wrong_sig = sign_camera_entity("een-ander-wachtwoord", "camera.voordeur")

    response = client.get(f"/api/ha/camera-stream/camera.voordeur?sig={wrong_sig}")

    assert response.status_code == 403


def test_ha_camera_stream_rejects_signature_for_different_entity(tmp_path):
    client, app, _ = _client(tmp_path)
    # geldige signature, maar voor een andere entity_id -- voorkomt dat een
    # ondertekende URL voor de eigen camera hergebruikt wordt voor andermans
    sig = sign_camera_entity("testwachtwoord", "camera.achterdeur")

    response = client.get(f"/api/ha/camera-stream/camera.voordeur?sig={sig}")

    assert response.status_code == 403


def test_ha_camera_stream_returns_502_when_ha_unreachable(tmp_path, monkeypatch):
    client, app, _ = _client(tmp_path)

    def failing_open(ha_url, ha_token, entity_id):
        raise OSError("HA onbereikbaar")

    monkeypatch.setattr("admin.app.routers.ha.open_camera_stream", failing_open)
    sig = sign_camera_entity("testwachtwoord", "camera.voordeur")

    response = client.get(f"/api/ha/camera-stream/camera.voordeur?sig={sig}")

    assert response.status_code == 502


def test_ha_camera_stream_is_public_no_session_needed(tmp_path, monkeypatch):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    monkeypatch.setattr(
        "admin.app.routers.ha.open_camera_stream",
        lambda ha_url, ha_token, entity_id: _FakeHaStreamResponse([b"x"]),
    )
    client = TestClient(app)  # geen /api/login: dit endpoint mag geen sessie vereisen
    sig = sign_camera_entity("testwachtwoord", "camera.woonkamer")

    response = client.get(f"/api/ha/camera-stream/camera.woonkamer?sig={sig}")

    # 200, niet 401 -- bewijst dat de auth-middleware dit pad als publiek
    # herkent i.p.v. een ingelogde sessie te eisen (de signature-check zelf
    # blijft wel gelden, zie de rejects_missing/wrong_signature-tests).
    assert response.status_code == 200


def test_ha_camera_stream_url_requires_session(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)  # geen /api/login

    response = client.get("/api/ha/camera-stream-url/camera.voordeur")

    assert response.status_code == 401


def test_ha_camera_stream_url_returns_working_signature(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.get("/api/ha/camera-stream-url/camera.voordeur")

    assert response.status_code == 200
    url = response.json()["url"]
    assert url.startswith("/api/ha/camera-stream/camera.voordeur?sig=")
    sig = url.split("sig=", 1)[1]
    assert sig == sign_camera_entity("testwachtwoord", "camera.voordeur")


def test_ha_camera_stream_url_rejects_invalid_entity_id(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.get("/api/ha/camera-stream-url/light.woonkamer")

    assert response.status_code == 400
