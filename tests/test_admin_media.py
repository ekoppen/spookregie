import os
import shutil
import subprocess

import pytest

from admin.app.db import init_db
from admin.app.media import (
    MAX_UPLOAD_SIZE,
    save_media,
    get_media_path,
    list_media,
    delete_media,
    validate_upload,
    extract_audio_if_video,
    get_media_audio_path,
)
from shared.media_sync import content_hash


def test_validate_upload_rejects_oversized_data():
    data = b"\x89PNG" + b"x" * MAX_UPLOAD_SIZE

    assert validate_upload(data, "mirror_overlay") is not None


def test_validate_upload_accepts_valid_headers():
    assert validate_upload(b"\x89PNG\r\n\x1a\nrest", "mirror_overlay") is None
    assert validate_upload(b"RIFF\x24\x00\x00\x00WAVEfmt ", "scare_audio") is None


def test_validate_upload_rejects_wrong_headers():
    assert validate_upload(b"GIF89a", "mirror_overlay") is not None
    assert validate_upload(b"ID3iets", "scare_audio") is not None
    # RIFF zonder WAVE (bijv. een AVI) hoort ook geweigerd te worden
    assert validate_upload(b"RIFF\x24\x00\x00\x00AVI ", "scare_audio") is not None


def test_validate_upload_ignores_unknown_category():
    assert validate_upload(b"wat-dan-ook", "iets_anders") is None


def test_save_media_stores_file_and_returns_hash(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")
    data = b"fake-png-bytes"

    result_hash = save_media(conn, media_dir, data, "spook.png", "mirror_overlay")

    assert result_hash == content_hash(data)
    assert get_media_path(media_dir, result_hash) is not None
    with open(get_media_path(media_dir, result_hash), "rb") as f:
        assert f.read() == data


def test_get_media_path_returns_none_for_unknown_hash(tmp_path):
    media_dir = str(tmp_path / "media")
    assert get_media_path(media_dir, "a" * 64) is None


def test_list_media_filters_by_category(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")
    save_media(conn, media_dir, b"overlay-data", "spook.png", "mirror_overlay")
    save_media(conn, media_dir, b"audio-data", "gil.wav", "scare_audio")

    overlays = list_media(conn, category="mirror_overlay")

    assert len(overlays) == 1
    assert overlays[0]["filename"] == "spook.png"
    assert overlays[0]["category"] == "mirror_overlay"


def test_list_media_without_category_returns_all(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")
    save_media(conn, media_dir, b"overlay-data", "spook.png", "mirror_overlay")
    save_media(conn, media_dir, b"audio-data", "gil.wav", "scare_audio")

    assert len(list_media(conn)) == 2


def test_delete_media_removes_file_and_row(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")
    h = save_media(conn, media_dir, b"data", "x.wav", "scare_audio")

    deleted = delete_media(conn, media_dir, h)

    assert deleted is True
    assert get_media_path(media_dir, h) is None
    assert list_media(conn) == []


def test_delete_media_returns_false_for_unknown_hash(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")

    assert delete_media(conn, media_dir, "a" * 64) is False


def test_get_media_path_rejects_absolute_path(tmp_path):
    media_dir = str(tmp_path / "media")
    assert get_media_path(media_dir, "/etc/passwd") is None


def test_get_media_path_rejects_path_traversal(tmp_path):
    media_dir = str(tmp_path / "media")
    assert get_media_path(media_dir, "../../etc/passwd") is None


def test_get_media_path_rejects_malformed_hash_uppercase(tmp_path):
    media_dir = str(tmp_path / "media")
    # Uppercase hex is invalid
    assert get_media_path(media_dir, "A" * 64) is None


def test_get_media_path_rejects_malformed_hash_non_hex(tmp_path):
    media_dir = str(tmp_path / "media")
    # Non-hex characters
    assert get_media_path(media_dir, "z" * 64) is None


def test_get_media_path_rejects_malformed_hash_wrong_length(tmp_path):
    media_dir = str(tmp_path / "media")
    # Wrong length
    assert get_media_path(media_dir, "a" * 63) is None
    assert get_media_path(media_dir, "a" * 65) is None


def test_delete_media_rejects_malformed_hash(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")

    assert delete_media(conn, media_dir, "/etc/passwd") is False
    assert delete_media(conn, media_dir, "../../etc/passwd") is False
    assert delete_media(conn, media_dir, "A" * 64) is False


def test_delete_media_orphan_file_not_deleted(tmp_path):
    """Test that delete_media does not delete orphan files (DB row missing).

    This ensures the DB is the source of truth: if a file exists on disk but
    has no corresponding DB row, calling delete_media with that hash should
    return False and NOT delete the file (it might be re-added later, or
    retained for audit purposes).
    """
    conn = init_db(str(tmp_path / "test.db"))
    media_dir = str(tmp_path / "media")

    # Create an orphan file by writing directly (bypassing save_media)
    orphan_hash = "b" * 64
    orphan_dir = tmp_path / "media"
    orphan_dir.mkdir()
    orphan_file = orphan_dir / orphan_hash
    orphan_file.write_bytes(b"orphan-data")

    # Try to delete it via delete_media (no DB row, so it should return False)
    result = delete_media(conn, str(media_dir), orphan_hash)

    assert result is False  # No DB row, so delete returns False
    assert orphan_file.exists()  # File should still exist
    assert orphan_file.read_bytes() == b"orphan-data"  # Unchanged


def _mp4_bytes():
    return b"\x00\x00\x00\x18ftypisom" + b"fake-mp4-body"


def test_validate_upload_accepts_valid_mp4_header():
    assert validate_upload(_mp4_bytes(), "mirror_scare_video") is None


def test_validate_upload_rejects_video_without_mp4_header():
    assert validate_upload(b"GIF89a-niet-een-mp4", "mirror_scare_video") is not None


def test_extract_audio_if_video_creates_companion_file(tmp_path, monkeypatch):
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)
    video_hash = "a" * 64
    with open(os.path.join(media_dir, video_hash), "wb") as f:
        f.write(b"fake-mp4-bytes")

    def fake_run(cmd, capture_output=True, timeout=30):
        with open(cmd[-1], "wb") as f:
            f.write(b"fake-wav-bytes")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run)

    extract_audio_if_video(media_dir, video_hash, "mirror_scare_video")

    assert get_media_audio_path(media_dir, video_hash) is not None
    with open(get_media_audio_path(media_dir, video_hash), "rb") as f:
        assert f.read() == b"fake-wav-bytes"


def test_extract_audio_if_video_skips_non_video_category(tmp_path, monkeypatch):
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)
    calls = []
    monkeypatch.setattr("admin.app.media.subprocess.run", lambda *a, **k: calls.append(1))

    extract_audio_if_video(media_dir, "a" * 64, "mirror_overlay")

    assert calls == []


def test_extract_audio_if_video_cleans_up_on_ffmpeg_failure(tmp_path, monkeypatch):
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)
    video_hash = "b" * 64

    def fake_run(cmd, capture_output=True, timeout=30):
        with open(cmd[-1], "wb"):
            pass  # ffmpeg laat soms een leeg bestand achter bij falen
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run)

    extract_audio_if_video(media_dir, video_hash, "mirror_scare_video")

    assert get_media_audio_path(media_dir, video_hash) is None


def test_extract_audio_if_video_handles_missing_ffmpeg_binary(tmp_path, monkeypatch):
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)

    def fake_run(cmd, capture_output=True, timeout=30):
        raise FileNotFoundError("ffmpeg niet gevonden")

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run)

    extract_audio_if_video(media_dir, "c" * 64, "mirror_scare_video")  # mag niet crashen

    assert get_media_audio_path(media_dir, "c" * 64) is None


