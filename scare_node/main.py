import os
import random
import subprocess
import threading

import paho.mqtt.client as mqtt
from gpiozero import MotionSensor

from shared.mqtt_contract import (
    TOPIC_MIRROR_TRIGGERED,
    TOPIC_SYSTEM_SLEEP,
    scare_topic,
    trigger_payload,
)
from shared.logging_setup import setup_logging
from scare_node.playback import pick_audio_file
from scare_node.debounce import Cooldown

ZONE = os.environ.get("SCARE_ZONE", "zone-a")
MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MEDIA_DIR = os.environ.get("SCARE_MEDIA_DIR", "/opt/halloween/media")
PIR_PIN = int(os.environ.get("SCARE_PIR_PIN", "4"))
COOLDOWN_SECONDS = float(os.environ.get("SCARE_COOLDOWN_SECONDS", "12"))
LOG_DIR = os.environ.get("LOG_DIR", "/var/log/halloween")

sleeping = threading.Event()
cooldown = Cooldown(COOLDOWN_SECONDS)


def play_scare(logger):
    if not cooldown.ready():
        return
    try:
        audio_file = pick_audio_file(MEDIA_DIR)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return
    logger.info("speelt %s af", audio_file)
    subprocess.run(["aplay", audio_file], check=False)


def make_on_message(logger):
    def on_message(client, userdata, msg):
        if msg.topic == TOPIC_SYSTEM_SLEEP:
            if msg.payload.decode() == "on":
                sleeping.set()
            else:
                sleeping.clear()
            return
        if msg.topic == TOPIC_MIRROR_TRIGGERED and not sleeping.is_set():
            delay = random.uniform(0, 2)
            threading.Timer(delay, play_scare, args=(logger,)).start()
    return on_message


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    def on_connect(client, userdata, flags, rc):
        client.subscribe(TOPIC_MIRROR_TRIGGERED)
        client.subscribe(TOPIC_SYSTEM_SLEEP)

    client = mqtt.Client(client_id=f"scare-node-{ZONE}")
    client.on_connect = on_connect
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec).
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    logger = setup_logging(f"scare-{ZONE}", LOG_DIR, mqtt_client=client)
    client.on_message = make_on_message(logger)

    pir = MotionSensor(PIR_PIN)

    def on_motion():
        if sleeping.is_set():
            return
        play_scare(logger)
        client.publish(scare_topic(ZONE), trigger_payload())

    pir.when_motion = on_motion

    logger.info("scare-node %s gestart op pin %s", ZONE, PIR_PIN)
    threading.Event().wait()  # blokkeert voor altijd


if __name__ == "__main__":
    main()
