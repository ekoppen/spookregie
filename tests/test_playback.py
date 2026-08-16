import pytest
from scare_node.playback import pick_audio_file


def test_picks_one_of_the_audio_files(tmp_path):
    (tmp_path / "scream1.wav").write_bytes(b"fake")
    (tmp_path / "scream2.wav").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_bytes(b"ignore me")
    (tmp_path / "scream3.mp3").write_bytes(b"aplay kan dit niet afspelen")

    picked = pick_audio_file(str(tmp_path))

    assert picked in (str(tmp_path / "scream1.wav"), str(tmp_path / "scream2.wav"))


def test_raises_when_no_audio_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        pick_audio_file(str(tmp_path))


def test_enabled_filter_restricts_selection(tmp_path):
    (tmp_path / "scream1.wav").write_bytes(b"fake")
    (tmp_path / "scream2.wav").write_bytes(b"fake")

    picked = pick_audio_file(str(tmp_path), enabled={"scream1.wav"})

    assert picked == str(tmp_path / "scream1.wav")


def test_enabled_filter_empty_set_raises(tmp_path):
    (tmp_path / "scream1.wav").write_bytes(b"fake")

    with pytest.raises(FileNotFoundError):
        pick_audio_file(str(tmp_path), enabled=set())


def test_no_enabled_argument_still_considers_all_files(tmp_path):
    (tmp_path / "scream1.wav").write_bytes(b"fake")

    picked = pick_audio_file(str(tmp_path))

    assert picked == str(tmp_path / "scream1.wav")
