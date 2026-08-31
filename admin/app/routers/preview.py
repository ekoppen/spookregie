import cv2
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from mirror_node.camera import open_camera
from mirror_node.effects import get_effect
from mirror_node.overlay import composite_overlay, place_on_canvas
from admin.app.media import get_media_path
from admin.app.routers.players import _resolve_source_id

router = APIRouter()


def _render_preview_frame(draft, db, media_dir):
    """Blocking body van preview_frame_route -- draait in een threadpool
    (via run_in_threadpool) zodat een tragere/haperende camera niet de
    hele event loop, en dus elke andere admin-request, blokkeert."""
    source_id = _resolve_source_id(db, draft.get("source_id"))
    source_row = db.execute(
        "SELECT value FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if source_row is None:
        raise HTTPException(status_code=400, detail="source_id verwijst naar een onbestaande source")
    camera_source = source_row[0]

    cap = open_camera(camera_source)
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise HTTPException(status_code=502, detail="Kon geen frame van de camera-bron ophalen")

    try:
        effect_fn = get_effect(draft.get("effect", "xray"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Onbekend effect: {draft.get('effect')!r}")
    result = effect_fn(frame, draft.get("params", {}))

    canvas_size = draft.get("canvas_size")
    if canvas_size:
        result = place_on_canvas(
            result, tuple(canvas_size),
            scale=draft.get("source_scale", 1.0),
            position=tuple(draft.get("source_position", [0.5, 0.5])),
        )

    overlay_hash = draft.get("overlay_hash")
    if overlay_hash:
        overlay_path = get_media_path(media_dir, overlay_hash)
        overlay_img = cv2.imread(overlay_path, cv2.IMREAD_UNCHANGED) if overlay_path else None
        if overlay_img is not None and overlay_img.ndim == 3 and overlay_img.shape[2] == 4:
            result = composite_overlay(
                result, overlay_img,
                scale=draft.get("scale", 1.0),
                position=tuple(draft.get("position", [0.5, 0.5])),
            )

    ok, buf = cv2.imencode(".jpg", result)
    if not ok:
        raise HTTPException(status_code=500, detail="Kon voorbeeld niet coderen")
    return buf.tobytes()


@router.post("/api/scenes/preview-frame")
async def preview_frame_route(request: Request):
    """Rendert één losstaand voorbeeldbeeld voor de concept-scene in
    `draft` -- zonder de fysieke spiegel/mirror-node aan te raken. Haalt
    zelf één camera-frame op van de gekozen output en past dezelfde
    effect-/overlay-code toe als de mirror-node. De eigenlijke camera-/
    beeldbewerking draait via run_in_threadpool: dat is blokkerende I/O
    (cap.read() kan seconden duren op een haperende camera) en zou anders
    de hele event loop -- dus elk ander admin-verzoek -- laten wachten."""
    draft = await request.json()
    jpeg_bytes = await run_in_threadpool(
        _render_preview_frame, draft, request.app.state.db, request.app.state.settings.media_dir
    )
    return Response(content=jpeg_bytes, media_type="image/jpeg")
