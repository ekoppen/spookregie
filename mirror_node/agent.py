import json
import os
import socket
import subprocess
import sys
import time

import paho.mqtt.client as mqtt

from shared.mqtt_contract import Topics
from shared.topic_prefix import fetch_topic_prefix
from shared.logging_setup import setup_logging
from mirror_node.device_identity import get_or_create_device_uuid

MQTT_HOST = os.environ.get("MQTT_HOST", "homeassistant.local")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_TOPIC_PREFIX_ENV = os.environ.get("MQTT_TOPIC_PREFIX", "")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
REPO_DIR = os.environ.get("SPOOKREGIE_REPO_DIR", os.path.expanduser("~/spookregie"))
LOG_DIR = os.environ.get("LOG_DIR", "./logs")
CHECKIN_INTERVAL_SECONDS = float(os.environ.get("AGENT_CHECKIN_INTERVAL_SECONDS", "300"))
UPDATE_CHECK_INTERVAL_SECONDS = float(os.environ.get("AGENT_UPDATE_CHECK_INTERVAL_SECONDS", "600"))
# Servicemanager-commando om mirror_node te herstarten na een update --
# platformafhankelijk, door het install-script (Task 9) in de omgeving
# gezet zodat dit script zelf niets over macOS/Linux hoeft te weten.
MIRROR_RESTART_COMMAND = os.environ.get("MIRROR_RESTART_COMMAND", "")


def build_checkin_payload(name, platform, git_sha):
    return json.dumps({"name": name, "platform": platform, "git_sha": git_sha})


def needs_update(local_sha, remote_sha):
    return local_sha != remote_sha


def _git(args, cwd, logger=None):
    try:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        # Geen rollback/crash -- zelfde no-rollback-gedrag als een falende
        # git-opdracht: loggen en de volgende cyclus opnieuw proberen. Zonder
        # deze timeout blokkeert een hangende remote de hele main-loop,
        # inclusief de periodieke checkin (zie commit 3938d40 voor precedent).
        if logger:
            logger.warning("git %s timed out na 30s", " ".join(args))
        return 1, "", "timeout"
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _current_git_sha(cwd, logger=None):
    code, out, _err = _git(["rev-parse", "HEAD"], cwd, logger)
    return out if code == 0 else None


def _pip_install(repo_dir, logger=None):
    """Herinstalleert mirror_node/requirements.txt in de venv na een
    succesvolle pull -- zonder dit herstart de mirror-service in een
    ImportError zodra een update een nieuwe/gewijzigde dependency
    toevoegt, en crash-loopt hij (Restart=always/KeepAlive) voor altijd.
    Zelfde timeout/geen-rollback-vorm als _git: bij mislukken loggen en
    stoppen (geen herstart in een kapotte dependency-staat), volgende
    cyclus probeert opnieuw."""
    pip = os.path.join(repo_dir, ".venv", "bin", "pip")
    requirements = os.path.join(repo_dir, "mirror_node", "requirements.txt")
    try:
        result = subprocess.run(
            [pip, "install", "-q", "-r", requirements], timeout=120, capture_output=True, text=True
        )
    except subprocess.TimeoutExpired:
        if logger:
            logger.warning("pip install timed out na 120s")
        return False
    if result.returncode != 0:
        if logger:
            logger.error("pip install mislukt: %s", result.stderr.strip())
        return False
    return True


def _restart_mirror_node(logger):
    if not MIRROR_RESTART_COMMAND:
        logger.warning("MIRROR_RESTART_COMMAND niet gezet, kan mirror_node niet herstarten na update")
        return
    try:
        # Geen shell=True: het install-script (Task 9) schrijft dit als een
        # al-opgeloste, simpele opdracht zonder shell-features nodig (bv.
        # launchd's $(id -u) is al door de heredoc geëxpandeerd op
        # installatiemoment) -- .split() + een lijst voorkomt command-
        # injection via een env-var, ook al is de bron hier vertrouwd.
        subprocess.run(MIRROR_RESTART_COMMAND.split(), check=True, timeout=10)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # Geen rollback (bewuste keuze, zie spec) -- gewoon loggen en de
        # volgende update-cyclus opnieuw proberen.
        logger.error("Herstarten van mirror_node mislukt: %s", exc)


def check_and_apply_update(repo_dir, logger):
    """Eén update-cyclus: git fetch, vergelijk lokale met remote HEAD van
    main, pull + herstart bij verschil. Geen rollback bij een falende
    herstart -- de volgende cyclus (interval of MQTT-duw) probeert het
    gewoon opnieuw."""
    code, _out, err = _git(["fetch", "origin", "main"], repo_dir, logger)
    if code != 0:
        logger.warning("git fetch mislukt: %s", err)
        return
    local_sha = _current_git_sha(repo_dir, logger)
    code, remote_sha, err = _git(["rev-parse", "origin/main"], repo_dir, logger)
    if code != 0 or not remote_sha:
        logger.warning("kon remote HEAD niet bepalen: %s", err)
        return
    if not needs_update(local_sha, remote_sha):
        return
    logger.info("nieuwe commit gevonden (%s -> %s), pull + herstart", local_sha, remote_sha)
    code, _out, err = _git(["pull", "--ff-only"], repo_dir, logger)
    if code != 0:
        logger.error("git pull mislukt: %s", err)
        return
    if not _pip_install(repo_dir, logger):
        logger.error("pip install mislukt na pull, herstart overgeslagen (blijf op oude dependencies draaien)")
        return
    _restart_mirror_node(logger)


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    device_uuid = get_or_create_device_uuid()
    # Zelfde fetch-bij-startup-patroon als mirror_node.main: haalt de actuele
    # topic-prefix bij de backend op i.p.v. alleen de env-var te lezen, zodat
    # een prefix-wijziging via Instellingen ook de agent bereikt (na een
    # herstart) en niet alleen mirror_node zelf.
    topic_prefix = fetch_topic_prefix(BACKEND_URL, fallback=MQTT_TOPIC_PREFIX_ENV)
    topics = Topics(prefix=topic_prefix)
    logger = setup_logging(f"agent-{device_uuid}", LOG_DIR)

    client = mqtt.Client(client_id=f"agent-{device_uuid}")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    def do_checkin():
        git_sha = _current_git_sha(REPO_DIR) or "onbekend"
        payload = build_checkin_payload(name=socket.gethostname(), platform=sys.platform, git_sha=git_sha)
        client.publish(topics.device_info(device_uuid), payload, retain=True)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            logger.error("MQTT verbinden mislukt (rc=%s)", rc)
            return
        logger.info("agent verbonden met MQTT %s:%s als %s", MQTT_HOST, MQTT_PORT, device_uuid)
        client.subscribe(topics.device_update_check)
        do_checkin()

    def on_message(client, userdata, msg):
        if msg.topic == topics.device_update_check:
            logger.info("directe update-check aangevraagd via MQTT")
            check_and_apply_update(REPO_DIR, logger)

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    last_checkin = 0.0
    last_update_check = 0.0
    try:
        while True:
            now = time.time()
            if now - last_checkin >= CHECKIN_INTERVAL_SECONDS:
                do_checkin()
                last_checkin = now
            if now - last_update_check >= UPDATE_CHECK_INTERVAL_SECONDS:
                check_and_apply_update(REPO_DIR, logger)
                last_update_check = now
            time.sleep(5)
    finally:
        client.loop_stop()


if __name__ == "__main__":
    main()
