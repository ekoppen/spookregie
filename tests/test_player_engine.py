from mirror_node.players import PlayerGraph, _time_in_window


def _graph(players, branches, triggers, root_id, **kwargs):
    g = PlayerGraph(**kwargs)
    g.set_graph(players, branches, triggers, root_id)
    return g


# Branch-ids zijn hier bewust ANDERS dan player-ids (101/102 i.p.v. 1/2) --
# zou de indirectie in set_graph() ontbreken (of stilletjes op id-gelijkenis
# leunen), dan falen deze tests meteen in plaats van toevallig te slagen.
_BASIC_BRANCH = {"id": 101, "player_id": 1, "name": "Uitgang 1"}
_SCARE_BRANCH = {"id": 102, "player_id": 2, "name": "Uitgang 1"}


def test_resolves_to_root_with_no_triggers():
    g = _graph([{"id": 1, "name": "Basis"}], [_BASIC_BRANCH], [], root_id=1)

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_transitions_on_matching_motion_trigger():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_no_transition_without_motion():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_only_current_players_own_triggers_are_checked():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 2, "name": "Scare"}
    assert transitioned is False


def test_return_trigger_brings_state_back_on_next_resolve():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH, _SCARE_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_branch_id": 102, "to_player_id": 1, "kind": "always",
         "schedule_from": None, "schedule_until": None, "priority": 0},
    ]
    g = _graph(players, branches, triggers, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is True


def test_non_live_triggers_are_ignored():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": None, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_branch_id": 101, "to_player_id": 2, "kind": None,
         "schedule_from": None, "schedule_until": None, "priority": 1},
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_priority_order_first_matching_trigger_wins():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}, {"id": 3, "name": "B"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 3, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 1},
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 2, "name": "A"}


def test_unknown_current_player_resets_to_root():
    g = _graph([{"id": 1, "name": "Basis"}], [_BASIC_BRANCH], [], root_id=1)
    g._current_id = 999

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}


def test_no_root_and_no_players_returns_none():
    g = PlayerGraph()
    g.set_graph([], [], [], root_player_id=None)

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player is None
    assert transitioned is False


def test_disabled_player_is_never_resolved_to():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare", "enabled": False}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_trigger_to_unknown_player_is_skipped_not_followed():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 999, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 0},
        {"from_branch_id": 101, "to_player_id": 2, "kind": "motion",
         "schedule_from": None, "schedule_until": None, "priority": 1},
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert player == {"id": 2, "name": "A"}
    assert transitioned is True


def test_trigger_from_an_orphaned_branch_id_is_ignored():
    """Regressie: als een trigger een from_branch_id heeft die niet (meer)
    in de meegestuurde branches-lijst voorkomt, mag dat niet crashen --
    de trigger wordt simpelweg genegeerd (verweesde/inconsistente data)."""
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}]
    triggers = [
        {"from_branch_id": 999, "to_player_id": 2, "kind": "always",
         "schedule_from": None, "schedule_until": None, "priority": 0}
    ]
    g = _graph(players, [], triggers, root_id=1)  # geen branches meegestuurd

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_preview_overrides_graph_evaluation():
    clock = {"t": 0.0}
    g = PlayerGraph(preview_timeout=30, clock=lambda: clock["t"])
    g.set_graph([{"id": 1, "name": "Basis"}], [], [], root_player_id=1)
    preview = {"id": 99, "name": "Preview"}
    g.set_preview(preview)

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == preview
    assert transitioned is False


def test_preview_expires_after_timeout():
    clock = {"t": 0.0}
    g = PlayerGraph(preview_timeout=30, clock=lambda: clock["t"])
    root = {"id": 1, "name": "Basis"}
    g.set_graph([root], [], [], root_player_id=1)
    g.set_preview({"id": 99, "name": "Preview"})
    clock["t"] = 31.0

    player, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert player == root


def test_ha_sensor_trigger_matches_only_its_own_fired_entity():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "ha_sensor",
         "schedule_from": None, "schedule_until": None, "ha_entity_id": "binary_sensor.tuin",
         "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    not_fired = g.resolve(motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset())
    assert not_fired == ({"id": 1, "name": "Basis"}, False)

    other_entity_fired = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.woonkamer"})
    )
    assert other_entity_fired == ({"id": 1, "name": "Basis"}, False)

    player, transitioned = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.tuin"})
    )
    assert player == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_ha_sensor_trigger_without_ha_entity_id_never_matches():
    players = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    branches = [_BASIC_BRANCH]
    triggers = [
        {"from_branch_id": 101, "to_player_id": 2, "kind": "ha_sensor",
         "schedule_from": None, "schedule_until": None, "ha_entity_id": None, "priority": 0}
    ]
    g = _graph(players, branches, triggers, root_id=1)

    player, transitioned = g.resolve(
        motion_active=False, now_hhmm="12:00", fired_ha_entities=frozenset({"binary_sensor.tuin"})
    )

    assert player == {"id": 1, "name": "Basis"}
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
