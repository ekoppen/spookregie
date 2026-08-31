from fastapi import APIRouter, HTTPException, Request
from admin.app.graph_publish import publish_graph

router = APIRouter()

_TRIGGER_COLUMNS = (
    "id, from_scene_id, to_scene_id, kind, schedule_from, schedule_until, "
    "ha_entity_id, priority, canvas_x, canvas_y, name, color"
)

_DEFAULT_TRIGGER = {
    "to_scene_id": None,
    "kind": None,
    "schedule_from": None,
    "schedule_until": None,
    "ha_entity_id": None,
    "priority": 0,
    "canvas_x": 0.0,
    "canvas_y": 0.0,
    "name": None,
    "color": None,
}

_VALID_KINDS = {"always", "motion", "schedule", "ha_sensor"}


def _row_to_trigger(row):
    return {
        "id": row[0],
        "from_scene_id": row[1],
        "to_scene_id": row[2],
        "kind": row[3],
        "schedule_from": row[4],
        "schedule_until": row[5],
        "ha_entity_id": row[6],
        "priority": row[7],
        "canvas_x": row[8],
        "canvas_y": row[9],
        "name": row[10],
        "color": row[11],
    }


def _list_triggers(db):
    rows = db.execute(
        f"SELECT {_TRIGGER_COLUMNS} FROM triggers ORDER BY from_scene_id, priority"
    ).fetchall()
    return [_row_to_trigger(r) for r in rows]


def _validate_kind(fields):
    if fields["kind"] is not None and fields["kind"] not in _VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind moet één van {sorted(_VALID_KINDS)} zijn")
    if fields["kind"] == "ha_sensor" and not fields["ha_entity_id"]:
        raise HTTPException(status_code=400, detail="ha_entity_id is verplicht bij kind='ha_sensor'")


@router.get("/api/triggers")
def list_triggers_route(request: Request):
    return _list_triggers(request.app.state.db)


@router.post("/api/triggers")
async def create_trigger_route(request: Request):
    body = await request.json()
    from_scene_id = body.get("from_scene_id")
    db = request.app.state.db
    if not isinstance(from_scene_id, int):
        raise HTTPException(status_code=400, detail="from_scene_id is verplicht")
    exists = db.execute("SELECT id FROM players WHERE id = ?", (from_scene_id,)).fetchone()
    if exists is None:
        raise HTTPException(status_code=400, detail="from_scene_id verwijst naar een onbestaande scene")
    fields = {k: body.get(k, v) for k, v in _DEFAULT_TRIGGER.items()}
    _validate_kind(fields)
    cursor = db.execute(
        """INSERT INTO triggers
             (from_scene_id, to_scene_id, kind, schedule_from, schedule_until, ha_entity_id,
              priority, canvas_x, canvas_y, name, color)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (from_scene_id, fields["to_scene_id"], fields["kind"], fields["schedule_from"],
         fields["schedule_until"], fields["ha_entity_id"], fields["priority"],
         fields["canvas_x"], fields["canvas_y"], fields["name"], fields["color"]),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    row = db.execute(f"SELECT {_TRIGGER_COLUMNS} FROM triggers WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_trigger(row)


@router.put("/api/triggers/{trigger_id:int}")
async def update_trigger_route(trigger_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Trigger niet gevonden")
    body = await request.json()
    fields = {k: body.get(k, v) for k, v in _DEFAULT_TRIGGER.items()}
    _validate_kind(fields)
    if fields["to_scene_id"] is not None:
        target = db.execute("SELECT id FROM players WHERE id = ?", (fields["to_scene_id"],)).fetchone()
        if target is None:
            raise HTTPException(status_code=400, detail="to_scene_id verwijst naar een onbestaande scene")
    db.execute(
        """UPDATE triggers SET to_scene_id=?, kind=?, schedule_from=?, schedule_until=?,
             ha_entity_id=?, priority=?, canvas_x=?, canvas_y=?, name=?, color=? WHERE id=?""",
        (fields["to_scene_id"], fields["kind"], fields["schedule_from"], fields["schedule_until"],
         fields["ha_entity_id"], fields["priority"], fields["canvas_x"], fields["canvas_y"],
         fields["name"], fields["color"], trigger_id),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    row = db.execute(f"SELECT {_TRIGGER_COLUMNS} FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
    return _row_to_trigger(row)


@router.put("/api/triggers/{trigger_id:int}/position")
async def update_trigger_position_route(trigger_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Trigger niet gevonden")
    body = await request.json()
    try:
        x, y = float(body.get("canvas_x")), float(body.get("canvas_y"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="canvas_x/canvas_y moeten getallen zijn")
    db.execute("UPDATE triggers SET canvas_x = ?, canvas_y = ? WHERE id = ?", (x, y, trigger_id))
    db.commit()
    # Bewust GEEN publish_graph hier -- canvaspositie is een editor-
    # aangelegenheid, zelfde reden als bij scenes' /position-route.
    return {"ok": True}


@router.delete("/api/triggers/{trigger_id:int}")
def delete_trigger_route(trigger_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Trigger niet gevonden")
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}
