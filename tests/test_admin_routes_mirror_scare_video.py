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

    def publish_mirror_scare_video_config(self, enabled_hashes):
        self.calls.append(("mirror_scare_video_config", enabled_hashes))


def _settings(tmp_path):
    return Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"),
        media_dir=str(tmp_path / "media"),
        port=8000,
    )


def _client(tmp_path):
    app = create_app(settings=_settings(tmp_path))
    app.state.bridge = FakeBridge()
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app.state.bridge


def test_get_mirror_scare_video_config_defaults_to_empty(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.get("/api/mirror/scare-video-config")

    assert response.json() == {"enabled_hashes": []}


def test_put_mirror_scare_video_config_saves_and_publishes(tmp_path):
    client, bridge = _client(tmp_path)

    response = client.put(
        "/api/mirror/scare-video-config", json={"enabled_hashes": ["a" * 64, "b" * 64]}
    )

    assert response.status_code == 200
    assert ("mirror_scare_video_config", ["a" * 64, "b" * 64]) in bridge.calls
    assert client.get("/api/mirror/scare-video-config").json() == {
        "enabled_hashes": ["a" * 64, "b" * 64]
    }


def test_mirror_scare_video_config_requires_auth(tmp_path):
    app = create_app(settings=_settings(tmp_path))
    app.state.bridge = FakeBridge()
    client = TestClient(app)  # geen login

    assert client.get("/api/mirror/scare-video-config").status_code == 401
    assert client.put("/api/mirror/scare-video-config", json={"enabled_hashes": []}).status_code == 401
