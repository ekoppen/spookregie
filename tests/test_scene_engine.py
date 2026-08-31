from mirror_node.scenes import SceneGraph, _time_in_window


def _graph(scenes, edges, root_id, **kwargs):
    g = SceneGraph(**kwargs)
    g.set_graph(scenes, edges, root_id)
    return g


def test_resolves_to_root_with_no_edges():
    g = _graph([{"id": 1, "name": "Basis"}], [], root_id=1)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_transitions_on_matching_motion_edge():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0}
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is True


def test_no_transition_without_motion():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0}
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_only_current_nodes_own_edges_are_checked():
    """Root heeft een motion-edge naar Scare; Scare heeft er zelf geen
    -- eenmaal bij Scare aangekomen, matcht een volgende beweging niets
    meer (Scare's eigen edge-lijst is leeg)."""
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0}
    ]
    g = _graph(scenes, edges, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")  # naar Scare

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "Scare"}
    assert transitioned is False


def test_return_edge_brings_state_back_on_next_resolve():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
        {"from_scene_id": 2, "to_scene_id": 1, "trigger_type": "always",
         "trigger_from": None, "trigger_until": None, "priority": 0},
    ]
    g = _graph(scenes, edges, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")  # naar Scare

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")  # altijd-edge terug

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is True


def test_non_live_edges_are_ignored():
    """Een edge zonder to_scene_id (lege output) of zonder trigger_type
    (nog niet ingesteld) telt niet mee."""
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": None, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": None,
         "trigger_from": None, "trigger_until": None, "priority": 1},
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_priority_order_first_matching_edge_wins():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "A"}, {"id": 3, "name": "B"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 3, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 1},
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 2, "name": "A"}


def test_unknown_current_scene_resets_to_root():
    g = _graph([{"id": 1, "name": "Basis"}], [], root_id=1)
    g._current_id = 999  # gesimuleerd: vorige graaf had een scene die nu weg is

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}


def test_no_root_and_no_scenes_returns_none():
    g = SceneGraph()
    g.set_graph([], [], root_scene_id=None)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene is None
    assert transitioned is False


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


def test_one_shot_pulse_causes_exactly_one_scare_video_transition():
    """Regressie voor Critical 1 (mirror_node/main.py): de hoofdlus moet
    een eenmalige puls doorgeven aan resolve(), niet het aanhoudende
    cooldown-niveau. Met root --motion--> Scare en Scare --always--> root
    (de gebruikelijke terugkeer-edge) zou een aanhoudend niveau bij elke
    terugkeer op root de motion-edge opnieuw laten matchen en de graaf
    oneindig laten ping-pongen. Eén puls (True op precies één resolve(),
    daarna False) mag maar één keer naar Scare transitioneren."""
    scenes = [
        {"id": 1, "name": "Basis", "source_mode": "camera"},
        {"id": 2, "name": "Scare", "source_mode": "scare_video"},
    ]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
        {"from_scene_id": 2, "to_scene_id": 1, "trigger_type": "always",
         "trigger_from": None, "trigger_until": None, "priority": 0},
    ]
    g = _graph(scenes, edges, root_id=1)

    transitions_into_scare = 0
    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")  # de ene puls
    if scene["id"] == 2 and transitioned:
        transitions_into_scare += 1
    for _ in range(5):  # cooldown-vensters later, geen nieuwe puls
        scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")
        if scene["id"] == 2 and transitioned:
            transitions_into_scare += 1

    assert transitions_into_scare == 1


def test_sustained_level_would_replay_scare_video_repeatedly():
    """Tegenbewijs bij de vorige test: als motion_active per ongeluk het
    aanhoudende niveau is (de bug die Critical 1 fixt) i.p.v. een puls,
    ping-pongt dezelfde graaf oneindig door en 'transitioneert' telkens
    opnieuw naar Scare -- exact het symptoom uit de bug-report."""
    scenes = [
        {"id": 1, "name": "Basis", "source_mode": "camera"},
        {"id": 2, "name": "Scare", "source_mode": "scare_video"},
    ]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
        {"from_scene_id": 2, "to_scene_id": 1, "trigger_type": "always",
         "trigger_from": None, "trigger_until": None, "priority": 0},
    ]
    g = _graph(scenes, edges, root_id=1)

    transitions_into_scare = 0
    for _ in range(6):  # niveau blijft True zolang de cooldown "loopt"
        scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")
        if scene["id"] == 2 and transitioned:
            transitions_into_scare += 1

    assert transitions_into_scare > 1  # de bug: meerdere replays uit één trigger


def test_disabled_scene_is_never_resolved_to():
    """Regressie voor Important 5: de oude SceneEngine sloeg enabled=False
    over, de nieuwe SceneGraph deed dat niet meer. Een edge naar een
    uitgeschakelde scene mag niet matchen."""
    scenes = [
        {"id": 1, "name": "Basis"},
        {"id": 2, "name": "Uit", "enabled": False},
    ]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=True, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}
    assert transitioned is False


def test_current_scene_disabled_between_graph_updates_resets_to_root():
    scenes = [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 2, "trigger_type": "motion",
         "trigger_from": None, "trigger_until": None, "priority": 0},
    ]
    g = _graph(scenes, edges, root_id=1)
    g.resolve(motion_active=True, now_hhmm="12:00")  # naar Scare
    assert g._current_id == 2

    g.set_graph(
        [{"id": 1, "name": "Basis"}, {"id": 2, "name": "Scare", "enabled": False}],
        edges,
        root_scene_id=1,
    )
    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

    assert scene == {"id": 1, "name": "Basis"}


def test_edge_to_missing_scene_falls_through_instead_of_looping_black():
    """Regressie voor Important 6: resolve() volgt geen edge naar een
    scene die niet (meer) bestaat -- de spec zegt expliciet dat zo'n
    edge gewoon niet matcht en doorvalt, i.p.v. er blindelings naartoe
    te gaan en (None, True) terug te geven (permanente zwart-beeld-lus:
    elk volgend frame reset naar root en matcht dezelfde kapotte edge
    opnieuw)."""
    scenes = [{"id": 1, "name": "Basis"}]
    edges = [
        {"from_scene_id": 1, "to_scene_id": 999, "trigger_type": "always",
         "trigger_from": None, "trigger_until": None, "priority": 0},
    ]
    g = _graph(scenes, edges, root_id=1)

    scene, transitioned = g.resolve(motion_active=False, now_hhmm="12:00")

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
