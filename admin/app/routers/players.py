import json
from fastapi import APIRouter, HTTPException, Request
from admin.app.graph_publish import publish_graph

router = APIRouter()

_PLAYER_COLUMNS = (
    "id, name, enabled, source_mode, effect, params, overlay_hash, "
    "scale, position, canvas_width, canvas_height, source_scale, source_position, "
    "is_root, canvas_x, canvas_y, color, source_id, playback_mode, repeat_while_ha_entity_id"
)

_DEFAULT_PLAYER = {
    "name": "Nieuwe scene",
    "enabled": True,
    "source_mode": "camera",
    "effect": "xray",
    "params": {},
    "overlay_hash": None,
    "scale": 1.0,
    "position": [0.5, 0.5],
    "canvas_size": None,
    "source_scale": 1.0,
    "source_position": [0.5, 0.5],
    "is_root": False,
    "canvas_x": 0.0,
    "canvas_y": 0.0,
    "color": None,
    "source_id": None,
    "playback_mode": "once",
    "repeat_while_ha_entity_id": None,
}


def _row_to_player(row):
    canvas_width, canvas_height = row[9], row[10]
    return {
        "id": row[0],
        "name": row[1],
        "enabled": bool(row[2]),
        "source_mode": row[3],
        "effect": row[4],
        "params": json.loads(row[5]),
        "overlay_hash": row[6],
        "scale": row[7],
        "position": json.loads(row[8]),
        "canvas_size": [canvas_width, canvas_height] if canvas_width and canvas_height else None,
        "source_scale": row[11],
        "source_position": json.loads(row[12]),
        "is_root": bool(row[13]),
        "canvas_x": row[14],
        "canvas_y": row[15],
        "color": row[16],
        "source_id": row[17],
        "playback_mode": row[18],
        "repeat_while_ha_entity_id": row[19],
    }


def _list_players(db):
    rows = db.execute(f"SELECT {_PLAYER_COLUMNS} FROM players ORDER BY id").fetchall()
    return [_row_to_player(r) for r in rows]


def _fields_from_body(body):
    return {k: body.get(k, v) for k, v in _DEFAULT_PLAYER.items()}


def _canvas_columns(fields):
    canvas_size = fields["canvas_size"]
    return tuple(canvas_size) if canvas_size else (None, None)


def _clear_other_roots(db, scene_id):
    db.execute("UPDATE players SET is_root = 0 WHERE id != ?", (scene_id,))


def _resolve_source_id(db, source_id):
    """Geeft source_id terug als 'ie gezet is, anders de eerste/enige
    source. 400 als er helemaal geen source bestaat (kan alleen als de
    Taak-1-migratie nooit gedraaid heeft, defensief)."""
    if source_id is not None:
        return source_id
    default_source = db.execute("SELECT id FROM sources ORDER BY id LIMIT 1").fetchone()
    if default_source is None:
        raise HTTPException(status_code=400, detail="Geen source beschikbaar, maak er eerst één aan")
    return default_source[0]


@router.get("/api/players")
def list_players_route(request: Request):
    return _list_players(request.app.state.db)


