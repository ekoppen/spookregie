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

    def publish_device_assignment(self, device_uuid, output_id):
        self.calls.append(("device_assignment", device_uuid, output_id))


def _client(tmp_path, real_bridge=False):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "admin.db"),
        media_dir=str(tmp_path / "media"),
        log_dir=str(tmp_path / "logs"),
        port=8000,
    )
    app = create_app(settings)
    # ponytail: real_bridge keeps create_app()'s actual MqttBridge in place
    # (needed by the device-checkin/-assignment tests below, which poke at
    # bridge internals) instead of swapping in the calls-recording FakeBridge
    # the plain CRUD tests use.
    if not real_bridge:
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


def test_list_devices_includes_role_flags_and_camera_stream_url(tmp_path):
    client = _client(tmp_path)
    db = client.app.state.db
    _seed_device(db)

    response = client.get("/api/devices")

    body = response.json()
    assert body[0]["is_mirror"] is True
    assert body[0]["is_camera"] is False
    assert body[0]["camera_stream_url"] is None


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


def test_update_device_publishes_assignment_when_output_id_changes(tmp_path, monkeypatch):
    import admin.app.mqtt_bridge as mqtt_bridge_module

    class FakeMqttClient:
        def __init__(self, client_id=None):
            self.published = []
            self.subscribed = []

        def username_pw_set(self, *a, **k):
            pass

        def reconnect_delay_set(self, **k):
            pass

        def connect_async(self, *a, **k):
            pass

        def loop_start(self):
            pass

        def loop_stop(self):
            pass

        def subscribe(self, topic):
            self.subscribed.append(topic)

        def publish(self, topic, payload=None, retain=False):
            self.published.append((topic, payload, retain))

    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)
    client = _client(tmp_path, real_bridge=True)
    db = client.app.state.db
    device_id = _seed_device(db)
    output = client.post("/api/outputs", json={"name": "Spiegel"}).json()

    client.put(f"/api/devices/{device_id}", json={"name": "Voordeur-spiegel", "output_id": output["id"]})

    published = client.app.state.bridge._client.published
    assignment_messages = [p for p in published if "device-assignment/abc-123" in p[0]]
    assert len(assignment_messages) == 1
    import json as jsonlib
    assert jsonlib.loads(assignment_messages[0][1]) == {"output_id": output["id"]}


def test_device_info_checkin_creates_a_new_device(tmp_path):
    client = _client(tmp_path, real_bridge=True)
    client.app.state.bridge._on_device_info("new-device-uuid", {"name": "Pi Achtertuin", "platform": "linux", "git_sha": "abc1234"})

    devices = client.get("/api/devices").json()
    assert len(devices) == 1
    assert devices[0]["device_uuid"] == "new-device-uuid"
    assert devices[0]["name"] == "Pi Achtertuin"
    assert devices[0]["platform"] == "linux"
    assert devices[0]["git_sha"] == "abc1234"


def test_device_info_checkin_does_not_overwrite_a_user_renamed_device(tmp_path):
    client = _client(tmp_path, real_bridge=True)
    db = client.app.state.db
    device_id = _seed_device(db, device_uuid="abc-123", name="Voordeur-spiegel")

    client.app.state.bridge._on_device_info("abc-123", {"name": "hostname-gerapporteerd-door-apparaat", "platform": "darwin", "git_sha": "cafe123"})

    devices = client.get("/api/devices").json()
    assert devices[0]["name"] == "Voordeur-spiegel"
    assert devices[0]["platform"] == "darwin"
    assert devices[0]["git_sha"] == "cafe123"


