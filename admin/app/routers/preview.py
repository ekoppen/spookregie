import cv2
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from mirror_node.camera import open_camera
from mirror_node.effects import get_effect
from mirror_node.overlay import composite_overlay, place_on_canvas
from admin.app.media import get_media_path

router = APIRouter()


@router.post("/api/scenes/preview-frame")
async def preview_frame_route(request: Request):
    """Rendert één losstaand voorbeeldbeeld voor de concept-scene in
    `draft` -- zonder de fysieke spiegel/mirror-node aan te raken. Haalt
    zelf één camera-frame op van de gekozen output en past dezelfde
    effect-/overlay-code toe als de mirror-node."""
    draft = await request.json()
    db = request.app.state.db
    output_row = db.execute(
        "SELECT camera_source FROM outputs WHERE id = ?", (draft.get("output_id"),)
    ).fetchone()
    if output_row is None:
        raise HTTPException(status_code=400, detail="output_id verwijst naar een onbestaande output")
    camera_source = output_row[0]

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
        overlay_path = get_media_path(request.app.state.settings.media_dir, overlay_hash)
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
    return Response(content=buf.tobytes(), media_type="image/jpeg")
