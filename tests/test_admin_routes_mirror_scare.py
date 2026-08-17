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

    def publish_mirror_config(self, config):
        self.calls.append(("mirror_config", config))

    def publish_mirror_preview(self, config):
        self.calls.append(("mirror_preview", config))

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
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()  # vervang de echte MQTT-bridge door een fake
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app.state.bridge


def test_put_mirror_config_saves_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    payload = {"effect": "thermal", "params": {"intensity": 0.8}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]}

    response = client.put("/api/mirror/config", json=payload)

    assert response.status_code == 200
    assert ("mirror_config", payload) in bridge.calls

    get_response = client.get("/api/mirror/config")
    assert get_response.json() == payload


def test_post_mirror_preview_publishes_without_saving(tmp_path):
    client, bridge = _client(tmp_path)
    client.put("/api/mirror/config", json={"effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    preview_payload = {"effect": "contour", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]}

    response = client.post("/api/mirror/preview", json=preview_payload)

    assert response.status_code == 200
    assert ("mirror_preview", preview_payload) in bridge.calls
    # opgeslagen config blijft ongewijzigd
    assert client.get("/api/mirror/config").json()["effect"] == "xray"


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


def test_put_mirror_config_normalizes_partial_payload(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/mirror/config", json={"effect": "thermal"})

    assert response.status_code == 200
    published = [c for c in bridge.calls if c[0] == "mirror_config"][-1][1]
    stored = client.get("/api/mirror/config").json()
    # gepubliceerde en opgeslagen config zijn identiek en volledig
    assert published == stored
    assert published == {
        "effect": "thermal", "params": {}, "overlay_hash": None,
        "scale": 1.0, "position": [0.5, 0.5],
    }


def test_post_scare_test_publishes(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/scare/zone-a/test")

    assert response.status_code == 200
    assert ("scare_test", "zone-a") in bridge.calls
