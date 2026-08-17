import json
from fastapi import APIRouter, Request

router = APIRouter()

_DEFAULT_MIRROR_CONFIG = {"effect": "xray", "params": {}, "overlay_hash": None, "scale": 1.0, "position": [0.5, 0.5]}


@router.get("/api/mirror/config")
def get_mirror_config(request: Request):
    row = request.app.state.db.execute(
        "SELECT effect, params, overlay_hash, scale, position FROM mirror_config WHERE id = 1"
    ).fetchone()
    if row is None:
        return _DEFAULT_MIRROR_CONFIG
    return {
        "effect": row[0],
        "params": json.loads(row[1]),
        "overlay_hash": row[2],
        "scale": row[3],
        "position": json.loads(row[4]),
    }


@router.put("/api/mirror/config")
async def put_mirror_config(request: Request):
    body = await request.json()
    # Defaults één keer toepassen, daarna dezelfde dict voor de DB-write én de
    # publish — zo kunnen opgeslagen en gepubliceerde config niet uit elkaar
    # lopen bij een gedeeltelijke payload.
    config = {k: body.get(k, v) for k, v in _DEFAULT_MIRROR_CONFIG.items()}
    db = request.app.state.db
    db.execute(
        """INSERT INTO mirror_config (id, effect, params, overlay_hash, scale, position)
           VALUES (1, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET effect=excluded.effect, params=excluded.params,
             overlay_hash=excluded.overlay_hash, scale=excluded.scale, position=excluded.position""",
        (
            config["effect"],
            json.dumps(config["params"]),
            config["overlay_hash"],
            config["scale"],
            json.dumps(config["position"]),
        ),
    )
    db.commit()
    request.app.state.bridge.publish_mirror_config(config)
    return {"ok": True}


@router.post("/api/mirror/preview")
async def post_mirror_preview(request: Request):
    config = await request.json()
    request.app.state.bridge.publish_mirror_preview(config)
    return {"ok": True}


@router.post("/api/mirror/test")
def post_mirror_test(request: Request):
    request.app.state.bridge.publish_mirror_test()
    return {"ok": True}
