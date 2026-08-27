import pytest

# Zonder paho/cv2 (optionele node-dependencies) alleen dit bestand overslaan,
# i.p.v. de hele testsuite te laten afbreken tijdens collection.
pytest.importorskip("paho.mqtt.client")
pytest.importorskip("cv2")

import mirror_node.main as mirror_main  # noqa: E402


class _FakeLogger:
    def __init__(self):
        self.errors = []

    def error(self, *args):
        self.errors.append(args)

    def warning(self, *args):
        pass


def _reset_cache():
    mirror_main._overlay_cache["hash"] = None
    mirror_main._overlay_cache["image"] = None


def test_load_overlay_rejects_invalid_hash_format():
    _reset_cache()
    logger = _FakeLogger()
    result = mirror_main._load_overlay("not-a-valid-hash", logger)
    assert result is None
    assert logger.errors


def test_load_overlay_decodes_once_and_caches_by_hash(monkeypatch):
    _reset_cache()
    h = "a" * 64
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    calls = []

    def fake_imread(path, flag):
        calls.append(path)
        return "decoded-image"

    monkeypatch.setattr(mirror_main.cv2, "imread", fake_imread)
    logger = _FakeLogger()

    first = mirror_main._load_overlay(h, logger)
    second = mirror_main._load_overlay(h, logger)

    assert first == "decoded-image"
    assert second == "decoded-image"
    assert len(calls) == 1  # tweede call kwam uit cache, geen herdecode


def test_load_overlay_redecodes_when_hash_changes(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    calls = []
    monkeypatch.setattr(mirror_main.cv2, "imread", lambda path, flag: calls.append(path) or "img")
    logger = _FakeLogger()

    mirror_main._load_overlay("a" * 64, logger)
    mirror_main._load_overlay("b" * 64, logger)

    assert len(calls) == 2


class _FakeMsg:
    def __init__(self, topic, payload=b"{}"):
        self.topic = topic
        self.payload = payload


def test_apply_config_message_ignores_non_dict_json():
    logger = _FakeLogger()
    mirror_main._apply_config_message("[1, 2, 3]", is_preview=False, logger=logger)
    assert logger.errors


def test_on_message_survives_malformed_payload(monkeypatch):
    # Niet-UTF8 bytes: mag paho's netwerkthread niet killen.
    logger = _FakeLogger()
    topics = mirror_main.Topics()
    on_message = mirror_main.make_on_message(logger, topics)
    on_message(None, None, _FakeMsg(topics.config_mirror, b"\xff\xfe"))
    assert logger.errors


def test_on_message_sets_test_trigger_event():
    mirror_main.test_trigger_requested.clear()
    topics = mirror_main.Topics()
    on_message = mirror_main.make_on_message(_FakeLogger(), topics)

    on_message(None, None, _FakeMsg(topics.control_mirror_test, b""))

    assert mirror_main.test_trigger_requested.is_set()
    mirror_main.test_trigger_requested.clear()


def test_preview_config_also_syncs_overlay(monkeypatch):
    started = []
    monkeypatch.setattr(
        mirror_main.threading,
        "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    mirror_main._apply_config_message(
        '{"overlay_hash": "' + "a" * 64 + '"}', is_preview=True, logger=_FakeLogger()
    )
    assert started and started[0]["args"][2] == ["a" * 64]
