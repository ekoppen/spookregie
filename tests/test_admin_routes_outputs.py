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


def test_list_outputs_includes_the_migrated_default(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/outputs")

    assert response.status_code == 200
    outputs = response.json()
    assert len(outputs) == 1
    assert outputs[0]["name"] == "Spiegel"


def test_create_output(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/outputs", json={"name": "Beamer tuin", "camera_source": "rtsp://x"})

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Beamer tuin"
    assert created["camera_source"] == "rtsp://x"


def test_create_output_rejects_empty_name(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/outputs", json={"name": "  ", "camera_source": ""})

    assert response.status_code == 400


def test_update_output(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/outputs", json={"name": "A", "camera_source": ""}).json()

    response = client.put(f"/api/outputs/{created['id']}", json={"name": "B", "camera_source": "rtsp://y"})

    assert response.status_code == 200
    assert response.json()["name"] == "B"


def test_update_output_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/outputs/999", json={"name": "X", "camera_source": ""})

    assert response.status_code == 404


def test_delete_output_without_scenes(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/outputs", json={"name": "Tijdelijk", "camera_source": ""}).json()

    response = client.delete(f"/api/outputs/{created['id']}")

    assert response.status_code == 200
    remaining_ids = [o["id"] for o in client.get("/api/outputs").json()]
    assert created["id"] not in remaining_ids


# test_delete_output_rejected_when_it_has_a_scene lived here: it exercised
# outputs.py's players-based delete-guard (SELECT ... FROM players WHERE
# output_id = ?), which can no longer be triggered through the API now
# that output_id is dead weight on players (superseded by branch-based
# routing). Task 6 replaces this with an output_connections-based guard
# and its own test.


def test_output_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    assert client.get("/api/outputs").status_code == 401


def test_output_canvas_position_round_trips(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/outputs", json={
        "name": "A", "camera_source": "", "canvas_x": 12.5, "canvas_y": -3.0,
    }).json()

    assert created["canvas_x"] == 12.5
    assert created["canvas_y"] == -3.0
    fetched = client.get(f"/api/outputs/{created['id']}").json()
    assert fetched["canvas_x"] == 12.5
