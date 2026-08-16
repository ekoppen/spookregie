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
