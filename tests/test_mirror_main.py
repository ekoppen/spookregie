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
    on_message(None, None, _FakeMsg(topics.config_mirror_graph, b"\xff\xfe"))
    assert logger.errors


def test_on_message_sets_test_trigger_event():
    mirror_main.test_trigger_requested.clear()
    topics = mirror_main.Topics()
    on_message = mirror_main.make_on_message(_FakeLogger(), topics)

    on_message(None, None, _FakeMsg(topics.control_mirror_test, b""))

    assert mirror_main.test_trigger_requested.is_set()
    mirror_main.test_trigger_requested.clear()


def test_redact_source_strips_credentials():
    assert mirror_main._redact_source("rtsp://user:pass@192.168.1.50:554/stream1") == "192.168.1.50:554/stream1"


def test_redact_source_leaves_plain_source_untouched():
    assert mirror_main._redact_source("rtsp://cam.local/stream1") == "rtsp://cam.local/stream1"
    assert mirror_main._redact_source("") == mirror_main.CAMERA_INDEX


def test_apply_graph_message_ignores_non_dict_json():
    logger = _FakeLogger()
    mirror_main._apply_graph_message("[1, 2, 3]", logger)
    assert logger.errors


def test_apply_graph_message_ignores_malformed_json():
    logger = _FakeLogger()
    mirror_main._apply_graph_message("{niet-geldig-json", logger)
    assert logger.errors


def test_apply_graph_message_ignores_non_list_players_or_triggers():
    logger = _FakeLogger()
    mirror_main._apply_graph_message(json.dumps({"players": "nope", "triggers": [], "root_player_id": 1}), logger)
    assert logger.errors


def test_apply_graph_message_updates_player_graph():
    player = {"id": 1, "trigger_type": None, "overlay_hash": None}
    payload = {"players": [player], "branches": [], "triggers": [], "root_player_id": 1}
    mirror_main._apply_graph_message(json.dumps(payload), _FakeLogger())

    result, transitioned = mirror_main.player_graph.resolve(False, "12:00")
    assert result == player
    assert transitioned is False


def test_apply_graph_message_reads_triggers_key():
    player = {"id": 1, "trigger_type": None, "overlay_hash": None}
    payload = {"players": [player], "branches": [], "triggers": [], "root_player_id": 1}
    mirror_main._apply_graph_message(json.dumps(payload), _FakeLogger())

    result, transitioned = mirror_main.player_graph.resolve(False, "12:00")
    assert result == player
    assert transitioned is False


def test_apply_graph_message_syncs_overlay_for_each_player(monkeypatch):
    started = []
    monkeypatch.setattr(
        mirror_main.threading, "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    players = [
        {"id": 1, "overlay_hash": "a" * 64},
        {"id": 2, "overlay_hash": "b" * 64},
    ]
    payload = {"players": players, "branches": [], "triggers": [], "root_player_id": 1}

    mirror_main._apply_graph_message(json.dumps(payload), _FakeLogger())

    synced_hashes = [kw["args"][2] for kw in started]
    assert synced_hashes == [["a" * 64], ["b" * 64]]


def test_apply_scene_preview_message_sets_preview_and_syncs_overlay(monkeypatch):
    started = []
    monkeypatch.setattr(
        mirror_main.threading, "Thread",
        lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None})(),
    )
    scene = {"id": 5, "overlay_hash": "a" * 64}
    try:
        mirror_main._apply_scene_preview_message(json.dumps(scene), _FakeLogger())
        result, transitioned = mirror_main.player_graph.resolve(False, "12:00")
        assert result == scene
        assert started and started[0]["args"][2] == ["a" * 64]
    finally:
        mirror_main.player_graph._preview = None
        mirror_main.player_graph._preview_set_at = None


def test_render_action_no_winner_is_blank():
    assert mirror_main._render_action(None, False) == "blank"
    assert mirror_main._render_action(None, True) == "blank"


def test_render_action_scare_video_on_transition_plays():
    winning = {"source_mode": "scare_video"}
    assert mirror_main._render_action(winning, True) == "scare_video"


