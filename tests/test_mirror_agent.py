import json
import logging
import subprocess
from unittest.mock import patch

from mirror_node.agent import build_checkin_payload, check_and_apply_update, needs_update


def test_build_checkin_payload_shape():
    payload = build_checkin_payload(name="Oude MacBook", platform="darwin", git_sha="abc1234")
    assert json.loads(payload) == {"name": "Oude MacBook", "platform": "darwin", "git_sha": "abc1234"}


def test_needs_update_true_when_shas_differ():
    assert needs_update(local_sha="abc123", remote_sha="def456") is True


def test_needs_update_false_when_shas_match():
    assert needs_update(local_sha="abc123", remote_sha="abc123") is False


def test_check_and_apply_update_survives_hung_git_fetch():
    """Een hangende 'git fetch' mag de update-cyclus niet laten crashen --
    anders blokkeert dat ook de periodieke checkin in dezelfde main-loop."""
    logger = logging.getLogger("test-agent-timeout")
    with patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git fetch", timeout=30)
    ):
        check_and_apply_update("/tmp/does-not-matter", logger)  # mag niet raisen
