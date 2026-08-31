import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import threading

# Vóór cv2-import: forceert TCP i.p.v. ffmpeg's standaard RTSP-transport.
# Sommige camera's (in de praktijk waargenomen: Reolink) sturen RTP-pakketten
# met beschadigde/dooreengehusselde sequentienummers over UDP, wat ffmpeg
# eindeloos laat spammen met "bad cseq" en de renderloop laat vastlopen.
# TCP is betrouwbaar/geordend, dus dat symptoom verdwijnt.
# stimeout (microseconden): socket-timeout voor de RTSP-verbinding. Zonder
# dit blokkeert cap.read() voor onbepaalde tijd zodra de camera/verbinding
# ook maar even hapert -- in de praktijk waargenomen, geen enkele
# foutmelding, de hele renderloop staat dan stil. Met deze timeout geeft
# read() na 5s zonder data gewoon False terug, en pakt de bestaande
# heropen-logica (MAX_FAILURES_BEFORE_REOPEN) het vanzelf weer op.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000"
)

import cv2
import paho.mqtt.client as mqtt

from shared.mqtt_contract import SLEEP_PAYLOAD_ON, Topics, trigger_payload
from shared.topic_prefix import fetch_topic_prefix, fetch_mirror_camera_source
from shared.logging_setup import setup_logging
from shared.media_sync import sync_media, fetch_scare_video_audio
from mirror_node.trigger import FrameDiffTrigger
from mirror_node.camera import open_camera
from mirror_node.effects import get_effect
from mirror_node.overlay import composite_overlay, place_on_canvas
from mirror_node.players import PlayerGraph
from mirror_node.stream import MJPEGStreamer

NODE_NAME = "mirror"

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
# Optioneel: brokers zonder authenticatie laten MQTT_USER leeg.
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_TOPIC_PREFIX_ENV = os.environ.get("MQTT_TOPIC_PREFIX", "")
MIRROR_CAMERA_SOURCE_ENV = os.environ.get("MIRROR_CAMERA_SOURCE", "")
CAMERA_INDEX = int(os.environ.get("MIRROR_CAMERA_INDEX", "0"))
ACTIVE_SECONDS = float(os.environ.get("MIRROR_ACTIVE_SECONDS", "6"))
# Default schrijfbaar voor een gewone gebruiker die het script direct start;
# systemd zet LOG_DIR expliciet op /var/log/halloween.
LOG_DIR = os.environ.get("LOG_DIR", "./logs")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
MEDIA_CACHE_DIR = os.environ.get("MIRROR_MEDIA_CACHE_DIR", "./media_cache")
STREAM_PORT = int(os.environ.get("MIRROR_STREAM_PORT", "8091"))
# Voor ontwerp/test zonder beamer: sla het fysieke fullscreen-venster over,
# de MJPEG-preview blijft gewoon werken.
MIRROR_HEADLESS = os.environ.get("MIRROR_HEADLESS", "0") == "1"

sleeping = threading.Event()
# Handmatige test-trigger vanaf de beheerpagina; de camera-loop leest en wist
# hem. Event i.p.v. een bool zodat het thread-safe is, net als `sleeping`.
test_trigger_requested = threading.Event()
scene_graph = PlayerGraph()
synced_scare_videos = {}
_fired_ha_entities_lock = threading.Lock()
_fired_ha_entities = set()

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


def _sync_scare_videos_in_background(enabled_hashes):
    """Haalt de ingeschakelde scare-video's (en hun optionele geluid) op de
    achtergrond op -- zelfde reden als _sync_overlay_in_background:
    sync_media kan ~10s blokkeren en mag de MQTT-callbackthread niet
    ophouden."""
    def _do_sync():
        global synced_scare_videos
        videos = sync_media(BACKEND_URL, MEDIA_CACHE_DIR, enabled_hashes)
        result = {}
        for h, video_path in videos.items():
            audio_path = fetch_scare_video_audio(BACKEND_URL, MEDIA_CACHE_DIR, h)
            result[h] = {"video": video_path, "audio": audio_path}
        synced_scare_videos = result
    threading.Thread(target=_do_sync, daemon=True).start()


