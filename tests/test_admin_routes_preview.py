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


def test_preview_frame_returns_jpeg_for_the_default_source(tmp_path):
    client = _client(tmp_path)
    default_source = client.get("/api/sources").json()[0]
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, fake_frame)
        mock_open_camera.return_value = mock_cap

        response = client.post("/api/players/preview-frame", json={**_DRAFT, "source_id": default_source["id"]})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0
    mock_cap.release.assert_called_once()


def test_preview_frame_falls_back_to_default_source_when_source_id_is_null(tmp_path):
    """Regression voor Finding 5: een net-geopende, nog-niet-opgeslagen
    wizard stuurt source_id: null (EMPTY_DRAFT) -- dat moet net als een
    weggelaten source_id op de enige/eerste source terugvallen i.p.v. 400."""
    client = _client(tmp_path)
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, fake_frame)
        mock_open_camera.return_value = mock_cap

        response = client.post("/api/players/preview-frame", json={**_DRAFT, "source_id": None})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_preview_frame_rejects_unknown_source_id(tmp_path):
    client = _client(tmp_path)

    response = client.post("/api/players/preview-frame", json={**_DRAFT, "source_id": 999})

    assert response.status_code == 400


def test_preview_frame_returns_502_when_camera_read_fails(tmp_path):
    client = _client(tmp_path)
    default_source = client.get("/api/sources").json()[0]

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (False, None)
        mock_open_camera.return_value = mock_cap

        response = client.post("/api/players/preview-frame", json={**_DRAFT, "source_id": default_source["id"]})

    assert response.status_code == 502


def test_preview_frame_rejects_unknown_effect(tmp_path):
    client = _client(tmp_path)
    default_source = client.get("/api/sources").json()[0]
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)

    with patch("admin.app.routers.preview.open_camera") as mock_open_camera:
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, fake_frame)
        mock_open_camera.return_value = mock_cap

        response = client.post(
            "/api/players/preview-frame",
            json={**_DRAFT, "source_id": default_source["id"], "effect": "onbestaand"},
        )

    assert response.status_code == 400


def test_preview_frame_from_static_image_source(tmp_path, monkeypatch):
    client = _client(tmp_path)
    image_hash = "deadbeef" * 8  # 64 hex chars -- geldig content-hash-formaat
    media_dir = tmp_path / "media"
    media_dir.mkdir(exist_ok=True)
    (media_dir / image_hash).write_bytes(b"not-a-real-image-but-cv2.imread-is-mocked-below")
    source = client.post("/api/sources", json={
        "name": "Stilstaand", "kind": "static_image", "value": image_hash, "canvas_x": 0, "canvas_y": 0,
    }).json()
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)
    monkeypatch.setattr("admin.app.routers.preview.cv2.imread", lambda *a, **k: fake_frame)

    response = client.post(
        "/api/players/preview-frame", json={**_DRAFT, "source_id": source["id"]}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_preview_frame_route_requires_auth(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    app.state.bridge = FakeBridge()
    client = TestClient(app)

    response = client.post("/api/players/preview-frame", json=_DRAFT)

    assert response.status_code == 401
