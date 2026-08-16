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
