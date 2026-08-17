from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    hub = websocket.app.state.ws_hub
    hub.register(websocket)
    try:
        while True:
            await websocket.receive_text()  # we verwachten niets van de client, houdt de verbinding open
    except WebSocketDisconnect:
        hub.unregister(websocket)
