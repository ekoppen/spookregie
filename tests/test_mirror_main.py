import pytest

import json

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


def test_on_message_survives_malformed_payload(monkeypatch):
    # Niet-UTF8 bytes: mag paho's netwerkthread niet killen.
    logger = _FakeLogger()
    topics = mirror_main.Topics()
    on_message = mirror_main.make_on_message(logger, topics)
    on_message(None, None, _FakeMsg(topics.config_mirror_scenes, b"\xff\xfe"))
    assert logger.errors


def test_on_message_sets_test_trigger_event():
    mirror_main.test_trigger_requested.clear()
    topics = mirror_main.Topics()
    on_message = mirror_main.make_on_message(_FakeLogger(), topics)

    on_message(None, None, _FakeMsg(topics.control_mirror_test, b""))

    assert mirror_main.test_trigger_requested.is_set()
    mirror_main.test_trigger_requested.clear()


def test_open_camera_uses_local_index_when_source_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: calls.append(a) or "cap")

    result = mirror_main._open_camera("")

    assert calls == [(mirror_main.CAMERA_INDEX,)]
    assert result == "cap"


def test_open_camera_uses_local_index_when_source_is_numeric_string(monkeypatch):
    calls = []
    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: calls.append(a) or "cap")

    mirror_main._open_camera("2")

    assert calls == [(2,)]


def test_open_camera_uses_ffmpeg_url_for_network_source(monkeypatch):
    calls = []
    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: calls.append(a) or "cap")

    mirror_main._open_camera("rtsp://cam.local/stream1")

    assert calls == [("rtsp://cam.local/stream1", mirror_main.cv2.CAP_FFMPEG)]


def test_redact_source_strips_credentials():
    assert mirror_main._redact_source("rtsp://user:pass@192.168.1.50:554/stream1") == "192.168.1.50:554/stream1"


def test_redact_source_leaves_plain_source_untouched():
    assert mirror_main._redact_source("rtsp://cam.local/stream1") == "rtsp://cam.local/stream1"
    assert mirror_main._redact_source("") == mirror_main.CAMERA_INDEX


def test_apply_scenes_message_ignores_non_list_json():
    logger = _FakeLogger()
    mirror_main._apply_scenes_message('{"not": "a list"}', logger)
    assert logger.errors


def test_apply_scenes_message_ignores_malformed_json():
    logger = _FakeLogger()
    mirror_main._apply_scenes_message("{niet-geldig-json", logger)
    assert logger.errors


def test_apply_scenes_message_updates_scene_engine():
    scene = {"id": 1, "trigger_type": "always", "overlay_hash": None}
    mirror_main._apply_scenes_message(json.dumps([scene]), _FakeLogger())

    assert mirror_main.scene_engine.resolve(False, "12:00") == scene


def test_apply_scenes_message_syncs_overlay_for_each_scene(monkeypatch):
    started = []
    monkeypatch.setattr(
        mirror_main.threading, "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    scenes = [
        {"id": 1, "trigger_type": "always", "overlay_hash": "a" * 64},
        {"id": 2, "trigger_type": "motion", "overlay_hash": "b" * 64},
    ]

    mirror_main._apply_scenes_message(json.dumps(scenes), _FakeLogger())

    synced_hashes = [kw["args"][2] for kw in started]
    assert synced_hashes == [["a" * 64], ["b" * 64]]


