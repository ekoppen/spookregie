from mirror_node.active_config import ActiveMirrorConfig


def test_get_returns_default_persistent_config_initially():
    cfg = ActiveMirrorConfig(clock=lambda: 0.0)
    result = cfg.get()
    assert result["effect"] == "xray"


def test_set_persistent_updates_get():
    cfg = ActiveMirrorConfig(clock=lambda: 0.0)
    cfg.set_persistent({"effect": "thermal", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    assert cfg.get()["effect"] == "thermal"


def test_preview_overrides_persistent_within_timeout():
    times = iter([0.0, 0.0, 5.0])  # set_persistent, set_preview, get
    cfg = ActiveMirrorConfig(preview_timeout=30, clock=lambda: next(times))
    cfg.set_persistent({"effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    cfg.set_preview({"effect": "contour", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    assert cfg.get()["effect"] == "contour"


def test_preview_expires_after_timeout():
    times = iter([0.0, 0.0, 40.0])  # set_persistent, set_preview, get (na timeout)
    cfg = ActiveMirrorConfig(preview_timeout=30, clock=lambda: next(times))
    cfg.set_persistent({"effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    cfg.set_preview({"effect": "contour", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    assert cfg.get()["effect"] == "xray"


def test_new_persistent_config_clears_active_preview():
    times = iter([0.0, 0.0, 0.0])
    cfg = ActiveMirrorConfig(preview_timeout=30, clock=lambda: next(times))
    cfg.set_preview({"effect": "contour", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    cfg.set_persistent({"effect": "thermal", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]})
    assert cfg.get()["effect"] == "thermal"
