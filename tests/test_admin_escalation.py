from admin.app.db import init_db
from admin.app.escalation import current_tier, filter_by_tier, read_escalation_time, read_intensity_by_hash
from admin.app.media import save_media, set_media_intensity
from admin.app.runtime_settings import write_runtime_settings


def test_current_tier_is_none_when_no_escalation_time_set():
    assert current_tier("22:00", "") is None


def test_current_tier_is_subtle_before_escalation_time():
    assert current_tier("19:00", "21:00") == "subtle"


def test_current_tier_is_full_after_escalation_time():
    assert current_tier("22:00", "21:00") == "full"


def test_current_tier_is_full_at_exact_escalation_time():
    assert current_tier("21:00", "21:00") == "full"


def test_filter_by_tier_passes_everything_when_tier_is_none():
    assert filter_by_tier(["a", "b"], {"a": "full"}, None) == ["a", "b"]


def test_filter_by_tier_keeps_untagged_hashes_in_any_tier():
    assert filter_by_tier(["a"], {}, "subtle") == ["a"]


def test_filter_by_tier_keeps_only_matching_intensity():
    hashes = ["a", "b", "c"]
    intensity = {"a": "subtle", "b": "full", "c": "subtle"}
    assert filter_by_tier(hashes, intensity, "subtle") == ["a", "c"]
    assert filter_by_tier(hashes, intensity, "full") == ["b"]


def test_read_intensity_by_hash_returns_tagged_media(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    h = save_media(conn, str(tmp_path / "media"), b"data", "x.wav", "audio")
    set_media_intensity(conn, h, "full")

    assert read_intensity_by_hash(conn) == {h: "full"}


def test_read_intensity_by_hash_includes_untagged_media_as_none(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    h = save_media(conn, str(tmp_path / "media"), b"data", "x.wav", "audio")

    assert read_intensity_by_hash(conn) == {h: None}


def test_read_escalation_time_defaults_to_empty(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))

    assert read_escalation_time(conn) == ""


def test_read_escalation_time_returns_saved_value(tmp_path):
    conn = init_db(str(tmp_path / "test.db"))
    write_runtime_settings(conn, scare_escalation_time="21:00")

    assert read_escalation_time(conn) == "21:00"
