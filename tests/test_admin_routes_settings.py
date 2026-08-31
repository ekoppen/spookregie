from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeBridge:
    def __init__(self):
        self.reconfigured_with = None

    def start(self):
        pass

    def stop(self):
        pass

    def reconfigure(self, runtime_settings):
        self.reconfigured_with = runtime_settings


def _client(tmp_path):
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


def test_get_settings_never_returns_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "seed-broker")
    client, app, _ = _client(tmp_path)

    response = client.get("/api/settings")

    body = response.json()
    assert body["mqtt_host"] == "seed-broker"
    assert "mqtt_pass" not in body
    assert "ha_token" not in body
    assert body["mqtt_pass_set"] is False
    assert body["ha_token_set"] is False


def test_put_settings_persists_and_reconfigures_bridge(tmp_path):
    client, app, bridge = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1884, "mqtt_user": "operator",
        "mqtt_pass": "geheim", "ha_url": "http://ha.local:8123",
        "ha_token": "token123", "mirror_stream_url": "http://mirror.local:8091/stream",
    })

    assert response.status_code == 200
    assert bridge.reconfigured_with.mqtt_host == "pi-broker"
    assert bridge.reconfigured_with.mqtt_pass == "geheim"

    get_response = client.get("/api/settings")
    body = get_response.json()
    assert body["mqtt_host"] == "pi-broker"
    assert body["mirror_stream_url"] == "http://mirror.local:8091/stream"
    assert body["mqtt_pass_set"] is True
    assert body["ha_token_set"] is True


def test_put_settings_blank_secret_keeps_existing_value(tmp_path):
    client, app, bridge = _client(tmp_path)
    client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_user": "",
        "mqtt_pass": "geheim", "ha_url": "", "ha_token": "", "mirror_stream_url": "",
    })

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_user": "",
        "mqtt_pass": "", "ha_url": "", "ha_token": "", "mirror_stream_url": "",
    })

    assert response.status_code == 200
    assert bridge.reconfigured_with.mqtt_pass == "geheim"


def test_put_settings_rejects_invalid_port(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={"mqtt_host": "pi-broker", "mqtt_port": 99999})

    assert response.status_code == 400


def test_put_settings_rejects_missing_host(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={"mqtt_host": "", "mqtt_port": 1883})

    assert response.status_code == 400


def test_put_settings_updates_runtime_settings_for_ha_router(tmp_path, monkeypatch):
    client, app, _ = _client(tmp_path)

    client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883,
        "ha_url": "http://new-ha.local:8123", "ha_token": "new-token-xyz",
        "mirror_stream_url": "",
    })

    def fake_get_states(ha_url, ha_token, fetch=None):
        assert ha_url == "http://new-ha.local:8123"
        assert ha_token == "new-token-xyz"
        return [{"entity_id": "light.test", "state": "on"}]

    monkeypatch.setattr("admin.app.routers.ha.get_states", fake_get_states)

    response = client.get("/api/ha/states")

    assert response.json() == [{"entity_id": "light.test", "state": "on"}]


def test_put_settings_rejects_malformed_url(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "ha_url": "not-a-url",
    })

    assert response.status_code == 400


def test_get_settings_includes_topic_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_TOPIC_PREFIX", "seed-prefix")
    client, app, _ = _client(tmp_path)

    response = client.get("/api/settings")

    assert response.json()["mqtt_topic_prefix"] == "seed-prefix"


def test_put_settings_persists_topic_prefix(tmp_path):
    client, app, bridge = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883,
        "mqtt_topic_prefix": "test",
    })

    assert response.status_code == 200
    assert bridge.reconfigured_with.mqtt_topic_prefix == "test"
    assert client.get("/api/settings").json()["mqtt_topic_prefix"] == "test"


def test_put_settings_rejects_hash_in_topic_prefix(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_topic_prefix": "test#",
    })

    assert response.status_code == 400


def test_put_settings_rejects_plus_in_topic_prefix(tmp_path):
    client, app, _ = _client(tmp_path)

    response = client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_topic_prefix": "te+st",
    })

    assert response.status_code == 400


