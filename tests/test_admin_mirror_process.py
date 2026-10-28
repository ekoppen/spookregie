from admin.app.mirror_process import MirrorProcessManager


class FakeSettings:
    mqtt_host = "localhost"
    mqtt_port = 1883
    mqtt_user = ""
    mqtt_pass = ""


class FakeProc:
    def __init__(self, pid=1234, lines=None):
        self.pid = pid
        self.stdout = iter(lines or [])
        self._terminated = False
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._terminated = True
        self._returncode = 0

    def wait(self, timeout=None):
        return self._returncode

    def kill(self):
        self._returncode = -9


def test_start_spawns_process_with_expected_env(monkeypatch):
    captured = {}

    def fake_popen(cmd, env=None, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        return FakeProc()

    monkeypatch.setattr("admin.app.mirror_process.subprocess.Popen", fake_popen)
    manager = MirrorProcessManager(FakeSettings())

    result = manager.start()

    assert result == {"running": True, "pid": 1234}
    assert captured["cmd"][1:] == ["-m", "mirror_node.main"]
    assert captured["env"]["MIRROR_HEADLESS"] == "1"
    assert captured["env"]["MQTT_HOST"] == "localhost"
    assert captured["env"]["MQTT_PORT"] == "1883"
    assert captured["env"]["BACKEND_URL"] == "http://localhost:8000"
    assert captured["env"]["LOG_DIR"] == "./logs"  # default, Task 2 geeft de echte settings.log_dir door


def test_start_twice_is_a_no_op(monkeypatch):
    calls = []

    def fake_popen(cmd, env=None, **kwargs):
        calls.append(1)
        return FakeProc()

    monkeypatch.setattr("admin.app.mirror_process.subprocess.Popen", fake_popen)
    manager = MirrorProcessManager(FakeSettings())

    manager.start()
    manager.start()

    assert len(calls) == 1


def test_stop_terminates_running_process(monkeypatch):
    proc = FakeProc()
    monkeypatch.setattr("admin.app.mirror_process.subprocess.Popen", lambda *a, **k: proc)
    manager = MirrorProcessManager(FakeSettings())
    manager.start()

    result = manager.stop()

    assert result == {"running": False, "pid": None}
    assert proc._terminated is True


def test_stop_when_not_running_is_a_no_op():
    manager = MirrorProcessManager(FakeSettings())

    result = manager.stop()

    assert result == {"running": False, "pid": None}


def test_status_detects_process_that_exited_on_its_own(monkeypatch):
    proc = FakeProc()
    monkeypatch.setattr("admin.app.mirror_process.subprocess.Popen", lambda *a, **k: proc)
    manager = MirrorProcessManager(FakeSettings())
    manager.start()

    proc._returncode = 1  # simuleert een proces dat zelfstandig is gestopt (bv. foute RTSP-URL)

    assert manager.status() == {"running": False, "pid": None}


def test_read_output_broadcasts_each_line():
    proc = FakeProc(lines=["mirror-node gestart\n", "mirror triggered\n"])
    manager = MirrorProcessManager(FakeSettings())
    manager._proc = proc
    broadcasts = []
    manager._broadcast = broadcasts.append

    manager._read_output()

    assert broadcasts == ["mirror-node gestart", "mirror triggered"]


def test_broadcast_is_noop_without_ws_hub():
    manager = MirrorProcessManager(FakeSettings())

    manager._broadcast("een regel")  # mag niet crashen zonder ws_hub/loop


def test_ensure_running_restarts_a_wanted_process_that_died(monkeypatch):
    procs = []
    monkeypatch.setattr(
        "admin.app.mirror_process.subprocess.Popen",
        lambda *a, **k: procs.append(FakeProc()) or procs[-1],
    )
    manager = MirrorProcessManager(FakeSettings())
    manager.start()
    procs[0]._returncode = 1  # crasht vanzelf

    manager.ensure_running()

    assert len(procs) == 2
    assert manager.status()["running"] is True


def test_ensure_running_leaves_a_deliberately_stopped_process_alone(monkeypatch):
    procs = []
    monkeypatch.setattr(
        "admin.app.mirror_process.subprocess.Popen",
        lambda *a, **k: procs.append(FakeProc()) or procs[-1],
    )
    manager = MirrorProcessManager(FakeSettings())
    manager.start()
    manager.stop()

    manager.ensure_running()

    assert len(procs) == 1
    assert manager.status()["running"] is False
