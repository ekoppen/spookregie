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


def test_list_sources_includes_the_migrated_default(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/sources")

    assert response.status_code == 200
    sources = response.json()
    assert len(sources) == 1
    assert sources[0]["kind"] == "camera_stream"


def test_create_source(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/sources", json={
        "name": "Tuinbeeld", "kind": "camera_stream", "value": "rtsp://x", "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Tuinbeeld"
    assert created["kind"] == "camera_stream"


def test_create_source_rejects_empty_name(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/sources", json={
        "name": "  ", "kind": "camera_stream", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 400


def test_create_source_rejects_invalid_kind(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/sources", json={
        "name": "X", "kind": "teleport", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 400


def test_update_source(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/sources", json={
        "name": "A", "kind": "camera_stream", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    }).json()

    response = client.put(f"/api/sources/{created['id']}", json={
        "name": "B", "kind": "static_image", "value": "abc123", "canvas_x": 10.0, "canvas_y": 5.0,
    })

    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "B"
    assert updated["kind"] == "static_image"
    assert updated["canvas_x"] == 10.0


def test_update_source_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/sources/999", json={
        "name": "X", "kind": "camera_stream", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    })

    assert response.status_code == 404


def test_delete_source_without_players(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/sources", json={
        "name": "Tijdelijk", "kind": "camera_stream", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    }).json()

    response = client.delete(f"/api/sources/{created['id']}")

    assert response.status_code == 200
    remaining_ids = [s["id"] for s in client.get("/api/sources").json()]
    assert created["id"] not in remaining_ids


def test_source_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    assert client.get("/api/sources").status_code == 401
