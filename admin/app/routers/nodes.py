from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/nodes")
def get_nodes(request: Request):
    return request.app.state.tracker.get_nodes()


@router.get("/api/logs")
def get_logs(request: Request, node: str | None = None, limit: int = 100):
    return request.app.state.tracker.get_recent_logs(node=node, limit=limit)
