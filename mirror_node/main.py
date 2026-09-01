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
from mirror_node.device_identity import get_or_create_device_uuid
from mirror_node.effects import get_effect
from mirror_node.overlay import composite_overlay, place_on_canvas
from mirror_node.players import PlayerGraph
from mirror_node.stream import MJPEGStreamer

# Wordt pas in main() gezet (niet hier op module-niveau): get_or_create_device_uuid()
# schrijft een bestand naar de echte home-dir van wie dit process draait, en
# elke import van deze module (bv. door tests) mag daar geen bijwerking van
# hebben -- alleen het daadwerkelijk starten van de node moet dat triggeren.
NODE_NAME = None

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
# Optioneel: brokers zonder authenticatie laten MQTT_USER leeg.
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_TOPIC_PREFIX_ENV = os.environ.get("MQTT_TOPIC_PREFIX", "")
MIRROR_CAMERA_SOURCE_ENV = os.environ.get("MIRROR_CAMERA_SOURCE", "")
CAMERA_INDEX = int(os.environ.get("MIRROR_CAMERA_INDEX", "0"))
ACTIVE_SECONDS = float(os.environ.get("MIRROR_ACTIVE_SECONDS", "6"))
# Losstaande constante (geen shared import voor één drempelwaarde) --
# admin/app/ha_trigger_poller.py pollt elke 5s (check_interval default).
# Een level-state ouder dan ~3x die tick-interval is niet meer vers: de
# backend/broker-verbinding is waarschijnlijk weg, dus behandel 'm als
# 'off' (fail-safe) i.p.v. een repeat_while-loop voor altijd te laten
# doorlopen (Kritiek 3c).
HA_ENTITY_STATE_STALE_SECONDS = 15.0
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
player_graph = PlayerGraph()
synced_scare_videos = {}
_fired_ha_entities_lock = threading.Lock()
_fired_ha_entities = set()
_ha_entity_states_lock = threading.Lock()
_ha_entity_states = {}

# Laatst ontvangen graaf-metadata (naast player_graph zelf) die de
# output-routing-publish en de dynamische source-resolutie nodig hebben --
# bijgewerkt door _apply_graph_message, gelezen door main()'s lus.
_assigned_output_id = None
_current_output_connections = []
_current_branches = []
_current_sources = []
_last_published_output_player_id = None

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