def test_extract_audio_if_video_survives_cleanup_failure(tmp_path, monkeypatch):
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)
    video_hash = "d" * 64

    def fake_run(cmd, capture_output=True, timeout=30):
        with open(cmd[-1], "wb"):
            pass  # ffmpeg laat een leeg bestand achter bij falen
        return subprocess.CompletedProcess(cmd, 1)

    def failing_remove(path):
        raise PermissionError("kan niet verwijderen")

    monkeypatch.setattr("admin.app.media.subprocess.run", fake_run)
    monkeypatch.setattr("admin.app.media.os.remove", failing_remove)

    extract_audio_if_video(media_dir, video_hash, "mirror_scare_video")  # mag niet crashen


def test_get_media_audio_path_rejects_malformed_hash(tmp_path):
    media_dir = str(tmp_path / "media")
    assert get_media_audio_path(media_dir, "not-a-hash") is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg niet geïnstalleerd")
def test_extract_audio_if_video_produces_real_playable_wav(tmp_path):
    """Regressietest: eerdere versie miste -f wav, waardoor ffmpeg altijd
    non-zero exitte en er nooit een geluidsbestand ontstond -- elke test
    die subprocess.run mockte kon dit niet zien."""
    media_dir = str(tmp_path / "media")
    os.makedirs(media_dir)
    video_hash = "e" * 64
    video_path = os.path.join(media_dir, video_hash)

    # Genereer een echte, korte mp4 met een testtoon als geluidsspoor.
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
            "-shortest", "-c:v", "libx264", "-c:a", "aac", "-f", "mp4",
            video_path,
        ],
        capture_output=True,
        timeout=30,
    )
    assert os.path.exists(video_path)

    extract_audio_if_video(media_dir, video_hash, "mirror_scare_video")

    audio_path = get_media_audio_path(media_dir, video_hash)
    assert audio_path is not None
    with open(audio_path, "rb") as f:
        header = f.read(12)
    assert header[:4] == b"RIFF"
    assert header[8:12] == b"WAVE"
