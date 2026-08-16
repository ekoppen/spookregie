import mirror_node.main as mirror_main


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
