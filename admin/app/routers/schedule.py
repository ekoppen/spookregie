import re

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

_DEFAULT_SCHEDULE = {"on_time": "18:00", "off_time": "22:00", "enabled": True}
# Strikt HH:MM — een andere vorm laat should_be_sleeping's unpack crashen in de
# scheduler-thread.
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def read_schedule(conn):
    """Enige plek waar het schema uit de DB gelezen wordt (met defaults als er
    nog geen rij is) — zowel de HTTP-route als de scheduler gebruikt dit."""
    row = conn.execute(
        "SELECT on_time, off_time, enabled FROM schedule WHERE id = 1"
    ).fetchone()
    if row is None:
        return dict(_DEFAULT_SCHEDULE)
    return {"on_time": row[0], "off_time": row[1], "enabled": bool(row[2])}


@router.get("/api/schedule")
def get_schedule(request: Request):
    return read_schedule(request.app.state.db)


@router.put("/api/schedule")
async def put_schedule(request: Request):
    body = await request.json()
    on_time = body.get("on_time", _DEFAULT_SCHEDULE["on_time"])
    off_time = body.get("off_time", _DEFAULT_SCHEDULE["off_time"])
    if not _TIME_RE.match(str(on_time)) or not _TIME_RE.match(str(off_time)):
        raise HTTPException(status_code=400, detail="tijd moet HH:MM zijn")
    db = request.app.state.db
    db.execute(
        """INSERT INTO schedule (id, on_time, off_time, enabled) VALUES (1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET on_time=excluded.on_time, off_time=excluded.off_time, enabled=excluded.enabled""",
        (on_time, off_time, int(bool(body.get("enabled", True)))),
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
