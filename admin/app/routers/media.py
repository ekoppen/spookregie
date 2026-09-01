from fastapi import APIRouter, HTTPException, Request, UploadFile, Form, Response

from admin.app.media import (
    save_media,
    get_media_path,
    get_media_audio_path,
    list_media,
    delete_media,
    validate_upload,
    extract_audio_if_video,
)

router = APIRouter()


@router.post("/api/media")
async def upload_media(request: Request, file: UploadFile, kind: str = Form(...)):
    data = await file.read()
    error = validate_upload(data, kind)
    if error is not None:
        raise HTTPException(status_code=400, detail=error)
    h = save_media(request.app.state.db, request.app.state.settings.media_dir, data, file.filename, kind)
    extract_audio_if_video(request.app.state.settings.media_dir, h, kind)
    return {"hash": h, "filename": file.filename, "kind": kind}


@router.get("/api/media")
def list_media_route(request: Request, kind: str | None = None):
    return list_media(request.app.state.db, kind=kind)


@router.get("/api/media/{hash_}")
def download_media(hash_: str, request: Request):
    path = get_media_path(request.app.state.settings.media_dir, hash_)
    if path is None:
        return Response(status_code=404)
    with open(path, "rb") as f:
        data = f.read()
    return Response(content=data, media_type="application/octet-stream")


@router.get("/api/media/{hash_}/audio")
def download_media_audio(hash_: str, request: Request):
    path = get_media_audio_path(request.app.state.settings.media_dir, hash_)
    if path is None:
        return Response(status_code=404)
    with open(path, "rb") as f:
        data = f.read()
    return Response(content=data, media_type="application/octet-stream")


@router.delete("/api/media/{hash_}")
def delete_media_route(hash_: str, request: Request):
    deleted = delete_media(request.app.state.db, request.app.state.settings.media_dir, hash_)
    return {"deleted": deleted}
