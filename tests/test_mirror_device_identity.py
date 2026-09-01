import os

from mirror_node.device_identity import get_or_create_device_uuid


def test_generates_and_persists_a_uuid_on_first_call(tmp_path):
    path = str(tmp_path / "device-id")
    first = get_or_create_device_uuid(path)
    assert len(first) == 36  # uuid4 string length
    assert os.path.exists(path)


def test_returns_the_same_uuid_on_a_second_call(tmp_path):
    path = str(tmp_path / "device-id")
    first = get_or_create_device_uuid(path)
    second = get_or_create_device_uuid(path)
    assert first == second


def test_creates_parent_directories_if_missing(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "device-id")
    uuid_value = get_or_create_device_uuid(path)
    assert os.path.exists(path)
    assert len(uuid_value) == 36
