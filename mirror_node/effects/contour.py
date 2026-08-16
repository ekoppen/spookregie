import cv2


def contour(frame_bgr, params):
    """params: {"threshold1": int standaard 50, "threshold2": int standaard 150}."""
    threshold1 = int(params.get("threshold1", 50))
    threshold2 = int(params.get("threshold2", 150))
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, threshold1, threshold2)
    return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
