import json
import re

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

# Zones worden in een MQTT-topic gezet; wildcards (#, +) zijn daar een
# protocolfout waar de broker de verbinding op verbreekt.
_ZONE_RE = re.compile(r"^[a-z0-9-]+$")


def _check_zone(zone):
    if not _ZONE_RE.match(zone):
        raise HTTPException(status_code=400, detail="ongeldige zone-naam")


@router.get("/api/scare/{zone}/config")
def get_scare_config(zone: str, request: Request):
    _check_zone(zone)
    row = request.app.state.db.execute(
        "SELECT enabled_hashes FROM scare_zone_config WHERE zone = ?", (zone,)
    ).fetchone()
    if row is None:
        return {"enabled_hashes": []}
    return {"enabled_hashes": json.loads(row[0])}


@router.put("/api/scare/{zone}/config")
async def put_scare_config(zone: str, request: Request):
    _check_zone(zone)
    body = await request.json()
    # Eén genormaliseerde waarde voor zowel de DB-write als de publish, zodat
    # opgeslagen en gepubliceerde config nooit uit elkaar kunnen lopen.
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
    _check_zone(zone)
    request.app.state.bridge.publish_scare_test(zone)
    return {"ok": True}