def test_apply_scene_preview_message_sets_preview_and_syncs_overlay(monkeypatch):
    started = []
    monkeypatch.setattr(
        mirror_main.threading, "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    scene = {"id": 5, "trigger_type": "always", "overlay_hash": "a" * 64}
    try:
        mirror_main._apply_scene_preview_message(json.dumps(scene), _FakeLogger())
        assert mirror_main.scene_engine.resolve(False, "12:00") == scene
        assert started and started[0]["args"][2] == ["a" * 64]
    finally:
        mirror_main.scene_engine._preview = None
        mirror_main.scene_engine._preview_set_at = None


def test_decide_action_no_winner_is_blank():
    assert mirror_main._decide_action(False, None) == "blank"
    assert mirror_main._decide_action(True, None) == "blank"


def test_decide_action_scare_video_scene_fired_plays_scare_video():
    winning = {"source_mode": "scare_video"}
    assert mirror_main._decide_action(True, winning) == "scare_video"


def test_decide_action_scare_video_scene_not_fired_is_blank():
    winning = {"source_mode": "scare_video"}
    assert mirror_main._decide_action(False, winning) == "blank"


def test_decide_action_camera_scene_renders_regardless_of_fired():
    winning = {"source_mode": "camera"}
    assert mirror_main._decide_action(True, winning) == "render"
    assert mirror_main._decide_action(False, winning) == "render"


def _engine(scenes):
    engine = mirror_main.SceneEngine()
    engine.set_scenes(scenes)
    return engine


def test_resolve_action_scare_video_scene_at_trigger_instant_plays_clip():
    """fired=True (het trigger-moment zelf): ongewijzigd gedrag, de clip
    moet nu afspelen, niet meteen doorvallen naar de basisscene."""
    scare = {"source_mode": "scare_video", "trigger_type": "motion"}
    engine = _engine([scare])

    action, winning = mirror_main._resolve_action(engine, fired=True, motion_active=True, now_hhmm="12:00")

    assert action == "scare_video"
    assert winning == scare


def test_resolve_action_falls_back_to_base_scene_after_clip_finished():
    """De kern van de fix: fired=False maar nog binnen het actieve venster
    (de clip is net afgespeeld) mag niet zwart blijven zolang de
    scare-video-scene nog wint op motion -- val terug op de always-scene."""
    scare = {"source_mode": "scare_video", "trigger_type": "motion"}
    base = {"source_mode": "camera", "effect": "xray", "trigger_type": "always"}
    engine = _engine([scare, base])

    action, winning = mirror_main._resolve_action(engine, fired=False, motion_active=True, now_hhmm="12:00")

    assert action == "render"
    assert winning == base


def test_resolve_action_stays_blank_when_no_fallback_scene_matches():
    """Zonder een always/schedule-scene die zonder beweging matcht, blijft
    het resultaat terecht zwart -- geen fallback beschikbaar."""
    scare = {"source_mode": "scare_video", "trigger_type": "motion"}
    engine = _engine([scare])

    action, winning = mirror_main._resolve_action(engine, fired=False, motion_active=True, now_hhmm="12:00")

    assert action == "blank"
    assert winning is None


def test_resolve_action_camera_motion_scene_keeps_rendering_during_its_window():
    """Niet-scare_video-scenes zijn ongewijzigd: een camera-scene op motion
    blijft gewoon renderen voor de duur van haar eigen actieve venster."""
    motion_scene = {"source_mode": "camera", "effect": "xray", "trigger_type": "motion"}
    engine = _engine([motion_scene])

    action, winning = mirror_main._resolve_action(engine, fired=False, motion_active=True, now_hhmm="12:00")

    assert action == "render"
    assert winning == motion_scene


def test_resolve_action_no_winner_at_all_is_blank():
    engine = _engine([])

    action, winning = mirror_main._resolve_action(engine, fired=False, motion_active=False, now_hhmm="12:00")

    assert action == "blank"
    assert winning is None


def test_apply_scare_video_config_message_ignores_non_dict_json():
    logger = _FakeLogger()
    mirror_main._apply_scare_video_config_message("[1, 2, 3]", logger)
    assert logger.errors


def test_apply_scare_video_config_message_ignores_malformed_json():
    logger = _FakeLogger()
    mirror_main._apply_scare_video_config_message("{niet-geldig-json", logger)
    assert logger.errors


def test_apply_scare_video_config_message_ignores_non_list_hashes():
    logger = _FakeLogger()
    mirror_main._apply_scare_video_config_message('{"enabled_hashes": "niet-een-lijst"}', logger)
    assert logger.errors


def test_apply_scare_video_config_message_triggers_background_sync(monkeypatch):
    calls = []
    monkeypatch.setattr(mirror_main, "_sync_scare_videos_in_background", lambda hashes: calls.append(hashes))

    mirror_main._apply_scare_video_config_message('{"enabled_hashes": ["a"]}', _FakeLogger())

    assert calls == [["a"]]


def test_play_scare_video_publishes_all_frames(monkeypatch):
    class FakeCap:
        def __init__(self):
            self._remaining = 3

        def get(self, prop):
            return 24.0

        def read(self):
            if self._remaining > 0:
                self._remaining -= 1
                return True, f"frame-{self._remaining}"
            return False, None

        def release(self):
            pass

    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: FakeCap())
    monkeypatch.setattr(mirror_main.time, "sleep", lambda s: None)
    monkeypatch.setattr(mirror_main, "MIRROR_HEADLESS", True)

    published = []

    class FakeStreamer:
        def publish_frame(self, frame):
            published.append(frame)

    mirror_main._play_scare_video("video.mp4", None, FakeStreamer(), _FakeLogger())

    assert published == ["frame-2", "frame-1", "frame-0"]


