from fastapi import APIRouter, HTTPException, Request

from admin.app.runtime_settings import read_runtime_settings, write_runtime_settings

router = APIRouter()


def _validate_url(value, field_name):
    if value and not (value.startswith("http://") or value.startswith("https://")):
        raise HTTPException(status_code=400, detail=f"{field_name} moet leeg zijn of met http(s):// beginnen")


def _validate_topic_prefix(value):
    if "#" in value or "+" in value:
        raise HTTPException(status_code=400, detail="mqtt_topic_prefix mag geen # of + bevatten")


@router.get("/api/settings")
def get_settings_route(request: Request):
    settings = read_runtime_settings(request.app.state.db)
    return {
        "mqtt_host": settings.mqtt_host,
        "mqtt_port": settings.mqtt_port,
        "mqtt_user": settings.mqtt_user,
        "ha_url": settings.ha_url,
        "mirror_stream_url": settings.mirror_stream_url,
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mqtt_pass_set": bool(settings.mqtt_pass),
        "ha_token_set": bool(settings.ha_token),
    }


@router.put("/api/settings")
async def put_settings_route(request: Request):
    body = await request.json()

    mqtt_host = str(body.get("mqtt_host", "")).strip()
    if not mqtt_host:
        raise HTTPException(status_code=400, detail="mqtt_host mag niet leeg zijn")

    try:
        mqtt_port = int(body.get("mqtt_port"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="mqtt_port moet een getal zijn")
    if not (1 <= mqtt_port <= 65535):
        raise HTTPException(status_code=400, detail="mqtt_port moet tussen 1 en 65535 liggen")

    ha_url = str(body.get("ha_url", "")).strip()
    mirror_stream_url = str(body.get("mirror_stream_url", "")).strip()
    _validate_url(ha_url, "ha_url")
    _validate_url(mirror_stream_url, "mirror_stream_url")

    mqtt_topic_prefix = str(body.get("mqtt_topic_prefix", "")).strip()
    _validate_topic_prefix(mqtt_topic_prefix)

    updates = {
        "mqtt_host": mqtt_host,
        "mqtt_port": mqtt_port,
        "mqtt_user": str(body.get("mqtt_user", "")),
        "ha_url": ha_url,
        "mirror_stream_url": mirror_stream_url,
        "mqtt_topic_prefix": mqtt_topic_prefix,
    }
    mqtt_pass = body.get("mqtt_pass")
    if mqtt_pass:
        updates["mqtt_pass"] = mqtt_pass
    ha_token = body.get("ha_token")
    if ha_token:
        updates["ha_token"] = ha_token

    db = request.app.state.db
    new_settings = write_runtime_settings(db, **updates)
    request.app.state.runtime_settings = new_settings
    request.app.state.bridge.reconfigure(new_settings)
    request.app.state.mirror_process._settings = new_settings

    return {"ok": True}
