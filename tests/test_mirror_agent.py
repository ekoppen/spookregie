import json
import logging
import subprocess
from unittest.mock import patch

import mirror_node.agent as agent_module
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


def _fake_git_pull_run(cmd, **kwargs):
    if cmd[0] == "git":
        if cmd[1] == "fetch":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[1] == "rev-parse" and cmd[2] == "HEAD":
            return subprocess.CompletedProcess(cmd, 0, "abc123", "")
        if cmd[1] == "rev-parse" and cmd[2] == "origin/main":
            return subprocess.CompletedProcess(cmd, 0, "def456", "")
        if cmd[1] == "pull":
            return subprocess.CompletedProcess(cmd, 0, "", "")
    raise AssertionError(f"onverwachte git-aanroep: {cmd}")


def test_check_and_apply_update_reinstalls_requirements_before_restart(monkeypatch, tmp_path):
    """Na een succesvolle pull moet pip install -r requirements.txt draaien
    vóór de herstart -- anders crash-loopt de mirror-service op een
    ontbrekende dependency (Belangrijk 6)."""
    logger = logging.getLogger("test-agent-pip-success")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "git":
            return _fake_git_pull_run(cmd, **kwargs)
        if cmd[0].endswith("/pip"):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd == ["restart-mirror"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"onverwacht commando: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(agent_module, "MIRROR_RESTART_COMMAND", "restart-mirror")

    check_and_apply_update(str(tmp_path), logger)

    pip_calls = [c for c in calls if c[0].endswith("/pip")]
    assert len(pip_calls) == 1
    assert pip_calls[0][1:4] == ["install", "-q", "-r"]
    assert calls.index(pip_calls[0]) < calls.index(["restart-mirror"])


def test_check_and_apply_update_skips_restart_when_pip_install_fails(monkeypatch, tmp_path):
    """Een mislukte pip install mag de mirror-service niet herstarten in een
    kapotte dependency-staat -- loggen en overslaan, volgende cyclus
    probeert opnieuw."""
    logger = logging.getLogger("test-agent-pip-fail")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "git":
            return _fake_git_pull_run(cmd, **kwargs)
        if cmd[0].endswith("/pip"):
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        raise AssertionError(f"onverwacht commando: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(agent_module, "MIRROR_RESTART_COMMAND", "restart-mirror")

    check_and_apply_update(str(tmp_path), logger)

    assert ["restart-mirror"] not in calls
