import json

from mirror_node.agent import build_checkin_payload, needs_update


def test_build_checkin_payload_shape():
    payload = build_checkin_payload(name="Oude MacBook", platform="darwin", git_sha="abc1234")
    assert json.loads(payload) == {"name": "Oude MacBook", "platform": "darwin", "git_sha": "abc1234"}


def test_needs_update_true_when_shas_differ():
    assert needs_update(local_sha="abc123", remote_sha="def456") is True


def test_needs_update_false_when_shas_match():
    assert needs_update(local_sha="abc123", remote_sha="abc123") is False
