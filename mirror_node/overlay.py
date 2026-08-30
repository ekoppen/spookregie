import cv2
import numpy as np


def composite_overlay(frame_bgr, overlay_bgra, scale=1.0, position=(0.5, 0.5)):
    """Legt `overlay_bgra` (met alphakanaal) over `frame_bgr` heen.
    `scale` schaalt de overlay t.o.v. zijn eigen afmetingen; `position`
    is het middelpunt van de overlay als fractie (x, y) van het frame
    (0.0-1.0). Geeft een nieuw frame terug, wijzigt de input niet."""
    frame_h, frame_w = frame_bgr.shape[:2]
    ov_h, ov_w = overlay_bgra.shape[:2]

    new_w = max(1, int(ov_w * scale))
    new_h = max(1, int(ov_h * scale))
    resized = cv2.resize(overlay_bgra, (new_w, new_h))

    center_x = int(position[0] * frame_w)
    center_y = int(position[1] * frame_h)
    x0 = center_x - new_w // 2
    y0 = center_y - new_h // 2

    result = frame_bgr.copy()

    src_x0, src_y0 = max(0, -x0), max(0, -y0)
    dst_x0, dst_y0 = max(0, x0), max(0, y0)
    dst_x1 = min(frame_w, x0 + new_w)
    dst_y1 = min(frame_h, y0 + new_h)
    if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
        return result  # overlay valt volledig buiten het frame

    src_x1 = src_x0 + (dst_x1 - dst_x0)
    src_y1 = src_y0 + (dst_y1 - dst_y0)

    overlay_region = resized[src_y0:src_y1, src_x0:src_x1]
    alpha = overlay_region[:, :, 3:4].astype(np.float32) / 255.0
    overlay_rgb = overlay_region[:, :, :3].astype(np.float32)

    dst_region = result[dst_y0:dst_y1, dst_x0:dst_x1].astype(np.float32)
    blended = overlay_rgb * alpha + dst_region * (1 - alpha)
    result[dst_y0:dst_y1, dst_x0:dst_x1] = blended.astype(np.uint8)

    return result


def place_on_canvas(frame_bgr, canvas_size, scale=1.0, position=(0.5, 0.5)):
    """Plaatst `frame_bgr` geschaald op een zwart canvas van `canvas_size`
    (breedte, hoogte). Zelfde plaatsingswiskunde als `composite_overlay`,
    maar zonder alphakanaal -- het frame is altijd ondoorzichtig, delen van
    het canvas die niet bedekt worden blijven zwart (letterbox)."""
    canvas_w, canvas_h = canvas_size
    frame_h, frame_w = frame_bgr.shape[:2]

    new_w = max(1, int(frame_w * scale))
    new_h = max(1, int(frame_h * scale))
    resized = cv2.resize(frame_bgr, (new_w, new_h))

    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=frame_bgr.dtype)

    center_x = int(position[0] * canvas_w)
    center_y = int(position[1] * canvas_h)
    x0 = center_x - new_w // 2
    y0 = center_y - new_h // 2

    src_x0, src_y0 = max(0, -x0), max(0, -y0)
    dst_x0, dst_y0 = max(0, x0), max(0, y0)
    dst_x1 = min(canvas_w, x0 + new_w)
    dst_y1 = min(canvas_h, y0 + new_h)
    if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
        return canvas  # frame valt volledig buiten het canvas

    src_x1 = src_x0 + (dst_x1 - dst_x0)
    src_y1 = src_y0 + (dst_y1 - dst_y0)

    canvas[dst_y0:dst_y1, dst_x0:dst_x1] = resized[src_y0:src_y1, src_x0:src_x1]
    return canvas
