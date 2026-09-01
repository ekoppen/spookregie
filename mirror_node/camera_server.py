import os
import time

from mirror_node.camera import open_camera
from mirror_node.stream import MJPEGStreamer
from shared.logging_setup import setup_logging

CAMERA_SOURCE = os.environ.get("CAMERA_SOURCE", "")
CAMERA_SERVER_PORT = int(os.environ.get("CAMERA_SERVER_PORT", "8080"))
LOG_DIR = os.environ.get("LOG_DIR", "./logs")
MAX_FAILURES_BEFORE_REOPEN = 30  # ~2s bij 1/15s sleep tussen mislukte reads


def read_frame_with_reopen(cap, source, consecutive_failures, logger, max_failures=MAX_FAILURES_BEFORE_REOPEN):
    """Eén cyclus: leest een frame van `cap`. Bij een mislukte read wordt de
    faalteller verhoogd; bij `max_failures` op rij wordt de capture heropend
    (nieuwe open_camera(source)) en de teller gereset. Puur genoeg om zonder
    een echte camera te testen -- cap is elk object met .read()/.release().
    Retourneert (frame-of-None, mogelijk-nieuwe cap, nieuwe consecutive_failures)."""
    ok, frame = cap.read()
    if ok:
        return frame, cap, 0
    consecutive_failures += 1
    if consecutive_failures >= max_failures:
        logger.warning("camera levert al %s keer geen frame, capture wordt heropend", consecutive_failures)
        cap.release()
        return None, open_camera(source), 0
    return None, cap, consecutive_failures


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = setup_logging("camera-server", LOG_DIR)
    cap = open_camera(CAMERA_SOURCE)
    streamer = MJPEGStreamer(CAMERA_SERVER_PORT)
    streamer.start()
    logger.info("camera-server gestart op poort %s (bron=%r)", CAMERA_SERVER_PORT, CAMERA_SOURCE)
    consecutive_failures = 0
    try:
        while True:
            frame, cap, consecutive_failures = read_frame_with_reopen(cap, CAMERA_SOURCE, consecutive_failures, logger)
            if frame is not None:
                streamer.publish_frame(frame)
            time.sleep(1 / 15)
    finally:
        streamer.stop()
        cap.release()


if __name__ == "__main__":
    main()
