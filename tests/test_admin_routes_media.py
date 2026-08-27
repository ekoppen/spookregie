import io
from fastapi.testclient import TestClient
from admin.app.config import Settings
from admin.app.main import create_app
from shared.media_sync import content_hash


def _client(tmp_path):
    settings = Settings(
        admin_password="testwachtwoord",
        db_path=str(tmp_path / "test.db"), media_dir=str(tmp_path / "media"),
        port=8000,
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    client.post("/api/login", json={"password": "testwachtwoord"})
    return client


PNG = b"\x89PNG\r\n\x1a\n" + b"nep-overlay"
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"nep-audio"


def test_upload_list_download_delete_roundtrip(tmp_path):
    client = _client(tmp_path)
    data = PNG

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
        files={"file": ("spook.png", io.BytesIO(PNG), "image/png")},
        data={"category": "mirror_overlay"},
    )
    client.post(
        "/api/media",
        files={"file": ("gil.wav", io.BytesIO(WAV), "audio/wav")},
        data={"category": "scare_audio"},
    )

    response = client.get("/api/media", params={"category": "scare_audio"})

    assert len(response.json()) == 1
    assert response.json()[0]["filename"] == "gil.wav"


def _upload(client, name, data, category):
    return client.post(
        "/api/media",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
        data={"category": category},
    )


def test_upload_rejects_overlay_without_png_header(tmp_path):
    client = _client(tmp_path)

    response = _upload(client, "spook.png", b"GIF89a-niet-echt-png", "mirror_overlay")

    assert response.status_code == 400
    assert client.get("/api/media").json() == []


def test_upload_rejects_audio_without_wav_header(tmp_path):
    client = _client(tmp_path)

    response = _upload(client, "gil.wav", b"ID3-dit-is-een-mp3", "scare_audio")

    assert response.status_code == 400
    assert client.get("/api/media").json() == []


def test_upload_accepts_valid_png_and_wav(tmp_path):
    client = _client(tmp_path)

    assert _upload(client, "spook.png", PNG, "mirror_overlay").status_code == 200
    assert _upload(client, "gil.wav", WAV, "scare_audio").status_code == 200
    assert len(client.get("/api/media").json()) == 2
