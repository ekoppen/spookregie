import cv2


def xray(frame_bgr, params):
    """params: {"intensity": float 0.0-1.0, standaard 1.0}."""
    intensity = float(params.get("intensity", 1.0))
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    inverted = cv2.bitwise_not(gray)
    blurred = cv2.GaussianBlur(inverted, (9, 9), 0)
    effect = cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR)
    if intensity >= 1.0:
        return effect
    base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return cv2.addWeighted(effect, intensity, base, 1 - intensity, 0)
