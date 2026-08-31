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

    def publish_mirror_scene_preview(self, scene):
        self.calls.append(("scene_preview", scene))

    def publish_mirror_test(self):
        self.calls.append(("mirror_test",))


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
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0, "output_id": None, "color": None,
}


def test_create_scene_persists_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]

    response = client.post("/api/scenes", json=_SCENE_PAYLOAD)

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Basis"
    # Eerste scene ooit wordt automatisch root (Minor 12), ook al vroeg de
    # payload expliciet is_root: False.
    assert created["is_root"] is True
    assert (
        "graph",
        {"output_id": default_output["id"], "scenes": [created], "triggers": [], "root_scene_id": created["id"]},
    ) in bridge.calls

    listed = client.get("/api/scenes").json()
    assert listed == [created]


def test_first_scene_ever_becomes_root_automatically(tmp_path):
    """Regressie voor Minor 12: zonder root staat de mirror-node
    permanent op zwart zonder aanwijzing waarom. De eerste scene wordt
    daarom altijd root, ongeacht wat de body vraagt; een tweede scene
    daarna wordt dat niet vanzelf."""
    client, bridge = _client(tmp_path)

    first = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "Eerste", "is_root": False}).json()
    second = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "Tweede", "is_root": False}).json()

    assert first["is_root"] is True
    assert second["is_root"] is False


def test_get_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/scenes/999")

    assert response.status_code == 404


def test_update_scene_persists_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    response = client.put(f"/api/scenes/{created['id']}", json={**_SCENE_PAYLOAD, "name": "Bijgewerkt"})

    assert response.status_code == 200
    assert response.json()["name"] == "Bijgewerkt"
    assert client.get(f"/api/scenes/{created['id']}").json()["name"] == "Bijgewerkt"
    assert (
        "graph",
        {"output_id": default_output["id"], "scenes": [response.json()], "triggers": [], "root_scene_id": None},
    ) in bridge.calls


def test_update_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scenes/999", json=_SCENE_PAYLOAD)

    assert response.status_code == 404


def test_delete_scene_removes_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    response = client.delete(f"/api/scenes/{created['id']}")

    assert response.status_code == 200
    assert client.get("/api/scenes").json() == []
    assert (
        "graph",
        {"output_id": default_output["id"], "scenes": [], "triggers": [], "root_scene_id": None},
    ) in bridge.calls


def test_delete_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/scenes/999")

    assert response.status_code == 404


def test_preview_scene_publishes_without_saving(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()
    bridge.calls.clear()

    response = client.post(
        f"/api/scenes/{created['id']}/preview", json={**_SCENE_PAYLOAD, "effect": "contour"}
    )

    assert response.status_code == 200
    assert bridge.calls == [("scene_preview", {**_SCENE_PAYLOAD, "effect": "contour"})]
    # niet opgeslagen:
    assert client.get(f"/api/scenes/{created['id']}").json()["effect"] == "xray"


def test_scene_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)  # geen login

    assert client.get("/api/scenes").status_code == 401
    assert client.post("/api/scenes", json=_SCENE_PAYLOAD).status_code == 401


def test_canvas_size_round_trips_through_width_height_columns(tmp_path):
    client, bridge = _client(tmp_path)

    created = client.post(
        "/api/scenes", json={**_SCENE_PAYLOAD, "canvas_size": [576, 720]}
    ).json()

    assert created["canvas_size"] == [576, 720]
    assert client.get(f"/api/scenes/{created['id']}").json()["canvas_size"] == [576, 720]


def test_post_mirror_test_still_works(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/mirror/test")

    assert response.status_code == 200
    assert ("mirror_test",) in bridge.calls


def test_setting_is_root_unsets_it_elsewhere(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A", "is_root": True}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()

    client.put(f"/api/scenes/{b['id']}", json={**_SCENE_PAYLOAD, "name": "B", "is_root": True})

    scenes = {s["id"]: s["is_root"] for s in client.get("/api/scenes").json()}
    assert scenes[a["id"]] is False
    assert scenes[b["id"]] is True


def test_update_scene_position_does_not_publish_to_mqtt(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()
    bridge.calls.clear()

    response = client.put(f"/api/scenes/{created['id']}/position", json={"canvas_x": 12.5, "canvas_y": -3.0})

    assert response.status_code == 200
    assert bridge.calls == []
    updated = client.get(f"/api/scenes/{created['id']}").json()
    assert updated["canvas_x"] == 12.5
    assert updated["canvas_y"] == -3.0


def test_update_scene_position_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scenes/999/position", json={"canvas_x": 0, "canvas_y": 0})

    assert response.status_code == 404


def test_update_scene_position_rejects_non_numeric(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    response = client.put(f"/api/scenes/{created['id']}/position", json={"canvas_x": "nope", "canvas_y": 0})

    assert response.status_code == 400


def test_deleting_scene_clears_its_own_and_incoming_edges(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()
    client.post("/api/scene-edges", json={
        "from_scene_id": a["id"], "to_scene_id": b["id"],
        "trigger_type": "motion", "trigger_from": None, "trigger_until": None, "priority": 0,
    })
    client.post("/api/scene-edges", json={
        "from_scene_id": b["id"], "to_scene_id": a["id"],
        "trigger_type": "always", "trigger_from": None, "trigger_until": None, "priority": 0,
    })

    client.delete(f"/api/scenes/{a['id']}")

    remaining = client.get("/api/scene-edges").json()
    assert len(remaining) == 1
    assert remaining[0]["from_scene_id"] == b["id"]
    assert remaining[0]["to_scene_id"] is None
    assert remaining[0]["trigger_type"] is None


def test_create_scene_without_output_id_uses_the_default_output(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]

    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    assert created["output_id"] == default_output["id"]


def test_create_scene_with_explicit_output_id(tmp_path):
    client, bridge = _client(tmp_path)
    other_output = client.post("/api/outputs", json={"name": "Beamer", "camera_source": ""}).json()

    created = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "output_id": other_output["id"]}).json()

    assert created["output_id"] == other_output["id"]


def test_scene_color_round_trips(tmp_path):
    client, bridge = _client(tmp_path)

    created = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "color": "#ff8800"}).json()

    assert created["color"] == "#ff8800"
    fetched = client.get(f"/api/scenes/{created['id']}").json()
    assert fetched["color"] == "#ff8800"


def test_published_graph_includes_output_id(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    bridge.calls.clear()

    client.post("/api/scenes", json=_SCENE_PAYLOAD)

    kind, graph = bridge.calls[-1]
    assert kind == "graph"
    assert graph["output_id"] == default_output["id"]
