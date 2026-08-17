from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/schedule")
def get_schedule(request: Request):
    row = request.app.state.db.execute(
        "SELECT on_time, off_time, enabled FROM schedule WHERE id = 1"
    ).fetchone()
    if row is None:
        return {"on_time": "18:00", "off_time": "22:00", "enabled": True}
    return {"on_time": row[0], "off_time": row[1], "enabled": bool(row[2])}


@router.put("/api/schedule")
async def put_schedule(request: Request):
    body = await request.json()
    db = request.app.state.db
    db.execute(
        """INSERT INTO schedule (id, on_time, off_time, enabled) VALUES (1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET on_time=excluded.on_time, off_time=excluded.off_time, enabled=excluded.enabled""",
        (body.get("on_time", "18:00"), body.get("off_time", "22:00"), int(bool(body.get("enabled", True)))),
    )
    db.commit()
    return {"ok": True}


@router.post("/api/system/emergency-stop")
def emergency_stop(request: Request):
    request.app.state.bridge.publish_sleep(True)
    return {"ok": True}


@router.post("/api/system/wake")
def wake(request: Request):
    request.app.state.bridge.publish_sleep(False)
    return {"ok": True}
