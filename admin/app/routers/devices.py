from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_DEVICE_COLUMNS = (
    "id, device_uuid, name, platform, git_sha, last_seen_at, output_id, "
    "is_mirror, is_camera, camera_stream_url"
)


def _row_to_device(row):
    return {
        "id": row[0],
        "device_uuid": row[1],
        "name": row[2],
        "platform": row[3],
        "git_sha": row[4],
        "last_seen_at": row[5],
        "output_id": row[6],
        "is_mirror": bool(row[7]),
        "is_camera": bool(row[8]),
        "camera_stream_url": row[9],
    }


@router.get("/api/devices")
def list_devices_route(request: Request):
    rows = request.app.state.db.execute(f"SELECT {_DEVICE_COLUMNS} FROM devices ORDER BY name").fetchall()
    return [_row_to_device(r) for r in rows]


@router.put("/api/devices/{device_id:int}")
async def update_device_route(device_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id, device_uuid, output_id FROM devices WHERE id = ?", (device_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Apparaat niet gevonden")
    device_uuid, old_output_id = existing[1], existing[2]
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name mag niet leeg zijn")
    output_id = body.get("output_id")
    db.execute("UPDATE devices SET name = ?, output_id = ? WHERE id = ?", (name, output_id, device_id))
    db.commit()
    if output_id != old_output_id:
        request.app.state.bridge.publish_device_assignment(device_uuid, output_id)
    row = db.execute(f"SELECT {_DEVICE_COLUMNS} FROM devices WHERE id = ?", (device_id,)).fetchone()
    return _row_to_device(row)


@router.delete("/api/devices/{device_id:int}")
def delete_device_route(device_id: int, request: Request):
    db = request.app.state.db
    existing = db.execute("SELECT id FROM devices WHERE id = ?", (device_id,)).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Apparaat niet gevonden")
    db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    db.commit()
    return {"ok": True}
