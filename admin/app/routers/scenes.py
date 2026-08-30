import json
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_SCENE_COLUMNS = (
    "id, name, order_index, enabled, source_mode, effect, params, overlay_hash, "
    "scale, position, canvas_width, canvas_height, source_scale, source_position, "
    "trigger_type, trigger_from, trigger_until"
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
    "trigger_type": "always",
    "trigger_from": None,
    "trigger_until": None,
}


def _row_to_scene(row):
    canvas_width, canvas_height = row[10], row[11]
    return {
        "id": row[0],
        "name": row[1],
        "order_index": row[2],
        "enabled": bool(row[3]),
        "source_mode": row[4],
        "effect": row[5],
        "params": json.loads(row[6]),
        "overlay_hash": row[7],
        "scale": row[8],
        "position": json.loads(row[9]),
        "canvas_size": [canvas_width, canvas_height] if canvas_width and canvas_height else None,
        "source_scale": row[12],
        "source_position": json.loads(row[13]),
        "trigger_type": row[14],
        "trigger_from": row[15],
        "trigger_until": row[16],
    }


def _list_scenes(db):
    rows = db.execute(f"SELECT {_SCENE_COLUMNS} FROM scenes ORDER BY order_index").fetchall()
    return [_row_to_scene(r) for r in rows]


def _publish_scenes(request):
    request.app.state.bridge.publish_mirror_scenes(_list_scenes(request.app.state.db))


def _fields_from_body(body):
    return {k: body.get(k, v) for k, v in _DEFAULT_SCENE.items()}


def _canvas_columns(fields):
    canvas_size = fields["canvas_size"]
    return tuple(canvas_size) if canvas_size else (None, None)


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
    max_order = db.execute("SELECT MAX(order_index) FROM scenes").fetchone()[0]
    order_index = 0 if max_order is None else max_order + 1
    canvas_width, canvas_height = _canvas_columns(fields)
    cursor = db.execute(
        """INSERT INTO scenes
             (name, order_index, enabled, source_mode, effect, params, overlay_hash,
              scale, position, canvas_width, canvas_height, source_scale, source_position,
              trigger_type, trigger_from, trigger_until)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fields["name"], order_index, int(fields["enabled"]), fields["source_mode"],
            fields["effect"], json.dumps(fields["params"]), fields["overlay_hash"],
            fields["scale"], json.dumps(fields["position"]), canvas_width, canvas_height,
            fields["source_scale"], json.dumps(fields["source_position"]),
            fields["trigger_type"], fields["trigger_from"], fields["trigger_until"],
        ),
    )
    db.commit()
    _publish_scenes(request)
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
             trigger_type=?, trigger_from=?, trigger_until=? WHERE id=?""",
        (
            fields["name"], int(fields["enabled"]), fields["source_mode"], fields["effect"],
            json.dumps(fields["params"]), fields["overlay_hash"], fields["scale"],
            json.dumps(fields["position"]), canvas_width, canvas_height, fields["source_scale"],
            json.dumps(fields["source_position"]), fields["trigger_type"], fields["trigger_from"],
            fields["trigger_until"], scene_id,
        ),
    )
    db.commit()
    _publish_scenes(request)
    return get_scene_route(scene_id, request)


@router.delete("/api/scenes/{scene_id:int}")
def delete_scene_route(scene_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM scenes WHERE id = ?", (scene_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Scene niet gevonden")
    _publish_scenes(request)
    return {"ok": True}


@router.put("/api/scenes/order")
async def reorder_scenes_route(request: Request):
    body = await request.json()
    order = body.get("order")
    if not isinstance(order, list):
        raise HTTPException(status_code=400, detail="order moet een lijst met scene-id's zijn")
    db = request.app.state.db
    for index, scene_id in enumerate(order):
        db.execute("UPDATE scenes SET order_index = ? WHERE id = ?", (index, scene_id))
    db.commit()
    _publish_scenes(request)
    return {"ok": True}


@router.post("/api/scenes/{scene_id}/preview")
async def preview_scene_route(scene_id: int, request: Request):
    scene = await request.json()
    request.app.state.bridge.publish_mirror_scene_preview(scene)
    return {"ok": True}
