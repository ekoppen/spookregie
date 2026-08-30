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

    def publish_mirror_scenes(self, scenes):
        self.calls.append(("scenes", scenes))

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
    "trigger_type": "always", "trigger_from": None, "trigger_until": None,
}


def test_create_scene_persists_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/scenes", json=_SCENE_PAYLOAD)

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Basis"
    assert created["order_index"] == 0
    assert ("scenes", [created]) in bridge.calls

    listed = client.get("/api/scenes").json()
    assert listed == [created]


def test_create_scene_assigns_increasing_order_index(tmp_path):
    client, bridge = _client(tmp_path)

    first = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()
    second = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "Tweede"}).json()

    assert first["order_index"] == 0
    assert second["order_index"] == 1


def test_get_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/scenes/999")

    assert response.status_code == 404


def test_update_scene_persists_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    response = client.put(f"/api/scenes/{created['id']}", json={**_SCENE_PAYLOAD, "name": "Bijgewerkt"})

    assert response.status_code == 200
    assert response.json()["name"] == "Bijgewerkt"
    assert client.get(f"/api/scenes/{created['id']}").json()["name"] == "Bijgewerkt"
    assert ("scenes", [response.json()]) in bridge.calls


def test_update_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scenes/999", json=_SCENE_PAYLOAD)

    assert response.status_code == 404


def test_delete_scene_removes_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/scenes", json=_SCENE_PAYLOAD).json()

    response = client.delete(f"/api/scenes/{created['id']}")

    assert response.status_code == 200
    assert client.get("/api/scenes").json() == []
    assert ("scenes", []) in bridge.calls


def test_delete_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/scenes/999")

    assert response.status_code == 404


def test_reorder_scenes_updates_order_index(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/scenes", json={**_SCENE_PAYLOAD, "name": "B"}).json()

    response = client.put("/api/scenes/order", json={"order": [b["id"], a["id"]]})

    assert response.status_code == 200
    names = [s["name"] for s in client.get("/api/scenes").json()]
    assert names == ["B", "A"]


def test_reorder_scenes_rejects_non_list_order(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/scenes/order", json={"order": "niet-een-lijst"})

    assert response.status_code == 400


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