def _apply_scare_video_config_message(payload, logger):
    try:
        config = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige scare-video-config-JSON ontvangen, genegeerd")
        return
    if not isinstance(config, dict):
        logger.error("Scare-video-config is geen JSON-object, genegeerd: %r", config)
        return
    hashes = config.get("enabled_hashes", [])
    if not isinstance(hashes, list):
        logger.error("enabled_hashes is geen lijst, genegeerd: %r", hashes)
        return
    _sync_scare_videos_in_background(hashes)


def _apply_graph_message(payload, logger):
    try:
        graph = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige graaf-JSON ontvangen, genegeerd")
        return
    if not isinstance(graph, dict):
        logger.error("Graaf-config is geen object, genegeerd: %r", graph)
        return
    scenes = graph.get("scenes", [])
    triggers = graph.get("triggers", [])
    root_scene_id = graph.get("root_scene_id")
    if not isinstance(scenes, list) or not isinstance(triggers, list):
        logger.error("Graaf-config heeft geen geldige scenes/triggers-lijst, genegeerd: %r", graph)
        return
    # ponytail: branches komen pas met de nieuwe graaf-payload (Task 11);
    # tot dan een lege lijst, wat identiek gedrag geeft aan de oude
    # 3-parameter aanroep zolang triggers ook geen from_branch_id gebruiken
    # die naar een echte branch moet resolven.
    branches = graph.get("branches", [])
    scene_graph.set_graph(scenes, branches, triggers, root_scene_id)
    for scene in scenes:
        if isinstance(scene, dict):
            _sync_overlay_in_background(scene)


def _apply_scene_preview_message(payload, logger):
    try:
        scene = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige scene-preview-JSON ontvangen, genegeerd")
        return
    if not isinstance(scene, dict):
        logger.error("Scene-preview is geen object, genegeerd: %r", scene)
        return
    scene_graph.set_preview(scene)
    _sync_overlay_in_background(scene)


def _apply_ha_trigger_message(payload, logger):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige ha-trigger-JSON ontvangen, genegeerd")
        return
    entity_id = data.get("entity_id") if isinstance(data, dict) else None
    if not isinstance(entity_id, str) or not entity_id:
        logger.error("ha-trigger-bericht zonder geldige entity_id, genegeerd: %r", data)
        return
    with _fired_ha_entities_lock:
        _fired_ha_entities.add(entity_id)


def make_on_message(logger, topics):
    def on_message(client, userdata, msg):
        # Vangnet: een exception hier zou paho's netwerkthread killen — de node
        # blijft dan renderen maar reageert nergens meer op, ook niet op
        # system/sleep (de noodstop). Alles loggen en doorgaan dus.
        try:
            if msg.topic == topics.system_sleep:
                if msg.payload.decode() == SLEEP_PAYLOAD_ON:
                    sleeping.set()
                else:
                    sleeping.clear()
                return
            if msg.topic == topics.config_mirror_graph:
                _apply_graph_message(msg.payload.decode(), logger)
                return
            if msg.topic == topics.control_mirror_scene_preview:
                _apply_scene_preview_message(msg.payload.decode(), logger)
                return
            if msg.topic == topics.control_mirror_test:
                test_trigger_requested.set()
                return
            if msg.topic == topics.config_mirror_scare_video:
                _apply_scare_video_config_message(msg.payload.decode(), logger)
            if msg.topic == topics.control_mirror_ha_trigger:
                _apply_ha_trigger_message(msg.payload.decode(), logger)
                return
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


def _render(frame, scene, logger):
    try:
        effect_fn = get_effect(scene.get("effect", "xray"))
    except ValueError:
        logger.error("Onbekend effect in actieve scene: %s", scene.get("effect"))
        return frame

    result = effect_fn(frame, scene.get("params", {}))

    canvas_size = scene.get("canvas_size")
    if canvas_size:
        result = place_on_canvas(
            result,
            tuple(canvas_size),
            scale=scene.get("source_scale", 1.0),
            position=tuple(scene.get("source_position", [0.5, 0.5])),
        )

    overlay_hash = scene.get("overlay_hash")
    if overlay_hash:
        overlay_img = _load_overlay(overlay_hash, logger)
        if overlay_img is not None and overlay_img.ndim == 3 and overlay_img.shape[2] == 4:
            position = scene.get("position", [0.5, 0.5])
            if len(position) != 2:
                logger.warning("Ongeldige position in scene, val terug op (0.5, 0.5): %r", position)
                position = (0.5, 0.5)
            result = composite_overlay(
                result,
                overlay_img,
                scale=scene.get("scale", 1.0),
                position=tuple(position),
            )
    return result


