import json
import os
import random
import subprocess
import sys
import threading
import time

import paho.mqtt.client as mqtt

from shared.mqtt_contract import SLEEP_PAYLOAD_ON, Topics, trigger_payload
from shared.topic_prefix import fetch_topic_prefix
from shared.logging_setup import setup_logging
from shared.media_sync import sync_media
from scare_node.playback import pick_audio_file
from scare_node.debounce import Cooldown

ZONE = os.environ.get("SCARE_ZONE", "zone-a")
NODE_NAME = f"scare-{ZONE}"

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
# Optioneel: brokers zonder authenticatie laten MQTT_USER leeg.
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_TOPIC_PREFIX_ENV = os.environ.get("MQTT_TOPIC_PREFIX", "")
MEDIA_DIR = os.environ.get("SCARE_MEDIA_DIR", "/opt/halloween/media")
PIR_PIN = int(os.environ.get("SCARE_PIR_PIN", "4"))
COOLDOWN_SECONDS = float(os.environ.get("SCARE_COOLDOWN_SECONDS", "12"))
# Default schrijfbaar voor een gewone gebruiker die het script direct start;
# systemd zet LOG_DIR expliciet op /var/log/halloween.
LOG_DIR = os.environ.get("LOG_DIR", "./logs")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
MEDIA_CACHE_DIR = os.environ.get("SCARE_MEDIA_CACHE_DIR", "./media_cache")

sleeping = threading.Event()
cooldown = Cooldown(COOLDOWN_SECONDS)
# None = nog nooit een configbericht gehad -> val terug op de statische
# MEDIA_DIR (werkwijze van vóór de beheerpagina). Zodra er wél config binnen is
# gekomen, is dit de dict {hash: lokaal pad} die sync_media teruggaf en is de
# backend eigenaar van de audioselectie — ook als die dict leeg is.
synced_audio = None


