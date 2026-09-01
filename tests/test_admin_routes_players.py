import sqlite3
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


_PLAYER_PAYLOAD = {
    "name": "Basis", "enabled": True, "source_mode": "camera", "effect": "xray",
    "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5],
    "canvas_size": None, "source_scale": 1.0, "source_position": [0.5, 0.5],
    "is_root": False, "canvas_x": 0.0, "canvas_y": 0.0,
    "source_id": None, "playback_mode": "once", "repeat_while_ha_entity_id": None, "color": None,
}


def test_create_player_persists_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]

    response = client.post("/api/players", json=_PLAYER_PAYLOAD)

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Basis"
    # Eerste scene ooit wordt automatisch root (Minor 12), ook al vroeg de
    # payload expliciet is_root: False.
    assert created["is_root"] is True
    graph_sources = client.get("/api/sources").json()
    graph_branches = client.get(f"/api/players/{created['id']}/branches").json()
    graph_output_connections = client.get("/api/output-connections").json()
    assert (
        "graph",
        {
            "players": [created], "sources": graph_sources,
            "branches": graph_branches, "triggers": [], "output_connections": graph_output_connections,
            "root_player_id": created["id"],
        },
    ) in bridge.calls

    listed = client.get("/api/players").json()
    assert listed == [created]


def test_first_scene_ever_becomes_root_automatically(tmp_path):
    """Regressie voor Minor 12: zonder root staat de mirror-node
    permanent op zwart zonder aanwijzing waarom. De eerste scene wordt
    daarom altijd root, ongeacht wat de body vraagt; een tweede scene
    daarna wordt dat niet vanzelf."""
    client, bridge = _client(tmp_path)

    first = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "Eerste", "is_root": False}).json()
    second = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "Tweede", "is_root": False}).json()

    assert first["is_root"] is True
    assert second["is_root"] is False


def test_get_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/players/999")

    assert response.status_code == 404


def test_update_player_persists_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    response = client.put(f"/api/players/{created['id']}", json={**_PLAYER_PAYLOAD, "name": "Bijgewerkt"})

    assert response.status_code == 200
    assert response.json()["name"] == "Bijgewerkt"
    assert client.get(f"/api/players/{created['id']}").json()["name"] == "Bijgewerkt"
    graph_sources = client.get("/api/sources").json()
    graph_branches = client.get(f"/api/players/{created['id']}/branches").json()
    graph_output_connections = client.get("/api/output-connections").json()
    assert (
        "graph",
        {
            "players": [response.json()], "sources": graph_sources,
            "branches": graph_branches, "triggers": [], "output_connections": graph_output_connections,
            "root_player_id": None,
        },
    ) in bridge.calls


def test_update_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/players/999", json=_PLAYER_PAYLOAD)

    assert response.status_code == 404


def test_delete_player_removes_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    response = client.delete(f"/api/players/{created['id']}")

    assert response.status_code == 200
    assert client.get("/api/players").json() == []
    graph_sources = client.get("/api/sources").json()
    graph_output_connections = client.get("/api/output-connections").json()
    assert (
        "graph",
        {
            "players": [], "sources": graph_sources,
            "branches": [], "triggers": [], "output_connections": graph_output_connections,
            "root_player_id": None,
        },
    ) in bridge.calls


def test_delete_scene_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/players/999")

    assert response.status_code == 404


def test_preview_scene_publishes_without_saving(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    bridge.calls.clear()

    response = client.post(
        f"/api/scenes/{created['id']}/preview", json={**_PLAYER_PAYLOAD, "effect": "contour"}
    )

    assert response.status_code == 200
    assert bridge.calls == [("scene_preview", {**_PLAYER_PAYLOAD, "effect": "contour"})]
    # niet opgeslagen:
    assert client.get(f"/api/players/{created['id']}").json()["effect"] == "xray"


def test_scene_routes_require_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)  # geen login

    assert client.get("/api/players").status_code == 401
    assert client.post("/api/players", json=_PLAYER_PAYLOAD).status_code == 401