def _play_scare_video(video_path, audio_path, streamer, logger):
    """Speelt één scare-video (+ optioneel geluid) volledig af, blokkerend
    -- vervangt het live camerabeeld voor de duur van de clip. Een falende
    audio-subprocess (bv. geen ALSA-hardware in de Docker-testmodus) mag
    de video niet onderbreken -- best-effort, gewoon stil doorspelen."""
    if audio_path:
        try:
            subprocess.Popen(["aplay", audio_path])
        except Exception as exc:
            logger.warning("Kon geluid niet starten: %s", exc)

    cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frame_delay = 1.0 / fps
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            streamer.publish_frame(frame)
            if not MIRROR_HEADLESS:
                cv2.imshow("mirror", frame)
                cv2.waitKey(1)
            time.sleep(frame_delay)
    finally:
        cap.release()


def _handle_trigger(streamer, logger):
    """Reageert op een trigger (echt of test): speelt een willekeurige
    ingeschakelde scare-video af als er minstens één is gesynct, anders
    blijft het gewone effect actief. Geeft altijd ACTIVE_SECONDS terug --
    de aanroeper gebruikt dit met een verse time.time() (na de eventueel
    blokkerende video-afspeel) zodat een net geschrokken bezoeker die nog
    beweegt de trigger niet meteen laat herhalen (de trigger zelf heeft
    geen eigen cooldown; dit is wat er normaal voor zorgt)."""
    if synced_scare_videos:
        chosen = random.choice(list(synced_scare_videos.values()))
        _play_scare_video(chosen["video"], chosen["audio"], streamer, logger)
    return ACTIVE_SECONDS


def _render_action(winning, transitioned):
    """Bepaalt wat de hoofdlus deze cyclus moet doen, gegeven wat
    scene_graph.resolve() teruggaf. Puur -- geen state, geen I/O --
    zodat de driewegs-keuze (scare-video afspelen / camera-effect
    renderen / zwart beeld) los van de camera-lus getest kan worden."""
    if winning is None:
        return "blank"
    if winning.get("source_mode") == "scare_video":
        return "scare_video" if transitioned else "blank"
    return "render"


def _redact_source(source):
    """Verbergt inloggegevens (user:pass@) uit een camera-URL voor logging."""
    source = source or CAMERA_INDEX
    return str(source).split("@")[-1] if "@" in str(source) else source


