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

    def publish_mirror_graph(self, graph):
        pass


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
    assert response.json() == {"mqtt_topic_prefix": "seed-prefix", "mirror_camera_source": ""}


def test_node_config_reflects_saved_prefix(tmp_path):
    client, app = _client(tmp_path)
    client.post("/api/login", json={"password": "testwachtwoord"})
    client.put("/api/settings", json={
        "mqtt_host": "pi-broker", "mqtt_port": 1883, "mqtt_topic_prefix": "gewijzigd",
    })

    response = client.get("/api/node-config")

    assert response.json() == {"mqtt_topic_prefix": "gewijzigd", "mirror_camera_source": ""}


def test_node_config_includes_camera_source(tmp_path):
    """Nieuwe source, gekoppeld aan de root-player -- bewijst dat de bron
    via de root player's source_id resolvet (niet zomaar "de eerste
    source in de tabel"). Een verse db heeft geen enkele player/source
    totdat de test er zelf een aanmaakt (geen seed-data)."""
    client, app = _client(tmp_path)
    client.post("/api/login", json={"password": "testwachtwoord"})
    source = client.post("/api/sources", json={
        "name": "Tuin", "kind": "camera_stream", "value": "rtsp://cam.local/stream1",
        "canvas_x": 0.0, "canvas_y": 0.0,
    }).json()
    # De allereerste player krijgt altijd is_root, ongeacht de body
    # (zie admin/app/routers/players.py create_player_route).
    player = client.post("/api/players", json={"name": "Basis", "source_id": source["id"]}).json()
    assert player["is_root"] is True

    response = client.get("/api/node-config")

    assert response.json() == {
        "mqtt_topic_prefix": "",
        "mirror_camera_source": "rtsp://cam.local/stream1",
    }
