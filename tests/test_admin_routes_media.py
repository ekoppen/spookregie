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
        data={"kind": "image"},
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
        data={"kind": "image"},
    )
    client.post(
        "/api/media",
        files={"file": ("gil.wav", io.BytesIO(WAV), "audio/wav")},
        data={"kind": "audio"},
    )

    response = client.get("/api/media", params={"kind": "audio"})

    assert len(response.json()) == 1
    assert response.json()[0]["filename"] == "gil.wav"


def _upload(client, name, data, kind):
    return client.post(
        "/api/media",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
        data={"kind": kind},
    )


def test_upload_rejects_overlay_without_png_header(tmp_path):
    client = _client(tmp_path)

    response = _upload(client, "spook.png", b"GIF89a-niet-echt-png", "image")

    assert response.status_code == 400
    assert client.get("/api/media").json() == []


def test_upload_rejects_audio_without_wav_header(tmp_path):
    client = _client(tmp_path)

    response = _upload(client, "gil.wav", b"ID3-dit-is-een-mp3", "audio")

    assert response.status_code == 400
    assert client.get("/api/media").json() == []


def test_upload_accepts_valid_png_and_wav(tmp_path):
    client = _client(tmp_path)

    assert _upload(client, "spook.png", PNG, "image").status_code == 200
    assert _upload(client, "gil.wav", WAV, "audio").status_code == 200
    assert len(client.get("/api/media").json()) == 2


def _mp4_bytes():
    return b"\x00\x00\x00\x18ftypisom" + b"fake-mp4-body"


def test_upload_scare_video_extracts_audio_via_ffmpeg(tmp_path, monkeypatch):
    client = _client(tmp_path)

    def fake_run(cmd, capture_output=True, timeout=30):
        import subprocess
        with open(cmd[-1], "wb") as f:
            f.write(b"fake-wav-bytes")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run)

    upload_resp = _upload(client, "zombie.mp4", _mp4_bytes(), "video")
    assert upload_resp.status_code == 200
    h = upload_resp.json()["hash"]

    from fastapi.testclient import TestClient as PlainTestClient
    anon_client = PlainTestClient(client.app)
    audio_resp = anon_client.get(f"/api/media/{h}/audio")
    assert audio_resp.status_code == 200
    assert audio_resp.content == b"fake-wav-bytes"


def test_download_audio_for_video_without_sound_returns_404(tmp_path, monkeypatch):
    client = _client(tmp_path)

    def fake_run_no_audio(cmd, capture_output=True, timeout=30):
        import subprocess
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run_no_audio)

    upload_resp = _upload(client, "bliksem.mp4", _mp4_bytes(), "video")
    h = upload_resp.json()["hash"]

    from fastapi.testclient import TestClient as PlainTestClient
    anon_client = PlainTestClient(client.app)
    audio_resp = anon_client.get(f"/api/media/{h}/audio")
    assert audio_resp.status_code == 404


def test_upload_rejects_video_without_mp4_header(tmp_path):
    client = _client(tmp_path)

    response = _upload(client, "zombie.mp4", b"GIF89a-niet-een-mp4", "video")

    assert response.status_code == 400
