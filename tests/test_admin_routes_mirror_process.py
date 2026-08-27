from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeMirrorProcess:
    def __init__(self):
        self.calls = []
        self._running = False

    def start(self):
        self.calls.append("start")
        self._running = True
        return {"running": True, "pid": 1234}

    def stop(self):
        self.calls.append("stop")
        self._running = False
        return {"running": False, "pid": None}

    def status(self):
        return {"running": self._running, "pid": 1234 if self._running else None}


def _settings(tmp_path):
    return Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"),
        media_dir=str(tmp_path / "media"),
        port=8000,
    )


def _client(tmp_path):
    app = create_app(settings=_settings(tmp_path))
    app.state.mirror_process = FakeMirrorProcess()
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client, app.state.mirror_process


def test_start_requires_auth(tmp_path):
    app = create_app(settings=_settings(tmp_path))
    app.state.mirror_process = FakeMirrorProcess()
    client = TestClient(app)  # geen login

    response = client.post("/api/mirror-node/start")

    assert response.status_code == 401


def test_start_calls_manager_and_returns_status(tmp_path):
    client, manager = _client(tmp_path)

    response = client.post("/api/mirror-node/start")

    assert response.status_code == 200
    assert response.json() == {"running": True, "pid": 1234}
    assert manager.calls == ["start"]


def test_stop_calls_manager_and_returns_status(tmp_path):
    client, manager = _client(tmp_path)
    client.post("/api/mirror-node/start")

    response = client.post("/api/mirror-node/stop")

    assert response.status_code == 200
    assert response.json() == {"running": False, "pid": None}
    assert manager.calls == ["start", "stop"]


def test_status_returns_current_state(tmp_path):
    client, manager = _client(tmp_path)

    response = client.get("/api/mirror-node/status")

    assert response.status_code == 200
    assert response.json() == {"running": False, "pid": None}