def _normalize_string_list(value):
    """Geeft een lijst van strings terug uit onbetrouwbare MQTT-JSON. Bij een
    verkeerd type (geen lijst, of elementen die geen string zijn) worden die
    elementen/het geheel genegeerd i.p.v. de node te laten crashen — zelfde
    fail-safe insteek als elders in dit project (media_sync valideert hashes
    zelf ook al stilzwijgend)."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def _sync_and_apply(hashes):
    """Haalt de ingeschakelde fragmenten op en zet ze daarna pas als actieve
    selectie. Draait op een achtergrondthread (sync_media blokkeert tot ~10s
    per hash en mag de MQTT-callbackthread niet ophouden). Simpele toewijzing
    aan een module-variabele is onder de GIL veilig genoeg — geen lock nodig,
    net als bij `sleeping`."""
    global synced_audio
    synced_audio = sync_media(BACKEND_URL, MEDIA_CACHE_DIR, hashes)


def _apply_scare_config(payload, logger):
    try:
        config = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige scare-config-JSON ontvangen, genegeerd")
        return
    if not isinstance(config, dict):
        logger.error("Scare-config is geen JSON-object, genegeerd")
        return
    hashes = _normalize_string_list(config.get("enabled_hashes", []))
    threading.Thread(target=_sync_and_apply, args=(hashes,), daemon=True).start()


def _pick_synced_audio(logger):
    """Kiest het af te spelen bestand. Zodra er ooit config binnen is gekomen
    bepaalt de backend de selectie (ook een lege selectie = niets afspelen);
    daarvóór draait de node op de statische mediamap."""
    if synced_audio is None:
        return pick_audio_file(MEDIA_DIR)
    if not synced_audio:
        logger.info("Geen ingeschakelde audio voor zone %s", ZONE)
        return None
    return random.choice(list(synced_audio.values()))


def play_scare(logger):
    """Speelt één willekeurig fragment af uit de ingeschakelde set (of uit de
    statische mediamap als er nog geen config binnen is). Doet zelf geen
    cooldown-check."""
    try:
        audio_file = _pick_synced_audio(logger)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return
    if audio_file is None:
        return
    logger.info("speelt %s af", audio_file)
    result = subprocess.run(["aplay", audio_file], check=False)
    if result.returncode != 0:
        logger.error("aplay faalde (returncode=%s) op %s", result.returncode, audio_file)


def trigger_scare(client, logger, topics):
    """Enige plek waar een scare start: cooldown-check, dan meteen het
    scare-topic publiceren (zodat HA/WLED niet op het geluid hoeft te
    wachten) en pas daarna afspelen."""
    if not cooldown.ready():
        return
    client.publish(topics.scare(ZONE), trigger_payload())
    play_scare(logger)


def make_on_message(logger, topics):
    def on_message(client, userdata, msg):
        # Vangnet: een exception hier zou paho's netwerkthread killen — de node
        # reageert dan nergens meer op, ook niet op system/sleep (de noodstop).
        try:
            if msg.topic == topics.system_sleep:
                if msg.payload.decode() == SLEEP_PAYLOAD_ON:
                    sleeping.set()
                else:
                    sleeping.clear()
                return
            if msg.topic == topics.config_scare(ZONE):
                _apply_scare_config(msg.payload.decode(), logger)
                return
            if msg.topic == topics.control_scare_test(ZONE):
                trigger_scare(client, logger, topics)
                return
            if msg.topic == topics.mirror_triggered and not sleeping.is_set():
                delay = random.uniform(0, 2)
                threading.Timer(delay, trigger_scare, args=(client, logger, topics)).start()
        except Exception as exc:
            logger.error("Fout bij verwerken MQTT-bericht op topic %s: %s", msg.topic, exc)
    return on_message


def selfcheck():
    """Speelt één fragment af en publiceert (best-effort) één testbericht.
    Heeft geen PIR-sensor en geen bereikbare broker nodig."""
    print(f"selfcheck scare-node {ZONE}")
    try:
        audio_file = pick_audio_file(MEDIA_DIR)
    except FileNotFoundError as exc:
        print(f"selfcheck MISLUKT: {exc}")
        sys.exit(1)

    print(f"speelt {audio_file} af")
    try:
        result = subprocess.run(["aplay", audio_file], check=False)
    except FileNotFoundError:
        print("selfcheck MISLUKT: `aplay` niet gevonden (alsa-utils installeren)")
        sys.exit(1)
    if result.returncode != 0:
        print(f"selfcheck MISLUKT: aplay returncode={result.returncode}")
        sys.exit(1)

    topic_prefix = fetch_topic_prefix(BACKEND_URL, fallback=MQTT_TOPIC_PREFIX_ENV)
    topics = Topics(prefix=topic_prefix)

    client = mqtt.Client(client_id=f"scare-selfcheck-{ZONE}")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
        client.loop_start()
        client.publish(topics.scare(ZONE), trigger_payload())
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()
        print(f"MQTT OK: {topics.scare(ZONE)} gepubliceerd")
    except OSError as exc:
        print(f"MQTT niet bereikbaar ({exc}) — audio werkte wel")

    print("selfcheck OK")


def main():
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)

    topic_prefix = fetch_topic_prefix(BACKEND_URL, fallback=MQTT_TOPIC_PREFIX_ENV)
    topics = Topics(prefix=topic_prefix)

    client = mqtt.Client(client_id=f"scare-node-{ZONE}")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    logger = setup_logging(NODE_NAME, LOG_DIR, mqtt_client=client, mqtt_log_topic=topics.log(NODE_NAME))
    logger.info("MQTT-topic-prefix: %r", topic_prefix)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            logger.error("MQTT verbinden mislukt (rc=%s)", rc)
            return
        logger.info("MQTT verbonden met %s:%s", MQTT_HOST, MQTT_PORT)
        client.publish(topics.status(NODE_NAME), "online", retain=True)
        client.subscribe(topics.mirror_triggered)
        client.subscribe(topics.system_sleep)
        client.subscribe(topics.config_scare(ZONE))
        client.subscribe(topics.control_scare_test(ZONE))

    def on_disconnect(client, userdata, rc):
        logger.warning("MQTT verbinding verbroken (rc=%s)", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = make_on_message(logger, topics)

    # Mediamap bij opstarten valideren (spec-eis), niet pas midden in een
    # scare-moment. De uitkomst zelf wordt niet hergebruikt: elke scare kiest
    # opnieuw willekeurig.
    try:
        logger.info("mediamap %s OK (bijv. %s)", MEDIA_DIR, pick_audio_file(MEDIA_DIR))
    except FileNotFoundError as exc:
        logger.error("Mediamap onbruikbaar, node stopt: %s", exc)
        return

    # Last-will: broker publiceert "offline" als deze node wegvalt.
    client.will_set(topics.status(NODE_NAME), payload="offline", retain=True)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec). on_message staat hierboven
    # al vast, zodat het achtergrondthread geen berichten kan missen terwijl
    # de main thread nog met de rest van de setup bezig is.
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    from gpiozero import MotionSensor  # pas hier nodig: selfcheck werkt zonder GPIO

    pir = MotionSensor(PIR_PIN)

    def on_motion():
        if sleeping.is_set():
            return
        trigger_scare(client, logger, topics)

    pir.when_motion = on_motion

    logger.info("scare-node %s gestart op pin %s", ZONE, PIR_PIN)
    threading.Event().wait()  # blokkeert voor altijd


if __name__ == "__main__":
    main()
