from admin.app.db import init_db
from admin.app.media import save_media, get_media_path, list_media, delete_media
from shared.media_sync import content_hash


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
