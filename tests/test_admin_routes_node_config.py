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
    """Vervangt app.state.bridge door een FakeBridge -- anders roept een PUT
    /api/settings tijdens de test een ECHTE MqttBridge.reconfigure() aan, die
    een reëel achtergrondthread + verbindingspoging start. Zelfde patroon als
    _client() in tests/test_admin_routes_settings.py."""
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    return TestClient(app), app


def test_node_config_works_without_session_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_TOPIC_PREFIX", "seed-prefix")
    client, app = _client(tmp_path)

    response = client.get("/api/node-config")

    assert response.status_code == 200
    assert response.json() == {"mqtt_topic_prefix": "seed-prefix"}


def test_node_config_reflects_saved_prefix(tmp_path):
    client, app = _client(tmp_path)
    client.post("/api/login", json={"password": "testwachtwoord"})
    client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_topic_prefix": "gewijzigd",
    })

    response = client.get("/api/node-config")

    assert response.json() == {"mqtt_topic_prefix": "gewijzigd"}