def test_device_info_checkin_publishes_update_check_nudge(tmp_path, monkeypatch):
    import admin.app.mqtt_bridge as mqtt_bridge_module

    class FakeMqttClient:
        def __init__(self, client_id=None):
            self.published = []
            self.subscribed = []

        def username_pw_set(self, *a, **k):
            pass

        def reconnect_delay_set(self, **k):
            pass

        def connect_async(self, *a, **k):
            pass

        def loop_start(self):
            pass

        def loop_stop(self):
            pass

        def subscribe(self, topic):
            self.subscribed.append(topic)

        def publish(self, topic, payload=None, retain=False):
            self.published.append((topic, payload, retain))

    monkeypatch.setattr(mqtt_bridge_module.mqtt, "Client", FakeMqttClient)
    client = _client(tmp_path, real_bridge=True)

    client.app.state.bridge._on_device_info(
        "new-device-uuid", {"name": "Pi Achtertuin", "platform": "linux", "git_sha": "abc1234"}
    )

    published = client.app.state.bridge._client.published
    nudges = [p for p in published if "device-update-check" in p[0]]
    assert len(nudges) == 1
    assert nudges[0][2] is False  # niet-retained


def test_device_info_checkin_stores_camera_role_and_stream_url(tmp_path):
    client = _client(tmp_path, real_bridge=True)

    client.app.state.bridge._on_device_info(
        "camera-device-uuid",
        {
            "name": "MacBook camera",
            "platform": "darwin",
            "git_sha": "abc1234",
            "is_mirror": False,
            "is_camera": True,
            "camera_stream_url": "http://192.168.1.50:8080/stream",
        },
    )

    devices = client.get("/api/devices").json()
    assert len(devices) == 1
    assert devices[0]["is_mirror"] is False
    assert devices[0]["is_camera"] is True
    assert devices[0]["camera_stream_url"] == "http://192.168.1.50:8080/stream"


def test_device_info_checkin_without_role_fields_defaults_to_mirror_only(tmp_path):
    """Backward compat: een oude agent die nog geen is_mirror/is_camera
    stuurt mag een bestaand of nieuw apparaat niet naar camera-only zetten."""
    client = _client(tmp_path, real_bridge=True)

    client.app.state.bridge._on_device_info(
        "old-agent-uuid", {"name": "Oude node", "platform": "linux", "git_sha": "abc1234"}
    )

    devices = client.get("/api/devices").json()
    assert devices[0]["is_mirror"] is True
    assert devices[0]["is_camera"] is False
    assert devices[0]["camera_stream_url"] is None


def test_device_info_checkin_updates_camera_stream_url_on_existing_device(tmp_path):
    client = _client(tmp_path, real_bridge=True)
    db = client.app.state.db
    _seed_device(db, device_uuid="cam-1", name="MacBook camera")

    client.app.state.bridge._on_device_info(
        "cam-1",
        {
            "name": "hostname-genegeerd",
            "platform": "darwin",
            "git_sha": "def456",
            "is_mirror": False,
            "is_camera": True,
            "camera_stream_url": "http://192.168.1.51:8080/stream",
        },
    )

    devices = client.get("/api/devices").json()
    assert devices[0]["is_camera"] is True
    assert devices[0]["camera_stream_url"] == "http://192.168.1.51:8080/stream"


def test_device_info_checkin_without_role_fields_preserves_existing_camera_role(tmp_path):
    """Backward compat, UPDATE path: een oude/onvolledige check-in mag een
    al bekend camera-apparaat niet terugzetten naar mirror-only."""
    client = _client(tmp_path, real_bridge=True)
    client.app.state.bridge._on_device_info(
        "cam-2",
        {
            "name": "MacBook camera",
            "platform": "darwin",
            "git_sha": "abc1234",
            "is_mirror": False,
            "is_camera": True,
            "camera_stream_url": "http://192.168.1.52:8080/stream",
        },
    )

    client.app.state.bridge._on_device_info(
        "cam-2", {"name": "hostname-genegeerd", "platform": "darwin", "git_sha": "def5678"}
    )

    devices = client.get("/api/devices").json()
    assert devices[0]["is_mirror"] is False
    assert devices[0]["is_camera"] is True
    assert devices[0]["camera_stream_url"] == "http://192.168.1.52:8080/stream"


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