@router.get("/api/players/{player_id:int}")
def get_player_route(player_id: int, request: Request):
    row = request.app.state.db.execute(
        f"SELECT {_PLAYER_COLUMNS} FROM players WHERE id = ?", (player_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    return _row_to_player(row)


@router.post("/api/players")
async def create_player_route(request: Request):
    body = await request.json()
    fields = _fields_from_body(body)
    db = request.app.state.db
    # Eerste scene ooit krijgt altijd is_root, ongeacht wat de body vroeg
    # -- zonder root staat de mirror-node stil op zwart, zonder enige
    # aanwijzing in de UI waarom (Minor 12).
    has_root = db.execute("SELECT 1 FROM players WHERE is_root = 1 LIMIT 1").fetchone()
    if has_root is None:
        fields["is_root"] = True
    canvas_width, canvas_height = _canvas_columns(fields)
    fields["source_id"] = _resolve_source_id(db, fields["source_id"])
    cursor = db.execute(
        # ponytail: order_index blijft NOT NULL in het schema (legacy
        # migratiekolom) maar wordt door de graaf-app niet meer gebruikt
        # -- vaste 0 om aan de constraint te voldoen zonder db.py aan te
        # raken (buiten scope van deze taak).
        """INSERT INTO players
             (name, order_index, enabled, source_mode, effect, params, overlay_hash,
              scale, position, canvas_width, canvas_height, source_scale, source_position,
              is_root, canvas_x, canvas_y, color, source_id, playback_mode, repeat_while_ha_entity_id)
           VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"],
            fields["effect"], json.dumps(fields["params"]), fields["overlay_hash"],
            fields["scale"], json.dumps(fields["position"]), canvas_width, canvas_height,
            fields["source_scale"], json.dumps(fields["source_position"]),
            int(fields["is_root"]), fields["canvas_x"], fields["canvas_y"],
            fields["color"], fields["source_id"], fields["playback_mode"],
            fields["repeat_while_ha_entity_id"],
        ),
    )
    if fields["is_root"]:
        _clear_other_roots(db, cursor.lastrowid)
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return get_player_route(cursor.lastrowid, request)


@router.put("/api/players/{player_id:int}")
async def update_player_route(player_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM players WHERE id = ?", (player_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    body = await request.json()
    fields = _fields_from_body(body)
    canvas_width, canvas_height = _canvas_columns(fields)
    fields["source_id"] = _resolve_source_id(db, fields["source_id"])
    db.execute(
        """UPDATE players SET name=?, enabled=?, source_mode=?, effect=?, params=?, overlay_hash=?,
             scale=?, position=?, canvas_width=?, canvas_height=?, source_scale=?, source_position=?,
             is_root=?, canvas_x=?, canvas_y=?, color=?, source_id=?, playback_mode=?,
             repeat_while_ha_entity_id=? WHERE id=?""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"], fields["effect"],
            json.dumps(fields["params"]), fields["overlay_hash"], fields["scale"],
            json.dumps(fields["position"]), canvas_width, canvas_height, fields["source_scale"],
            json.dumps(fields["source_position"]), int(fields["is_root"]),
            fields["canvas_x"], fields["canvas_y"], fields["color"], fields["source_id"],
            fields["playback_mode"], fields["repeat_while_ha_entity_id"], player_id,
        ),
    )
    if fields["is_root"]:
        _clear_other_roots(db, player_id)
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return get_player_route(player_id, request)


@router.put("/api/players/{player_id:int}/position")
async def update_player_position_route(player_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM players WHERE id = ?", (player_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    body = await request.json()
    try:
        x, y = float(body.get("canvas_x")), float(body.get("canvas_y"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="canvas_x/canvas_y moeten getallen zijn")
    db.execute("UPDATE players SET canvas_x = ?, canvas_y = ? WHERE id = ?", (x, y, player_id))
    db.commit()
    # Bewust GEEN publish_graph hier -- canvaspositie is een editor-
    # aangelegenheid, de mirror-node heeft er niets aan, en dit endpoint
    # wordt tijdens het slepen vaak aangeroepen.
    return {"ok": True}


@router.delete("/api/players/{player_id:int}")
def delete_player_route(player_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM players WHERE id = ?", (player_id,))
    if cursor.rowcount == 0:
        db.commit()
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    # Geen DB-foreign-key-afdwinging in dit project -- expliciet
    # opruimen: eigen uitgaande edges verdwijnen mee, inkomende edges
    # vallen terug op een lege output-stub i.p.v. een edge naar een
    # niet-bestaande scene te laten hangen.
    db.execute("DELETE FROM triggers WHERE from_scene_id = ?", (player_id,))
    db.execute(
        "UPDATE triggers SET to_scene_id = NULL, kind = NULL, "
        "schedule_from = NULL, schedule_until = NULL, ha_entity_id = NULL WHERE to_scene_id = ?",
        (player_id,),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}


@router.post("/api/scenes/{scene_id}/preview")
async def preview_scene_route(scene_id: int, request: Request):
    scene = await request.json()
    request.app.state.bridge.publish_mirror_scene_preview(scene)
    return {"ok": True}
