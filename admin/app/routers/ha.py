from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from admin.app.ha_client import (
    CAMERA_ENTITY_RE,
    get_states,
    call_service,
    open_camera_stream,
    sign_camera_entity,
    verify_camera_entity_signature,
)

router = APIRouter()


def _iter_camera_stream(resp, chunk_size=8192):
    try:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        resp.close()


@router.get("/api/ha/states")
def ha_states(request: Request):
    settings = request.app.state.runtime_settings
    return get_states(settings.ha_url, settings.ha_token)


@router.post("/api/ha/service")
async def ha_service(request: Request):
    body = await request.json()
    settings = request.app.state.runtime_settings
    try:
        call_service(settings.ha_url, settings.ha_token, body["domain"], body["service"], body.get("data", {}))
    except Exception:
        raise HTTPException(status_code=502, detail="Home Assistant onbereikbaar")
    return {"ok": True}


@router.get("/api/ha/camera-stream-url/{entity_id}")
def ha_camera_stream_url(entity_id: str, request: Request):
    """Ingelogde-sessie-vereisend (normale auth-middleware): geeft de
    ondertekende, publiek-opvraagbare URL terug voor ha_camera_stream
    hieronder. De sessie zorgt dat alleen de beheerder deze URL kan
    aanmaken; de signature zorgt dat een buitenstaander 'm niet kan raden
    zodra hij bestaat (nodig omdat mirror-node zelf geen sessie heeft)."""
    if not CAMERA_ENTITY_RE.match(entity_id):
        raise HTTPException(status_code=400, detail="Ongeldige camera entity_id")
    secret = request.app.state.settings.admin_password
    sig = sign_camera_entity(secret, entity_id)
    return {"url": f"/api/ha/camera-stream/{entity_id}?sig={sig}"}


@router.get("/api/ha/camera-stream/{entity_id}")
def ha_camera_stream(entity_id: str, request: Request):
    """Publiek pad (geen sessie nodig, zie main.py) dat HA's eigen
    camera_proxy_stream doorstreamt -- mirror-node opent dit rechtstreeks
    als camera-URL (cv2.VideoCapture), net zoals een RTSP-URL. Vereist
    wel een geldige ?sig= (zie ha_camera_stream_url hierboven), anders
    zou elke camera-entiteit zonder enige credential te raden zijn."""
    if not CAMERA_ENTITY_RE.match(entity_id):
        raise HTTPException(status_code=400, detail="Ongeldige camera entity_id")
    secret = request.app.state.settings.admin_password
    if not verify_camera_entity_signature(secret, entity_id, request.query_params.get("sig", "")):
        raise HTTPException(status_code=403, detail="Ongeldige of ontbrekende signature")
    settings = request.app.state.runtime_settings
    try:
        resp = open_camera_stream(settings.ha_url, settings.ha_token, entity_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Home Assistant camera-stream onbereikbaar")
    content_type = resp.headers.get("Content-Type", "multipart/x-mixed-replace")
    return StreamingResponse(_iter_camera_stream(resp), media_type=content_type)
