from fastapi import APIRouter, HTTPException, Request

from admin.app.graph_publish import publish_graph

router = APIRouter()

_SOURCE_COLUMNS = "id, name, kind, value, canvas_x, canvas_y"
_VIDEO_KINDS = {"camera_stream", "static_image", "video_loop"}
_AUDIO_KINDS = {"audio"}
_VALID_KINDS = _VIDEO_KINDS | _AUDIO_KINDS


def _row_to_source(row):
    return {"id": row[0], "name": row[1], "kind": row[2], "value": row[3], "canvas_x": row[4], "canvas_y": row[5]}


def _list_sources(db):
    rows = db.execute(f"SELECT {_SOURCE_COLUMNS} FROM sources ORDER BY id").fetchall()
    return [_row_to_source(r) for r in rows]


def _validate_source_body(body):
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name mag niet leeg zijn")
    kind = body.get("kind", "camera_stream")
    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind moet één van {sorted(_VALID_KINDS)} zijn")
    return {
        "name": name,
        "kind": kind,
        "value": str(body.get("value", "")),
        "canvas_x": float(body.get("canvas_x", 0.0)),
        "canvas_y": float(body.get("canvas_y", 0.0)),
    }


def _reject_kind_change_breaking_players(db, source_id, new_kind):
    """400 als een kind-wijziging een bestaande koppeling ongeldig maakt.
    players.source_id mag alleen naar een video-kind wijzen en
    players.audio_source_id alleen naar 'audio' (zelfde regel als
    players._validate_source_kind bij het koppelen zelf) -- zonder deze
    guard kan de UI een gekoppelde camera-source in twee klikken naar
    'audio' omzetten, waarna de mirror-node de media-hash als camera-URL
    probeert te openen en permanent zwart blijft."""
    if new_kind not in _VIDEO_KINDS:
        if db.execute("SELECT 1 FROM players WHERE source_id = ? LIMIT 1", (source_id,)).fetchone():
            raise HTTPException(
                status_code=400,
                detail=f"Source is het videospoor van een player -- kind moet {sorted(_VIDEO_KINDS)} blijven",
            )
    if new_kind not in _AUDIO_KINDS:
        if db.execute("SELECT 1 FROM players WHERE audio_source_id = ? LIMIT 1", (source_id,)).fetchone():
            raise HTTPException(
                status_code=400,
                detail="Source is het audiospoor van een player -- kind moet 'audio' blijven",
            )


@router.get("/api/sources")
def list_sources_route(request: Request):
    return _list_sources(request.app.state.db)


@router.get("/api/sources/{source_id:int}")
def get_source_route(source_id: int, request: Request):
    row = request.app.state.db.execute(
        f"SELECT {_SOURCE_COLUMNS} FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Source niet gevonden")
    return _row_to_source(row)


@router.post("/api/sources")
async def create_source_route(request: Request):
    body = await request.json()
    fields = _validate_source_body(body)
    db = request.app.state.db
    cursor = db.execute(
        "INSERT INTO sources (name, kind, value, canvas_x, canvas_y) VALUES (?, ?, ?, ?, ?)",
        (fields["name"], fields["kind"], fields["value"], fields["canvas_x"], fields["canvas_y"]),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return get_source_route(cursor.lastrowid, request)


@router.put("/api/sources/{source_id:int}")
async def update_source_route(source_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT kind FROM sources WHERE id = ?", (source_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Source niet gevonden")
    body = await request.json()
    fields = _validate_source_body(body)
    if fields["kind"] != existing[0]:
        _reject_kind_change_breaking_players(db, source_id, fields["kind"])
    db.execute(
        "UPDATE sources SET name = ?, kind = ?, value = ?, canvas_x = ?, canvas_y = ? WHERE id = ?",
        (fields["name"], fields["kind"], fields["value"], fields["canvas_x"], fields["canvas_y"], source_id),
    )
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return get_source_route(source_id, request)


@router.delete("/api/sources/{source_id:int}")
def delete_source_route(source_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM sources WHERE id = ?", (source_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Source niet gevonden")
    has_players = db.execute("SELECT 1 FROM players WHERE source_id = ? LIMIT 1", (source_id,)).fetchone()
    if has_players is not None:
        raise HTTPException(status_code=400, detail="Source heeft nog players -- verplaats of verwijder die eerst")
    db.execute("UPDATE players SET audio_source_id = NULL WHERE audio_source_id = ?", (source_id,))
    db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    db.commit()
    publish_graph(db, request.app.state.bridge)
    return {"ok": True}
