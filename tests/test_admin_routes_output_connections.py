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

    def publish_mirror_graph(self, graph):
        self.calls.append(("graph", graph))

    def publish_mirror_scare_video_config(self, enabled_hashes):
        self.calls.append(("scare_video_config", enabled_hashes))

    def publish_mirror_ha_trigger(self, entity_id):
        self.calls.append(("ha_trigger", entity_id))


def _client(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app.state.bridge


_PLAYER_PAYLOAD = {
    "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
    "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
    "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0, "color": None,
    "source_id": None, "playback_mode": "once", "repeat_while_ha_entity_id": None,
}


def test_create_output_connection(tmp_path):
    client, bridge = _client(tmp_path)
    output = client.post("/api/outputs", json={"name": "Beamer", "camera_source": "", "canvas_x": 0, "canvas_y": 0}).json()
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]

    response = client.post("/api/output-connections", json={"output_id": output["id"], "from_branch_id": branch["id"]})

    assert response.status_code == 200
    created = response.json()
    assert created["output_id"] == output["id"]
    assert created["from_branch_id"] == branch["id"]


def test_create_output_connection_requires_existing_output(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]

    response = client.post("/api/output-connections", json={"output_id": 999, "from_branch_id": branch["id"]})

    assert response.status_code == 400


def test_create_output_connection_requires_existing_branch(tmp_path):
    client, bridge = _client(tmp_path)
    output = client.post("/api/outputs", json={"name": "Beamer", "camera_source": "", "canvas_x": 0, "canvas_y": 0}).json()

    response = client.post("/api/output-connections", json={"output_id": output["id"], "from_branch_id": 999})

    assert response.status_code == 400


def test_delete_output_connection(tmp_path):
    client, bridge = _client(tmp_path)
    output = client.post("/api/outputs", json={"name": "Beamer", "camera_source": "", "canvas_x": 0, "canvas_y": 0}).json()
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]
    connection = client.post("/api/output-connections", json={"output_id": output["id"], "from_branch_id": branch["id"]}).json()

    response = client.delete(f"/api/output-connections/{connection['id']}")

    assert response.status_code == 200


def test_delete_output_connection_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/output-connections/999")

    assert response.status_code == 404


def test_output_connection_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    assert client.post("/api/output-connections", json={"output_id": 1, "from_branch_id": 1}).status_code == 401