def test_render_action_scare_video_without_transition_is_blank():
    """Dit is precies het geval dat de vorige feature met een losse
    dubbele-resolve-hack moest oplappen (zwart na afloop van een clip
    zonder terugpad) -- de state machine zelf voorkomt het nu, en dit
    is de test die dat vastlegt."""
    winning = {"source_mode": "scare_video"}
    assert mirror_main._render_action(winning, False) == "blank"


def test_render_action_camera_scene_renders_regardless_of_transition():
    winning = {"source_mode": "camera"}
    assert mirror_main._render_action(winning, True) == "render"
    assert mirror_main._render_action(winning, False) == "render"


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


def test_apply_ha_trigger_message_adds_entity_to_fired_set():
    mirror_main._fired_ha_entities.clear()
    mirror_main._apply_ha_trigger_message(json.dumps({"entity_id": "binary_sensor.tuin"}), _FakeLogger())

    with mirror_main._fired_ha_entities_lock:
        assert "binary_sensor.tuin" in mirror_main._fired_ha_entities
    mirror_main._fired_ha_entities.clear()


def test_apply_ha_trigger_message_ignores_malformed_payload():
    logger = _FakeLogger()
    mirror_main._apply_ha_trigger_message("{niet-geldig-json", logger)
    assert logger.errors


def test_apply_ha_trigger_message_ignores_missing_entity_id():
    logger = _FakeLogger()
    mirror_main._apply_ha_trigger_message(json.dumps({}), logger)
    assert logger.errors


def test_play_scare_video_sequence_once_plays_exactly_one_clip(monkeypatch):
    mirror_main.synced_scare_videos = {"h1": {"video": "v.mp4", "audio": None}}
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)

    try:
        winning = {"playback_mode": "once"}
        result = mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())
        assert result == mirror_main.ACTIVE_SECONDS
        assert len(play_calls) == 1
    finally:
        mirror_main.synced_scare_videos = {}


def test_play_scare_video_sequence_repeat_once_plays_exactly_two_clips(monkeypatch):
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)

    winning = {"playback_mode": "repeat_once"}
    mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())

    assert len(play_calls) == 2


def test_play_scare_video_sequence_repeat_while_loops_until_sensor_drops(monkeypatch):
    # synced_scare_videos moet gevuld zijn, anders breekt de busy-spin-guard
    # (Kritiek 3a) de loop meteen af -- ongeacht sensor-state.
    mirror_main.synced_scare_videos = {"h1": {"video": "v.mp4", "audio": None}}
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)
    states = iter(["on", "on", "off"])  # 1 verplichte keer + 2x nog 'on' + stop op 'off'
    mirror_main._ha_entity_states["binary_sensor.tuin"] = "on"
    monkeypatch.setattr(mirror_main, "_ha_entity_state", lambda entity_id: next(states, "off"))

    try:
        winning = {"playback_mode": "repeat_while", "repeat_while_ha_entity_id": "binary_sensor.tuin"}
        mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())

        assert len(play_calls) == 3  # 1 gegarandeerde keer + 2 herhalingen zolang 'on'
    finally:
        mirror_main.synced_scare_videos = {}


def test_play_scare_video_sequence_repeat_while_without_entity_id_plays_once(monkeypatch):
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)

    winning = {"playback_mode": "repeat_while", "repeat_while_ha_entity_id": None}
    mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())

    assert len(play_calls) == 1


def test_play_scare_video_sequence_repeat_while_breaks_when_nothing_synced(monkeypatch):
    # Kritiek 3a: geen gesynct scare-video mag de loop niet laten busy-
    # spinnen (elke boot ~10s, of nul enabled scare-videos).
    mirror_main.synced_scare_videos = {}
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)
    monkeypatch.setattr(mirror_main, "_ha_entity_state", lambda entity_id: "on")

    winning = {"playback_mode": "repeat_while", "repeat_while_ha_entity_id": "binary_sensor.tuin"}
    mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())

    assert len(play_calls) == 1  # alleen de gegarandeerde eerste keer, dan break


