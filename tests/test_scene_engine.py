from mirror_node.scenes import SceneEngine, _time_in_window


def test_always_scene_wins_without_conditions():
    engine = SceneEngine()
    scene = {"id": 1, "trigger_type": "always"}
    engine.set_scenes([scene])

    assert engine.resolve(motion_active=False, now_hhmm="12:00") == scene


def test_motion_scene_only_wins_when_motion_active():
    engine = SceneEngine()
    scene = {"id": 1, "trigger_type": "motion"}
    engine.set_scenes([scene])

    assert engine.resolve(motion_active=False, now_hhmm="12:00") is None
    assert engine.resolve(motion_active=True, now_hhmm="12:00") == scene


def test_schedule_scene_matches_within_window():
    engine = SceneEngine()
    scene = {"id": 1, "trigger_type": "schedule", "trigger_from": "20:00", "trigger_until": "23:00"}
    engine.set_scenes([scene])

    assert engine.resolve(motion_active=False, now_hhmm="21:00") == scene
    assert engine.resolve(motion_active=False, now_hhmm="19:00") is None


def test_schedule_scene_handles_midnight_wraparound():
    engine = SceneEngine()
    scene = {"id": 1, "trigger_type": "schedule", "trigger_from": "22:00", "trigger_until": "02:00"}
    engine.set_scenes([scene])

    assert engine.resolve(motion_active=False, now_hhmm="23:30") == scene
    assert engine.resolve(motion_active=False, now_hhmm="01:00") == scene
    assert engine.resolve(motion_active=False, now_hhmm="12:00") is None


def test_priority_order_first_match_wins():
    engine = SceneEngine()
    motion_scene = {"id": 1, "trigger_type": "motion"}
    always_scene = {"id": 2, "trigger_type": "always"}
    engine.set_scenes([motion_scene, always_scene])

    result = engine.resolve(motion_active=True, now_hhmm="12:00")

    assert result == motion_scene


def test_disabled_scene_is_skipped():
    engine = SceneEngine()
    disabled = {"id": 1, "trigger_type": "always", "enabled": False}
    enabled = {"id": 2, "trigger_type": "always", "enabled": True}
    engine.set_scenes([disabled, enabled])

    assert engine.resolve(motion_active=False, now_hhmm="12:00") == enabled


def test_no_scene_matches_returns_none():
    engine = SceneEngine()
    engine.set_scenes(
        [{"id": 1, "trigger_type": "schedule", "trigger_from": "20:00", "trigger_until": "21:00"}]
    )

    assert engine.resolve(motion_active=False, now_hhmm="12:00") is None


def test_preview_overrides_normal_resolution():
    clock = {"t": 0.0}
    engine = SceneEngine(preview_timeout=30, clock=lambda: clock["t"])
    engine.set_scenes([{"id": 1, "trigger_type": "always"}])
    preview = {"id": 99, "trigger_type": "always"}
    engine.set_preview(preview)

    assert engine.resolve(motion_active=False, now_hhmm="12:00") == preview


def test_preview_expires_after_timeout():
    clock = {"t": 0.0}
    engine = SceneEngine(preview_timeout=30, clock=lambda: clock["t"])
    normal = {"id": 1, "trigger_type": "always"}
    engine.set_scenes([normal])
    engine.set_preview({"id": 99, "trigger_type": "always"})
    clock["t"] = 31.0

    assert engine.resolve(motion_active=False, now_hhmm="12:00") == normal


def test_time_in_window_normal_range():
    assert _time_in_window("21:00", "20:00", "23:00") is True
    assert _time_in_window("19:00", "20:00", "23:00") is False


def test_time_in_window_midnight_wraparound():
    assert _time_in_window("23:30", "22:00", "02:00") is True
    assert _time_in_window("01:00", "22:00", "02:00") is True
    assert _time_in_window("12:00", "22:00", "02:00") is False


def test_time_in_window_missing_bounds_never_matches():
    assert _time_in_window("12:00", None, None) is False
