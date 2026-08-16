import json
import os
import re
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
    TOPIC_CONFIG_MIRROR,
    TOPIC_CONTROL_MIRROR_PREVIEW,
    TOPIC_CONTROL_MIRROR_TEST,
    status_topic,
    trigger_payload,
)
from shared.logging_setup import setup_logging
from shared.media_sync import sync_media
from mirror_node.trigger import FrameDiffTrigger
from mirror_node.effects import get_effect
from mirror_node.overlay import composite_overlay
from mirror_node.active_config import ActiveMirrorConfig
from mirror_node.stream import MJPEGStreamer

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
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
MEDIA_CACHE_DIR = os.environ.get("MIRROR_MEDIA_CACHE_DIR", "./media_cache")
STREAM_PORT = int(os.environ.get("MIRROR_STREAM_PORT", "8091"))

sleeping = threading.Event()
# Handmatige test-trigger vanaf de beheerpagina; de camera-loop leest en wist
# hem. Event i.p.v. een bool zodat het thread-safe is, net als `sleeping`.
test_trigger_requested = threading.Event()
active_config = ActiveMirrorConfig()

# ponytail: same hash format sync_media/content_hash produce; duplicated
# locally (not imported from shared.media_sync) since it's a one-liner and
# that module's _HASH_RE is private.
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_overlay_cache = {"hash": None, "image": None}


def _sync_overlay_in_background(config):
    """Haalt het overlay-bestand bij `config["overlay_hash"]` op de achtergrond
    op. sync_media kan ~10s blokkeren; dat mag de MQTT-callbackthread niet
    ophouden (system/sleep moet altijd meteen doorkomen). De render-loop kijkt
    zelf of het bestand al bestaat en slaat de overlay tot die tijd over."""
    overlay_hash = config.get("overlay_hash")
    if not isinstance(overlay_hash, str) or not overlay_hash:
        return
    threading.Thread(
        target=sync_media,
        args=(BACKEND_URL, MEDIA_CACHE_DIR, [overlay_hash]),
        daemon=True,
    ).start()


def _apply_config_message(payload, is_preview, logger):
    try:
        config = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige config-JSON ontvangen, genegeerd")
        return
    if not isinstance(config, dict):
        logger.error("Config-JSON is geen object, genegeerd: %r", config)
        return
    if is_preview:
        active_config.set_preview(config)
        _sync_overlay_in_background(config)
        return
    active_config.set_persistent(config)
    _sync_overlay_in_background(config)


def make_on_message(logger):
    def on_message(client, userdata, msg):
        # Vangnet: een exception hier zou paho's netwerkthread killen — de node
        # blijft dan renderen maar reageert nergens meer op, ook niet op
        # system/sleep (de noodstop). Alles loggen en doorgaan dus.
        try:
            if msg.topic == TOPIC_SYSTEM_SLEEP:
                if msg.payload.decode() == SLEEP_PAYLOAD_ON:
                    sleeping.set()
                else:
                    sleeping.clear()
                return
            if msg.topic == TOPIC_CONFIG_MIRROR:
                _apply_config_message(msg.payload.decode(), is_preview=False, logger=logger)
                return
            if msg.topic == TOPIC_CONTROL_MIRROR_PREVIEW:
                _apply_config_message(msg.payload.decode(), is_preview=True, logger=logger)
                return
            if msg.topic == TOPIC_CONTROL_MIRROR_TEST:
                test_trigger_requested.set()
        except Exception as exc:
            logger.error("Fout bij verwerken MQTT-bericht op topic %s: %s", msg.topic, exc)
    return on_message


def _load_overlay(overlay_hash, logger):
    """Geeft het gedecodeerde overlay-beeld voor `overlay_hash` terug, uit
    cache als de hash ongewijzigd is (voorkomt herlezen/decoden vanaf schijf
    op elk frame). Valideert het hash-formaat zelf — dit is config uit MQTT,
    dus niet vertrouwd genoeg om direct als padonderdeel te gebruiken."""
    if not _HASH_RE.match(overlay_hash):
        logger.error("Ongeldige overlay-hash genegeerd: %s", overlay_hash)
        return None
    if _overlay_cache["hash"] != overlay_hash:
        overlay_path = os.path.join(MEDIA_CACHE_DIR, overlay_hash)
        if not os.path.exists(overlay_path):
            return None
        _overlay_cache["hash"] = overlay_hash
        _overlay_cache["image"] = cv2.imread(overlay_path, cv2.IMREAD_UNCHANGED)
    return _overlay_cache["image"]


def _render(frame, logger):
    config = active_config.get()
    try:
        effect_fn = get_effect(config.get("effect", "xray"))
    except ValueError:
        logger.error("Onbekend effect in actieve config: %s", config.get("effect"))
        return frame

    result = effect_fn(frame, config.get("params", {}))

    overlay_hash = config.get("overlay_hash")
    if overlay_hash:
        overlay_img = _load_overlay(overlay_hash, logger)
        if overlay_img is not None and overlay_img.ndim == 3 and overlay_img.shape[2] == 4:
            position = config.get("position", [0.5, 0.5])
            if len(position) != 2:
                logger.warning("Ongeldige position in config, val terug op (0.5, 0.5): %r", position)
                position = (0.5, 0.5)
            result = composite_overlay(
                result,
                overlay_img,
                scale=config.get("scale", 1.0),
                position=tuple(position),
            )
    return result


def selfcheck():
    """Pakt één frame, draait het door het standaard xray-effect en
    laat/bewaart het resultaat. Heeft geen MQTT nodig."""
    cap = cv2.VideoCapture(CAMERA_INDEX)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print(f"selfcheck MISLUKT: geen frame van camera index {CAMERA_INDEX}")
        sys.exit(1)

    ghost = get_effect("xray")(frame, {})
    path = os.path.join(tempfile.gettempdir(), "mirror-selfcheck.png")
    cv2.imwrite(path, ghost)
    print(f"selfcheck OK: xray-frame opgeslagen als {path}")

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
    os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)

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
        client.subscribe(TOPIC_CONFIG_MIRROR)
        client.subscribe(TOPIC_CONTROL_MIRROR_PREVIEW)
        client.subscribe(TOPIC_CONTROL_MIRROR_TEST)

    def on_disconnect(client, userdata, rc):
        logger.warning("MQTT verbinding verbroken (rc=%s)", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = make_on_message(logger)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # Last-will: broker publiceert "offline" als deze node wegvalt.
    client.will_set(status_topic(NODE_NAME), payload="offline", retain=True)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec).
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    streamer = MJPEGStreamer(STREAM_PORT)
    streamer.start()
    logger.info("MJPEG-stream op poort %s (/stream)", STREAM_PORT)

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

            # Handmatige test vanaf de beheerpagina: wel het effect tonen, maar
            # bewust géén mirror/triggered publiceren — dat topic betekent
            # "echte beweging gezien" en laat de scare-nodes meedoen.
            if test_trigger_requested.is_set():
                test_trigger_requested.clear()
                active_until = now + ACTIVE_SECONDS
                logger.info("mirror test-trigger")

            if now < active_until:
                try:
                    rendered = _render(frame, logger)
                except Exception as exc:
                    # Val terug op het rauwe beeld: een kapotte config mag de
                    # camera-loop nooit onderuit halen (fail-safe eis).
                    logger.error("Fout bij renderen: %s", exc)
                    rendered = frame
            else:
                rendered = frame * 0
            streamer.publish_frame(rendered)
            cv2.imshow("mirror", rendered)
            cv2.waitKey(1)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        streamer.stop()
        client.loop_stop()


if __name__ == "__main__":
    main()
