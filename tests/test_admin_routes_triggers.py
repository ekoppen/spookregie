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


_SCENE_PAYLOAD = {
    "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
    "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
    "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0,
    "source_id": None, "playback_mode": "once", "repeat_while_ha_entity_id": None, "color": None,
}


def _two_scenes(client):
    a = client.post("/api/players", json={**_SCENE_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/players", json={**_SCENE_PAYLOAD, "name": "B"}).json()
    return a, b


def _branch_of(client, player):
    return client.get(f"/api/players/{player['id']}/branches").json()[0]["id"]


def test_create_trigger_with_empty_output_stub(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)

    response = client.post("/api/triggers", json={"from_branch_id": _branch_of(client, a)})

    assert response.status_code == 200
    created = response.json()
    assert created["from_branch_id"] == _branch_of(client, a)
    assert created["to_player_id"] is None
    assert created["kind"] is None
    assert created["ha_entity_id"] is None


def test_create_trigger_requires_valid_from_branch_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/triggers", json={"from_branch_id": 999})

    assert response.status_code == 400


def test_update_trigger_connects_and_sets_kind(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    branch_a = _branch_of(client, a)
    trigger = client.post("/api/triggers", json={"from_branch_id": branch_a}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={
        "from_branch_id": branch_a, "to_player_id": b["id"], "kind": "motion", "priority": 0,
    })

    assert response.status_code == 200
    updated = response.json()
    assert updated["to_player_id"] == b["id"]
    assert updated["kind"] == "motion"


def test_update_trigger_rejects_invalid_kind(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_branch_id": _branch_of(client, a)}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={"kind": "nonsense"})

    assert response.status_code == 400


def test_ha_sensor_kind_requires_ha_entity_id(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_branch_id": _branch_of(client, a)}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={
        "to_player_id": b["id"], "kind": "ha_sensor",
    })

    assert response.status_code == 400


def test_ha_sensor_kind_with_entity_id_succeeds(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_branch_id": _branch_of(client, a)}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={
        "to_player_id": b["id"], "kind": "ha_sensor", "ha_entity_id": "binary_sensor.tuin",
    })

    assert response.status_code == 200
    assert response.json()["ha_entity_id"] == "binary_sensor.tuin"


def test_update_trigger_rejects_unknown_to_player_id(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_branch_id": _branch_of(client, a)}).json()

    response = client.put(f"/api/triggers/{trigger['id']}", json={"to_player_id": 999, "kind": "always"})

    assert response.status_code == 400


def test_update_trigger_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/triggers/999", json={"from_branch_id": 1})

    assert response.status_code == 404


def test_delete_trigger(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_branch_id": _branch_of(client, a)}).json()

    response = client.delete(f"/api/triggers/{trigger['id']}")

    assert response.status_code == 200
    assert client.get("/api/triggers").json() == []


def test_delete_trigger_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/triggers/999")

    assert response.status_code == 404


def test_update_trigger_position_does_not_publish_to_mqtt(tmp_path):
    client, bridge = _client(tmp_path)
    a, _ = _two_scenes(client)
    trigger = client.post("/api/triggers", json={"from_branch_id": _branch_of(client, a)}).json()
    bridge.calls.clear()

    response = client.put(f"/api/triggers/{trigger['id']}/position", json={"canvas_x": 12.5, "canvas_y": -3.0})

    assert response.status_code == 200
    assert bridge.calls == []
    updated = client.get("/api/triggers").json()[0]
    assert updated["canvas_x"] == 12.5
    assert updated["canvas_y"] == -3.0


def test_update_trigger_position_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/triggers/999/position", json={"canvas_x": 0, "canvas_y": 0})

    assert response.status_code == 404


def test_every_write_publishes_full_graph_with_triggers_key(tmp_path):
    client, bridge = _client(tmp_path)
    a, b = _two_scenes(client)
    client.put(f"/api/players/{a['id']}", json={**_SCENE_PAYLOAD, "name": "A", "is_root": True})
    bridge.calls.clear()

    trigger = client.post("/api/triggers", json={
        "from_branch_id": _branch_of(client, a), "to_player_id": b["id"], "kind": "always", "priority": 0,
    }).json()

    kind, graph = bridge.calls[-1]
    assert kind == "graph"
    assert graph["triggers"] == [trigger]


def test_trigger_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    assert client.get("/api/triggers").status_code == 401
    assert client.post("/api/triggers", json={"from_branch_id": 1}).status_code == 401
