def publish_graph(db, bridge):
    """Publiceert de volledige graaf (players + sources + branches +
    triggers + output_connections + root + output) naar MQTT -- gedeeld
    door players.py/triggers.py/sources.py/output_connections.py/outputs.py,
    elke schrijvende route roept dit aan (behalve pure positie-updates)
    zodat opgeslagen en gepubliceerde graaf nooit uit elkaar kunnen lopen.
    Lazy imports om een cirkel met de routers te vermijden (die importeren
    dit bestand). output_id is
    voorlopig altijd de eerste/enige output -- zelfde ruling als voorheen,
    een toekomstige multi-output-uitrol geeft dit expliciet mee per
    aanroep."""
    from admin.app.routers.players import _list_players
    from admin.app.routers.triggers import _list_triggers
    from admin.app.routers.sources import _list_sources
    from admin.app.routers.output_connections import _list_output_connections

    players = _list_players(db)
    sources = _list_sources(db)
    triggers = _list_triggers(db)
    output_connections = _list_output_connections(db)
    branch_rows = db.execute("SELECT id, player_id, name FROM player_branches ORDER BY id").fetchall()
    branches = [{"id": r[0], "player_id": r[1], "name": r[2]} for r in branch_rows]
    root_player_id = next((p["id"] for p in players if p["is_root"]), None)
    output_row = db.execute("SELECT id FROM outputs ORDER BY id LIMIT 1").fetchone()
    output_id = output_row[0] if output_row else None
    bridge.publish_mirror_graph({
        "output_id": output_id,
        "players": players,
        "sources": sources,
        "branches": branches,
        "triggers": triggers,
        "output_connections": output_connections,
        "root_player_id": root_player_id,
    })
