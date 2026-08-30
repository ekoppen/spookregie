from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/api/mirror/test")
def post_mirror_test(request: Request):
    request.app.state.bridge.publish_mirror_test()
    return {"ok": True}
