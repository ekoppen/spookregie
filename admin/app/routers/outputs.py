from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_OUTPUT_COLUMNS = "id, name, camera_source"


def _row_to_output(row):
    return {"id": row[0], "name": row[1], "camera_source": row[2]}


def _list_outputs(db):
    rows = db.execute(f"SELECT {_OUTPUT_COLUMNS} FROM outputs ORDER BY id").fetchall()
    return [_row_to_output(r) for r in rows]


@router.get("/api/outputs")
def list_outputs_route(request: Request):
    return _list_outputs(request.app.state.db)


@router.get("/api/outputs/{output_id:int}")
def get_output_route(output_id: int, request: Request):
    row = request.app.state.db.execute(
        f"SELECT {_OUTPUT_COLUMNS} FROM outputs WHERE id = ?", (output_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Output niet gevonden")
    return _row_to_output(row)


@router.post("/api/outputs")
async def create_output_route(request: Request):
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name mag niet leeg zijn")
    camera_source = str(body.get("camera_source", ""))
    db = request.app.state.db
    cursor = db.execute("INSERT INTO outputs (name, camera_source) VALUES (?, ?)", (name, camera_source))
    db.commit()
    return get_output_route(cursor.lastrowid, request)


@router.put("/api/outputs/{output_id:int}")
async def update_output_route(output_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM outputs WHERE id = ?", (output_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Output niet gevonden")
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name mag niet leeg zijn")
    camera_source = str(body.get("camera_source", ""))
    db.execute("UPDATE outputs SET name = ?, camera_source = ? WHERE id = ?", (name, camera_source, output_id))
    db.commit()
    return get_output_route(output_id, request)


@router.delete("/api/outputs/{output_id:int}")
def delete_output_route(output_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM outputs WHERE id = ?", (output_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Output niet gevonden")
    has_scenes = db.execute("SELECT 1 FROM scenes WHERE output_id = ? LIMIT 1", (output_id,)).fetchone()
    if has_scenes is not None:
        raise HTTPException(status_code=400, detail="Output heeft nog scenes -- verplaats of verwijder die eerst")
    db.execute("DELETE FROM outputs WHERE id = ?", (output_id,))
    db.commit()
    return {"ok": True}
