import pytest

# Zonder paho (optionele node-dependency) alleen dit bestand overslaan, i.p.v.
# de hele testsuite te laten afbreken tijdens collection.
pytest.importorskip("paho.mqtt.client")

import scare_node.main as scare_main  # noqa: E402


class _FakeLogger:
    def __init__(self):
        self.errors = []

    def error(self, *args):
        self.errors.append(args)

    def info(self, *args):
        pass


def test_normalize_string_list_passes_through_valid_list():
    assert scare_main._normalize_string_list(["a.wav", "b.wav"]) == ["a.wav", "b.wav"]


def test_normalize_string_list_drops_non_string_elements():
    assert scare_main._normalize_string_list(["a.wav", 5, None, "b.wav"]) == ["a.wav", "b.wav"]


def test_normalize_string_list_rejects_non_list_types():
    assert scare_main._normalize_string_list("a.wav") == []
    assert scare_main._normalize_string_list(None) == []
    assert scare_main._normalize_string_list(5) == []
    assert scare_main._normalize_string_list({"a.wav": True}) == []


class _SyncThread:
    """Draait de 'achtergrond'-sync meteen, zodat de test deterministisch is."""

    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


def _apply_sync(monkeypatch, payload, result=None, logger=None):
    """Draait _apply_scare_config met een nagebootste sync_media en een
    synchrone 'thread', zodat de test het eindresultaat kan controleren."""
    calls = []
    monkeypatch.setattr(
        scare_main, "sync_media", lambda *a, **k: calls.append(a) or (result or {})
    )
    monkeypatch.setattr(scare_main.threading, "Thread", _SyncThread)
    scare_main.synced_audio = None
    scare_main._apply_scare_config(payload, logger or _FakeLogger())
    return calls


def test_apply_scare_config_survives_malformed_json(monkeypatch):
    logger = _FakeLogger()

    calls = _apply_sync(monkeypatch, "not json", logger=logger)

    assert logger.errors
    assert not calls
    assert scare_main.synced_audio is None  # niets gewijzigd


def test_apply_scare_config_survives_non_dict_json(monkeypatch):
    logger = _FakeLogger()

    calls = _apply_sync(monkeypatch, "[1, 2, 3]", logger=logger)

    assert logger.errors
    assert not calls
    assert scare_main.synced_audio is None  # niets gewijzigd


def test_apply_scare_config_survives_wrong_field_types(monkeypatch):
    calls = _apply_sync(monkeypatch, '{"enabled_hashes": "not-a-list"}')

    assert calls[0][2] == []  # wanted_hashes viel terug op lege lijst
    assert scare_main.synced_audio == {}  # geen crash, wel lege selectie


def test_apply_scare_config_normal_case(monkeypatch):
    synced = {"a" * 64: "/cache/" + "a" * 64}

    calls = _apply_sync(
        monkeypatch, '{"enabled_hashes": ["' + "a" * 64 + '"]}', result=synced
    )

    assert calls[0][2] == ["a" * 64]
    assert scare_main.synced_audio == synced  # sync_media-resultaat is de selectie


def test_pick_synced_audio_falls_back_to_media_dir_before_any_config(monkeypatch):
    scare_main.synced_audio = None
    monkeypatch.setattr(scare_main, "pick_audio_file", lambda d: d + "/legacy.wav")

    assert scare_main._pick_synced_audio(_FakeLogger()) == scare_main.MEDIA_DIR + "/legacy.wav"


def test_pick_synced_audio_plays_nothing_when_selection_is_empty():
    scare_main.synced_audio = {}

    assert scare_main._pick_synced_audio(_FakeLogger()) is None


def test_pick_synced_audio_picks_from_cache_paths():
    scare_main.synced_audio = {"a" * 64: "/cache/aaa", "b" * 64: "/cache/bbb"}

    assert scare_main._pick_synced_audio(_FakeLogger()) in ("/cache/aaa", "/cache/bbb")
