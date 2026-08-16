import scare_node.main as scare_main


class _FakeLogger:
    def __init__(self):
        self.errors = []

    def error(self, *args):
        self.errors.append(args)


def test_normalize_string_list_passes_through_valid_list():
    assert scare_main._normalize_string_list(["a.wav", "b.wav"]) == ["a.wav", "b.wav"]


def test_normalize_string_list_drops_non_string_elements():
    assert scare_main._normalize_string_list(["a.wav", 5, None, "b.wav"]) == ["a.wav", "b.wav"]


def test_normalize_string_list_rejects_non_list_types():
    assert scare_main._normalize_string_list("a.wav") == []
    assert scare_main._normalize_string_list(None) == []
    assert scare_main._normalize_string_list(5) == []
    assert scare_main._normalize_string_list({"a.wav": True}) == []


def test_apply_scare_config_survives_malformed_json(monkeypatch):
    monkeypatch.setattr(scare_main, "sync_media", lambda *a, **k: {})
    scare_main.enabled_files = None
    logger = _FakeLogger()

    scare_main._apply_scare_config("not json", logger)

    assert logger.errors
    assert scare_main.enabled_files is None  # niets gewijzigd


def test_apply_scare_config_survives_non_dict_json(monkeypatch):
    monkeypatch.setattr(scare_main, "sync_media", lambda *a, **k: {})
    scare_main.enabled_files = None
    logger = _FakeLogger()

    scare_main._apply_scare_config("[1, 2, 3]", logger)

    assert logger.errors
    assert scare_main.enabled_files is None  # niets gewijzigd


def test_apply_scare_config_survives_wrong_field_types(monkeypatch):
    calls = []
    monkeypatch.setattr(scare_main, "sync_media", lambda *a, **k: calls.append(a) or {})
    scare_main.enabled_files = None
    logger = _FakeLogger()

    scare_main._apply_scare_config(
        '{"enabled_hashes": "not-a-list", "enabled_filenames": "scream1.wav"}', logger
    )

    assert calls[0][2] == []  # wanted_hashes viel terug op lege lijst
    assert scare_main.enabled_files == set()  # geen crash, wel lege selectie


def test_apply_scare_config_normal_case(monkeypatch):
    calls = []
    monkeypatch.setattr(scare_main, "sync_media", lambda *a, **k: calls.append(a) or {})
    scare_main.enabled_files = None
    logger = _FakeLogger()

    scare_main._apply_scare_config(
        '{"enabled_hashes": ["' + "a" * 64 + '"], "enabled_filenames": ["scream1.wav"]}', logger
    )

    assert calls[0][2] == ["a" * 64]
    assert scare_main.enabled_files == {"scream1.wav"}
