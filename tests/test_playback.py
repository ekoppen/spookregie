import pytest
from scare_node.playback import pick_audio_file


def test_picks_one_of_the_audio_files(tmp_path):
    (tmp_path / "scream1.wav").write_bytes(b"fake")
    (tmp_path / "scream2.wav").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_bytes(b"ignore me")

    picked = pick_audio_file(str(tmp_path))

    assert picked in (str(tmp_path / "scream1.wav"), str(tmp_path / "scream2.wav"))


def test_raises_when_no_audio_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        pick_audio_file(str(tmp_path))
