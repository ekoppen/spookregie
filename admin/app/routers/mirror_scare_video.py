import json
from datetime import datetime

from fastapi import APIRouter, Request

from admin.app.escalation import current_tier, filter_by_tier, read_escalation_time, read_intensity_by_hash

router = APIRouter()


def read_enabled_hashes(db):
    row = db.execute(
        "SELECT enabled_hashes FROM mirror_scare_video_config WHERE id = 1"
    ).fetchone()
    if row is None:
        return []
    return json.loads(row[0])


@router.get("/api/mirror/scare-video-config")
def get_mirror_scare_video_config(request: Request):
    return {"enabled_hashes": read_enabled_hashes(request.app.state.db)}


@router.put("/api/mirror/scare-video-config")
async def put_mirror_scare_video_config(request: Request):
    body = await request.json()
    enabled_hashes = body.get("enabled_hashes", [])
    db = request.app.state.db
    db.execute(
        """INSERT INTO mirror_scare_video_config (id, enabled_hashes) VALUES (1, ?)
           ON CONFLICT(id) DO UPDATE SET enabled_hashes=excluded.enabled_hashes""",
        (json.dumps(enabled_hashes),),
    )
    db.commit()
    tier = current_tier(datetime.now().strftime("%H:%M"), read_escalation_time(db))
    effective_hashes = filter_by_tier(enabled_hashes, read_intensity_by_hash(db), tier)
    request.app.state.bridge.publish_mirror_scare_video_config(effective_hashes)
    return {"ok": True}
