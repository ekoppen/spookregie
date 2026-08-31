def publish_graph(db, bridge):
    """Publiceert de volledige graaf (scenes + triggers + root + output)
    naar MQTT -- gedeeld door scenes.py en triggers.py, elke schrijvende
    route in beide roept dit aan zodat opgeslagen en gepubliceerde graaf
    nooit uit elkaar kunnen lopen. Lazy imports om een cirkel met de
    routers te vermijden (die importeren dit bestand). output_id is
    voorlopig altijd de eerste/enige output -- een toekomstige
    multi-output-uitrol geeft dit expliciet mee per aanroep."""
    from admin.app.routers.scenes import _list_scenes
    from admin.app.routers.triggers import _list_triggers

    scenes = _list_scenes(db)
    triggers = _list_triggers(db)
    root_scene_id = next((s["id"] for s in scenes if s["is_root"]), None)
    output_row = db.execute("SELECT id FROM outputs ORDER BY id LIMIT 1").fetchone()
    output_id = output_row[0] if output_row else None
    bridge.publish_mirror_graph({
        "output_id": output_id, "scenes": scenes, "triggers": triggers, "root_scene_id": root_scene_id,
    })
