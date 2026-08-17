import json
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/scare/{zone}/config")
def get_scare_config(zone: str, request: Request):
    row = request.app.state.db.execute(
        "SELECT enabled_hashes FROM scare_zone_config WHERE zone = ?", (zone,)
    ).fetchone()
    if row is None:
        return {"enabled_hashes": []}
    return {"enabled_hashes": json.loads(row[0])}


@router.put("/api/scare/{zone}/config")
async def put_scare_config(zone: str, request: Request):
    body = await request.json()
    enabled_hashes = body.get("enabled_hashes", [])
    db = request.app.state.db
    db.execute(
        """INSERT INTO scare_zone_config (zone, enabled_hashes) VALUES (?, ?)
           ON CONFLICT(zone) DO UPDATE SET enabled_hashes=excluded.enabled_hashes""",
        (zone, json.dumps(enabled_hashes)),
    )
    db.commit()
    request.app.state.bridge.publish_scare_config(zone, enabled_hashes)
    return {"ok": True}


@router.post("/api/scare/{zone}/test")
def post_scare_test(zone: str, request: Request):
    request.app.state.bridge.publish_scare_test(zone)
    return {"ok": True}
