from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_CONNECTION_COLUMNS = "id, output_id, from_branch_id"


def _row_to_connection(row):
    return {"id": row[0], "output_id": row[1], "from_branch_id": row[2]}


@router.post("/api/output-connections")
async def create_output_connection_route(request: Request):
    body = await request.json()
    output_id = body.get("output_id")
    from_branch_id = body.get("from_branch_id")
    db = request.app.state.db
    if db.execute("SELECT id FROM outputs WHERE id = ?", (output_id,)).fetchone() is None:
        raise HTTPException(status_code=400, detail="output_id verwijst naar een onbestaande output")
    if db.execute("SELECT id FROM player_branches WHERE id = ?", (from_branch_id,)).fetchone() is None:
        raise HTTPException(status_code=400, detail="from_branch_id verwijst naar een onbestaande aftakking")
    cursor = db.execute(
        "INSERT INTO output_connections (output_id, from_branch_id) VALUES (?, ?)",
        (output_id, from_branch_id),
    )
    db.commit()
    row = db.execute(f"SELECT {_CONNECTION_COLUMNS} FROM output_connections WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_connection(row)


@router.delete("/api/output-connections/{connection_id:int}")
def delete_output_connection_route(connection_id: int, request: Request):
    db = request.app.state.db
    cursor = db.execute("DELETE FROM output_connections WHERE id = ?", (connection_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Verbinding niet gevonden")
    return {"ok": True}
