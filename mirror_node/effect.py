import cv2


def ghost_effect(frame_bgr):
    """Startpunt-effect: grijswaarden + geïnverteerd + zachte blur, voor een
    x-ray/spookachtige look. Puur een `(frame_bgr) -> frame_bgr`-transform,
    dus tijdens het testen op locatie vrij te vervangen/aan te passen zonder
    de rest van de mirror-node te raken.
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    inverted = cv2.bitwise_not(gray)
    blurred = cv2.GaussianBlur(inverted, (9, 9), 0)
    return cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR)
