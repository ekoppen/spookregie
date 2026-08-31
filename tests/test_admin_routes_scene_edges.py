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


_SCENE_PAYLOAD = {
    "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
    "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
    "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0,
}


def _two_scenes(client):
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()
    return a, b


def test_create_edge_with_empty_output_stub(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)

    response = client.post("/api/scene-edges", json={"from_scene_id": a["id"]})

    assert response.status_code == 200
    created = response.json()
    assert created["from_scene_id"] == a["id"]
    assert created["to_scene_id"] is None
    assert created["trigger_type"] is None
    assert client.get("/api/scene-edges").json() == [created]


def test_create_edge_requires_valid_from_scene_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/scene-edges", json={"from_scene_id": 999})

    assert response.status_code == 400


def test_update_edge_connects_and_configures_trigger(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    edge = client.post("/api/scene-edges", json={"from_scene_id": a["id"]}).json()

    response = client.put(f"/api/scene-edges/{edge['id']}", json={
        "from_scene_id": a["id"], "to_scene_id": b["id"],
        "trigger_type": "motion", "trigger_from": None, "trigger_until": None, "priority": 0,
    })

    assert response.status_code == 200
    updated = response.json()
    assert updated["to_scene_id"] == b["id"]
    assert updated["trigger_type"] == "motion"


def test_update_edge_requires_valid_to_scene_id(tmp_path):
    """Regressie voor Important 6: zonder deze validatie kan de UI (of
    een losse aanroep) een edge naar een onbestaande scene laten wijzen
    -- mirror_node volgt zo'n edge dan naar een lege scene en zit
    permanent op zwart."""
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    edge = client.post("/api/scene-edges", json={"from_scene_id": a["id"]}).json()

    response = client.put(f"/api/scene-edges/{edge['id']}", json={
        "from_scene_id": a["id"], "to_scene_id": 999,
        "trigger_type": "always", "trigger_from": None, "trigger_until": None, "priority": 0,
    })

    assert response.status_code == 400


def test_update_edge_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scene-edges/999", json={"from_scene_id": 1})

    assert response.status_code == 404


def test_delete_edge(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    edge = client.post("/api/scene-edges", json={"from_scene_id": a["id"]}).json()

    response = client.delete(f"/api/scene-edges/{edge['id']}")

    assert response.status_code == 200
    assert client.get("/api/scene-edges").json() == []


def test_delete_edge_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/scene-edges/999")

    assert response.status_code == 404


def test_every_write_publishes_full_graph_with_root(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    client.put(f"/api/scenes/{a['id']}", json={**_SCENE_PAYLOAD, "name": "A", "is_root": True})
    bridge.calls.clear()

    edge = client.post("/api/scene-edges", json={
        "from_scene_id": a["id"], "to_scene_id": b["id"],
        "trigger_type": "always", "trigger_from": None, "trigger_until": None, "priority": 0,
    }).json()

    kind, graph = bridge.calls[-1]
    assert kind == "graph"
    assert graph["root_scene_id"] == a["id"]
    assert graph["edges"] == [edge]


def test_scene_edge_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)  # geen login

    assert client.get("/api/scene-edges").status_code == 401
    assert client.post("/api/scene-edges", json={"from_scene_id": 1}).status_code == 401
