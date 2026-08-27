from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/api/mirror-node/start")
def post_mirror_node_start(request: Request):
    return request.app.state.mirror_process.start()


@router.post("/api/mirror-node/stop")
def post_mirror_node_stop(request: Request):
    return request.app.state.mirror_process.stop()


@router.get("/api/mirror-node/status")
def get_mirror_node_status(request: Request):
    return request.app.state.mirror_process.status()
