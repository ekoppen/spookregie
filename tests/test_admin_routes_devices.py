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
        db_path=str(tmp_path / "admin.db"),
        media_dir=str(tmp_path / "media"),
        log_dir=str(tmp_path / "logs"),
        port=8000,
    )
    app = create_app(settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client


def _seed_device(db, device_uuid="abc-123", name="Oude MacBook", platform="darwin"):
    db.execute(
        "INSERT INTO devices (device_uuid, name, platform) VALUES (?, ?, ?)",
        (device_uuid, name, platform),
    )
    db.commit()
    return db.execute("SELECT id FROM devices WHERE device_uuid = ?", (device_uuid,)).fetchone()[0]


def test_list_devices_returns_empty_list_initially(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/devices")
    assert response.status_code == 200
    assert response.json() == []


def test_list_devices_returns_seeded_device(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db)
    response = client.get("/api/devices")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == device_id
    assert body[0]["device_uuid"] == "abc-123"
    assert body[0]["name"] == "Oude MacBook"
    assert body[0]["platform"] == "darwin"
    assert body[0]["output_id"] is None


def test_update_device_renames_and_assigns_output(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db)
    output = client.post("/api/outputs", json={"name": "Spiegel"}).json()

    response = client.put(f"/api/devices/{device_id}", json={"name": "Voordeur-spiegel", "output_id": output["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Voordeur-spiegel"
    assert body["output_id"] == output["id"]


def test_update_device_can_unassign_with_null_output_id(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db)
    output = client.post("/api/outputs", json={"name": "Spiegel"}).json()
    client.put(f"/api/devices/{device_id}", json={"name": "Voordeur-spiegel", "output_id": output["id"]})

    response = client.put(f"/api/devices/{device_id}", json={"name": "Voordeur-spiegel", "output_id": None})

    assert response.status_code == 200
    assert response.json()["output_id"] is None


def test_update_device_returns_404_for_unknown_id(tmp_path):
    client = _client(tmp_path)
    response = client.put("/api/devices/999", json={"name": "X", "output_id": None})
    assert response.status_code == 404


def test_delete_device_removes_it(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    device_id = _seed_device(db)

    response = client.delete(f"/api/devices/{device_id}")

    assert response.status_code == 200
    assert client.get("/api/devices").json() == []


def test_devices_route_requires_login(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "admin.db"),
        media_dir=str(tmp_path / "media"),
        log_dir=str(tmp_path / "logs"),
        port=8000,
    )
    app = create_app(settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)
    response = client.get("/api/devices")
    assert response.status_code == 401
