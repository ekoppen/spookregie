import os
import sys
import tempfile
import time
import threading

import cv2
import paho.mqtt.client as mqtt

from shared.mqtt_contract import (
    SLEEP_PAYLOAD_ON,
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    status_topic,
    trigger_payload,
)
from shared.logging_setup import setup_logging
from mirror_node.trigger import FrameDiffTrigger
from mirror_node.effect import ghost_effect

NODE_NAME = "mirror"

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
# Optioneel: brokers zonder authenticatie laten MQTT_USER leeg.
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
CAMERA_INDEX = int(os.environ.get("MIRROR_CAMERA_INDEX", "0"))
ACTIVE_SECONDS = float(os.environ.get("MIRROR_ACTIVE_SECONDS", "6"))
# Default schrijfbaar voor een gewone gebruiker die het script direct start;
# systemd zet LOG_DIR expliciet op /var/log/halloween.
LOG_DIR = os.environ.get("LOG_DIR", "./logs")

sleeping = threading.Event()


def on_message(client, userdata, msg):
    if msg.topic == TOPIC_SYSTEM_SLEEP:
        if msg.payload.decode() == SLEEP_PAYLOAD_ON:
            sleeping.set()
        else:
            sleeping.clear()


def selfcheck():
    """Pakt één frame, draait het door ghost_effect en laat/bewaart het
    resultaat. Heeft geen MQTT nodig."""
    cap = cv2.VideoCapture(CAMERA_INDEX)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print(f"selfcheck MISLUKT: geen frame van camera index {CAMERA_INDEX}")
        sys.exit(1)

    ghost = ghost_effect(frame)
    path = os.path.join(tempfile.gettempdir(), "mirror-selfcheck.png")
    cv2.imwrite(path, ghost)
    print(f"selfcheck OK: ghost-frame opgeslagen als {path}")

    try:
        cv2.imshow("mirror-selfcheck", ghost)
        cv2.waitKey(2000)
        cv2.destroyAllWindows()
    except cv2.error as exc:
        print(f"(geen display beschikbaar: {exc})")


def main():
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    os.makedirs(LOG_DIR, exist_ok=True)

    client = mqtt.Client(client_id="mirror-node")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    # setup_logging vóór de callbacks: die loggen naar het lokale bestand,
    # wat ook werkt als de broker onbereikbaar is.
    logger = setup_logging(NODE_NAME, LOG_DIR, mqtt_client=client)

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT verbonden met %s:%s", MQTT_HOST, MQTT_PORT)
        else:
            logger.error("MQTT verbinden mislukt (rc=%s)", rc)
            return
        client.publish(status_topic(NODE_NAME), "online", retain=True)
        client.subscribe(TOPIC_SYSTEM_SLEEP)

    def on_disconnect(client, userdata, rc):
        logger.warning("MQTT verbinding verbroken (rc=%s)", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # Last-will: broker publiceert "offline" als deze node wegvalt.
    client.will_set(status_topic(NODE_NAME), payload="offline", retain=True)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec).
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        logger.error("Kon camera index %s niet openen", CAMERA_INDEX)
        return

    trigger = FrameDiffTrigger()
    cv2.namedWindow("mirror", cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty("mirror", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    active_until = 0.0
    logger.info("mirror-node gestart")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                logger.warning("Kon geen frame lezen van camera")
                time.sleep(0.5)
                continue

            if sleeping.is_set():
                cv2.imshow("mirror", frame * 0)
                cv2.waitKey(1)
                time.sleep(0.2)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            now = time.time()

            if trigger.detect(gray) and now > active_until:
                active_until = now + ACTIVE_SECONDS
                client.publish(TOPIC_MIRROR_TRIGGERED, trigger_payload())
                logger.info("mirror triggered")

            cv2.imshow("mirror", ghost_effect(frame) if now < active_until else frame * 0)
            cv2.waitKey(1)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        client.loop_stop()


if __name__ == "__main__":
    main()
