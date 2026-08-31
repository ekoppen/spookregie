from mirror_node.scenes import SceneGraph, _time_in_window


def _graph(scenes, triggers, root_id, **kwargs):
    g = SceneGraph(**kwargs)
    g.set_graph(scenes, triggers, root_id)
    return g


def test_resolves_to_root_with_no_triggers():
    g = _graph([{"id": 1, "name": "Basis"}], [], root_id=1)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_transitions_on_matching_motion_trigger():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_no_transition_without_motion():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_only_current_nodes_own_triggers_are_checked():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is False


def test_return_trigger_brings_state_back_on_next_resolve():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_branch_id": 2, "to_player_id": 1, "kind": "always",
         "schedule_from": None, "schedule_until": None, "priority": 0},
    ]
    g = _graph(scenes, triggers, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is True


def test_non_live_triggers_are_ignored():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": None, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_branch_id": 1, "to_player_id": 2, "kind": None,
         "schedule_from": None, "schedule_until": None, "priority": 1},
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_priority_order_first_matching_trigger_wins():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}, {"id": 3, "name": "B"}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": 3, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 1},
        {"from_branch_id": 1, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "A"}


def test_unknown_current_scene_resets_to_root():
    g = _graph([{"id": 1, "name": "Basis"}], [], root_id=1)
    g._current_id = 999

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}


def test_no_root_and_no_scenes_returns_none():
    g = SceneGraph()
    g.set_graph([], [], root_scene_id=None)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene is None
    assert transitioned is False


def test_disabled_scene_is_never_resolved_to():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare", "enabled": False}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_trigger_to_unknown_scene_is_skipped_not_followed():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": 999, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_branch_id": 1, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 1},
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "A"}
    assert transitioned is True


def test_preview_overrides_graph_evaluation():
    clock = {"t": 0.0}
    g = SceneGraph(preview_timeout=30, clock=lambda: clock["t"])
    g.set_graph([{"id": 1, "name": "Basis"}], [], root_scene_id=1)
    preview = {"id": 99, "name": "Preview"}
    g.set_preview(preview)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == preview
    assert transitioned is False


def test_preview_expires_after_timeout():
    clock = {"t": 0.0}
    g = SceneGraph(preview_timeout=30, clock=lambda: clock["t"])
    root = {"id": 1, "name": "Basis"}
    g.set_graph([root], [], root_scene_id=1)
    g.set_preview({"id": 99, "name": "Preview"})
    clock["t"] = 31.0

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == root


def test_ha_sensor_trigger_matches_only_its_own_fired_entity():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": 2, "kind": "ha_sensor",
         "schedule_from": None, "schedule_until": None, "ha_entity_id": "binary_sensor.tuin",
         "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    not_fired = g.resolve(motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset())
    assert not_fired == ({"id": 1, "name": "Basis"}, False)

    other_entity_fired = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.woonkamer"})
    )
    assert other_entity_fired == ({"id": 1, "name": "Basis"}, False)

    scene, transitioned = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.tuin"})
    )
    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_ha_sensor_trigger_without_ha_entity_id_never_matches():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    triggers = [
        {"from_branch_id": 1, "to_player_id": 2, "kind": "ha_sensor",
         "schedule_from": None, "schedule_until": None, "ha_entity_id": None, "priority": 0}
    ]
    g = _graph(scenes, triggers, root_id=1)

    scene, transitioned = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.tuin"})
    )

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_time_in_window_normal_range():
    assert _time_in_window("21:00", "20:00", "23:00") is True
    assert _time_in_window("19:00", "20:00", "23:00") is False


def test_time_in_window_midnight_wraparound():
    assert _time_in_window("23:30", "22:00", "02:00") is True
    assert _time_in_window("01:00", "22:00", "02:00") is True
    assert _time_in_window("12:00", "22:00", "02:00") is False


def test_time_in_window_missing_bounds_never_matches():
    assert _time_in_window("12:00", None, None) is False