def test_play_scare_video_starts_audio_when_provided(monkeypatch):
    class FakeCap:
        def get(self, prop):
            return 24.0

        def read(self):
            return False, None

        def release(self):
            pass

    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: FakeCap())
    monkeypatch.setattr(mirror_main.time, "sleep", lambda s: None)
    monkeypatch.setattr(mirror_main, "MIRROR_HEADLESS", True)

    popen_calls = []
    monkeypatch.setattr(mirror_main.subprocess, "Popen", lambda cmd: popen_calls.append(cmd))

    class FakeStreamer:
        def publish_frame(self, frame):
            pass

    mirror_main._play_scare_video("video.mp4", "audio.wav", FakeStreamer(), _FakeLogger())

    assert popen_calls == [["aplay", "audio.wav"]]


def test_play_scare_video_survives_audio_start_failure(monkeypatch):
    class FakeCap:
        def get(self, prop):
            return 24.0

        def read(self):
            return False, None

        def release(self):
            pass

    monkeypatch.setattr(mirror_main.cv2, "VideoCapture", lambda *a, **k: FakeCap())
    monkeypatch.setattr(mirror_main.time, "sleep", lambda s: None)
    monkeypatch.setattr(mirror_main, "MIRROR_HEADLESS", True)

    def failing_popen(cmd):
        raise FileNotFoundError("aplay niet gevonden")

    monkeypatch.setattr(mirror_main.subprocess, "Popen", failing_popen)

    published = []

    class FakeStreamer:
        def publish_frame(self, frame):
            published.append(frame)

    mirror_main._play_scare_video("video.mp4", "audio.wav", FakeStreamer(), _FakeLogger())

    assert published == []  # FakeCap.read() geeft meteen False terug, mag niet crashen


def test_handle_trigger_plays_scare_video_when_available(monkeypatch):
    mirror_main.synced_scare_videos = {"h1": {"video": "v.mp4", "audio": "a.wav"}}
    play_calls = []
    monkeypatch.setattr(mirror_main, "_play_scare_video", lambda v, a, s, l: play_calls.append((v, a)))

    try:
        result = mirror_main._handle_trigger("streamer", _FakeLogger())
        assert result == mirror_main.ACTIVE_SECONDS
        assert play_calls == [("v.mp4", "a.wav")]
    finally:
        mirror_main.synced_scare_videos = {}


def test_handle_trigger_returns_active_seconds_when_no_scare_videos():
    mirror_main.synced_scare_videos = {}

    result = mirror_main._handle_trigger("streamer", _FakeLogger())

    assert result == mirror_main.ACTIVE_SECONDS