def test_play_scare_video_sequence_repeat_while_stops_on_sleeping(monkeypatch):
    # Kritiek 3b: system/sleep (noodstop) moet een lopende repeat_while
    # -loop kunnen onderbreken.
    mirror_main.synced_scare_videos = {"h1": {"video": "v.mp4", "audio": None}}
    play_calls = []
    monkeypatch.setattr(mirror_main, "_handle_trigger", lambda s, l: play_calls.append(1) or mirror_main.ACTIVE_SECONDS)
    monkeypatch.setattr(mirror_main, "_ha_entity_state", lambda entity_id: "on")
    mirror_main.sleeping.set()

    try:
        winning = {"playback_mode": "repeat_while", "repeat_while_ha_entity_id": "binary_sensor.tuin"}
        mirror_main._play_scare_video_sequence(winning, "streamer", _FakeLogger())

        assert len(play_calls) == 1  # alleen de gegarandeerde eerste keer, dan stop
    finally:
        mirror_main.sleeping.clear()
        mirror_main.synced_scare_videos = {}


def test_ha_entity_state_expires_after_stale_threshold(monkeypatch):
    # Kritiek 3c: een level-state die niet meer ververst wordt (broker/
    # backend weg) mag geen repeat_while-loop voor altijd laten doorlopen.
    mirror_main._ha_entity_states.clear()
    fake_now = [1000.0]
    monkeypatch.setattr(mirror_main.time, "time", lambda: fake_now[0])
    mirror_main._apply_ha_sensor_state_message(
        json.dumps({"entity_id": "binary_sensor.tuin", "state": "on"}), _FakeLogger()
    )
    assert mirror_main._ha_entity_state("binary_sensor.tuin") == "on"

    fake_now[0] += mirror_main.HA_ENTITY_STATE_STALE_SECONDS + 1
    assert mirror_main._ha_entity_state("binary_sensor.tuin") is None
    mirror_main._ha_entity_states.clear()


def test_apply_ha_sensor_state_message_updates_state():
    mirror_main._ha_entity_states.clear()
    mirror_main._apply_ha_sensor_state_message(
        json.dumps({"entity_id": "binary_sensor.tuin", "state": "on"}), _FakeLogger()
    )

    assert mirror_main._ha_entity_state("binary_sensor.tuin") == "on"
    mirror_main._ha_entity_states.clear()


def test_apply_ha_sensor_state_message_ignores_malformed_payload():
    logger = _FakeLogger()
    mirror_main._apply_ha_sensor_state_message("{niet-geldig-json", logger)
    assert logger.errors


def test_resolve_frame_source_reuses_open_capture_for_unchanged_source(monkeypatch):
    open_calls = []
    monkeypatch.setattr(mirror_main, "open_camera", lambda value, idx: open_calls.append(value) or "cap-object")
    state = mirror_main._SourceState()

    cap1 = mirror_main._ensure_source(state, {"id": 5, "kind": "camera_stream", "value": "rtsp://a"}, _FakeLogger())
    cap2 = mirror_main._ensure_source(state, {"id": 5, "kind": "camera_stream", "value": "rtsp://a"}, _FakeLogger())

    assert cap1 is cap2
    assert open_calls == ["rtsp://a"]  # maar 1x geopend, niet 2x


def test_resolve_frame_source_reopens_when_source_id_changes(monkeypatch):
    monkeypatch.setattr(mirror_main, "open_camera", lambda value, idx: f"cap-{value}")
    released = []
    state = mirror_main._SourceState()
    state.capture = type("FakeCap", (), {"release": lambda self: released.append(1)})()
    state.source_id = 5

    mirror_main._ensure_source(state, {"id": 6, "kind": "camera_stream", "value": "rtsp://b"}, _FakeLogger())

    assert released == [1]  # oude capture netjes gesloten vóór de nieuwe geopend wordt
    assert state.source_id == 6


def test_resolve_frame_source_caches_static_image(monkeypatch):
    read_calls = []
    monkeypatch.setattr(mirror_main.os.path, "exists", lambda path: True)
    monkeypatch.setattr(mirror_main.cv2, "imread", lambda path, *a: read_calls.append(path) or "decoded-image")
    state = mirror_main._SourceState()

    img1 = mirror_main._ensure_source(state, {"id": 7, "kind": "static_image", "value": "a" * 64}, _FakeLogger())
    img2 = mirror_main._ensure_source(state, {"id": 7, "kind": "static_image", "value": "a" * 64}, _FakeLogger())

    assert img1 == "decoded-image"
    assert img2 == "decoded-image"
    assert len(read_calls) == 1  # niet opnieuw gedecodeerd, id ongewijzigd
