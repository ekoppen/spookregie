def publish_graph(db, bridge):
    """Publiceert de volledige graaf (scenes + edges + root) naar MQTT
    -- gedeeld door scenes.py en scene_edges.py, elke schrijvende
    route in beide roept dit aan zodat opgeslagen en gepubliceerde
    graaf nooit uit elkaar kunnen lopen. Lazy imports om een cirkel
    met de twee routers te vermijden (die importeren dit bestand)."""
    from admin.app.routers.scenes import _list_scenes
    from admin.app.routers.scene_edges import _list_edges

    scenes = _list_scenes(db)
    edges = _list_edges(db)
    root_scene_id = next((s["id"] for s in scenes if s["is_root"]), None)
    bridge.publish_mirror_graph({"scenes": scenes, "edges": edges, "root_scene_id": root_scene_id})
