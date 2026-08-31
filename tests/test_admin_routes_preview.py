from unittest.mock import patch, MagicMock
import numpy as np
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app


class FakeBridge:
    def start(self): pass
    def stop(self): pass
    def publish_mirror_graph(self, graph): pass
    def publish_mirror_scare_video_config(self, enabled_hashes): pass
    def publish_mirror_ha_trigger(self, entity_id): pass


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
    return client


_DRAFT = {
    "effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0,
    "position": [0.5, 0.5], "canvas_size": None, "source_scale": 1.0,
    "source_position": [0.5, 0.5],
}


def test_preview_frame_returns_jpeg_for_the_default_output(tmp_path):
    client = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, fake_frame)
        mock_open_camera.return_value = mock_cap

        response = client.post("/api/scenes/preview-frame", json={**_DRAFT, "output_id": default_output["id"]})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0
    mock_cap.release.assert_called_once()


def test_preview_frame_rejects_unknown_output_id(tmp_path):
    client = _client(tmp_path)

    response = client.post("/api/scenes/preview-frame", json={**_DRAFT, "output_id": 999})

    assert response.status_code == 400


def test_preview_frame_returns_502_when_camera_read_fails(tmp_path):
    client = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (False, None)
        mock_open_camera.return_value = mock_cap

        response = client.post("/api/scenes/preview-frame", json={**_DRAFT, "output_id": default_output["id"]})

    assert response.status_code == 502


def test_preview_frame_rejects_unknown_effect(tmp_path):
    client = _client(tmp_path)
    default_output = client.get("/api/outputs").json()[0]
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, fake_frame)
        mock_open_camera.return_value = mock_cap

        response = client.post(
            "/api/scenes/preview-frame",
            json={**_DRAFT, "output_id": default_output["id"], "effect": "onbestaand"},
        )

    assert response.status_code == 400


def test_preview_frame_route_requires_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    response = client.post("/api/scenes/preview-frame", json=_DRAFT)

    assert response.status_code == 401
