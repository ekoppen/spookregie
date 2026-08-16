import cv2


def thermal(frame_bgr, params):
    """params: {"intensity": float 0.0-1.0, standaard 1.0}."""
    intensity = float(params.get("intensity", 1.0))
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    colored = cv2.applyColorMap(gray, cv2.COLORMAP_JET)
    if intensity >= 1.0:
        return colored
    base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return cv2.addWeighted(colored, intensity, base, 1 - intensity, 0)
