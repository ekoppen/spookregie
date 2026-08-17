import io
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app
from shared.media_sync import content_hash


def _client(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        mqtt_host="localhost", mqtt_port=1883, mqtt_user="", mqtt_pass="",
        ha_url="http://localhost:8123", ha_token="",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client


def test_upload_list_download_delete_roundtrip(tmp_path):
    client = _client(tmp_path)
    data = b"fake-overlay-png-bytes"

    upload_resp = client.post(
        "/api/media",
        files={"file": ("spook.png", io.BytesIO(data), "image/png")},
        data={"category": "mirror_overlay"},
    )
    assert upload_resp.status_code == 200
    h = upload_resp.json()["hash"]
    assert h == content_hash(data)

    list_resp = client.get("/api/media")
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["hash"] == h

    # download werkt zonder sessie-cookie (nodes hebben geen login)
    from fastapi.testclient import TestClient as PlainTestClient
    anon_client = PlainTestClient(client.app)
    download_resp = anon_client.get(f"/api/media/{h}")
    assert download_resp.status_code == 200
    assert download_resp.content == data

    delete_resp = client.delete(f"/api/media/{h}")
    assert delete_resp.status_code == 200
    assert client.get("/api/media").json() == []


def test_download_unknown_hash_returns_404(tmp_path):
    client = _client(tmp_path)
    from fastapi.testclient import TestClient as PlainTestClient
    anon_client = PlainTestClient(client.app)

    response = anon_client.get(f"/api/media/{'a' * 64}")

    assert response.status_code == 404


def test_list_can_filter_by_category(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/api/media",
        files={"file": ("spook.png", io.BytesIO(b"overlay"), "image/png")},
        data={"category": "mirror_overlay"},
    )
    client.post(
        "/api/media",
        files={"file": ("gil.wav", io.BytesIO(b"audio"), "audio/wav")},
        data={"category": "scare_audio"},
    )

    response = client.get("/api/media", params={"category": "scare_audio"})

    assert len(response.json()) == 1
    assert response.json()[0]["filename"] == "gil.wav"
