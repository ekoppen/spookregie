from fastapi import APIRouter, Request

from admin.app.ha_client import get_states, call_service

router = APIRouter()


@router.get("/api/ha/states")
def ha_states(request: Request):
    settings = request.app.state.settings
    return get_states(settings.ha_url, settings.ha_token)


@router.post("/api/ha/service")
async def ha_service(request: Request):
    body = await request.json()
    settings = request.app.state.settings
    call_service(settings.ha_url, settings.ha_token, body["domain"], body["service"], body.get("data", {}))
    return {"ok": True}
