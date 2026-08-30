import json

from fastapi import APIRouter, Request

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
    request.app.state.bridge.publish_mirror_scare_video_config(enabled_hashes)
    return {"ok": True}
