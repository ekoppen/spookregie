import os
import time
import threading

import cv2
import paho.mqtt.client as mqtt

from shared.mqtt_contract import TOPIC_MIRROR_TRIGGERED, TOPIC_SYSTEM_SLEEP, trigger_payload
from shared.logging_setup import setup_logging
from mirror_node.trigger import FrameDiffTrigger
from mirror_node.effect import ghost_effect

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
CAMERA_INDEX = int(os.environ.get("MIRROR_CAMERA_INDEX", "0"))
ACTIVE_SECONDS = float(os.environ.get("MIRROR_ACTIVE_SECONDS", "6"))
LOG_DIR = os.environ.get("LOG_DIR", "/var/log/halloween")

sleeping = threading.Event()


def on_connect(client, userdata, flags, rc):
    client.subscribe(TOPIC_SYSTEM_SLEEP)


def on_message(client, userdata, msg):
    if msg.topic == TOPIC_SYSTEM_SLEEP:
        if msg.payload.decode() == "on":
            sleeping.set()
        else:
            sleeping.clear()


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    client = mqtt.Client(client_id="mirror-node")
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec).
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    logger = setup_logging("mirror", LOG_DIR, mqtt_client=client)

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
