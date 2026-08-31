from fastapi import APIRouter, HTTPException, Request
from admin.app.graph_publish import publish_graph

router = APIRouter()

_EDGE_COLUMNS = "id, from_scene_id, to_scene_id, trigger_type, trigger_from, trigger_until, priority"

_DEFAULT_EDGE = {
    "to_scene_id": None,
    "trigger_type": None,
    "trigger_from": None,
    "trigger_until": None,
    "priority": 0,
}


def _row_to_edge(row):
    return {
        "id": row[0],
        "from_scene_id": row[1],
        "to_scene_id": row[2],
        "trigger_type": row[3],
        "trigger_from": row[4],
        "trigger_until": row[5],
        "priority": row[6],
    }


def _list_edges(db):
    rows = db.execute(
        f"SELECT {_EDGE_COLUMNS} FROM scene_edges ORDER BY from_scene_id, priority"
    ).fetchall()
    return [_row_to_edge(r) for r in rows]


@router.get("/api/scene-edges")
def list_edges_route(request: Request):
    return _list_edges(request.app.state.db)


@router.post("/api/scene-edges")
async def create_edge_route(request: Request):
    body = await request.json()
    from_scene_id = body.get("from_scene_id")
    db = request.app.state.db
    if not isinstance(from_scene_id, int):
        raise HTTPException(status_code=400, detail="from_scene_id is verplicht")
    exists = db.execute("SELECT id FROM scenes WHERE id = ?", (from_scene_id,)).fetchone()
    if exists is None:
        raise HTTPException(status_code=400, detail="from_scene_id verwijst naar een onbestaande scene")
    fields = {k: body.get(k, v) for k, v in _DEFAULT_EDGE.items()}
    cursor = db.execute(
        """INSERT INTO scene_edges
             (from_scene_id, to_scene_id, trigger_type, trigger_from, trigger_until, priority)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (from_scene_id, fields["to_scene_id"], fields["trigger_type"], fields["trigger_from"],
         fields["trigger_until"], fields["priority"]),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    row = db.execute(f"SELECT {_EDGE_COLUMNS} FROM scene_edges WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_edge(row)


@router.put("/api/scene-edges/{edge_id:int}")
async def update_edge_route(edge_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM scene_edges WHERE id = ?", (edge_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Verbinding niet gevonden")
    body = await request.json()
    fields = {k: body.get(k, v) for k, v in _DEFAULT_EDGE.items()}
    db.execute(
        """UPDATE scene_edges SET to_scene_id=?, trigger_type=?, trigger_from=?,
             trigger_until=?, priority=? WHERE id=?""",
        (fields["to_scene_id"], fields["trigger_type"], fields["trigger_from"],
         fields["trigger_until"], fields["priority"], edge_id),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    row = db.execute(f"SELECT {_EDGE_COLUMNS} FROM scene_edges WHERE id = ?", (edge_id,)).fetchone()
    return _row_to_edge(row)


@router.delete("/api/scene-edges/{edge_id:int}")
def delete_edge_route(edge_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM scene_edges WHERE id = ?", (edge_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Verbinding niet gevonden")
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}