def selfcheck():
    """Pakt één frame, draait het door het standaard xray-effect en
    laat/bewaart het resultaat. Heeft geen MQTT nodig."""
    camera_source = fetch_mirror_camera_source(BACKEND_URL, fallback=MIRROR_CAMERA_SOURCE_ENV)
    cap = open_camera(camera_source, CAMERA_INDEX)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print(f"selfcheck MISLUKT: geen frame van camera-bron {_redact_source(camera_source)}")
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

    topic_prefix = fetch_topic_prefix(BACKEND_URL, fallback=MQTT_TOPIC_PREFIX_ENV)
    topics = Topics(prefix=topic_prefix)
    camera_source = fetch_mirror_camera_source(BACKEND_URL, fallback=MIRROR_CAMERA_SOURCE_ENV)

    client = mqtt.Client(client_id="mirror-node")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    # setup_logging vóór de callbacks: die loggen naar het lokale bestand,
    # wat ook werkt als de broker onbereikbaar is.
    logger = setup_logging(NODE_NAME, LOG_DIR, mqtt_client=client, mqtt_log_topic=topics.log(NODE_NAME))
    logger.info("MQTT-topic-prefix: %r", topic_prefix)

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT verbonden met %s:%s", MQTT_HOST, MQTT_PORT)
        else:
            logger.error("MQTT verbinden mislukt (rc=%s)", rc)
            return
        client.publish(topics.status(NODE_NAME), "online", retain=True)
        client.subscribe(topics.system_sleep)
        client.subscribe(topics.config_mirror_graph)
        client.subscribe(topics.control_mirror_scene_preview)
        client.subscribe(topics.control_mirror_test)
        client.subscribe(topics.config_mirror_scare_video)
        client.subscribe(topics.control_mirror_ha_trigger)

    def on_disconnect(client, userdata, rc):
        logger.warning("MQTT verbinding verbroken (rc=%s)", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = make_on_message(logger, topics)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # Last-will: broker publiceert "offline" als deze node wegvalt.
    client.will_set(topics.status(NODE_NAME), payload="offline", retain=True)
    # connect_async + loop_start: node blijft draaien en probeert op de
    # achtergrond te (her)verbinden, i.p.v. te crashen als HA nu niet
    # bereikbaar is (fail-safe eis uit de spec).
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    streamer = MJPEGStreamer(STREAM_PORT)
    streamer.start()
    logger.info("MJPEG-stream op poort %s (/stream)", STREAM_PORT)

    cap = open_camera(camera_source, CAMERA_INDEX)
    if not cap.isOpened():
        logger.error("Kon camera-bron niet openen: %s", _redact_source(camera_source))
        return

    trigger = FrameDiffTrigger()
    if not MIRROR_HEADLESS:
        cv2.namedWindow("mirror", cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty("mirror", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    active_until = 0.0
    consecutive_failures = 0
    MAX_FAILURES_BEFORE_REOPEN = 30  # ~15s bij 0.5s sleep tussen mislukte reads
    logger.info("mirror-node gestart")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                logger.warning("Kon geen frame lezen van camera")
                consecutive_failures += 1
                if consecutive_failures >= MAX_FAILURES_BEFORE_REOPEN:
                    logger.warning("Camera blijft falen, heropen de verbinding")
                    cap.release()
                    cap = open_camera(camera_source, CAMERA_INDEX)
                    consecutive_failures = 0
                time.sleep(0.5)
                continue
            consecutive_failures = 0

            if sleeping.is_set():
                if not MIRROR_HEADLESS:
                    cv2.imshow("mirror", frame * 0)
                    cv2.waitKey(1)
                time.sleep(0.2)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            now = time.time()
            now_hhmm = time.strftime("%H:%M")

            # fired: eenmalige puls voor dit frame, NIET het aanhoudende
            # "we zitten nog in de cooldown"-niveau (now < active_until).
            # scene_graph.resolve() is stateful en volgt een edge alleen
            # op het frame dat 'm matcht -- een niveau dat ACTIVE_SECONDS
            # lang True blijft laat een motion-edge bij elke terugkeer op
            # de bronscene opnieuw matchen, en ping-pongt de graaf
            # oneindig door zolang de cooldown loopt (Kritiek 1).
            fired = False
            if trigger.detect(gray) and now > active_until:
                client.publish(topics.mirror_triggered, trigger_payload())
                logger.info("mirror triggered")
                active_until = time.time() + ACTIVE_SECONDS
                fired = True

            if test_trigger_requested.is_set():
                test_trigger_requested.clear()
                logger.info("mirror test-trigger")
                active_until = time.time() + ACTIVE_SECONDS
                fired = True

            with _fired_ha_entities_lock:
                fired_ha_entities = frozenset(_fired_ha_entities)
                _fired_ha_entities.clear()

            winning, transitioned = scene_graph.resolve(fired, now_hhmm, fired_ha_entities)
            action = _render_action(winning, transitioned)

            if action == "scare_video":
                # Bij aankomst op een scare-video-scene: speel 'm nu
                # blokkerend af (bestaand _handle_trigger-pad,
                # ongewijzigd). _play_scare_video streamt zijn eigen
                # frames al, dus hier verder niets meer te renderen.
                cooldown = _handle_trigger(streamer, logger)
                active_until = time.time() + cooldown
                rendered = frame * 0
            elif action == "blank":
                rendered = frame * 0
            else:
                try:
                    rendered = _render(frame, winning, logger)
                except Exception as exc:
                    logger.error("Fout bij renderen: %s", exc)
                    rendered = frame
            streamer.publish_frame(rendered)
            if not MIRROR_HEADLESS:
                cv2.imshow("mirror", rendered)
                cv2.waitKey(1)
    finally:
        cap.release()
        if not MIRROR_HEADLESS:
            cv2.destroyAllWindows()
        streamer.stop()
        client.loop_stop()


if __name__ == "__main__":
    main()