def test_canvas_size_round_trips_through_width_height_columns(tmp_path):
    client, bridge = _client(tmp_path)

    created = client.post(
        "/api/players", json={**_PLAYER_PAYLOAD, "canvas_size": [576, 720]}
    ).json()

    assert created["canvas_size"] == [576, 720]
    assert client.get(f"/api/players/{created['id']}").json()["canvas_size"] == [576, 720]


def test_post_mirror_test_still_works(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/mirror/test")

    assert response.status_code == 200
    assert ("mirror_test",) in bridge.calls


def test_setting_is_root_unsets_it_elsewhere(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "A", "is_root": True}).json()
    b = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "B"}).json()

    client.put(f"/api/players/{b['id']}", json={**_PLAYER_PAYLOAD, "name": "B", "is_root": True})

    scenes = {s["id"]: s["is_root"] for s in client.get("/api/players").json()}
    assert scenes[a["id"]] is False
    assert scenes[b["id"]] is True


def test_update_scene_position_does_not_publish_to_mqtt(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    bridge.calls.clear()

    response = client.put(f"/api/players/{created['id']}/position", json={"canvas_x": 12.5, "canvas_y": -3.0})

    assert response.status_code == 200
    assert bridge.calls == []
    updated = client.get(f"/api/players/{created['id']}").json()
    assert updated["canvas_x"] == 12.5
    assert updated["canvas_y"] == -3.0


def test_update_scene_position_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put("/api/players/999/position", json={"canvas_x": 0, "canvas_y": 0})

    assert response.status_code == 404


def test_update_scene_position_rejects_non_numeric(tmp_path):
    client, bridge = _client(tmp_path)
    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    response = client.put(f"/api/players/{created['id']}/position", json={"canvas_x": "nope", "canvas_y": 0})

    assert response.status_code == 400


def test_deleting_scene_clears_its_own_and_incoming_triggers(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "B"}).json()
    branch_a = client.get(f"/api/players/{a['id']}/branches").json()[0]["id"]
    branch_b = client.get(f"/api/players/{b['id']}/branches").json()[0]["id"]
    client.post("/api/triggers", json={
        "from_branch_id": branch_a, "to_player_id": b["id"],
        "kind": "motion", "schedule_from": None, "schedule_until": None, "priority": 0,
    })
    client.post("/api/triggers", json={
        "from_branch_id": branch_b, "to_player_id": a["id"],
        "kind": "always", "schedule_from": None, "schedule_until": None, "priority": 0,
    })

    client.delete(f"/api/players/{a['id']}")

    remaining = client.get("/api/triggers").json()
    assert len(remaining) == 1
    assert remaining[0]["from_branch_id"] == branch_b
    assert remaining[0]["to_player_id"] is None
    assert remaining[0]["kind"] is None


def test_create_player_without_source_id_uses_the_default_source(tmp_path):
    client, bridge = _client(tmp_path)
    default_source = client.get("/api/sources").json()[0]

    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    assert created["source_id"] == default_source["id"]


def test_create_player_with_explicit_source_id(tmp_path):
    client, bridge = _client(tmp_path)
    other_source = client.post("/api/sources", json={
        "name": "Tuin", "kind": "camera_stream", "value": "", "canvas_x": 0.0, "canvas_y": 0.0,
    }).json()

    created = client.post("/api/players", json={**_PLAYER_PAYLOAD, "source_id": other_source["id"]}).json()

    assert created["source_id"] == other_source["id"]


def test_scene_color_round_trips(tmp_path):
    client, bridge = _client(tmp_path)

    created = client.post("/api/players", json={**_PLAYER_PAYLOAD, "color": "#ff8800"}).json()

    assert created["color"] == "#ff8800"
    fetched = client.get(f"/api/players/{created['id']}").json()
    assert fetched["color"] == "#ff8800"


