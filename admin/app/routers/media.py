from fastapi import APIRouter, Request, UploadFile, Form, Response

from admin.app.media import save_media, get_media_path, list_media, delete_media

router = APIRouter()


@router.post("/api/media")
async def upload_media(request: Request, file: UploadFile, category: str = Form(...)):
    data = await file.read()
    h = save_media(request.app.state.db, request.app.state.settings.media_dir, data, file.filename, category)
    return {"hash": h, "filename": file.filename, "category": category}


@router.get("/api/media")
def list_media_route(request: Request, category: str | None = None):
    return list_media(request.app.state.db, category=category)


@router.get("/api/media/{hash_}")
def download_media(hash_: str, request: Request):
    path = get_media_path(request.app.state.settings.media_dir, hash_)
    if path is None:
        return Response(status_code=404)
    with open(path, "rb") as f:
        data = f.read()
    return Response(content=data, media_type="application/octet-stream")


@router.delete("/api/media/{hash_}")
def delete_media_route(hash_: str, request: Request):
    deleted = delete_media(request.app.state.db, request.app.state.settings.media_dir, hash_)
    return {"deleted": deleted}
