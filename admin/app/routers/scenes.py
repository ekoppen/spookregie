import json
from fastapi import APIRouter, HTTPException, Request
from admin.app.graph_publish import publish_graph

router = APIRouter()

_SCENE_COLUMNS = (
    "id, name, enabled, source_mode, effect, params, overlay_hash, "
    "scale, position, canvas_width, canvas_height, source_scale, source_position, "
    "is_root, canvas_x, canvas_y"
)

_DEFAULT_SCENE = {
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
}


def _row_to_scene(row):
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
    }


def _list_scenes(db):
    rows = db.execute(f"SELECT {_SCENE_COLUMNS} FROM scenes ORDER BY id").fetchall()
    return [_row_to_scene(r) for r in rows]


def _fields_from_body(body):
    return {k: body.get(k, v) for k, v in _DEFAULT_SCENE.items()}


def _canvas_columns(fields):
    canvas_size = fields["canvas_size"]
    return tuple(canvas_size) if canvas_size else (None, None)


def _clear_other_roots(db, scene_id):
    db.execute("UPDATE scenes SET is_root = 0 WHERE id != ?", (scene_id,))


@router.get("/api/scenes")
def list_scenes_route(request: Request):
    return _list_scenes(request.app.state.db)


@router.get("/api/scenes/{scene_id:int}")
def get_scene_route(scene_id: int, request: Request):
    row = request.app.state.db.execute(
        f"SELECT {_SCENE_COLUMNS} FROM scenes WHERE id = ?", (scene_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    return _row_to_scene(row)


@router.post("/api/scenes")
async def create_scene_route(request: Request):
    body = await request.json()
    fields = _fields_from_body(body)
    db = request.app.state.db
    # Eerste scene ooit krijgt altijd is_root, ongeacht wat de body vroeg
    # -- zonder root staat de mirror-node stil op zwart, zonder enige
    # aanwijzing in de UI waarom (Minor 12).
    has_root = db.execute("SELECT 1 FROM scenes WHERE is_root = 1 LIMIT 1").fetchone()
    if has_root is None:
        fields["is_root"] = True
    canvas_width, canvas_height = _canvas_columns(fields)
    cursor = db.execute(
        # ponytail: order_index blijft NOT NULL in het schema (legacy
        # migratiekolom, Taak 1) maar wordt door de graaf-app niet meer
        # gebruikt -- vaste 0 om aan de constraint te voldoen zonder
        # db.py aan te raken (buiten scope van deze taak).
        """INSERT INTO scenes
             (name, order_index, enabled, source_mode, effect, params, overlay_hash,
              scale, position, canvas_width, canvas_height, source_scale, source_position,
              is_root, canvas_x, canvas_y)
           VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"],
            fields["effect"], json.dumps(fields["params"]), fields["overlay_hash"],
            fields["scale"], json.dumps(fields["position"]), canvas_width, canvas_height,
            fields["source_scale"], json.dumps(fields["source_position"]),
            int(fields["is_root"]), fields["canvas_x"], fields["canvas_y"],
        ),
    )
    if fields["is_root"]:
        _clear_other_roots(db, cursor.lastrowid)
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return get_scene_route(cursor.lastrowid, request)


@router.put("/api/scenes/{scene_id:int}")
async def update_scene_route(scene_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    body = await request.json()
    fields = _fields_from_body(body)
    canvas_width, canvas_height = _canvas_columns(fields)
    db.execute(
        """UPDATE scenes SET name=?, enabled=?, source_mode=?, effect=?, params=?, overlay_hash=?,
             scale=?, position=?, canvas_width=?, canvas_height=?, source_scale=?, source_position=?,
             is_root=?, canvas_x=?, canvas_y=? WHERE id=?""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"], fields["effect"],
            json.dumps(fields["params"]), fields["overlay_hash"], fields["scale"],
            json.dumps(fields["position"]), canvas_width, canvas_height, fields["source_scale"],
            json.dumps(fields["source_position"]), int(fields["is_root"]),
            fields["canvas_x"], fields["canvas_y"], scene_id,
        ),
    )
    if fields["is_root"]:
        _clear_other_roots(db, scene_id)
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return get_scene_route(scene_id, request)


@router.put("/api/scenes/{scene_id:int}/position")
async def update_scene_position_route(scene_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    body = await request.json()
    try:
        x, y = float(body.get("canvas_x")), float(body.get("canvas_y"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="canvas_x/canvas_y moeten getallen zijn")
    db.execute("UPDATE scenes SET canvas_x = ?, canvas_y = ? WHERE id = ?", (x, y, scene_id))
    db.commit()
    # Bewust GEEN publish_graph hier -- canvaspositie is een editor-
    # aangelegenheid, de mirror-node heeft er niets aan, en dit endpoint
    # wordt tijdens het slepen vaak aangeroepen.
    return {"ok": True}


@router.delete("/api/scenes/{scene_id:int}")
def delete_scene_route(scene_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM scenes WHERE id = ?", (scene_id,))
    if cursor.rowcount == 0:
        db.commit()
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    # Geen DB-foreign-key-afdwinging in dit project -- expliciet
    # opruimen: eigen uitgaande edges verdwijnen mee, inkomende edges
    # vallen terug op een lege output-stub i.p.v. een edge naar een
    # niet-bestaande scene te laten hangen.
    db.execute("DELETE FROM scene_edges WHERE from_scene_id = ?", (scene_id,))
    db.execute(
        "UPDATE scene_edges SET to_scene_id = NULL, trigger_type = NULL, "
        "trigger_from = NULL, trigger_until = NULL WHERE to_scene_id = ?",
        (scene_id,),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}


@router.post("/api/scenes/{scene_id}/preview")
async def preview_scene_route(scene_id: int, request: Request):
    scene = await request.json()
    request.app.state.bridge.publish_mirror_scene_preview(scene)
    return {"ok": True}