def test_published_graph_has_the_full_new_shape(tmp_path):
    client, bridge = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    bridge.calls.clear()

    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    kind, graph = bridge.calls[-1]
    assert kind == "graph"
    assert "output_id" not in graph
    assert graph["players"] == [created]
    assert graph["root_player_id"] == created["id"]
    assert {s["kind"] for s in graph["sources"]} <= {"camera_stream", "static_image"}
    branch = client.get(f"/api/players/{created['id']}/branches").json()[0]
    assert graph["branches"] == [branch]
    assert isinstance(graph["triggers"], list)
    assert isinstance(graph["output_connections"], list)


def test_new_player_gets_one_default_branch(tmp_path):
    client, bridge = _client(tmp_path)

    created = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    branches = client.get(f"/api/players/{created['id']}/branches").json()
    assert len(branches) == 1
    assert branches[0]["name"] == "Uitgang 1"


def test_create_branch_on_player(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    response = client.post(f"/api/players/{player['id']}/branches", json={"name": "Extra pad"})

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Extra pad"
    assert created["player_id"] == player["id"]
    branches = client.get(f"/api/players/{player['id']}/branches").json()
    assert len(branches) == 2


def test_create_branch_requires_existing_player(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.post("/api/players/999/branches", json={"name": "X"})

    assert response.status_code == 404


def test_rename_branch(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]

    response = client.put(f"/api/branches/{branch['id']}", json={"name": "Hernoemd"})

    assert response.status_code == 200
    assert response.json()["name"] == "Hernoemd"


def test_delete_branch(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    extra = client.post(f"/api/players/{player['id']}/branches", json={"name": "Extra"}).json()

    response = client.delete(f"/api/branches/{extra['id']}")

    assert response.status_code == 200
    branches = client.get(f"/api/players/{player['id']}/branches").json()
    assert len(branches) == 1


def test_delete_branch_returns_404_for_unknown_id(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.delete("/api/branches/999")

    assert response.status_code == 404


def test_deleting_player_removes_its_branches(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()

    client.delete(f"/api/players/{player['id']}")

    response = client.get(f"/api/players/{player['id']}/branches")
    assert response.status_code == 404
    # De 404 hierboven komt alleen van de players-existence-check in de
    # route en bewijst dus niets over de branches-tabel zelf (Task 3
    # review-finding) -- rechtstreeks tellen is de enige echte garantie
    # dat DELETE FROM player_branches ook echt gebeurd is.
    raw = sqlite3.connect(str(tmp_path / "test.db"))
    count = raw.execute(
        "SELECT COUNT(*) FROM player_branches WHERE player_id = ?", (player["id"],)
    ).fetchone()[0]
    raw.close()
    assert count == 0


def test_delete_branch_rejected_when_it_has_a_trigger(tmp_path):
    client, bridge = _client(tmp_path)
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]
    client.post("/api/triggers", json={"from_branch_id": branch["id"]})

    response = client.delete(f"/api/branches/{branch['id']}")

    assert response.status_code == 400


def test_delete_branch_rejected_when_it_has_an_output_connection(tmp_path):
    client, bridge = _client(tmp_path)
    output = client.post("/api/outputs", json={"name": "X", "camera_source": "", "canvas_x": 0, "canvas_y": 0}).json()
    player = client.post("/api/players", json=_PLAYER_PAYLOAD).json()
    branch = client.get(f"/api/players/{player['id']}/branches").json()[0]
    client.post("/api/output-connections", json={"output_id": output["id"], "from_branch_id": branch["id"]})

    response = client.delete(f"/api/branches/{branch['id']}")

    assert response.status_code == 400


def test_list_all_branches_across_players(tmp_path):
    client, bridge = _client(tmp_path)
    a = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "A"}).json()
    b = client.post("/api/players", json={**_PLAYER_PAYLOAD, "name": "B"}).json()

    response = client.get("/api/branches")

    assert response.status_code == 200
    player_ids = {branch["player_id"] for branch in response.json()}
    assert player_ids == {a["id"], b["id"]}