def _sync_sources_in_background(sources):
    """Haalt static_image-/video_loop-/audio-sourcebestanden op de
    achtergrond op -- zelfde patroon/reden als _sync_overlay_in_background:
    sync_media kan ~10s blokkeren en mag de MQTT-callbackthread niet
    ophouden. sync_media zelf slaat een hash over die al lokaal in
    MEDIA_CACHE_DIR staat. camera_stream-sources hebben geen media om te
    syncen."""
    hashes = [
        source.get("value")
        for source in sources
        if isinstance(source, dict)
        and source.get("kind") in ("static_image", "video_loop", "audio")
        and isinstance(source.get("value"), str)
        and source.get("value")
    ]
    if not hashes:
        return
    threading.Thread(
        target=sync_media,
        args=(BACKEND_URL, MEDIA_CACHE_DIR, hashes),
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
    global _current_output_connections, _current_branches, _current_sources
    try:
        graph = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige graaf-JSON ontvangen, genegeerd")
        return
    if not isinstance(graph, dict):
        logger.error("Graaf-config is geen object, genegeerd: %r", graph)
        return
    players = graph.get("players", [])
    branches = graph.get("branches", [])
    triggers = graph.get("triggers", [])
    root_player_id = graph.get("root_player_id")
    if not isinstance(players, list) or not isinstance(triggers, list):
        logger.error("Graaf-config heeft geen geldige players/triggers-lijst, genegeerd: %r", graph)
        return
    player_graph.set_graph(players, branches, triggers, root_player_id)
    _current_output_connections = graph.get("output_connections", [])
    _current_branches = branches
    _current_sources = graph.get("sources", [])
    _sync_sources_in_background(_current_sources)
    for player in players:
        if isinstance(player, dict):
            _sync_overlay_in_background(player)


def _apply_scene_preview_message(payload, logger):
    try:
        scene = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige scene-preview-JSON ontvangen, genegeerd")
        return
    if not isinstance(scene, dict):
        logger.error("Scene-preview is geen object, genegeerd: %r", scene)
        return
    player_graph.set_preview(scene)
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


def _apply_ha_sensor_state_message(payload, logger):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige ha-sensor-state-JSON ontvangen, genegeerd")
        return
    entity_id = data.get("entity_id") if isinstance(data, dict) else None
    state = data.get("state") if isinstance(data, dict) else None
    if not isinstance(entity_id, str) or not entity_id or not isinstance(state, str):
        logger.error("ha-sensor-state-bericht zonder geldige entity_id/state, genegeerd: %r", data)
        return
    with _ha_entity_states_lock:
        _ha_entity_states[entity_id] = (state, time.time())


def _apply_device_assignment_message(payload, logger):
    global _assigned_output_id
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Ongeldige device-assignment-JSON ontvangen, genegeerd")
        return
    if not isinstance(data, dict):
        logger.error("Device-assignment is geen object, genegeerd: %r", data)
        return
    _assigned_output_id = data.get("output_id")


def _ha_entity_state(entity_id):
    """Geeft de laatst-bekende state terug, of None als er nog niets
    binnenkwam OF de laatste update ouder is dan HA_ENTITY_STATE_STALE_SECONDS
    (fail-safe: een gestopte MQTT-/backendverbinding mag een repeat_while
    -loop niet voor altijd laten doorlopen op een verouderde 'on')."""
    with _ha_entity_states_lock:
        entry = _ha_entity_states.get(entity_id)
    if entry is None:
        return None
    state, ts = entry
    if time.time() - ts > HA_ENTITY_STATE_STALE_SECONDS:
        return None
    return state


def make_on_message(logger, topics):
    device_assignment_topic = topics.device_assignment(NODE_NAME)

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
            if msg.topic == device_assignment_topic:
                _apply_device_assignment_message(msg.payload.decode(), logger)
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
            if msg.topic == topics.control_mirror_ha_sensor_state:
                _apply_ha_sensor_state_message(msg.payload.decode(), logger)
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


class _SourceState:
    """Houdt bij welke source op dit moment 'open' is voor de camera-lus
    -- capture-object bij camera_stream, gedecodeerd beeld bij
    static_image -- zodat een ongewijzigde source niet elk frame opnieuw
    geopend/gedecodeerd wordt, en een gewijzigde source de oude capture
    netjes sluit voordat de nieuwe geopend wordt."""

    def __init__(self):
        self.source_id = None
        self.kind = None
        self.value = None
        self.capture = None
        self.image = None


def _ensure_source(state, source, logger):
    """Geeft het huidige frame-beeld terug voor `source`: cv2 capture voor
    camera_stream/video_loop, een gedecodeerd beeld voor static_image. Heropent/
    herdecodeert alleen als id, kind ÉN value ongewijzigd zijn sinds de vorige
    aanroep -- een bewerkte stream-URL of een nieuwe hash op dezelfde source
    moet wel opnieuw opgepakt worden."""
    if source is None:
        return None
    if (
        state.source_id == source.get("id")
        and state.kind == source.get("kind")
        and state.value == source.get("value")
    ):
        return state.image if state.kind == "static_image" else state.capture
    if state.capture is not None:
        state.capture.release()
        state.capture = None
    state.image = None
    kind = source.get("kind")
    value = source.get("value", "")
    if kind == "static_image":
        if not _HASH_RE.match(value):
            logger.error("Ongeldige static_image-hash op source: %s", value)
            return None
        image_path = os.path.join(MEDIA_CACHE_DIR, value)
        if not os.path.exists(image_path):
            # Nog niet gesynct of ongeldig -- state NIET bijwerken, zodat
            # de volgende _ensure_source-aanroep dit als onopgelost blijft
            # zien en blijft retryen i.p.v. deze mislukking permanent te
            # cachen als "al opgelost" (Belangrijk 5b).
            return None
        image = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if image is None:
            logger.error("static_image kon niet gedecodeerd worden: %s", value)
            return None
        state.source_id, state.kind, state.value = source.get("id"), kind, value
        state.image = image
        return state.image
    if kind == "video_loop":
        if not _HASH_RE.match(value):
            logger.error("Ongeldige video_loop-hash op source: %s", value)
            return None
        video_path = os.path.join(MEDIA_CACHE_DIR, value)
        if not os.path.exists(video_path):
            # Nog niet gesynct -- state NIET bijwerken, zelfde retry-gedrag
            # als static_image hierboven.
            return None
        capture = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            logger.error("video_loop kon niet geopend worden: %s", value)
            return None
        state.source_id, state.kind, state.value = source.get("id"), kind, value
        state.capture = capture
        return state.capture
    state.source_id, state.kind, state.value = source.get("id"), kind, value
    state.capture = open_camera(value, CAMERA_INDEX)
    return state.capture


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


def _play_scare_video_sequence(winning, streamer, logger):
    """Speelt scare-video's af volgens winning['playback_mode']: 'once'
    precies 1x (bestaand gedrag, ongewijzigd), 'repeat_once' precies 2x,
    'repeat_while' minstens 1x en daarna zolang de gekoppelde HA-sensor
    (NIVEAU, geen puls -- ander mechanisme dan de HA-trigger hierboven,
    zie het Global Constraints-punt over puls vs. niveau) 'on'/'detected'
    blijft rapporteren. Geeft ACTIVE_SECONDS terug, zelfde contract als
    het onderliggende _handle_trigger."""
    mode = winning.get("playback_mode", "once")
    if mode == "repeat_while":
        entity_id = winning.get("repeat_while_ha_entity_id")
        result = _handle_trigger(streamer, logger)
        while entity_id and not sleeping.is_set() and _ha_entity_state(entity_id) in ("on", "detected"):
            if not synced_scare_videos:
                # Geen enkele scare-video gesynct (elke boot, ~10s venster
                # voordat de achtergrond-sync klaar is, of nul ingeschakelde
                # video's): _handle_trigger doet dan niets en keert meteen
                # terug zonder sleep/I/O -- zonder deze check pint deze loop
                # één CPU-core op 100% en bevriest de hele renderloop.
                break
            result = _handle_trigger(streamer, logger)
        return result
    plays = 2 if mode == "repeat_once" else 1
    result = ACTIVE_SECONDS
    for _ in range(plays):
        result = _handle_trigger(streamer, logger)
    return result


def _player_feeds_this_output(player_id, output_id, branches, output_connections):
    """True als de gegeven player, via een van zijn branches, een
    output_connections-rij heeft naar output_id."""
    player_branch_ids = {b["id"] for b in branches if b.get("player_id") == player_id}
    return any(
        oc["from_branch_id"] in player_branch_ids and oc["output_id"] == output_id
        for oc in output_connections
    )


def _render_action(winning, transitioned):
    """Bepaalt wat de hoofdlus deze cyclus moet doen, gegeven wat
    player_graph.resolve() teruggaf. Puur -- geen state, geen I/O --
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

    global NODE_NAME
    NODE_NAME = get_or_create_device_uuid()

    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)

    topic_prefix = fetch_topic_prefix(BACKEND_URL, fallback=MQTT_TOPIC_PREFIX_ENV)
    topics = Topics(prefix=topic_prefix)
    camera_source = fetch_mirror_camera_source(BACKEND_URL, fallback=MIRROR_CAMERA_SOURCE_ENV)

    # Per-device client id (NODE_NAME is hierboven al gezet) -- een gedeelde,
    # vaste id zou een tweede fysiek apparaat permanent van de broker af laten
    # vechten met het eerste (elke connect kickt de vorige sessie eraf).
    client = mqtt.Client(client_id=f"mirror-{NODE_NAME}")
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
        client.subscribe(topics.control_mirror_ha_sensor_state)
        client.subscribe(topics.device_assignment(NODE_NAME))

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
        # Geen fallback-camera beschikbaar (bv. all-static-image-install
        # zonder camera_stream-source, of een kapotte lokale webcam-index)
        # -- niet meer hard exitten (Belangrijk 8): een camera-loze
        # installatie is nu een geldige configuratie, per-player
        # source-resolutie (_ensure_source) neemt het over zodra de eerste
        # graaf-config binnenkomt.
        logger.warning("Kon fallback-camerabron niet openen: %s -- ga verder zonder", _redact_source(camera_source))
        cap.release()
        cap = None

    trigger = FrameDiffTrigger()
    if not MIRROR_HEADLESS:
        cv2.namedWindow("mirror", cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty("mirror", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    active_until = 0.0
    consecutive_failures = 0
    MAX_FAILURES_BEFORE_REOPEN = 30  # ~15s bij 0.5s sleep tussen mislukte reads
    logger.info("mirror-node gestart")

    source_state = _SourceState()
    try:
        while True:
            sources_by_id = {s["id"]: s for s in _current_sources}
            current_player = player_graph._players.get(player_graph._current_id)
            resolved_source = sources_by_id.get(current_player.get("source_id")) if current_player else None
            acquired = _ensure_source(source_state, resolved_source, logger) if resolved_source else None

            if resolved_source is not None and resolved_source.get("kind") == "static_image":
                if acquired is None:
                    time.sleep(0.5)
                    continue
                frame = acquired.copy()
                ok = True
            elif acquired is not None:
                ok, frame = acquired.read()
                if not ok and resolved_source is not None and resolved_source.get("kind") == "video_loop":
                    # Einde van de lus bereikt -- spring terug naar het begin
                    # en lees opnieuw, zodat een video_loop-source oneindig
                    # blijft doorlopen i.p.v. na één keer afspelen stil te
                    # vallen (zelfde contract als camera_stream: altijd een
                    # geldig frame als de bron open is).
                    acquired.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = acquired.read()
            elif cap is not None:
                # Geen (nog) bekende source voor de huidige player -- val
                # terug op de startup-camera zodat het beeld nooit
                # volledig leeg blijft vóór de eerste graaf-config binnen is.
                ok, frame = cap.read()
            else:
                # Geen fallback-camera (Belangrijk 8) EN nog geen
                # geresolvede source -- gewoon wachten tot de eerste
                # graaf-config met een geldige source binnenkomt.
                ok, frame = False, None

            if not ok:
                logger.warning("Kon geen frame lezen van camera")
                consecutive_failures += 1
                if consecutive_failures >= MAX_FAILURES_BEFORE_REOPEN:
                    logger.warning("Camera blijft falen, heropen de verbinding")
                    if cap is not None:
                        cap.release()
                    # ponytail: guard resolved_source is not None -- source_state.kind
                    # kan nog "camera_stream" zijn van een vorige iteratie terwijl de
                    # huidige player's source dit frame (nog) niet resolvet, anders
                    # AttributeError op resolved_source.get(...) hieronder.
                    if source_state.kind == "camera_stream" and source_state.capture is not None and resolved_source is not None:
                        source_state.capture.release()
                        source_state.capture = open_camera(resolved_source.get("value", ""), CAMERA_INDEX)
                    else:
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
            # player_graph.resolve() is stateful en volgt een edge alleen
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

            winning, transitioned = player_graph.resolve(fired, now_hhmm, fired_ha_entities)

            global _last_published_output_player_id
            if (
                winning is not None
                and transitioned
                and _assigned_output_id is not None
                and _player_feeds_this_output(winning["id"], _assigned_output_id, _current_branches, _current_output_connections)
                and winning["id"] != _last_published_output_player_id
            ):
                client.publish(
                    topics.mirror_output, json.dumps({"player_id": winning["id"], "output_id": _assigned_output_id})
                )
                _last_published_output_player_id = winning["id"]

            action = _render_action(winning, transitioned)

            if action == "scare_video":
                # Bij aankomst op een scare-video-scene: speel de
                # scare-video('s) nu blokkerend af, volgens de
                # playback_mode van de winnende player (once/repeat_once/
                # repeat_while -- zie _play_scare_video_sequence).
                # _play_scare_video streamt zijn eigen frames al, dus hier
                # verder niets meer te renderen.
                cooldown = _play_scare_video_sequence(winning, streamer, logger)
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
        if cap is not None:
            cap.release()
        if not MIRROR_HEADLESS:
            cv2.destroyAllWindows()
        streamer.stop()
        client.loop_stop()


if __name__ == "__main__":
    main()
