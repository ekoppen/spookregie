from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeBridge:
    def __init__(self):
        self.calls = []

    def start(self):
        pass

    def stop(self):
        pass

    def publish_mirror_test(self):
        self.calls.append(("mirror_test",))

    def publish_scare_config(self, zone, enabled_hashes):
        self.calls.append(("scare_config", zone, enabled_hashes))

    def publish_scare_test(self, zone):
        self.calls.append(("scare_test", zone))

    def publish_sleep(self, is_sleeping):
        self.calls.append(("sleep", is_sleeping))


def _client(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()  # vervang de echte MQTT-bridge door een fake
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app.state.bridge


def test_post_mirror_test_publishes_test_trigger(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/mirror/test")

    assert response.status_code == 200
    assert ("mirror_test",) in bridge.calls


def test_put_scare_config_saves_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scare/zone-a/config", json={"enabled_hashes": ["a" * 64, "b" * 64]})

    assert response.status_code == 200
    assert ("scare_config", "zone-a", ["a" * 64, "b" * 64]) in bridge.calls
    assert client.get("/api/scare/zone-a/config").json() == {"enabled_hashes": ["a" * 64, "b" * 64]}


def test_get_scare_config_defaults_to_empty(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/scare/zone-b/config")

    assert response.json() == {"enabled_hashes": []}


def test_scare_routes_reject_zone_with_mqtt_wildcards(tmp_path):
    client, bridge = _client(tmp_path)

    # %23 = '#': als losse letter zou de client hem als URL-fragment zien
    for zone in ("zone%23a", "zone+a", "Zone_A"):
        assert client.get(f"/api/scare/{zone}/config").status_code == 400
        assert client.put(f"/api/scare/{zone}/config", json={"enabled_hashes": []}).status_code == 400
        assert client.post(f"/api/scare/{zone}/test").status_code == 400

    # de bridge is nooit aangeroepen met een ongeldige zone
    assert bridge.calls == []


def test_post_scare_test_publishes(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/scare/zone-a/test")

    assert response.status_code == 200
    assert ("scare_test", "zone-a") in bridge.calls
